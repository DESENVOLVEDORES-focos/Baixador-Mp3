"""Configurações persistentes do usuário (Etapa 3 — interface/configurações).

Centraliza tudo o que a interface gráfica salva e o núcleo respeita:

- chaves de API (somente dos serviços que o código realmente usa);
- caminho dos cookies do YouTube (gerenciado por ``cookies_youtube.py``);
- diretórios de saída MP3/MP4, formato e qualidade padrão;
- metadados/capas da IA 2 ligados ou desligados.

Armazenamento: ``<dados>/preferencias.json`` (pasta de dados do núcleo,
já ignorada pelo Git). A chave de IA **não** fica em texto puro quando o
Windows está disponível: é protegida com DPAPI (``CryptProtectData``,
vinculada ao usuário do Windows). Em outros sistemas, fica codificada em
um arquivo com permissão restrita (0600) — nunca no código-fonte, nunca
em logs e nunca em commits (``.baixador/`` está no ``.gitignore``).

O programa funciona sem nenhuma API configurada: os provedores musicais
(MusicBrainz/iTunes/Deezer) são públicos e a IA externa é opcional.
"""

from __future__ import annotations

import base64
import ctypes
import json
import logging
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

from configuracoes import CONFIG, Configuracoes

log = logging.getLogger("baixador.preferencias")

ARQUIVO_PREFERENCIAS = "preferencias.json"
IA_URL_PADRAO = "https://api.openai.com/v1/chat/completions"
IA_MODELO_PADRAO = "gpt-4o-mini"


# ---------------------------------------------------------------------------
# Cofre de segredos (DPAPI no Windows; codificação + 0600 nos demais)
# ---------------------------------------------------------------------------


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", ctypes.c_ulong), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _dpapi(disponivel: bool = sys.platform == "win32") -> bool:
    return disponivel


def proteger_segredo(texto: str) -> str:
    """Protege um segredo para persistência; prefixo indica o mecanismo."""
    if not texto:
        return ""
    bruto = texto.encode("utf-8")
    if _dpapi():
        try:
            entrada = _Blob(len(bruto), ctypes.cast(
                ctypes.create_string_buffer(bruto, len(bruto)),
                ctypes.POINTER(ctypes.c_char)))
            saida = _Blob()
            if ctypes.windll.crypt32.CryptProtectData(  # type: ignore[attr-defined]
                    ctypes.byref(entrada), None, None, None, None, 0,
                    ctypes.byref(saida)):
                try:
                    protegido = ctypes.string_at(saida.pbData, saida.cbData)
                    return "dpapi:" + base64.b64encode(protegido).decode("ascii")
                finally:
                    ctypes.windll.kernel32.LocalFree(saida.pbData)  # type: ignore[attr-defined]
        except Exception as erro:  # pragma: no cover - só ocorre no Windows
            log.warning("DPAPI indisponível (%s); usando armazenamento local restrito.", erro)
    return "local:" + base64.b64encode(bruto).decode("ascii")


def revelar_segredo(protegido: str) -> str:
    """Reverte ``proteger_segredo``; devolve ``""`` se inválido/ilegível."""
    if not protegido:
        return ""
    mecanismo, _, valor = protegido.partition(":")
    try:
        bruto = base64.b64decode(valor or protegido)
    except Exception:
        return ""
    if mecanismo == "dpapi" and _dpapi():
        try:
            entrada = _Blob(len(bruto), ctypes.cast(
                ctypes.create_string_buffer(bruto, len(bruto)),
                ctypes.POINTER(ctypes.c_char)))
            saida = _Blob()
            if ctypes.windll.crypt32.CryptUnprotectData(  # type: ignore[attr-defined]
                    ctypes.byref(entrada), None, None, None, None, 0,
                    ctypes.byref(saida)):
                try:
                    return ctypes.string_at(saida.pbData, saida.cbData).decode("utf-8")
                finally:
                    ctypes.windll.kernel32.LocalFree(saida.pbData)  # type: ignore[attr-defined]
            return ""
        except Exception:  # pragma: no cover - só ocorre no Windows
            return ""
    try:
        return bruto.decode("utf-8")
    except UnicodeDecodeError:
        return ""


