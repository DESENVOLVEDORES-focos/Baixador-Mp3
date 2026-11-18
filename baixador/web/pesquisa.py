"""Pesquisa real de vídeos **e playlists** usando a busca do yt-dlp.

O usuário digita o nome no próprio programa — não precisa colar link. A mesma
busca devolve vídeos e playlists; a interface mostra o tipo de cada resultado e,
para playlist, um botão que abre a lista para escolher as faixas.
"""

from __future__ import annotations

import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote_plus
from dataclasses import dataclass
from typing import Any

from baixador.nucleo.configuracoes import CONFIG, Configuracoes, argumentos_cookies


@dataclass(frozen=True)
class ResultadoPesquisa:
    id: str
    titulo: str
    canal: str
    duracao: int | None
    url: str
    disponibilidade: str | None = None
    canal_verificado: bool = False
    thumbnail: str = ""
    tipo: str = "video"          # "video" | "playlist" | "canal"
    quantidade: int | None = None  # itens, quando é playlist

    @property
    def eh_playlist(self) -> bool:
        return self.tipo == "playlist"

    @property
    def tipo_legivel(self) -> str:
        if self.tipo == "playlist":
            if self.quantidade:
                return f"Playlist ({self.quantidade} vídeos)"
            return "Playlist"
        if self.tipo == "canal":
            return "Canal"
        return "Vídeo"

    @property
    def duracao_formatada(self) -> str:
        if self.duracao is None:
            return "desconhecida"
        horas, resto = divmod(max(0, self.duracao), 3600)
        minutos, segundos = divmod(resto, 60)
        return f"{horas}:{minutos:02}:{segundos:02}" if horas else f"{minutos}:{segundos:02}"


class ErroPesquisa(RuntimeError):
    pass


# Duração (segundos) acima disto é "compilado/coletânea", não música avulsa.
DURACAO_DE_COMPILADO = 3600


def _slug(texto: str) -> str:
    """Título normalizado para comparar vídeos equivalentes.

    Remove caixa, acento, emoji, "(Official Video)", "[4K]", "HD", "Lyrics" e
    pontuação: ``Oficial`` e ``official`` são o mesmo vídeo. Nada é removido do
    título mostrado ao usuário — isto serve só para deduplicar.
    """
    import re
    import unicodedata

    base = unicodedata.normalize("NFKD", (texto or "").casefold())
    base = "".join(c for c in base if not unicodedata.combining(c))
    # Só o selo de divulgação sai; "(Ao Vivo)", "(Remix)", "(Remastered 2011)"
    # mudam a gravação e continuam contando como outra entrada.
    base = re.sub(r"\b(official|oficial|videoclipe|video|clipe|lyric|lyrics|"
                  r"letra|audio|hd|hq|visualizer|4k|8k)\b", " ", base)
    base = re.sub(r"[^a-z0-9]+", " ", base)
    return " ".join(base.split())


def chave_equivalencia(resultado: "ResultadoPesquisa") -> str:
    """Assinatura que faz dois resultados contarem como o mesmo vídeo."""
    identidade = _slug(resultado.titulo) or (resultado.id or resultado.url)
    return f"{_slug(resultado.canal)}|{identidade}"


def _duracao(resultado: "ResultadoPesquisa") -> int | None:
    return resultado.duracao if resultado.duracao is not None else None


def organizar_resultados(resultados: list["ResultadoPesquisa"],
                         *, remover_equivalentes: bool = True,
                         esconder_compilados: bool = False,
                         exigir_duracao: bool = False,
                         ) -> tuple[list["ResultadoPesquisa"], dict[str, int]]:
    """Ordena e filtra resultados **sem esconder nada sem explicar**.

    Devolve ``(lista, contagem)`` onde ``contagem`` diz quantos foram
    removidos por motivo (``duplicados``, ``compilados``, ``sem_duracao``).

    Regras:
    - vídeo antes de playlist antes de canal (uso mais comum primeiro);
    - canal verificado antes (é evidência vinda do extrator, não palpite);
    - duplicado = mesmo título normalizado no mesmo canal, ou mesmo id;
    - ``esconder_compilados`` remove só o que passa de 1 hora (compilado/mix);
    - ``exigir_duracao`` remove o que não tem duração conhecida.
    """
    contagem = {"duplicados": 0, "compilados": 0, "sem_duracao": 0}
    ordem_tipo = {"video": 0, "playlist": 1, "canal": 2}
    vistos_id: set[str] = set()
    vistos_chave: set[str] = set()
    mantidos: list[ResultadoPesquisa] = []
    for resultado in resultados:
        ident = resultado.id or resultado.url
        if ident and ident in vistos_id:
            contagem["duplicados"] += 1
            continue
        if ident:
            vistos_id.add(ident)
        if remover_equivalentes:
            chave = chave_equivalencia(resultado)
            if chave in vistos_chave:
                contagem["duplicados"] += 1
                continue
            vistos_chave.add(chave)
        if esconder_compilados:
            duracao = _duracao(resultado)
            if duracao is not None and duracao > DURACAO_DE_COMPILADO:
                contagem["compilados"] += 1
                continue
        if exigir_duracao and resultado.tipo == "video" and _duracao(resultado) is None:
            contagem["sem_duracao"] += 1
            continue
        mantidos.append(resultado)
    mantidos.sort(key=lambda r: (ordem_tipo.get(r.tipo, 3),
                                 not r.canal_verificado))
    return mantidos, contagem


