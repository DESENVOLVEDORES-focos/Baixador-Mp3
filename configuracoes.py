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
    """Caminhos locais do aplicativo; não depende do diretório de execução."""

    raiz: Path = field(default_factory=lambda: Path(__file__).resolve().parent)

    @property
    def ferramentas(self) -> Path:
        return self.raiz / "ferramentas"

    @property
    def musicas(self) -> Path:
        return self.raiz / "Musicas"

    @property
    def videos(self) -> Path:
        return self.raiz / "Videos"

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
