"""Metadados profissionais em MP3 + integração com o núcleo (IA 2).

Ponto de entrada do contrato (ver ``INTEGRATION.md``)::

    BAIXADOR_METADATA_MODULE=modulo_metadados python musica.py download <url> --formato mp3
    # ou: BAIXADOR_METADATA_MODULE=metadados

Fluxo de ``processar_mp3(caminho, metadados)``:

1. interpreta o nome do arquivo baixado (``"Artista - Título [id].mp3"``);
2. identifica a música nas APIs (``inteligencia.py``) — sem inventar dados;
3. baixa a capa oficial (``capas.py``);
4. grava título/artista/álbum/ano/gênero/faixa/gravadora e a capa (APIC)
   dentro do próprio MP3 com Mutagen, retornando ``None`` (mesmo caminho).

Falhas de API/capa NÃO levantam exceção: o MP3 recebe ao menos o
título/artista extraídos do próprio nome do arquivo e o download da IA 1
nunca é perdido. Só erros que impedem a gravação das tags (arquivo
inválido, Mutagen ausente) propagam — e, pelo contrato, o núcleo mantém
o arquivo original nesse caso.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from capas import GerenciadorCapas, validar_imagem
from inteligencia import (
    ClienteHTTPUrllib, IdentificadorMusical, InfoMusica, analisar_titulo,
    criar_assistente_padrao, limpar_nome_canal,
)

log = logging.getLogger("baixador.ia2.metadados")


class ErroMetadados(RuntimeError):
    """Impossível gravar metadados (arquivo inválido ou Mutagen ausente)."""


@dataclass(frozen=True)
class ConfigMetadados:
    buscar_capa: bool = True
    timeout: float = 15.0
    usar_ia: bool = True

    @classmethod
    def from_env(cls) -> "ConfigMetadados":
        def _verdadeiro(nome: str) -> bool:
            return os.environ.get(nome, "").strip().lower() in {
                "1", "true", "sim", "yes", "on"}

        def _ativo(nome: str, padrao: bool = True) -> bool:
            valor = os.environ.get(nome, "").strip().lower()
            return valor not in {"0", "false", "nao", "não", "off"} if valor else padrao

        try:
            timeout = float(os.environ.get("BAIXADOR_METADATA_TIMEOUT", "15") or 15)
        except ValueError:
            timeout = 15.0
        return cls(
            buscar_capa=not _verdadeiro("BAIXADOR_SEM_CAPA"),
            timeout=timeout,
            usar_ia=_ativo("BAIXADOR_IA_ATIVA"),
        )


# ---------------------------------------------------------------------------
# Gravação/leitura das tags (Mutagen / ID3)
# ---------------------------------------------------------------------------


def _carregar_mutagen():
    try:
        from mutagen.id3 import (  # type: ignore
            APIC, ID3, TALB, TCON, TDRC, TIT2, TPE1, TPE2, TPUB, TRCK, TSRC,
            ID3NoHeaderError,
        )
    except ImportError as erro:
        raise ErroMetadados(
            "Mutagen não instalado. Instale com: python -m pip install -r requirements.txt"
        ) from erro
    return {
        "ID3": ID3, "ID3NoHeaderError": ID3NoHeaderError, "APIC": APIC,
        "TIT2": TIT2, "TPE1": TPE1, "TPE2": TPE2, "TALB": TALB, "TCON": TCON,
        "TDRC": TDRC, "TRCK": TRCK, "TPUB": TPUB, "TSRC": TSRC,
    }


def aplicar_metadados(caminho: Path, info: InfoMusica, capa: bytes | None = None) -> None:
    """Grava os campos conhecidos e incorpora a capa ao MP3 (ID3v2.3)."""
    frames = _carregar_mutagen()
    caminho = Path(caminho)
    if not caminho.is_file() or caminho.stat().st_size == 0:
        raise ErroMetadados(f"MP3 inválido para metadados: {caminho}")
    try:
        audio = frames["ID3"](caminho)
    except frames["ID3NoHeaderError"]:
        audio = frames["ID3"]()
    except Exception as erro:
        raise ErroMetadados(f"Não foi possível ler as tags de {caminho}: {erro}") from erro

    def _definir(chave: str, valor: Any) -> None:
        audio.delall(chave)
        if valor not in (None, ""):
            audio.add(frames[chave](encoding=3, text=str(valor)))

    _definir("TIT2", info.titulo)
    _definir("TPE1", info.artista)
    _definir("TPE2", info.artista_album)
    _definir("TALB", info.album)
    _definir("TDRC", info.ano)
    _definir("TCON", info.genero)
    _definir("TPUB", info.gravadora)
    _definir("TSRC", info.isrc)
    audio.delall("TRCK")
    if info.faixa:
        faixa = str(info.faixa)
        if info.total_faixas:
            faixa = f"{info.faixa}/{info.total_faixas}"
        audio.add(frames["TRCK"](encoding=3, text=faixa))
    if capa:
        imagem = validar_imagem(capa)
        audio.delall("APIC")
        audio.add(frames["APIC"](
            encoding=3, mime=imagem.mime, type=3, desc="Capa", data=capa))
    audio.save(caminho, v2_version=3)


def ler_metadados(caminho: Path) -> dict[str, Any]:
    """Lê as tags atuais (verificação/testes); ``{}`` se não houver ID3."""
    frames = _carregar_mutagen()
    try:
        audio = frames["ID3"](Path(caminho))
    except frames["ID3NoHeaderError"]:
        return {}
    except Exception:
        return {}
    if audio is None:
        return {}
    resultado: dict[str, Any] = {}
    mapa = {"TIT2": "titulo", "TPE1": "artista", "TPE2": "artista_album",
            "TALB": "album", "TCON": "genero", "TPUB": "gravadora",
            "TRCK": "faixa", "TYER": "ano", "TDRC": "ano"}
    for chave, nome in mapa.items():
        if chave in audio:
            resultado[nome] = str(audio[chave].text[0]) if audio[chave].text else ""
    capas = audio.getall("APIC")
    resultado["tem_capa"] = bool(capas)
    if capas:
        resultado["capa_mime"] = capas[0].mime
        resultado["capa_bytes"] = len(capas[0].data)
    return resultado


# ---------------------------------------------------------------------------
# Processador que implementa o contrato da IA 1
# ---------------------------------------------------------------------------


class ProcessadorMusical:
    """Implementa ``ProcessadorMetadados.processar_mp3`` de ``integracao.py``."""

    def __init__(self, identificador: Any | None = None,
                 gerenciador_capas: Any | None = None,
                 config: ConfigMetadados | None = None):
        self.config = config or ConfigMetadados.from_env()
        if identificador is None or gerenciador_capas is None:
            cliente = ClienteHTTPUrllib(timeout=self.config.timeout)
            if identificador is None:
                assistente = (
                    criar_assistente_padrao(cliente) if self.config.usar_ia else None)
                identificador = IdentificadorMusical(
                    cliente=cliente, assistente=assistente)
            if gerenciador_capas is None:
                gerenciador_capas = GerenciadorCapas(cliente=cliente)
        self.identificador = identificador
        self.gerenciador_capas = gerenciador_capas
        self.ultimo_resumo: dict[str, Any] = {}

    def processar_mp3(self, caminho: Path,
                      metadados: Mapping[str, Any]) -> None:
        """Enriquece o MP3 no próprio caminho (retorno ``None`` do contrato)."""
        caminho = Path(caminho)
        metadados = dict(metadados or {})
        if not caminho.is_file() or caminho.stat().st_size == 0:
            raise ErroMetadados(f"MP3 inválido para metadados: {caminho}")

        # O resultado escolhido na pesquisa (contrato v2) é a melhor pista:
        # título real do vídeo e canal. O nome do arquivo é o plano B, porque o
        # yt-dlp trunca em 180 bytes e pode não ter separador "Artista - Título".
        canonico = str(metadados.get("titulo") or "").strip()
        canal = str(metadados.get("canal") or metadados.get("uploader") or "").strip()
        entrada = canonico or caminho.stem
        consulta = analisar_titulo(entrada, canal=canal or None)
        if canonico and not consulta.artista and not canal:
            # Sem canal e sem separador: tenta também o nome do arquivo.
            consulta = analisar_titulo(caminho.stem, canal=None)
            entrada = caminho.stem
        info: InfoMusica | None = None
        try:
            info = self.identificador.identificar(entrada, canal=canal or None)
        except Exception as erro:  # identificação nunca derruba o enriquecimento
            log.warning("Identificação falhou para %s: %s", caminho.name, erro)

        if info is None:
            # Sem confirmação externa: grava os dados do próprio vídeo, que são
            # fatos (título e canal informados pela fonte) — nunca álbum/ano/
            # gênero inventados.
            info = InfoMusica(
                titulo=consulta.titulo or caminho.stem,
                artista=consulta.artista or limpar_nome_canal(canal),
                fonte="resultado_da_pesquisa" if canonico else "nome_do_arquivo",
                confianca=0.0)
            log.info("Sem identificação externa para %r; usando título/canal do "
                     "próprio resultado.", caminho.name)

        capa: bytes | None = None
        if self.config.buscar_capa:
            try:
                # A URL do vídeo permite a thumbnail oficial como último recurso
                # (só quando nenhuma capa de álbum foi validada).
                capa = self.gerenciador_capas.buscar_e_baixar(
                    info, url_origem=metadados.get("url"),
                    thumbnail=metadados.get("thumbnail"))
            except Exception as erro:
                log.warning("Busca de capa falhou para %s: %s", caminho.name, erro)

        aplicar_metadados(caminho, info, capa)
        self.ultimo_resumo = {
            "titulo": info.titulo, "artista": info.artista, "album": info.album,
            "ano": info.ano, "genero": info.genero, "fonte": info.fonte,
            "confianca": info.confianca, "capa_incorporada": capa is not None,
            "identificado": info.fonte not in {"nome_do_arquivo",
                                               "resultado_da_pesquisa"},
        }
        # Relato honesto do que aconteceu, para a interface e o histórico:
        # campos confirmados por API, campos que vieram só do vídeo, e quais
        # provedores falharam (rede bloqueada, API fora do ar, sem chave).
        erros = list(getattr(self.identificador, "ultimos_erros", []) or [])
        self.ultimo_resumo["provedores_com_erro"] = erros
        self.ultimo_resumo["campos_confirmados"] = [
            campo for campo in ("album", "ano", "genero")
            if getattr(info, campo, None)]
        log.info("Metadados gravados em %s: %s", caminho.name, self.ultimo_resumo)
        return None


def criar_processador_padrao(config: ConfigMetadados | None = None) -> ProcessadorMusical:
    return ProcessadorMusical(config=config)


def processar_mp3(caminho: Path, metadados: Mapping[str, Any]) -> None:
    """Função exposta ao ``BAIXADOR_METADATA_MODULE`` (contrato da IA 1)."""
    criar_processador_padrao().processar_mp3(Path(caminho), metadados or {})
    return None


__all__ = [
    "ConfigMetadados", "ErroMetadados", "ProcessadorMusical",
    "aplicar_metadados", "criar_processador_padrao", "ler_metadados",
    "processar_mp3",
]
