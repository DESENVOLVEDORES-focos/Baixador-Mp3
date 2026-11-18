"""Pós-processamento de áudio com o FFmpeg que o programa já exige.

Duas coisas que a especificação pede e que o yt-dlp não faz por conta própria:

- **normalização de volume** (``loudnorm``, padrão de streaming EBU R128),
  para não ter faixa baixa e faixa estourada na mesma playlist;
- **verificação do MP3 final**, para o download só ser dado como concluído se
  o arquivo abre e toca de verdade (e não é um arquivo truncado).

Tudo aqui é opcional no uso e obrigatório na honestidade: se o FFmpeg não
estiver disponível, a função devolve ``ok=False`` com o motivo — nunca finge
que normalizou.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("baixador.audio")

# EBU R128: -16 LUFS é o alvo usual de streaming; TP -1.5 dB evita clipping
# depois da conversão para MP3 (que pode passar de 0 dBFS no decode).
ALVO_PADRAO = -16.0
PICO_PADRAO = -1.5


@dataclass(frozen=True)
class ResultadoAudio:
    caminho: Path
    ok: bool
    mensagem: str
    alterado: bool = False


def _executar(comando: list[str], timeout: float) -> tuple[bool, str]:
    try:
        processo = subprocess.run(comando, capture_output=True, text=True,
                                  timeout=timeout, check=False)
    except FileNotFoundError:
        return False, "FFmpeg não encontrado."
    except subprocess.TimeoutExpired:
        return False, f"FFmpeg demorou mais de {timeout:.0f}s."
    saida = (processo.stderr or processo.stdout or "").strip()
    if processo.returncode != 0:
        return False, saida.splitlines()[-1] if saida else (
            f"FFmpeg terminou com código {processo.returncode}.")
    return True, saida


def normalizar(caminho: str | Path, *,
               ffmpeg: str | None = None,
               alvo: float = ALVO_PADRAO,
               pico: float = PICO_PADRAO,
               timeout: float = 600.0) -> ResultadoAudio:
    """Aplica ``loudnorm`` no arquivo, mantendo o MP3 e sem perder as tags.

    A gravação é feita num arquivo temporário ao lado e só substitui o
    original quando o FFmpeg termina sem erro — um arquivo bom nunca é
    destruído por uma normalização interrompida.
    """
    arquivo = Path(caminho)
    if not arquivo.is_file():
        return ResultadoAudio(arquivo, False, "Arquivo não encontrado.")
    if arquivo.suffix.lower() != ".mp3":
        return ResultadoAudio(arquivo, False,
                              "Normalização disponível apenas para MP3.")
    binario = ffmpeg or shutil.which("ffmpeg")
    if not binario:
        return ResultadoAudio(arquivo, False,
                              "FFmpeg não encontrado: nada foi normalizado.")
    temporario = Path(tempfile.mkstemp(prefix="norm-", suffix=".mp3",
                                       dir=str(arquivo.parent))[1])
    try:
        comando = [
            binario, "-hide_banner", "-nostdin", "-y", "-loglevel", "error",
            "-i", str(arquivo),
            "-af", f"loudnorm=I={alvo}:TP={pico}:LRA=11",
            # Copia as tags (o FFmpeg leva ID3 junto na remuxagem).
            "-map_metadata", "0", "-id3v2_version", "3",
            "-codec:a", "libmp3lame", "-q:a", "0",
            str(temporario),
        ]
        ok, mensagem = _executar(comando, timeout)
        if not ok or not temporario.is_file() or temporario.stat().st_size < 1024:
            return ResultadoAudio(arquivo, False,
                                  f"Normalização falhou: {mensagem}")
        temporario.replace(arquivo)
        return ResultadoAudio(arquivo, True,
                              f"Volume normalizado (alvo {alvo:g} LUFS).",
                              alterado=True)
    finally:
        try:
            if temporario.exists():
                temporario.unlink()
        except OSError:
            pass


def duracao(caminho: str | Path, *, ffmpeg: str | None = None,
            timeout: float = 60.0) -> float | None:
    """Duração real do arquivo, lida do FFmpeg (``None`` = não foi possível)."""
    arquivo = Path(caminho)
    if not arquivo.is_file():
        return None
    binario = ffmpeg or shutil.which("ffmpeg")
    if not binario:
        return None
    try:
        processo = subprocess.run(
            [binario, "-hide_banner", "-i", str(arquivo)],
            capture_output=True, text=True, timeout=timeout, check=False)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    for linha in (processo.stderr or "").splitlines():
        if "Duration:" not in linha:
            continue
        trecho = linha.split("Duration:", 1)[1].split(",", 1)[0].strip()
        partes = trecho.split(":")
        if len(partes) != 3:
            continue
        try:
            horas, minutos, segundos = (float(partes[0]), float(partes[1]),
                                        float(partes[2]))
        except ValueError:
            continue
        return round(horas * 3600 + minutos * 60 + segundos, 2)
    return None


def verificar(caminho: str | Path, *, ffmpeg: str | None = None,
              duracao_minima: float = 5.0,
              timeout: float = 120.0) -> ResultadoAudio:
    """Confirma que o MP3 abre e tem áudio — antes de dizer "concluído".

    ``duracao_minima`` descarta o caso clássico de download que falhou no
    final e deixou um arquivo de poucos segundos.
    """
    arquivo = Path(caminho)
    if not arquivo.is_file():
        return ResultadoAudio(arquivo, False, "Arquivo não encontrado.")
    if arquivo.stat().st_size < 4096:
        return ResultadoAudio(arquivo, False,
                              "Arquivo pequeno demais para ser um MP3 válido.")
    binario = ffmpeg or shutil.which("ffmpeg")
    if not binario:
        return ResultadoAudio(arquivo, False,
                              "FFmpeg não encontrado: verificação não feita.")
    comando = [binario, "-hide_banner", "-v", "error", "-i", str(arquivo),
               "-f", "null", "-"]
    ok, mensagem = _executar(comando, timeout)
    if not ok:
        return ResultadoAudio(arquivo, False, f"MP3 inválido: {mensagem}")
    segundos = duracao(arquivo, ffmpeg=binario)
    if segundos is not None and segundos < duracao_minima:
        return ResultadoAudio(
            arquivo, False,
            f"Áudio com apenas {segundos:.1f}s (mínimo {duracao_minima:.0f}s).")
    tempo = "duração desconhecida" if segundos is None else f"{segundos:.1f}s"
    return ResultadoAudio(arquivo, True, f"MP3 verificado ({tempo}).")


__all__ = ["ResultadoAudio", "normalizar", "duracao", "verificar", "ALVO_PADRAO"]
