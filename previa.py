"""Pré-visualização antes de baixar: amostra de áudio + checagem do vídeo.

Motivo (pedido do usuário): música de **show/ao vivo** ou "extended version"
só é percebida depois de baixar. Aqui o usuário ouve/troca de fonte **antes**
de gastar banda e de sujar a pasta ``Musicas/``.

Como funciona:

1. ``preparar`` pergunta ao yt-dlp (``-J``, sem baixar mídia) título, canal,
   duração real, se é *livestream* e quantos formatos de áudio existem.
2. ``baixar_amostra`` traz **só um trecho** do áudio (``--download-sections``),
   limitado em segundos e em bytes, para um arquivo temporário que é apagado
   quando a prévia termina.
3. ``analisar`` sinaliza riscos de forma explícita e conservadora — nunca
   afirma "é show" sem indício: só marca o que o título/canal/duração mostram.

Nada aqui é obrigatório: qualquer falha devolve aviso e a interface segue
funcionando (o download normal continua disponível).
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from configuracoes import CONFIG, Configuracoes, argumentos_cookies

# Limites do trecho de prévia: curto o bastante para ser rápido e barato,
# longo o bastante para reconhecer a música e perceber público/ao vivo.
SEGUNDOS_PADRAO = 20
SEGUNDOS_MAXIMO = 40
TAMANHO_MAXIMO = 4 * 1024 * 1024  # 4 MB: trecho de 20 s em áudio comprimido
TAMANHO_MINIMO = 2 * 1024         # menos que 2 KB = trecho vazio/ inválido


@dataclass(frozen=True)
class AnaliseFaixa:
    """O que dá para afirmar sobre a faixa **sem baixá-la**."""

    titulo: str = ""
    canal: str = ""
    duracao: int | None = None
    ao_vivo: bool = False          # livestream/estreia ao vivo agora
    possivel_ao_vivo: bool = False  # indício no título (não é certeza)
    indicios: tuple[str, ...] = ()
    motivos: tuple[str, ...] = ()   # explicação curta de cada indício

    @property
    def alerta(self) -> bool:
        return bool(self.indicios)

    def resumo(self) -> str:
        """Frase para a tela: o que foi detectado e por quê."""
        if not self.indicios:
            return "Nenhum indício de gravação ao vivo pelo título, canal ou duração."
        return "; ".join(self.motivos)


# (rótulo, regex, motivo). Português e inglês; a comparação é sem acento.
_SINAIS_AO_VIVO = (
    ("ao vivo", r"\bao vivo\b", "título diz “ao vivo”"),
    ("live", r"\blive\b(?!\s*(?:session|sessions))", "título diz “live”"),
    ("show", r"\bshow\b|\bconcerto\b|\bem turn[eê]\b|\bturn[eê]\b",
     "título menciona show/turnê"),
    ("tour", r"\btour\b", "título menciona turnê (tour)"),
    ("festival", r"\bfestival\b", "título menciona festival"),
    ("concert", r"\bconcert\b|\bin concert\b", "título diz “concert”"),
    ("unplugged", r"\bunplugged\b|\bac[uú]stico ao vivo\b",
     "título indica apresentação ao vivo"),
    ("estadio", r"\best[aá]dio\b|\barena\b|\bno morumbi\b|\bno maracan[aã]\b",
     "título indica local de show"),
    ("pocket", r"\bpocket show\b|\btiny desk\b|\bNPR Music\b",
     "título indica apresentação"),
)

_SINAIS_EXTENSAO = (
    ("extended", r"\bextended\b|\bextended version\b|\b12\" version\b",
     "título indica versão estendida"),
    ("remix_longo", r"\bremix\b", "título indica remix"),
    ("instrumental", r"\binstrumental\b|\bplayback\b|\bkaraok[eê]\b",
     "título indica instrumental/playback"),
    ("cover", r"\bcover\b|\btribute\b|\bem vers[aã]o de\b",
     "título indica cover/tributo"),
    ("speed", r"\bslowed\b|\bspeed ?up\b|\bnightcore\b|\b8d\b",
     "título indica versão alterada (slowed/speed up)"),
    ("loop", r"\b\d+\s*(?:hours?|horas?)\b|\bloop\b|\b1 ?hour\b",
     "título indica repetição/duração longa"),
)

_RE_ACENTOS = str.maketrans(
    "áàâãäéèêëíìîïóòôõöúùûüçÁÀÂÃÄÉÈÊËÍÌÎÏÓÒÔÕÖÚÙÛÜÇ",
    "aaaaaeeeeiiiiooooouuuucAAAAAEEEEIIIIOOOOOUUUUC",
)


def _sem_acento(texto: str) -> str:
    return str(texto or "").translate(_RE_ACENTOS).lower()


def analisar(titulo: str = "", canal: str = "",
             duracao: int | None = None, ao_vivo: bool = False) -> AnaliseFaixa:
    """Detecta indícios de show/ao vivo e de versões que não são o estúdio.

    Conservador de propósito: só marca o que aparece no texto ou na duração e
    sempre diz **qual** foi o indício, para o usuário decidir.
    """
    texto = _sem_acento(f"{titulo} {canal}")
    indicios: list[str] = []
    motivos: list[str] = []

    def marcar(rotulo: str, motivo: str) -> None:
        if rotulo not in indicios:
            indicios.append(rotulo)
            motivos.append(motivo)

    for rotulo, padrao, motivo in _SINAIS_AO_VIVO:
        if re.search(padrao, texto):
            marcar(rotulo, motivo)
    for rotulo, padrao, motivo in _SINAIS_EXTENSAO:
        if re.search(padrao, texto):
            marcar(rotulo, motivo)

    # Duração é indício só quando foge muito do normal de uma faixa.
    if duracao is not None and duracao >= 12 * 60:
        marcar("longo", f"duração de {duracao // 60} min (faixa comum tem 3–6)")
    if ao_vivo:
        marcar("transmissao", "o vídeo está ao vivo/em estreia agora")

    # Canal de show/festival: "Ao Vivo", "Live", "Festival".
    canal_baixo = _sem_acento(canal)
    if re.search(r"\blive\b|\bao vivo\b|\bfestival\b|\bshow\b|\btour\b", canal_baixo):
        marcar("canal_ao_vivo", f"canal é {canal!r}")

    return AnaliseFaixa(
        titulo=titulo, canal=canal, duracao=duracao, ao_vivo=ao_vivo,
        possivel_ao_vivo=any(rotulo in {"ao vivo", "live", "show", "tour",
                                        "festival", "concert", "unplugged",
                                        "estadio", "pocket", "transmissao",
                                        "canal_ao_vivo"} for rotulo in indicios),
        indicios=tuple(indicios), motivos=tuple(motivos))


# ---------------------------------------------------------------------------
# yt-dlp: metadados e trecho de áudio
# ---------------------------------------------------------------------------


class ErroPrevia(RuntimeError):
    """Falha ao preparar ou baixar a prévia (mensagem já em português)."""


def _carregar_json(saida: str) -> dict[str, Any]:
    texto = (saida or "").strip()
    if not texto:
        raise ErroPrevia("O yt-dlp não devolveu dados do vídeo.")
    try:
        return json.loads(texto)
    except json.JSONDecodeError:
        inicio = texto.find("{")
        if inicio < 0:
            raise ErroPrevia("Não foi possível interpretar os dados do vídeo.")
        dados, _ = json.JSONDecoder().raw_decode(texto[inicio:])
        if not isinstance(dados, dict):
            raise ErroPrevia("Formato inesperado nos dados do vídeo.")
        return dados


@dataclass(frozen=True)
class DadosVideo:
    """Informações do vídeo coletadas sem baixar mídia."""

    titulo: str = ""
    canal: str = ""
    duracao: int | None = None
    ao_vivo: bool = False
    tem_audio: bool = True
    idade_restrita: bool = False
    analise: AnaliseFaixa = field(default_factory=AnaliseFaixa)


class Previa:
    """Prepara e baixa o trecho de prévia de uma URL."""

    def __init__(self, configuracoes: Configuracoes = CONFIG, timeout: int = 120):
        self.config = configuracoes
        self.timeout = timeout

    # -- comandos (isolados para teste) -------------------------------------
    def construir_comando_info(self, url: str) -> list[str]:
        return [
            *self.config.comando_yt_dlp(),
            "--ignore-config", "--no-warnings", "--skip-download",
            *argumentos_cookies(self.config),
            "-J", url,
        ]

    def construir_comando_amostra(self, url: str, destino: Path,
                                  segundos: int = SEGUNDOS_PADRAO) -> list[str]:
        segundos = max(5, min(int(segundos or SEGUNDOS_PADRAO), SEGUNDOS_MAXIMO))
        saida = str(Path(destino) / "previa.%(ext)s")
        # --download-sections depende do FFmpeg: sem isso o yt-dlp aborta com
        # "ffmpeg is not installed" mesmo com o ffmpeg.exe em ferramentas\.
        try:
            ffmpeg = ["--ffmpeg-location", self.config.caminho_ffmpeg()]
        except Exception:
            ffmpeg = []
        return [
            *self.config.comando_yt_dlp(),
            "--ignore-config", "--no-playlist", "--no-warnings", "--newline",
            *argumentos_cookies(self.config),
            "--format", "bestaudio/best",
            "--download-sections", f"*0-{segundos}",
            "--force-keyframes-at-cuts",
            "--no-part",
            *ffmpeg,
            "--paths", str(destino),
            "--output", saida,
            url,
        ]

    # -- execução -----------------------------------------------------------
    def preparar(self, url: str) -> DadosVideo:
        """Consulta o vídeo sem baixar mídia e devolve os dados + análise."""
        try:
            processo = subprocess.run(
                self.construir_comando_info(url), capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=self.timeout,
                check=False)
        except (OSError, subprocess.TimeoutExpired) as erro:
            raise ErroPrevia(f"Não foi possível consultar o vídeo: {erro}") from erro
        if processo.returncode:
            detalhes = (processo.stderr or processo.stdout or "").strip()
            ultimo = detalhes.splitlines()[-1] if detalhes else ""
            raise ErroPrevia(ultimo or f"yt-dlp terminou com código {processo.returncode}.")
        dados = _carregar_json(processo.stdout)
        duracao = dados.get("duration")
        try:
            duracao = int(float(duracao)) if duracao is not None else None
        except (TypeError, ValueError, OverflowError):
            duracao = None
        titulo = str(dados.get("title") or "").strip()
        canal = str(dados.get("channel") or dados.get("uploader") or "").strip()
        ao_vivo = bool(dados.get("is_live")) or str(dados.get("live_status") or "") \
            in {"is_live", "is_upcoming"}
        formatos = dados.get("formats") or []
        tem_audio = any(
            isinstance(f, dict) and str(f.get("acodec") or "none") != "none"
            for f in formatos) if formatos else True
        idade = bool(dados.get("age_limit"))
        return DadosVideo(
            titulo=titulo, canal=canal, duracao=duracao, ao_vivo=ao_vivo,
            tem_audio=tem_audio, idade_restrita=idade,
            analise=analisar(titulo, canal, duracao, ao_vivo))

    def baixar_amostra(self, url: str, destino: Path,
                       segundos: int = SEGUNDOS_PADRAO) -> Path:
        """Baixa só o trecho inicial do áudio para ``destino``."""
        destino = Path(destino)
        destino.mkdir(parents=True, exist_ok=True)
        try:
            processo = subprocess.run(
                self.construir_comando_amostra(url, destino, segundos),
                capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=self.timeout, check=False)
        except (OSError, subprocess.TimeoutExpired) as erro:
            raise ErroPrevia(f"Não foi possível baixar a prévia: {erro}") from erro
        arquivos = [
            caminho for caminho in destino.glob("previa.*")
            if caminho.is_file() and not caminho.name.endswith((".part", ".ytdl"))
        ]
        if not arquivos:
            detalhes = (processo.stderr or processo.stdout or "").strip()
            ultimo = detalhes.splitlines()[-1] if detalhes else ""
            raise ErroPrevia(
                ultimo or "O yt-dlp não produziu o trecho de prévia.")
        arquivo = max(arquivos, key=lambda caminho: caminho.stat().st_size)
        # Corte em fonte sem duração declarada gera arquivo de 0 áudio: detectar
        # antes de abrir um player vazio na cara do usuário.
        if arquivo.stat().st_size < TAMANHO_MINIMO:
            arquivo.unlink(missing_ok=True)
            raise ErroPrevia(
                "A prévia saiu vazia (o servidor não informa a duração do "
                "vídeo, então não é possível cortar um trecho). Baixe o vídeo "
                "ou escolha outra fonte.")
        if arquivo.stat().st_size > TAMANHO_MAXIMO:
            # Áudio muito grande para o trecho pedido: descarta e avisa.
            arquivo.unlink(missing_ok=True)
            raise ErroPrevia(
                "O trecho de prévia ficou maior que o limite (4 MB) e foi "
                "descartado; tente de novo com menos segundos.")
        return arquivo

    # -- ciclo de vida do arquivo temporário --------------------------------
    def pasta_temporaria(self, base: Path | None = None) -> Path:
        """Pasta de prévia (dentro de ``<dados>``, apagada ao fechar)."""
        raiz = Path(base) if base is not None else Path(self.config.dados)
        pasta = raiz / "previa"
        pasta.mkdir(parents=True, exist_ok=True)
        return pasta


def pasta_para_tocar(arquivo: Path, pasta: Path) -> Path:
    """Extensão que o player do sistema reconhece melhor.

    O ``bestaudio`` costuma vir em ``.webm``/``.m4a``; se o FFmpeg estiver
    disponível, converte para ``.mp3`` (toca em qualquer Windows sem codec
    extra). Sem FFmpeg, devolve o arquivo original — nunca falha por isso.
    """
    arquivo = Path(arquivo)
    pasta = Path(pasta)
    if arquivo.suffix.lower() == ".mp3":
        return arquivo
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        return arquivo
    convertido = pasta / "previa.mp3"
    try:
        processo = subprocess.run(
            [ffmpeg, "-y", "-loglevel", "error", "-i", str(arquivo),
             "-vn", "-ac", "2", "-b:a", "128k", str(convertido)],
            capture_output=True, text=True, timeout=120, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return arquivo
    if processo.returncode or not convertido.is_file() or convertido.stat().st_size == 0:
        return arquivo
    arquivo.unlink(missing_ok=True)
    return convertido


def limpar(pasta: Path) -> None:
    """Apaga a pasta de prévia (best-effort: nunca levanta exceção)."""
    try:
        shutil.rmtree(pasta, ignore_errors=True)
    except Exception:
        pass


__all__ = [
    "AnaliseFaixa", "DadosVideo", "ErroPrevia", "Previa", "SEGUNDOS_MAXIMO",
    "SEGUNDOS_PADRAO", "analisar", "limpar", "pasta_para_tocar",
]
