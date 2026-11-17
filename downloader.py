"""Motor de downloads MP3/MP4 baseado no yt-dlp e FFmpeg."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from configuracoes import CONFIG, Configuracoes, argumentos_cookies

Formato = Literal["mp3", "mp4"]


@dataclass(frozen=True)
class ResultadoDownload:
    url: str
    formato: Formato
    caminho: Path
    iniciado_em: str
    finalizado_em: str
    stdout: str = ""


class ErroDownload(RuntimeError):
    """Falha do yt-dlp ou saída final inválida/incompleta."""

    def __init__(self, mensagem: str, *, codigo: int | None = None, saida: str = ""):
        super().__init__(mensagem)
        self.codigo = codigo
        self.saida = saida


def validar_url(url: str) -> str:
    url = url.strip()
    partes = urlsplit(url)
    if partes.scheme not in {"http", "https"} or not partes.netloc:
        raise ValueError("Informe uma URL http(s) válida para iniciar o download.")
    return url


class Downloader:
    def __init__(self, configuracoes: Configuracoes = CONFIG, timeout: int | None = None):
        self.config = configuracoes
        self.timeout = timeout

    def construir_argumentos(self, url: str, formato: Formato) -> list[str]:
        """Monta argv sem shell; separar esta etapa facilita testes e auditoria."""
        url = validar_url(url)
        if formato not in ("mp3", "mp4"):
            raise ValueError("Formato deve ser 'mp3' ou 'mp4'.")
        destino = self.config.musicas if formato == "mp3" else self.config.videos
        destino.mkdir(parents=True, exist_ok=True)
        cmd = self.config.comando_yt_dlp()
        ffmpeg = self.config.caminho_ffmpeg()
        argumentos = [
            *cmd,
            "--ignore-config",
            "--no-playlist",
            "--no-overwrites",
            "--windows-filenames",
            "--retries", "10",
            "--fragment-retries", "10",
            "--extractor-retries", "5",
            "--socket-timeout", "30",
            "--retry-sleep", "http:exp=1:20",
            "--ffmpeg-location", ffmpeg,
            # Cookies do usuário (Etapa 3), quando importados na interface:
            # só o caminho vai ao yt-dlp local; o conteúdo nunca é lido aqui.
            *argumentos_cookies(self.config),
            "--paths", str(destino),
            "--output", "%(title).180B [%(id)s].%(ext)s",
            # A linha impressa após o processamento permite verificar o arquivo real.
            "--print", "after_move:filepath",
        ]
        if formato == "mp3":
            # Qualidade das preferências (Etapa 3); padrão "0" = melhor,
            # exatamente o comportamento original do núcleo.
            qualidade = str(getattr(self.config, "qualidade_mp3", "0") or "0")
            if not (qualidade.isdigit() or qualidade.upper().endswith("K")):
                qualidade = "0"
            argumentos.extend([
                "--format", "bestaudio/best",
                "--extract-audio",
                "--audio-format", "mp3",
                "--audio-quality", qualidade,
                "--embed-metadata",
            ])
        else:
            argumentos.extend([
                "--format", "bestvideo+bestaudio/best[ext=mp4]/best",
                "--merge-output-format", "mp4",
                "--remux-video", "mp4",
            ])
        argumentos.append(url)
        return argumentos

    def baixar(self, url: str, formato: Formato) -> ResultadoDownload:
        url = validar_url(url)
        self.config.preparar_diretorios()
        argumentos = self.construir_argumentos(url, formato)
        iniciado = datetime.now(timezone.utc).isoformat()
        try:
            processo = subprocess.run(
                argumentos,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as erro:
            saida = _texto(erro.stdout) + _texto(erro.stderr)
            raise ErroDownload("O download excedeu o tempo limite.", saida=saida) from erro
        except OSError as erro:
            raise ErroDownload(f"Não foi possível iniciar o yt-dlp: {erro}") from erro

        saida = "\n".join(parte for parte in (processo.stdout, processo.stderr) if parte)
        if processo.returncode != 0:
            resumo = _resumir_erro(saida) or f"yt-dlp terminou com código {processo.returncode}."
            raise ErroDownload(resumo, codigo=processo.returncode, saida=saida)

        destino = self.config.musicas if formato == "mp3" else self.config.videos
        arquivo = _encontrar_saida(processo.stdout or "", destino, formato)
        if arquivo is None:
            raise ErroDownload(
                "yt-dlp terminou sem erro, mas não foi possível confirmar um arquivo final "
                f"{formato.upper()} válido; o item não será marcado como concluído.",
                codigo=processo.returncode,
                saida=saida,
            )
        return ResultadoDownload(
            url=url,
            formato=formato,
            caminho=arquivo,
            iniciado_em=iniciado,
            finalizado_em=datetime.now(timezone.utc).isoformat(),
            stdout=saida,
        )


def _texto(valor: str | bytes | None) -> str:
    if isinstance(valor, bytes):
        return valor.decode("utf-8", errors="replace")
    return valor or ""


def _resumir_erro(saida: str) -> str:
    linhas = [linha.strip() for linha in saida.splitlines() if line.strip()]
    for linha in reversed(linhas):
        if "error:" in linha.lower() or "erro:" in linha.lower():
            return linha
    return linhas[-1] if linhas else "Falha no yt-dlp sem detalhes de saída."


def _encontrar_saida(stdout: str, destino: Path, formato: Formato) -> Path | None:
    extensoes = {"mp3"} if formato == "mp3" else {"mp4"}
    candidatos: list[Path] = []
    for linha in stdout.splitlines():
        texto = linha.strip().strip('"')
        if not texto:
            continue
        caminho = Path(texto)
        if not caminho.is_absolute():
            caminho = destino / caminho
        if caminho.suffix.lower().lstrip(".") in extensoes:
            candidatos.append(caminho)
    for caminho in reversed(candidatos):
        try:
            if caminho.is_file() and caminho.stat().st_size > 0:
                return caminho.resolve()
        except OSError:
            continue
    return None
