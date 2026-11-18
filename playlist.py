"""Playlists e canais: listar itens **sem baixar** para o usuário escolher.

Motivo (pedido do usuário): baixar playlist inteira de uma vez, escolher vários
vídeos e evitar "surpresa" (shows, covers, faixas repetidas).

- ``listar`` usa ``--flat-playlist -J``: só metadados, nada de mídia.
- Nada é baixado aqui; a interface monta a seleção e manda para a fila.
- Qualquer falha vira ``ErroPlaylist`` com mensagem em português; um item
  quebrado (vídeo privado dentro da playlist) não invalida a lista inteira.
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
from dataclasses import dataclass
from typing import Any

from configuracoes import CONFIG, Configuracoes, argumentos_cookies

log = logging.getLogger("baixador.playlist")

LIMITE_PADRAO = 200      # itens listados (playlists enormes ficam impraticáveis)
LIMITE_MAXIMO = 500


class ErroPlaylist(RuntimeError):
    """URL inválida, playlist privada/vazia ou yt-dlp indisponível."""


@dataclass(frozen=True)
class ItemPlaylist:
    """Um vídeo dentro de uma playlist/canal (somente metadados)."""

    indice: int
    id: str
    titulo: str
    url: str
    duracao: int | None = None
    canal: str = ""
    disponivel: bool = True

    @property
    def duracao_formatada(self) -> str:
        if not self.duracao:
            return "--:--"
        minutos, segundos = divmod(max(0, int(self.duracao)), 60)
        horas, minutos = divmod(minutos, 60)
        return f"{horas}:{minutos:02}:{segundos:02}" if horas else f"{minutos}:{segundos:02}"


@dataclass(frozen=True)
class Playlist:
    """Resultado da listagem."""

    titulo: str
    url: str
    itens: tuple[ItemPlaylist, ...]
    total_informado: int | None = None
    truncada: bool = False
    canal: str = ""

    @property
    def restantes(self) -> int:
        """Itens que existem mas não foram listados (playlist truncada)."""
        if self.total_informado:
            return max(0, self.total_informado - len(self.itens))
        return 0

    @property
    def quantidade(self) -> int:
        return len(self.itens)

    @property
    def duracao_total(self) -> int:
        return sum(item.duracao or 0 for item in self.itens)


def parece_playlist(url: str) -> bool:
    """Heurística local: URL que costuma ser lista, não vídeo único."""
    baixo = (url or "").lower()
    return any(marca in baixo for marca in (
        "list=", "/playlist", "/sets/", "/album/", "/channel/", "/@",
        "/c/", "/user/", "/videos", "/playlists", "music.youtube.com/browse"))


def construir_comando(url: str, limite: int = LIMITE_PADRAO,
                      config: Configuracoes = CONFIG) -> list[str]:
    """argv do yt-dlp para listar a playlist **sem baixar nada**."""
    limite = max(1, min(int(limite or LIMITE_PADRAO), LIMITE_MAXIMO))
    return [
        *config.comando_yt_dlp(),
        "--ignore-config", "--no-warnings", "--skip-download",
        *argumentos_cookies(config),
        "--flat-playlist", "--playlist-end", str(limite),
        "--dump-single-json", url,
    ]


def carregar_json(saida: str) -> dict[str, Any]:
    texto = (saida or "").strip()
    if not texto:
        raise ErroPlaylist("O yt-dlp não devolveu dados da playlist.")
    try:
        dados = json.loads(texto)
    except json.JSONDecodeError:
        inicio = texto.find("{")
        if inicio < 0:
            raise ErroPlaylist("Não foi possível interpretar a resposta do yt-dlp.")
        try:
            dados, _ = json.JSONDecoder().raw_decode(texto[inicio:])
        except json.JSONDecodeError as erro:
            raise ErroPlaylist("Resposta inválida do yt-dlp.") from erro
    if not isinstance(dados, dict):
        raise ErroPlaylist("Formato inesperado na resposta do yt-dlp.")
    return dados


def _duracao(valor: Any) -> int | None:
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        return None
    return int(numero) if numero >= 0 else None


def montar_playlist(dados: dict[str, Any], url: str = "",
                    limite: int = LIMITE_PADRAO) -> Playlist:
    """Transforma o JSON do yt-dlp em ``Playlist`` (tolerante a itens quebrados)."""
    entradas = dados.get("entries")
    if entradas is None:
        # URL de vídeo único: devolve playlist de um item (a interface avisa).
        entradas = [dados]
    itens: list[ItemPlaylist] = []
    for indice, entrada in enumerate(entradas or [], start=1):
        if not isinstance(entrada, dict):
            continue
        identificador = str(entrada.get("id") or "").strip()
        titulo = str(entrada.get("title") or "").strip()
        endereco = str(entrada.get("url") or entrada.get("webpage_url") or "").strip()
        if not endereco and identificador:
            endereco = f"https://www.youtube.com/watch?v={identificador}"
        # Em playlist do YouTube o flat entrega watch?v=…&list=…: o download
        # individual precisa perder o "list" (senão baixa a playlist toda).
        if "watch?" in endereco and "list=" in endereco:
            base, _, consulta = endereco.partition("?")
            partes = [parte for parte in consulta.split("&")
                      if parte and not parte.startswith(("list=", "index=", "start_radio="))]
            endereco = base + ("?" + "&".join(partes) if partes else "")
        if not endereco:
            continue
        # Item indisponível costuma vir como "[Private video]" ou sem título.
        disponivel = bool(titulo) and not re.match(
            r"^\[(?:private|deleted|vídeo removido|unavailable)",
            titulo, re.IGNORECASE)
        itens.append(ItemPlaylist(
            indice=indice,
            id=identificador,
            titulo=titulo or "(item sem título)",
            url=endereco,
            duracao=_duracao(entrada.get("duration")),
            canal=str(entrada.get("channel") or entrada.get("uploader") or ""),
            disponivel=disponivel,
        ))
    total = dados.get("playlist_count") or dados.get("n_entries")
    try:
        total = int(total) if total is not None else None
    except (TypeError, ValueError):
        total = None
    return Playlist(
        titulo=str(dados.get("title") or dados.get("playlist_title") or "").strip(),
        url=str(dados.get("webpage_url") or url or "").strip(),
        canal=str(dados.get("channel") or dados.get("uploader") or "").strip(),
        itens=tuple(itens),
        total_informado=total,
        truncada=bool(total and len(itens) < total) or len(itens) >= limite,
        # Só para a interface avisar honestamente o que ficou de fora.
    )


def listar(url: str, limite: int = LIMITE_PADRAO, config: Configuracoes = CONFIG,
           timeout: int = 120) -> Playlist:
    """Lista os itens da playlist/canal sem baixar mídia."""
    url = (url or "").strip()
    if not url.lower().startswith(("http://", "https://")):
        raise ErroPlaylist("Informe a URL da playlist (começando com http).")
    try:
        processo = subprocess.run(
            construir_comando(url, limite, config), capture_output=True,
            text=True, encoding="utf-8", errors="replace", timeout=timeout,
            check=False)
    except (OSError, subprocess.TimeoutExpired) as erro:
        raise ErroPlaylist(f"Não foi possível listar a playlist: {erro}") from erro
    if processo.returncode:
        detalhes = (processo.stderr or processo.stdout or "").strip()
        ultimo = detalhes.splitlines()[-1] if detalhes else ""
        raise ErroPlaylist(ultimo or f"yt-dlp terminou com código {processo.returncode}.")
    playlist = montar_playlist(carregar_json(processo.stdout), url, limite)
    if not playlist.itens:
        raise ErroPlaylist(
            "A playlist não tem itens acessíveis (privada, vazia ou removida).")
    log.info("Playlist %r: %d item(ns) listado(s).", playlist.titulo,
             playlist.quantidade)
    return playlist


def selecionar(playlist: Playlist, indices: list[int] | None = None,
               apenas_disponiveis: bool = True) -> list[ItemPlaylist]:
    """Filtra os itens escolhidos (índices 1-based, como na tela)."""
    escolhidos = {int(indice) for indice in (indices or [])}
    resultado: list[ItemPlaylist] = []
    for item in playlist.itens:
        if escolhidos and item.indice not in escolhidos:
            continue
        if apenas_disponiveis and not item.disponivel:
            continue
        resultado.append(item)
    return resultado


__all__ = [
    "ErroPlaylist", "ItemPlaylist", "LIMITE_MAXIMO", "LIMITE_PADRAO", "Playlist",
    "construir_comando", "listar", "montar_playlist", "parece_playlist",
    "selecionar",
]