def mascarar_segredo(texto: str) -> str:
    """Representação exibida na interface: nunca revela a chave inteira."""
    if not texto:
        return ""
    return "••••••••" if len(texto) <= 4 else "••••••••" + texto[-4:]


# ---------------------------------------------------------------------------
# Modelo de preferências
# ---------------------------------------------------------------------------


@dataclass
class Preferencias:
    """Preferências do usuário; padrões = comportamento original do núcleo."""

    # APIs e inteligência artificial (só serviços realmente usados no código)
    ia_api_key: str = ""                       # AssistenteIAOpenAI (inteligencia.py)
    ia_modelo: str = IA_MODELO_PADRAO
    ia_url: str = IA_URL_PADRAO
    # Cookies do YouTube (caminho da cópia gerenciada; conteúdo nunca sai daí)
    cookies_caminho: str = ""
    # Downloads
    diretorio_mp3: str = ""                    # vazio = padrão do núcleo (Musicas/)
    diretorio_mp4: str = ""                    # vazio = padrão do núcleo (Videos/)
    formato_padrao: str = "mp3"
    qualidade_mp3: str = "0"                   # yt-dlp --audio-quality (0 = melhor)
    limite_pesquisa: int = 10
    # Inteligência musical (IA 2)
    metadados_ativos: bool = True
    buscar_capas: bool = True
    # O que fazer quando o arquivo final já existe (nunca sobrescreve por
    # acidente): perguntar | pular | renomear | sobrescrever
    sobrescrita: str = "perguntar"
    # Nome apresentável "Artista - Título.ext" (desligado = nome do yt-dlp)
    organizar_nomes: bool = True
    # Guardar em Artista/Álbum/ quando a identificação musical confirmar
    organizar_por_album: bool = False

    def validar(self) -> None:
        if self.formato_padrao not in ("mp3", "mp4"):
            raise ValueError("Formato padrão deve ser 'mp3' ou 'mp4'.")
        if str(self.sobrescrita).lower() not in {
                "perguntar", "pular", "renomear", "sobrescrever"}:
            raise ValueError(
                "Política de sobrescrita inválida (perguntar/pular/renomear/sobrescrever).")
        if not 1 <= int(self.limite_pesquisa) <= 50:
            raise ValueError("O limite de pesquisa deve estar entre 1 e 50.")
        qualidade = str(self.qualidade_mp3).strip()
        if not (qualidade.isdigit() and 0 <= int(qualidade) <= 10) \
                and not (qualidade.upper().endswith("K") and qualidade[:-1].isdigit()):
            raise ValueError("Qualidade MP3 inválida (use 0–10 ou ex.: 192K).")


def caminho_arquivo(config: Configuracoes = CONFIG) -> Path:
    return config.dados / ARQUIVO_PREFERENCIAS


