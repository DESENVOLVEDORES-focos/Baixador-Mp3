"""Pesquisa real de vídeos/músicas usando a busca do yt-dlp."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from typing import Any

from configuracoes import CONFIG, Configuracoes


@dataclass(frozen=True)
class ResultadoPesquisa:
    id: str
    titulo: str
    canal: str
    duracao: int | None
    url: str
    disponibilidade: str | None = None
    canal_verificado: bool = False

    @property
    def duracao_formatada(self) -> str:
        if self.duracao is None:
            return "desconhecida"
        horas, resto = divmod(max(0, self.duracao), 3600)
        minutos, segundos = divmod(resto, 60)
        return f"{horas}:{minutos:02}:{segundos:02}" if horas else f"{minutos}:{segundos:02}"


class ErroPesquisa(RuntimeError):
    pass


class Pesquisador:
    def __init__(self, configuracoes: Configuracoes = CONFIG, timeout: int = 90):
        self.config = configuracoes
        self.timeout = timeout

    def pesquisar(self, consulta: str, limite: int = 10) -> list[ResultadoPesquisa]:
        consulta = consulta.strip()
        if not consulta:
            raise ValueError("Digite termos para pesquisar.")
        if not 1 <= limite <= 50:
            raise ValueError("O limite deve estar entre 1 e 50 resultados.")
        comando = [
            *self.config.comando_yt_dlp(),
            "--ignore-config", "--no-warnings", "--skip-download",
            "--flat-playlist", "--dump-single-json",
            f"ytsearch{limite}:{consulta}",
        ]
        try:
            processo = subprocess.run(
                comando, capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=self.timeout, check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as erro:
            raise ErroPesquisa(f"Não foi possível completar a pesquisa: {erro}") from erro
        if processo.returncode:
            detalhes = (processo.stderr or processo.stdout).strip()
            raise ErroPesquisa(detalhes or f"yt-dlp terminou com código {processo.returncode}.")
        dados = _carregar_json(processo.stdout)
        entradas = dados.get("entries") or [dados]
        resultados: list[ResultadoPesquisa] = []
        vistos: set[str] = set()
        for item in entradas:
            if not isinstance(item, dict):
                continue
            resultado = _converter_item(item)
            if resultado is None:
                continue
            chave = resultado.id or resultado.url
            if chave in vistos:
                continue
            vistos.add(chave)
            resultados.append(resultado)
        # Só prioriza canal oficial quando o extrator fornece evidência explícita.
        resultados.sort(key=lambda resultado: not resultado.canal_verificado)
        return resultados[:limite]


def _carregar_json(saida: str) -> dict[str, Any]:
    texto = saida.strip()
    if not texto:
        raise ErroPesquisa("A pesquisa não retornou resultados nem dados JSON.")
    try:
        dados = json.loads(texto)
    except json.JSONDecodeError as erro:
        # Alguns extratores podem escrever mensagens antes do objeto JSON.
        inicio = texto.find("{")
        if inicio < 0:
            raise ErroPesquisa("Não foi possível interpretar os resultados do yt-dlp.") from erro
        try:
            dados, _ = json.JSONDecoder().raw_decode(texto[inicio:])
        except json.JSONDecodeError as erro_json:
            raise ErroPesquisa("Resposta JSON inválida do yt-dlp.") from erro_json
    if not isinstance(dados, dict):
        raise ErroPesquisa("Formato inesperado nos resultados do yt-dlp.")
    return dados


def _converter_item(item: dict[str, Any]) -> ResultadoPesquisa | None:
    titulo = str(item.get("title") or "").strip()
    identificador = str(item.get("id") or "").strip()
    url = str(item.get("webpage_url") or item.get("url") or "").strip()
    if not url and identificador:
        # O resultado flat do YouTube retorna somente o id; essa URL aponta ao item encontrado.
        url = f"https://www.youtube.com/watch?v={identificador}"
    if not titulo or not url:
        return None
    duracao_bruta = item.get("duration")
    try:
        duracao = int(float(duracao_bruta)) if duracao_bruta is not None else None
    except (TypeError, ValueError, OverflowError):
        duracao = None
    canal = str(item.get("channel") or item.get("uploader") or item.get("channel_id") or "Canal desconhecido")
    disponibilidade = item.get("availability")
    verificado = item.get("channel_is_verified") is True or item.get("is_verified") is True
    return ResultadoPesquisa(
        id=identificador,
        titulo=titulo,
        canal=canal,
        duracao=duracao,
        url=url,
        disponibilidade=str(disponibilidade) if disponibilidade else None,
        canal_verificado=verificado,
    )
