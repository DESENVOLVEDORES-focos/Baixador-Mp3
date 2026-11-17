"""Pesquisa, download, validação e processamento de capas (IA 2).

Prioridade (sempre capas do álbum/single identificado, nunca imagens
aleatórias da web):

1. iTunes — ``artworkUrl100`` promovido para 1200x1200;
2. MusicBrainz / Cover Art Archive — ``front-1200`` do lançamento;
3. Deezer — ``cover_xl`` (1000x1000) do álbum;
4. Thumbnail do YouTube (``maxresdefault``) — apenas como último recurso
   quando a URL de origem é do YouTube; não é capa oficial.

Toda imagem baixada é validada pela assinatura do arquivo (JPEG/PNG) e
pelas dimensões reais; respostas HTML/erro e placeholders pequenos são
rejeitados. O processamento (reduzir para no máx. 1200px e converter para
JPEG) usa Pillow quando disponível e, sem ele, mantém a imagem original
já validada.
"""

from __future__ import annotations

import logging
import re
import struct
import urllib.parse
from dataclasses import dataclass
from typing import Any

from inteligencia import (
    ClienteHTTPUrllib, ConsultaMusica, ErroAPI, InfoMusica,
    ProvedorDeezer, ProvedorITunes,
)

log = logging.getLogger("baixador.ia2.capas")

TAMANHO_MINIMO = 50      # px: abaixo disso é placeholder/erro, não capa
TAMANHO_PREFERIDO = 500  # px: capas menores só são usadas se nada melhor vier


class ErroCapa(RuntimeError):
    """Imagem inválida, pequena demais ou download de capa impossível."""


@dataclass(frozen=True)
class InfoImagem:
    formato: str  # "jpeg" | "png"
    mime: str
    largura: int
    altura: int


@dataclass(frozen=True)
class CandidatoCapa:
    url: str
    fonte: str
    largura_esperada: int = 0
    oficial: bool = True


# ---------------------------------------------------------------------------
# Validação / processamento de imagens (sem depender de Pillow)
# ---------------------------------------------------------------------------


def _dimensoes_png(dados: bytes) -> tuple[int, int]:
    if len(dados) < 24 or dados[12:16] != b"IHDR":
        raise ErroCapa("PNG sem cabeçalho IHDR válido.")
    largura, altura = struct.unpack(">II", dados[16:24])
    return largura, altura


def _dimensoes_jpeg(dados: bytes) -> tuple[int, int]:
    # Percorre os marcadores JPEG até um SOF0/SOF1/SOF2, que traz as dimensões.
    pos = 2
    while pos + 4 <= len(dados):
        if dados[pos] != 0xFF:
            pos += 1
            continue
        marcador = dados[pos + 1]
        if marcador in (0xC0, 0xC1, 0xC2):
            if pos + 9 > len(dados):
                break
            altura, largura = struct.unpack(">HH", dados[pos + 5:pos + 9])
            return largura, altura
        if marcador in (0xD8, 0xD9) or 0xD0 <= marcador <= 0xD7:
            pos += 2
            continue
        tamanho = struct.unpack(">H", dados[pos + 2:pos + 4])[0]
        if tamanho < 2:
            break
        pos += 2 + tamanho
    raise ErroCapa("JPEG sem quadro SOF com dimensões.")


def validar_imagem(dados: bytes) -> InfoImagem:
    """Confere assinatura e dimensões reais; levanta ``ErroCapa`` se inválida."""
    if not dados or len(dados) < 100:
        raise ErroCapa("Imagem vazia ou pequena demais para ser uma capa.")
    if dados[:8] == b"\x89PNG\r\n\x1a\n":
        formato, mime = "png", "image/png"
        largura, altura = _dimensoes_png(dados)
    elif dados[:3] == b"\xff\xd8\xff":
        formato, mime = "jpeg", "image/jpeg"
        largura, altura = _dimensoes_jpeg(dados)
    else:
        raise ErroCapa("Formato não suportado (esperado JPEG ou PNG).")
    if largura < TAMANHO_MINIMO or altura < TAMANHO_MINIMO:
        raise ErroCapa(f"Imagem pequena demais para capa: {largura}x{altura}.")
    return InfoImagem(formato=formato, mime=mime, largura=largura, altura=altura)


def processar_imagem(dados: bytes, maximo: int = 1200) -> bytes:
    """Reduz/converte com Pillow se houver; senão devolve o original validado."""
    validar_imagem(dados)
    try:
        from PIL import Image  # type: ignore
    except ImportError:
        return dados
    try:
        import io
        imagem = Image.open(io.BytesIO(dados))
        imagem.load()
        if max(imagem.size) <= maximo and imagem.format == "JPEG":
            return dados
        imagem = imagem.convert("RGB")
        imagem.thumbnail((maximo, maximo))
        saida = io.BytesIO()
        imagem.save(saida, format="JPEG", quality=90)
        return saida.getvalue()
    except Exception as erro:  # imagem exótica: mantém o original já validado
        log.debug("Pillow não processou a capa (%s); usando original.", erro)
        return dados