def salvar(prefs: Preferencias, config: Configuracoes = CONFIG) -> Path:
    """Grava atomicamente; a chave de IA vai protegida, nunca em texto puro."""
    prefs.validar()
    destino = caminho_arquivo(config)
    destino.parent.mkdir(parents=True, exist_ok=True)
    dados = asdict(prefs)
    dados["ia_api_key"] = proteger_segredo(prefs.ia_api_key)
    temporario = destino.with_suffix(".json.tmp")
    temporario.write_text(
        json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        os.chmod(temporario, 0o600)
    except OSError:
        pass
    temporario.replace(destino)
    return destino


def carregar(config: Configuracoes = CONFIG) -> Preferencias:
    """Carrega as preferências; ausente/corrompido = padrões, sem quebrar."""
    arquivo = caminho_arquivo(config)
    if not arquivo.is_file():
        return Preferencias()
    try:
        dados = json.loads(arquivo.read_text(encoding="utf-8"))
        if not isinstance(dados, dict):
            return Preferencias()
        conhecidos = {campo for campo in Preferencias.__dataclass_fields__}  # type: ignore[attr-defined]
        prefs = Preferencias(**{k: v for k, v in dados.items() if k in conhecidos})
        prefs.ia_api_key = revelar_segredo(str(dados.get("ia_api_key") or ""))
        prefs.validar()
        return prefs
    except (OSError, ValueError, TypeError) as erro:
        log.warning("Preferências ilegíveis (%s); usando padrões.", erro)
        return Preferencias()


def aplicar_ao_ambiente(prefs: Preferencias) -> None:
    """Disponibiliza as escolhas aos módulos existentes (IA 1/IA 2) via env.

    É o mesmo mecanismo que o núcleo já respeita: a IA 2 lê
    ``BAIXADOR_IA_*``/``BAIXADOR_SEM_CAPA`` e o adaptador da IA 1 lê
    ``BAIXADOR_METADATA_MODULE``. Segredos vão só para o ambiente do
    processo — nunca para arquivos, logs ou rede além do serviço da IA.
    """
    chave = prefs.ia_api_key
    if not chave:
        # Chave importada como arquivo (api.txt), no mesmo espírito do
        # cookies.txt: vale sem o usuário digitar nada.
        try:
            import api_ia

            chave = api_ia.ler_chave()
        except Exception:
            chave = ""
    if chave:
        os.environ["BAIXADOR_IA_API_KEY"] = chave
    else:
        os.environ.pop("BAIXADOR_IA_API_KEY", None)
    os.environ["BAIXADOR_IA_MODELO"] = prefs.ia_modelo or IA_MODELO_PADRAO
    os.environ["BAIXADOR_IA_URL"] = prefs.ia_url or IA_URL_PADRAO
    if prefs.buscar_capas:
        os.environ.pop("BAIXADOR_SEM_CAPA", None)
    else:
        os.environ["BAIXADOR_SEM_CAPA"] = "1"
    if prefs.metadados_ativos:
        os.environ["BAIXADOR_METADATA_MODULE"] = "modulo_metadados"
    else:
        os.environ.pop("BAIXADOR_METADATA_MODULE", None)


def derivar_configuracoes(prefs: Preferencias,
                          base: Configuracoes = CONFIG) -> Configuracoes:
    """Monta o ``Configuracoes`` do núcleo a partir das preferências salvas."""
    cookies = Path(prefs.cookies_caminho).expanduser() if prefs.cookies_caminho else None
    if cookies is not None and not cookies.is_file():
        cookies = None
    return Configuracoes(
        raiz=base.raiz,
        diretorio_musicas=Path(prefs.diretorio_mp3).expanduser() if prefs.diretorio_mp3 else None,
        diretorio_videos=Path(prefs.diretorio_mp4).expanduser() if prefs.diretorio_mp4 else None,
        caminho_cookies=cookies,
        qualidade_mp3=str(prefs.qualidade_mp3 or "0"),
        organizar_nomes=bool(getattr(prefs, "organizar_nomes", True)),
        organizar_por_album=bool(getattr(prefs, "organizar_por_album", False)),
        # "perguntar" é resolvido na interface; no núcleo o padrão seguro é
        # não sobrescrever (a pergunta acontece antes de baixar).
        sobrescrita="pular" if str(prefs.sobrescrita).lower() == "perguntar"
        else str(prefs.sobrescrita).lower(),
    )


__all__ = [
    "IA_MODELO_PADRAO", "IA_URL_PADRAO", "Preferencias", "aplicar_ao_ambiente",
    "caminho_arquivo", "carregar", "derivar_configuracoes", "mascarar_segredo",
    "proteger_segredo", "revelar_segredo", "salvar",
]
