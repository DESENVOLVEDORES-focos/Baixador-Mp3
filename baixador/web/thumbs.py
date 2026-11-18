"""Miniaturas dos resultados de pesquisa (cache local em ``<dados>/thumbs``).

Regras:

- só baixa de http(s) e com limite de tamanho;
- valida a assinatura real da imagem (JPEG/PNG/WEBP) — nunca aceita HTML;
- guarda em cache por hash da URL, com poda por quantidade;
- qualquer falha devolve ``None``: a interface mostra um espaço vazio e segue.

Nada aqui usa a rede do usuário para APIs externas de música; é apenas o
thumbnail que o próprio yt-dlp já devolveu no resultado da pesquisa.
"""

from __future__ import annotations

import hashlib
import logging
import urllib.request
from pathlib import Path

log = logging.getLogger("baixador.thumbs")

LIMITE_BYTES = 3 * 1024 * 1024
MAXIMO_CACHE = 300
_AGENTE = "Baixador-Mp3/1.0 (thumbnail da pesquisa)"
_ASSINATURAS = (
    (b"\xff\xd8\xff", ".jpg"),
    (b"\x89PNG\r\n\x1a\n", ".png"),
    (b"RIFF", ".webp"),
)


def _extensao(dados: bytes) -> str | None:
    for assinatura, extensao in _ASSINATURAS:
        if dados.startswith(assinatura):
            if extensao == ".webp" and dados[8:12] != b"WEBP":
                return None
            return extensao
    return None


def pasta_cache(dados_dir: Path) -> Path:
    pasta = Path(dados_dir) / "thumbs"
    pasta.mkdir(parents=True, exist_ok=True)
    return pasta


def _chave(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:32]


def arquivo_em_cache(url: str, dados_dir: Path) -> Path | None:
    """Caminho já baixado para esta URL, se existir e não estiver vazio."""
    if not url:
        return None
    pasta = Path(dados_dir) / "thumbs"
    if not pasta.is_dir():
        return None
    for extensao in (".jpg", ".png", ".webp"):
        candidato = pasta / f"{_chave(url)}{extensao}"
        try:
            if candidato.is_file() and candidato.stat().st_size > 0:
                return candidato
        except OSError:
            continue
    return None


def obter(url: str, dados_dir: Path, timeout: float = 8.0) -> Path | None:
    """Devolve um arquivo de imagem local para ``url`` (cache ou download)."""
    if not url or not url.lower().startswith(("http://", "https://")):
        return None
    em_cache = arquivo_em_cache(url, dados_dir)
    if em_cache is not None:
        return em_cache
    requisicao = urllib.request.Request(url, headers={"User-Agent": _AGENTE})
    try:
        with urllib.request.urlopen(requisicao, timeout=timeout) as resposta:
            dados = resposta.read(LIMITE_BYTES + 1)
    except Exception as erro:  # rede/HTTP: thumbnail é opcional, nunca fatal
        log.debug("Thumbnail indisponível (%s): %s", url, erro)
        return None
    if len(dados) > LIMITE_BYTES:
        log.debug("Thumbnail grande demais, ignorada: %s", url)
        return None
    extensao = _extensao(dados)
    if extensao is None:
        log.debug("Thumbnail não é imagem válida: %s", url)
        return None
    pasta = pasta_cache(dados_dir)
    destino = pasta / f"{_chave(url)}{extensao}"
    temporario = destino.with_suffix(destino.suffix + ".tmp")
    try:
        temporario.write_bytes(dados)
        temporario.replace(destino)
    except OSError as erro:
        log.debug("Falha ao guardar thumbnail: %s", erro)
        try:
            temporario.unlink(missing_ok=True)
        except OSError:
            pass
        return None
    _podar(pasta)
    return destino


def _podar(pasta: Path) -> None:
    """Mantém o cache pequeno: remove os mais antigos quando passa do limite."""
    try:
        arquivos = sorted(
            (a for a in pasta.iterdir() if a.is_file() and a.suffix != ".tmp"),
            key=lambda a: a.stat().st_mtime)
    except OSError:
        return
    excedente = len(arquivos) - MAXIMO_CACHE
    for arquivo in arquivos[:max(0, excedente)]:
        try:
            arquivo.unlink()
        except OSError:
            continue


__all__ = ["MAXIMO_CACHE", "arquivo_em_cache", "obter", "pasta_cache"]