# ---------------------------------------------------------------------------
# Fontes de capa
# ---------------------------------------------------------------------------


def _candidatos_itunes(consulta: ConsultaMusica, cliente: Any) -> list[CandidatoCapa]:
    termo = f"{consulta.artista or ''} {consulta.titulo}".strip()
    url = "https://itunes.apple.com/search?" + urllib.parse.urlencode(
        {"term": termo, "media": "music", "entity": "song", "limit": 3})
    dados = cliente.get_json(url)
    candidatos: list[CandidatoCapa] = []
    for item in (dados or {}).get("results") or []:
        arte = str((item or {}).get("artworkUrl100") or "")
        if arte:
            alta = arte.replace("100x100bb.jpg", "1200x1200bb.jpg")
            candidatos.append(CandidatoCapa(alta, "itunes", 1200))
    return candidatos


def _candidatos_deezer(info: InfoMusica, cliente: Any) -> list[CandidatoCapa]:
    album_id = info.deezer_album_id
    if not album_id and info.titulo:
        # Sem ID guardado, refaz a busca enxuta para achar o álbum da faixa.
        achados = ProvedorDeezer().buscar(
            ConsultaMusica(titulo=info.titulo, artista=info.artista), cliente)
        for achado in achados:
            if achado.deezer_album_id:
                album_id = achado.deezer_album_id
                break
    if not album_id:
        return []
    album = cliente.get_json(f"https://api.deezer.com/album/{album_id}")
    url = str((album or {}).get("cover_xl") or "")
    return [CandidatoCapa(url, "deezer", 1000)] if url else []


def extrair_id_youtube(url: str | None) -> str | None:
    if not url:
        return None
    achado = re.search(r"(?:v=|youtu\.be/|/shorts/)([A-Za-z0-9_-]{6,})", url)
    return achado.group(1) if achado else None


# ---------------------------------------------------------------------------
# Gerenciador: busca em ordem, baixa, valida e entrega a melhor capa
# ---------------------------------------------------------------------------


class GerenciadorCapas:
    def __init__(self, cliente: Any | None = None):
        # ClienteHTTPUrllib oferece get_json + get_bytes.
        self.cliente = cliente or ClienteHTTPUrllib()

    def candidatos(self, info: InfoMusica, url_origem: str | None = None) -> list[CandidatoCapa]:
        consulta = ConsultaMusica(titulo=info.titulo, artista=info.artista)
        lista: list[CandidatoCapa] = []
        try:
            lista.extend(_candidatos_itunes(consulta, self.cliente))
        except ErroAPI as erro:
            log.info("Capas iTunes indisponíveis: %s", erro)
        if info.musicbrainz_id:
            lista.append(CandidatoCapa(
                f"https://coverartarchive.org/release/{info.musicbrainz_id}/front-1200",
                "coverartarchive", 1200))
        try:
            lista.extend(_candidatos_deezer(info, self.cliente))
        except ErroAPI as erro:
            log.info("Capas Deezer indisponíveis: %s", erro)
        video_id = extrair_id_youtube(url_origem)
        if video_id:
            lista.append(CandidatoCapa(
                f"https://i.ytimg.com/vi/{video_id}/maxresdefault.jpg",
                "youtube-thumbnail", 1280, oficial=False))
        return lista

    def buscar_e_baixar(self, info: InfoMusica,
                        url_origem: str | None = None) -> bytes | None:
        """Baixa a melhor capa válida; ``None`` se nenhuma fonte entregar."""
        reserva: bytes | None = None
        for candidato in self.candidatos(info, url_origem):
            try:
                dados = self.cliente.get_bytes(candidato.url)
                imagem = validar_imagem(dados)
            except (ErroAPI, ErroCapa) as erro:
                log.info("Capa %s rejeitada (%s): %s", candidato.fonte, candidato.url, erro)
                continue
            log.info("Capa via %s: %dx%d", candidato.fonte, imagem.largura, imagem.altura)
            if imagem.largura >= TAMANHO_PREFERIDO and imagem.altura >= TAMANHO_PREFERIDO:
                return processar_imagem(dados)
            if reserva is None:
                reserva = dados
        return processar_imagem(reserva) if reserva is not None else None


__all__ = [
    "CandidatoCapa", "ErroCapa", "GerenciadorCapas", "InfoImagem",
    "extrair_id_youtube", "processar_imagem", "validar_imagem",
]