def descrever_filtro(contagem: dict[str, int]) -> str:
    """Frase honesta do que foi escondido (vazia quando nada foi)."""
    partes = []
    if contagem.get("duplicados"):
        partes.append(f"{contagem['duplicados']} duplicado(s)")
    if contagem.get("compilados"):
        partes.append(f"{contagem['compilados']} compilado(s) longo(s)")
    if contagem.get("sem_duracao"):
        partes.append(f"{contagem['sem_duracao']} sem duração")
    return ", ".join(partes)


class Pesquisador:
    def __init__(self, configuracoes: Configuracoes = CONFIG, timeout: int = 90):
        self.config = configuracoes
        # Preenchido a cada pesquisa (a tela mostra o que foi filtrado).
        self.ultima_contagem: dict[str, int] = {}
        self.timeout = timeout

    def construir_comando(self, consulta: str, limite: int = 10,
                          tipo: str = "tudo") -> list[str]:
        """argv da pesquisa (isolado p/ testes; inclui cookies).

        ``tipo``: ``tudo`` (vídeos + playlists + canais, o padrão),
        ``videos`` ou ``playlists``. A busca nativa ``ytsearch`` só devolve
        vídeos, então para playlists usamos a página de resultados do YouTube
        com o filtro ``sp=EgIQAw`` (o próprio extrator do yt-dlp entende).
        """
        consulta = consulta.strip()
        if not consulta:
            raise ValueError("Digite termos para pesquisar.")
        if not 1 <= limite <= 50:
            raise ValueError("O limite deve estar entre 1 e 50 resultados.")
        if tipo not in ("tudo", "videos", "playlists"):
            raise ValueError("Tipo de pesquisa inválido.")
        if tipo == "videos":
            alvo = f"ytsearch{limite}:{consulta}"
        elif tipo == "playlists":
            alvo = (f"https://www.youtube.com/results?search_query="
                    f"{quote_plus(consulta)}&sp=EgIQAw%253D%253D")
        else:
            alvo = (f"https://www.youtube.com/results?search_query="
                    f"{quote_plus(consulta)}")
        return [
            *self.config.comando_yt_dlp(),
            "--ignore-config", "--no-warnings", "--skip-download",
            *argumentos_cookies(self.config),
            "--flat-playlist", "--playlist-end", str(limite),
            "--dump-single-json",
            alvo,
        ]

    def pesquisar(self, consulta: str, limite: int = 10,
                  tipo: str = "tudo", *,
                  remover_equivalentes: bool = True,
                  esconder_compilados: bool = False,
                  exigir_duracao: bool = False,
                  ) -> list[ResultadoPesquisa]:
        """Pesquisa no YouTube e devolve vídeos **e** playlists.

        ``tudo`` roda as duas buscas em paralelo (a busca nativa do yt-dlp só
        devolve vídeos; playlists vêm da página de resultados com filtro) e
        mescla sem duplicar. Se uma das duas falhar, a outra ainda entrega.
        """
        consulta = (consulta or "").strip()
        if not consulta:
            raise ValueError("Digite termos para pesquisar.")
        if not 1 <= int(limite) <= 50:
            raise ValueError("O limite deve estar entre 1 e 50 resultados.")
        if tipo in ("videos", "playlists"):
            return self._pesquisar_uma(consulta, limite, tipo)

        limite_playlists = max(3, limite // 2)
        with ThreadPoolExecutor(max_workers=2) as executor:
            futuro_videos = executor.submit(
                self._pesquisar_uma, consulta, limite, "videos")
            futuro_listas = executor.submit(
                self._pesquisar_uma, consulta, limite_playlists, "playlists")
            videos: list[ResultadoPesquisa] = []
            playlists: list[ResultadoPesquisa] = []
            erros: list[Exception] = []
            for futuro, destino in ((futuro_videos, videos),
                                    (futuro_listas, playlists)):
                try:
                    destino.extend(futuro.result())
                except ErroPesquisa as erro:
                    erros.append(erro)
                except Exception as erro:  # nunca deixa a tela sem resposta
                    erros.append(erro)
        if not videos and not playlists and erros:
            raise ErroPesquisa(str(erros[0]))
        mesclados: list[ResultadoPesquisa] = []
        vistos: set[str] = set()

        def acrescentar(itens: list[ResultadoPesquisa]) -> None:
            for item in itens:
                chave = item.id or item.url
                if chave in vistos:
                    continue
                vistos.add(chave)
                mesclados.append(item)

        acrescentar(videos)
        acrescentar(playlists)
        # Canal oficial primeiro dentro de cada grupo, sem inventar nada; aqui
        # também saem os equivalentes (mesmo título/canal com "Official Video").
        organizados, self.ultima_contagem = organizar_resultados(
            mesclados, remover_equivalentes=remover_equivalentes,
            esconder_compilados=esconder_compilados,
            exigir_duracao=exigir_duracao)
        return organizados[:max(limite, limite + limite_playlists)]

    def _pesquisar_uma(self, consulta: str, limite: int,
                       tipo: str) -> list[ResultadoPesquisa]:
        comando = self.construir_comando(consulta, limite, tipo)
        consulta = consulta.strip()
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


def _tipo_do_item(item: dict[str, Any], url: str) -> tuple[str, int | None]:
    """Classifica o resultado da busca em vídeo, playlist ou canal.

    Usa só evidência do extrator (``_type``, ``ie_key``, URL): nada de adivinhar
    pelo título.
    """
    tipo_bruto = str(item.get("_type") or "").lower()
    chave = str(item.get("ie_key") or "").lower()
    quantidade = item.get("playlist_count") or item.get("video_count")
    try:
        quantidade = int(quantidade) if quantidade is not None else None
    except (TypeError, ValueError):
        quantidade = None
    if "list=" in url or (tipo_bruto == "playlist" and "watch" not in url):
        return "playlist", quantidade
    if (chave == "youtubetab" or "/@" in url or "/channel/" in url
            or "/c/" in url or "/user/" in url):
        return "canal", quantidade
    return "video", None


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
    thumbnail = _melhor_thumbnail(item)
    disponibilidade = item.get("availability")
    verificado = item.get("channel_is_verified") is True or item.get("is_verified") is True
    tipo, quantidade = _tipo_do_item(item, url)
    return ResultadoPesquisa(
        id=identificador,
        titulo=titulo,
        canal=canal,
        duracao=duracao,
        url=url,
        disponibilidade=str(disponibilidade) if disponibilidade else None,
        canal_verificado=verificado,
        thumbnail=thumbnail,
        tipo=tipo,
        quantidade=quantidade,
    )


def _melhor_thumbnail(item: dict[str, Any]) -> str:
    """Maior thumbnail disponível no resultado flat, sem baixar nada.

    O ``--flat-playlist`` costuma trazer ``thumbnails`` (lista com largura) ou
    um único ``thumbnail``. Preferimos largura >= 320 para a lista da interface
    e nunca inventamos uma URL: sem dado, devolvemos string vazia.
    """
    lista = item.get("thumbnails")
    if isinstance(lista, list):
        validos = []
        for entrada in lista:
            if not isinstance(entrada, dict):
                continue
            url = str(entrada.get("url") or "").strip()
            if not url:
                continue
            try:
                largura = int(entrada.get("width") or 0)
            except (TypeError, ValueError):
                largura = 0
            if largura >= 320:
                validos.append((largura, url))
        if validos:
            return max(validos)[1]
        for entrada in reversed(lista):
            if isinstance(entrada, dict) and entrada.get("url"):
                return str(entrada["url"])
    url = str(item.get("thumbnail") or "").strip()
    if url:
        return url
    identificador = str(item.get("id") or "").strip()
    # Padrão estável do YouTube (não é invenção: é a URL canônica do vídeo).
    if identificador and len(identificador) == 11 and "/" not in identificador:
        return f"https://i.ytimg.com/vi/{identificador}/mqdefault.jpg"
    return ""
