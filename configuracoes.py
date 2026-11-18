"""Configuração e descoberta das ferramentas do Baixador-Mp3."""

from __future__ import annotations

import importlib.util
import os
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Configuracoes:
    """Caminhos locais do aplicativo; não depende do diretório de execução.

    Os campos opcionais (Etapa 3) vêm das preferências do usuário salvas
    pela interface (``preferencias.py``); sem eles, vale o comportamento
    original: ``Musicas/``, ``Videos/``, sem cookies e qualidade ``0``.
    """

    raiz: Path = field(default_factory=lambda: Path(__file__).resolve().parent)
    diretorio_musicas: Path | None = None
    diretorio_videos: Path | None = None
    caminho_cookies: Path | None = None
    qualidade_mp3: str = "0"
    # Política quando o arquivo final já existe: pular (padrão, não sobrescreve),
    # renomear (cria "nome (2).mp3") ou sobrescrever (só com autorização explícita).
    sobrescrita: str = "pular"
    # Nome "Artista - Título.ext" ao publicar (o yt-dlp baixa com ID; o nome
    # apresentável é aplicado só no fim, depois da identificação musical).
    organizar_nomes: bool = False
    # Usar Artista/Álbum/ confirmados pela identificação como subpasta.
    organizar_por_album: bool = False
    # Pós-processamento do MP3 com o FFmpeg do programa (audio.py).
    normalizar_volume: bool = False
    verificar_audio: bool = True
    # Teto de duração por item, em minutos (0 = sem limite).
    duracao_maxima_min: int = 0

    @property
    def ferramentas(self) -> Path:
        return self.raiz / "ferramentas"

    @property
    def musicas(self) -> Path:
        return self.diretorio_musicas or self.raiz / "Musicas"

    @property
    def videos(self) -> Path:
        return self.diretorio_videos or self.raiz / "Videos"

    def resolver_cookies(self) -> Path | None:
        """Arquivo de cookies do yt-dlp, sem nunca expor o conteúdo.

        Ordem: caminho configurado (interface), variável
        ``BAIXADOR_COOKIES`` e a cópia gerenciada em ``<dados>/cookies.txt``.
        Só devolve caminho existente; ``None`` = baixar sem cookies.
        """
        candidatos: list[Path] = []
        if self.caminho_cookies:
            candidatos.append(Path(self.caminho_cookies).expanduser())
        ambiente = os.environ.get("BAIXADOR_COOKIES", "").strip()
        if ambiente:
            candidatos.append(Path(ambiente).expanduser())
        # Cópia gerenciada pela interface e também o arquivo solto na pasta do
        # programa: quem baixa o cookies.txt do navegador costuma deixá-lo ali.
        candidatos.append(self.dados / "cookies.txt")
        candidatos.append(self.raiz / "cookies.txt")
        for candidato in candidatos:
            try:
                if candidato.is_file():
                    return candidato.resolve()
            except OSError:
                continue
        return None

    @property
    def dados(self) -> Path:
        override = os.environ.get("BAIXADOR_DATA_DIR")
        return Path(override).expanduser().resolve() if override else self.raiz / ".baixador"

    @property
    def fila(self) -> Path:
        return self.dados / "fila.json"

    @property
    def historico(self) -> Path:
        return self.dados / "historico.jsonl"

    @property
    def erros(self) -> Path:
        return self.dados / "erros.jsonl"

    def preparar_diretorios(self) -> None:
        for caminho in (self.musicas, self.videos, self.dados):
            caminho.mkdir(parents=True, exist_ok=True)

    def comando_yt_dlp(self) -> list[str]:
        """Retorna o executável instalado ou o fallback ``python -m yt_dlp``."""
        candidatos = (
            self.ferramentas / "yt-dlp.exe",
            self.ferramentas / "yt-dlp",
        )
        for candidato in candidatos:
            if candidato.is_file():
                return [str(candidato)]
        instalado = shutil.which("yt-dlp") or shutil.which("yt-dlp.exe")
        if instalado:
            return [instalado]
        if importlib.util.find_spec("yt_dlp") is not None:
            return [os.environ.get("PYTHON", sys.executable), "-m", "yt_dlp"]
        raise FileNotFoundError(
            "yt-dlp não encontrado. Instale com 'python -m pip install yt-dlp' "
            "ou coloque yt-dlp.exe na pasta ferramentas."
        )

    def caminho_ffmpeg(self) -> str:
        """Localiza FFmpeg; yt-dlp usa o executável ou seu diretório."""
        for nome in ("ffmpeg.exe", "ffmpeg"):
            candidato = self.ferramentas / nome
            if candidato.is_file():
                return str(candidato)
        instalado = shutil.which("ffmpeg") or shutil.which("ffmpeg.exe")
        if instalado:
            return instalado
        raise FileNotFoundError(
            "FFmpeg não encontrado. Instale-o e adicione ao PATH, "
            "ou coloque ffmpeg.exe na pasta ferramentas."
        )

    def verificar_dependencias(self, *, requer_ffmpeg: bool = True) -> dict[str, str]:
        encontradas: dict[str, str] = {}
        ausentes: list[str] = []
        verificacoes = [("yt-dlp", self.comando_yt_dlp)]
        if requer_ffmpeg:
            verificacoes.append(("ffmpeg", self.caminho_ffmpeg))
        for nome, localizar in verificacoes:
            try:
                valor = localizar()
                encontradas[nome] = " ".join(valor) if isinstance(valor, list) else valor
            except FileNotFoundError as erro:
                ausentes.append(str(erro))
        if ausentes:
            raise FileNotFoundError("\n".join(ausentes))
        return encontradas


CONFIG = Configuracoes()


def argumentos_cookies(configuracoes: object) -> list[str]:
    """``["--cookies", caminho]`` para o yt-dlp, ou ``[]`` sem cookies.

    Aceita qualquer objeto de configuração (inclusive os fakes de teste):
    usa ``resolver_cookies()`` quando existir e nunca registra o conteúdo
    do arquivo — apenas o caminho é passado ao yt-dlp, como credencial
    local do próprio usuário.
    """
    resolver = getattr(configuracoes, "resolver_cookies", None)
    caminho: Path | None = None
    if callable(resolver):
        try:
            caminho = resolver()
        except Exception:
            caminho = None
    if caminho is None:
        direto = getattr(configuracoes, "caminho_cookies", None)
        if direto and Path(direto).is_file():
            caminho = Path(direto)
    return ["--cookies", str(caminho)] if caminho else []
