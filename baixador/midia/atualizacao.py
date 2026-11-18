"""Atualização do yt-dlp pela própria interface.

Motivo prático: quando o YouTube muda algo, o yt-dlp antigo passa a falhar com
"Unable to extract" e o usuário fica sem baixar nada. Antes era preciso abrir o
prompt e digitar comando; agora é um botão.

Regras:
- ``pip`` só é chamado quando o yt-dlp é um **módulo** Python (é o caso da
  instalação feita pelo ``configurar.bat``); um ``yt-dlp.exe`` em ``ferramentas``
  é avisado, não sobrescrito por baixo dos panos.
- Tudo roda sem shell, com timeout, e a saída é resumida (sem despejar página
  de download no log).
- Nunca declara sucesso sem conferir a versão depois.
"""

from __future__ import annotations

import importlib.util
import logging
import subprocess
import sys
from dataclasses import dataclass

from baixador.nucleo.configuracoes import CONFIG, Configuracoes
from baixador.midia.reprodutor import localizar_ffplay

log = logging.getLogger("baixador.atualizacao")

COMANDO_PACOTE = "yt-dlp"

__all__ = ["ResultadoAtualizacao", "atualizar", "versao_instalada",
           "localizar_ffplay"]


@dataclass(frozen=True)
class ResultadoAtualizacao:
    """O que aconteceu, em linguagem de gente."""

    ok: bool
    versao_antes: str
    versao_depois: str
    mensagem: str
    saida: str = ""

    @property
    def mudou(self) -> bool:
        return bool(self.versao_depois) and self.versao_depois != self.versao_antes


def versao_instalada(config: Configuracoes = CONFIG,
                     timeout: int = 60) -> str:
    """Versão do yt-dlp em uso (string vazia se não der para descobrir)."""
    try:
        comando = [*config.comando_yt_dlp(), "--version"]
    except (FileNotFoundError, OSError):
        return ""
    try:
        processo = subprocess.run(
            comando, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    if processo.returncode:
        return ""
    linhas = (processo.stdout or "").strip().splitlines()
    return linhas[0].strip() if linhas else ""


def _usando_modulo(config: Configuracoes) -> bool:
    """True quando o yt-dlp é um pacote Python atualizável por pip.

    Não basta olhar o comando: se existe um ``yt-dlp`` no PATH (inclusive o do
    CI), ele tem prioridade e o textual "-m" não aparece. O que decide é o
    pacote existir de fato — é ele que o pip atualizaria.
    """
    try:
        if importlib.util.find_spec("yt_dlp") is None:
            return False
    except (ImportError, ValueError):
        return False
    try:
        comando = config.comando_yt_dlp()
    except (FileNotFoundError, OSError):
        return False
    # Um .exe/.bin dentro de ferramentas é gerenciado pelo usuário, não pelo pip.
    return not any("ferramentas" in str(parte) for parte in comando)


def _resumir(saida: str, limite: int = 400) -> str:
    """Última parte da saída, sem poluir a tela do usuário."""
    linhas = [linha for linha in (saida or "").splitlines() if linha.strip()]
    texto = " | ".join(linhas[-4:])
    return texto[-limite:]


def atualizar(config: Configuracoes = CONFIG, timeout: int = 300,
              ) -> ResultadoAtualizacao:
    """Atualiza o pacote yt-dlp via pip, com verificação honesta."""
    antes = versao_instalada(config)
    if not _usando_modulo(config):
        return ResultadoAtualizacao(
            ok=False, versao_antes=antes, versao_depois=antes,
            mensagem=("O yt-dlp em uso é um programa separado (pasta "
                      "ferramentas): baixe a versão nova em "
                      "github.com/yt-dlp/yt-dlp/releases e substitua o arquivo. "
                      "A atualização automática só vale para a instalação "
                      "feita pelo configurar.bat."))
    comando = [sys.executable, "-m", "pip", "install", "--upgrade",
               "--disable-pip-version-check", "--no-input", COMANDO_PACOTE]
    log.info("Atualizando %s (antes: %s).", COMANDO_PACOTE, antes or "?")
    try:
        processo = subprocess.run(
            comando, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as erro:
        return ResultadoAtualizacao(
            ok=False, versao_antes=antes, versao_depois=antes,
            mensagem=f"Não foi possível executar a atualização: {erro}")
    depois = versao_instalada(config)
    if processo.returncode:
        detalhe = _resumir(processo.stderr or processo.stdout)
        return ResultadoAtualizacao(
            ok=False, versao_antes=antes, versao_depois=depois,
            mensagem=("A atualização falhou (provavelmente sem internet). "
                      "O programa continua funcionando com a versão atual. "
                      f"Detalhe: {detalhe}" if detalhe else
                      "A atualização falhou (provavelmente sem internet)."),
            saida=detalhe)
    if not depois:
        return ResultadoAtualizacao(
            ok=False, versao_antes=antes, versao_depois="",
            mensagem=("O pip terminou, mas não consegui confirmar a versão "
                      "nova do yt-dlp. Tente abrir o programa de novo."))
    if depois == antes:
        return ResultadoAtualizacao(
            ok=True, versao_antes=antes, versao_depois=depois,
            mensagem=f"Já estava na versão mais nova do yt-dlp ({depois}).")
    log.info("yt-dlp atualizado: %s -> %s.", antes or "?", depois)
    return ResultadoAtualizacao(
        ok=True, versao_antes=antes, versao_depois=depois,
        mensagem=f"yt-dlp atualizado: {antes or '?'} → {depois}.")
