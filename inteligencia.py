"""Identificação musical inteligente (IA 2).

Responsabilidade: a partir do título bruto de um vídeo/arquivo (ex.:
``"Queen - Bohemian Rhapsody (Official Video) [dQw4w9WgXcQ]"``), descobrir
artista, título, álbum, ano, gênero, faixa e gravadora consultando bancos
musicais públicos (MusicBrainz, iTunes e Deezer).

Regras do módulo:

- Nenhuma informação factual (álbum, ano, gênero, gravadora) é inventada:
  esses campos só são preenchidos com dados devolvidos pelas APIs.
- A IA (quando configurada) ajuda apenas a *interpretar o título bruto*
  (separar artista/título/participação). Os campos que ela eventualmente
  devolver sobre álbum/ano/gênero são descartados pelo código.
- Falha de uma API não derruba a identificação: os provedores são tentados
  em ordem e os erros ficam registrados em ``IdentificadorMusical.ultimos_erros``.
"""

from __future__ import annotations

import json
import logging
import os
import re
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field, replace
from difflib import SequenceMatcher
from typing import Any, Protocol

log = logging.getLogger("baixador.ia2.inteligencia")

USER_AGENT = (
    "Baixador-Mp3/0.2 (IA2-metadados; "
    "+https://github.com/DESENVOLVEDORES-focos/Baixador-Mp3)"
)


class ErroAPI(RuntimeError):
    """Falha ao consultar uma API musical (rede, HTTP ou JSON inválido)."""


# ---------------------------------------------------------------------------
# Modelos
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ConsultaMusica:
    """O que entendemos do título bruto, antes de consultar as APIs."""

    titulo: str
    artista: str | None = None
    participacao: str | None = None  # "feat."
    bruto: str = ""


@dataclass
class InfoMusica:
    """Informações musicais confirmadas por uma fonte (nunca inventadas)."""

    titulo: str
    artista: str
    album: str | None = None
    ano: int | None = None
    genero: str | None = None
    faixa: int | None = None
    total_faixas: int | None = None
    gravadora: str | None = None
    artista_album: str | None = None
    isrc: str | None = None
    musicbrainz_id: str | None = None
    deezer_album_id: int | None = None
    fonte: str = ""
    confianca: float = 0.0

    def mesclar_faltantes(self, outra: "InfoMusica") -> None:
        """Preenche campos vazios com os de ``outra`` (mesma faixa confirmada)."""
        for campo in (
            "album", "ano", "genero", "faixa", "total_faixas",
            "gravadora", "artista_album", "isrc", "musicbrainz_id",
            "deezer_album_id",
        ):
            if getattr(self, campo) in (None, "") and getattr(outra, campo) not in (None, ""):
                setattr(self, campo, getattr(outra, campo))


# ---------------------------------------------------------------------------
# Cliente HTTP (injetável para testes; padrão usa apenas a stdlib)
# ---------------------------------------------------------------------------


class ClienteHTTP(Protocol):
    def get_json(self, url: str, headers: dict[str, str] | None = None) -> Any: ...

    def post_json(self, url: str, payload: dict[str, Any],
                  headers: dict[str, str] | None = None) -> Any: ...


class ClienteHTTPUrllib:
    """Cliente HTTP mínimo sobre ``urllib`` (sem dependências externas)."""

    def __init__(self, timeout: float = 15.0):
        self.timeout = timeout

    def _abrir(self, requisicao: urllib.request.Request) -> bytes:
        try:
            with urllib.request.urlopen(requisicao, timeout=self.timeout) as resposta:
                return resposta.read()
        except urllib.error.HTTPError as erro:
            raise ErroAPI(f"HTTP {erro.code} ao consultar {requisicao.full_url}") from erro
        except (urllib.error.URLError, TimeoutError, OSError) as erro:
            raise ErroAPI(f"Falha de rede ao consultar {requisicao.full_url}: {erro}") from erro

    def get_json(self, url: str, headers: dict[str, str] | None = None) -> Any:
        requisicao = urllib.request.Request(
            url,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json",
                     **(headers or {})},
            method="GET",
        )
        try:
            return json.loads(self._abrir(requisicao).decode("utf-8", errors="replace"))
        except json.JSONDecodeError as erro:
            raise ErroAPI(f"Resposta JSON inválida de {url}") from erro

    def post_json(self, url: str, payload: dict[str, Any],
                  headers: dict[str, str] | None = None) -> Any:
        corpo = json.dumps(payload).encode("utf-8")
        requisicao = urllib.request.Request(
            url,
            data=corpo,
            headers={"User-Agent": USER_AGENT, "Content-Type": "application/json",
                     "Accept": "application/json", **(headers or {})},
            method="POST",
        )
        try:
            return json.loads(self._abrir(requisicao).decode("utf-8", errors="replace"))
        except json.JSONDecodeError as erro:
            raise ErroAPI(f"Resposta JSON inválida de {url}") from erro

    def get_bytes(self, url: str, limite: int = 15 * 1024 * 1024) -> bytes:
        requisicao = urllib.request.Request(
            url, headers={"User-Agent": USER_AGENT}, method="GET")
        try:
            with urllib.request.urlopen(requisicao, timeout=self.timeout) as resposta:
                dados = resposta.read(limite + 1)
        except urllib.error.HTTPError as erro:
            raise ErroAPI(f"HTTP {erro.code} ao baixar {url}") from erro
        except (urllib.error.URLError, TimeoutError, OSError) as erro:
            raise ErroAPI(f"Falha de rede ao baixar {url}: {erro}") from erro
        if len(dados) > limite:
            raise ErroAPI(f"Conteúdo maior que o limite de {limite} bytes: {url}")
        return dados


# ---------------------------------------------------------------------------
# Interpretação do título bruto (heurística + IA opcional)
# ---------------------------------------------------------------------------

_RUIDOS = (
    "official", "oficial", "video", "vídeo", "music video", "lyric", "lyrics",
    "letra", "audio", "áudio", "clipe", "videoclipe", "hd", "hq", "4k", "1080p",
    "720p", "remaster", "remastered", "remasterizado", "full album", "visualizer",
    "legendado", "tradução", "ao vivo", "live", "session", "performance",
)
_RE_ID_ARQUIVO = re.compile(r"\s\[[A-Za-z0-9_-]{6,}\]$")
_RE_COLCHETES = re.compile(r"\[([^\]]*)\]")
_RE_PARENTESES = re.compile(r"\(([^)]*)\)")
_RE_FEAT = re.compile(
    r"(?i)(?:\(|\[)?\s*(?:feat\.?|ft\.?|featuring|part\.?)\s+([^\)\]\|]+?)\s*(?:\)|\]|$)")
_RE_SEPARADOR = re.compile(r"\s+[-–—]\s+|\s+-\s+|:\s+")


def _sem_ruido(texto: str) -> str:
    """Remove trechos entre parênteses/colchetes que são ruído de título de vídeo."""

    def _avaliar(match: re.Match[str]) -> str:
        conteudo = match.group(1).strip().lower()
        if any(ruido in conteudo for ruido in _RUIDOS):
            return " "
        return f" {match.group(1).strip()} "

    texto = _RE_PARENTESES.sub(_avaliar, texto)
    texto = _RE_COLCHETES.sub(_avaliar, texto)
    return re.sub(r"\s+", " ", texto).strip(" -–—|\"'")


def analisar_titulo(titulo_bruto: str, canal: str | None = None) -> ConsultaMusica:
    """Separa artista/título/participação a partir de um título bruto.

    Aceita o nome do arquivo gerado pelo núcleo (``"Título [id].mp3"``),
    títulos de vídeo (``"Artista - Música (Official Video)"``) e usa o canal
    como artista quando o título não traz separador (canais ``- Topic``).
    """
    bruto = (titulo_bruto or "").strip()
    texto = bruto
    if texto.lower().endswith((".mp3", ".mp4")):
        texto = texto[:-4]
    texto = _RE_ID_ARQUIVO.sub("", texto).strip()

    participacao: str | None = None
    achado_feat = _RE_FEAT.search(texto)
    if achado_feat:
        participacao = achado_feat.group(1).strip(" ,") or None
        texto = (texto[: achado_feat.start()] + texto[achado_feat.end():]).strip()

    texto = _sem_ruido(texto)

    artista: str | None = None
    titulo = texto
    partes = _RE_SEPARADOR.split(texto, maxsplit=1)
    if len(partes) == 2 and partes[0].strip() and partes[1].strip():
        artista, titulo = partes[0].strip(), partes[1].strip()

    if not artista and canal:
        canal_limpo = re.sub(r"(?i)\s*-\s*topic$", "", canal.strip())
        canal_limpo = re.sub(r"(?i)\s*(vevo|official|oficial)$", "", canal_limpo).strip()
        if canal_limpo and canal_limpo.lower() not in {"vários artistas", "various artists"}:
            artista = canal_limpo

    return ConsultaMusica(
        titulo=titulo.strip(" -–—\"'") or bruto,
        artista=(artista or None),
        participacao=participacao,
        bruto=bruto,
    )


def normalizar(texto: str | None) -> str:
    """Normaliza para comparação: minúsculas, sem acentos nem pontuação."""
    if not texto:
        return ""
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    texto = texto.lower().replace("&", " e ")
    texto = re.sub(r"[^a-z0-9]+", " ", texto)
    return re.sub(r"\s+", " ", texto).strip()


def similaridade(a: str | None, b: str | None) -> float:
    na, nb = normalizar(a), normalizar(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    return SequenceMatcher(None, na, nb).ratio()


def _confianca(consulta: ConsultaMusica, titulo: str, artista: str,
               bonus: float = 0.0) -> float:
    nota_titulo = similaridade(consulta.titulo, titulo)
    nota_artista = similaridade(consulta.artista, artista) if consulta.artista else 0.7
    return max(0.0, min(1.0, 0.6 * nota_titulo + 0.35 * nota_artista + bonus))


def _ano_de(data: Any) -> int | None:
    if not data:
        return None
    achado = re.search(r"(1[89]\d{2}|20\d{2})", str(data))
    return int(achado.group(1)) if achado else None


# ---------------------------------------------------------------------------
# Provedores de identificação (APIs públicas, sem chave)
# ---------------------------------------------------------------------------


class ProvedorMusicBrainz:
    """MusicBrainz (musicbrainz.org/ws/2) + IDs p/ Cover Art Archive."""

    nome = "musicbrainz"
    BASE = "https://musicbrainz.org/ws/2/recording/"

    def buscar(self, consulta: ConsultaMusica, cliente: ClienteHTTP) -> list[InfoMusica]:
        partes = [f'recording:"{consulta.titulo}"']
        if consulta.artista:
            partes.append(f'artist:"{consulta.artista}"')
        url = self.BASE + "?" + urllib.parse.urlencode(
            {"query": " AND ".join(partes), "fmt": "json", "limit": 5})
        dados = cliente.get_json(url)
        resultados: list[InfoMusica] = []
        for gravacao in (dados or {}).get("recordings") or []:
            if not isinstance(gravacao, dict):
                continue
            titulo = str(gravacao.get("title") or "").strip()
            creditos = gravacao.get("artist-credit") or []
            artistas = "".join(
                str(c.get("name") or "") + str(c.get("joinphrase") or "")
                for c in creditos if isinstance(c, dict)).strip()
            if not titulo or not artistas:
                continue
            lancamentos = [l for l in (gravacao.get("releases") or []) if isinstance(l, dict)]
            lancamento = lancamentos[0] if lancamentos else {}
            genero = None
            tags = [t for t in (gravacao.get("tags") or []) if isinstance(t, dict)]
            if tags:
                genero = str(max(tags, key=lambda t: t.get("count", 0)).get("name") or "") or None
            gravadora = None
            for info in lancamento.get("label-info") or []:
                rotulo = (info or {}).get("label") or {}
                if rotulo.get("name"):
                    gravadora = str(rotulo["name"])
                    break
            nota_api = 0.0
            try:
                nota_api = float(gravacao.get("score") or 0) / 100.0
            except (TypeError, ValueError):
                pass
            resultados.append(InfoMusica(
                titulo=titulo,
                artista=artistas,
                album=str(lancamento.get("title") or "") or None,
                ano=_ano_de(gravacao.get("first-release-date") or lancamento.get("date")),
                genero=genero.title() if genero else None,
                gravadora=gravadora,
                musicbrainz_id=str(lancamento.get("id") or "") or None,
                fonte=self.nome,
                confianca=_confianca(consulta, titulo, artistas, bonus=0.05 * nota_api),
            ))
        return resultados


class ProvedorITunes:
    """iTunes Search API (sem chave); também é fonte da capa oficial."""

    nome = "itunes"
    BASE = "https://itunes.apple.com/search"

    def buscar(self, consulta: ConsultaMusica, cliente: ClienteHTTP) -> list[InfoMusica]:
        termo = f"{consulta.artista or ''} {consulta.titulo}".strip()
        url = self.BASE + "?" + urllib.parse.urlencode(
            {"term": termo, "media": "music", "entity": "song", "limit": 5})
        dados = cliente.get_json(url)
        resultados: list[InfoMusica] = []
        for item in (dados or {}).get("results") or []:
            if not isinstance(item, dict):
                continue
            titulo = str(item.get("trackName") or "").strip()
            artista = str(item.get("artistName") or "").strip()
            if not titulo or not artista:
                continue
            faixa = item.get("trackNumber")
            total = item.get("trackCount")
            resultados.append(InfoMusica(
                titulo=titulo,
                artista=artista,
                album=str(item.get("collectionName") or "") or None,
                ano=_ano_de(item.get("releaseDate")),
                genero=str(item.get("primaryGenreName") or "") or None,
                faixa=int(faixa) if isinstance(faixa, int) else None,
                total_faixas=int(total) if isinstance(total, int) else None,
                fonte=self.nome,
                confianca=_confianca(consulta, titulo, artista),
            ))
        return resultados


class ProvedorDeezer:
    """Deezer (api.deezer.com, sem chave); álbum dá gênero/gravadora/ano."""

    nome = "deezer"
    BASE = "https://api.deezer.com"

    def buscar(self, consulta: ConsultaMusica, cliente: ClienteHTTP) -> list[InfoMusica]:
        if consulta.artista:
            consulta_api = f'artist:"{consulta.artista}" track:"{consulta.titulo}"'
        else:
            consulta_api = consulta.titulo
        url = f"{self.BASE}/search?" + urllib.parse.urlencode(
            {"q": consulta_api, "limit": 5})
        dados = cliente.get_json(url)
        resultados: list[InfoMusica] = []
        for item in (dados or {}).get("data") or []:
            if not isinstance(item, dict):
                continue
            titulo = str(item.get("title") or "").strip()
            artista = str(((item.get("artist") or {}).get("name")) or "").strip()
            album_info = item.get("album") or {}
            if not titulo or not artista:
                continue
            album_id = album_info.get("id")
            resultados.append(InfoMusica(
                titulo=titulo,
                artista=artista,
                album=str(album_info.get("title") or "") or None,
                deezer_album_id=int(album_id) if isinstance(album_id, int) else None,
                fonte=self.nome,
                confianca=_confianca(consulta, titulo, artista),
            ))
        # Enriquece somente o melhor candidato com dados do álbum (1 chamada extra).
        if resultados:
            melhor = max(resultados, key=lambda r: r.confianca)
            if melhor.deezer_album_id:
                try:
                    album = cliente.get_json(f"{self.BASE}/album/{melhor.deezer_album_id}")
                    if isinstance(album, dict):
                        generos = ((album.get("genres") or {}).get("data")) or []
                        if generos and isinstance(generos[0], dict):
                            melhor.genero = str(generos[0].get("name") or "") or None
                        melhor.gravadora = str(album.get("label") or "") or None
                        melhor.ano = _ano_de(album.get("release_date")) or melhor.ano
                        total = album.get("nb_tracks")
                        melhor.total_faixas = int(total) if isinstance(total, int) else None
                except ErroAPI as erro:
                    log.debug("Deezer: falha ao detalhar álbum: %s", erro)
        return resultados


# ---------------------------------------------------------------------------
# Assistente de IA (opcional): interpreta o título, nunca inventa fatos
# ---------------------------------------------------------------------------


class AssistenteIA(Protocol):
    def interpretar_titulo(self, titulo_bruto: str) -> ConsultaMusica | None: ...


class AssistenteHeuristico:
    """Fallback sem IA externa: usa apenas a heurística local de título."""

    def interpretar_titulo(self, titulo_bruto: str) -> ConsultaMusica | None:
        return analisar_titulo(titulo_bruto)


class AssistenteIAOpenAI:
    """IA via API compatível com OpenAI (chat completions), por variável de ambiente.

    Variáveis: ``BAIXADOR_IA_API_KEY`` (obrigatória), ``BAIXADOR_IA_MODELO``
    (padrão ``gpt-4o-mini``) e ``BAIXADOR_IA_URL`` (padrão API da OpenAI).
    Só extraímos artista/título/participação da resposta; qualquer campo
    factual (álbum, ano, gênero...) devolvido pela IA é ignorado.
    """

    def __init__(self, cliente: ClienteHTTP, api_key: str,
                 modelo: str = "gpt-4o-mini",
                 url: str = "https://api.openai.com/v1/chat/completions"):
        self.cliente = cliente
        self.api_key = api_key
        self.modelo = modelo
        self.url = url

    def interpretar_titulo(self, titulo_bruto: str) -> ConsultaMusica | None:
        prompt = (
            "Extraia artista e título da música deste título de vídeo. "
            "Responda SOMENTE JSON: {\"artista\": \"...\", \"titulo\": \"...\", "
            "\"participacao\": \"... ou null\"}. Não invente álbum, ano ou gênero.\n"
            f"Título: {titulo_bruto}"
        )
        try:
            resposta = self.cliente.post_json(
                self.url,
                {"model": self.modelo,
                 "messages": [{"role": "user", "content": prompt}],
                 "temperature": 0},
                headers={"Authorization": f"Bearer {self.api_key}"},
            )
            conteudo = (resposta["choices"][0]["message"]["content"] or "").strip()
            conteudo = re.sub(r"^```(?:json)?|```$", "", conteudo).strip()
            dados = json.loads(conteudo)
        except (ErroAPI, KeyError, IndexError, TypeError, json.JSONDecodeError) as erro:
            log.debug("Assistente de IA indisponível: %s", erro)
            return None
        titulo = str(dados.get("titulo") or "").strip()
        if not titulo:
            return None
        artista = str(dados.get("artista") or "").strip() or None
        participacao = dados.get("participacao")
        return ConsultaMusica(
            titulo=titulo, artista=artista,
            participacao=str(participacao).strip() if participacao else None,
            bruto=titulo_bruto,
        )


def criar_assistente_padrao(cliente: ClienteHTTP | None = None) -> AssistenteIA:
    """Usa a IA externa se houver chave configurada; senão, a heurística local."""
    api_key = os.environ.get("BAIXADOR_IA_API_KEY", "").strip()
    if api_key:
        return AssistenteIAOpenAI(
            cliente or ClienteHTTPUrllib(),
            api_key,
            modelo=os.environ.get("BAIXADOR_IA_MODELO", "gpt-4o-mini").strip() or "gpt-4o-mini",
            url=os.environ.get(
                "BAIXADOR_IA_URL",
                "https://api.openai.com/v1/chat/completions").strip(),
        )
    return AssistenteHeuristico()


# ---------------------------------------------------------------------------
# Orquestrador da identificação
# ---------------------------------------------------------------------------


class IdentificadorMusical:
    """Consulta os provedores, escolhe o melhor candidato e mescla faltantes."""

    def __init__(self, cliente: ClienteHTTP | None = None,
                 provedores: list[Any] | None = None,
                 limiar: float = 0.55,
                 assistente: AssistenteIA | None = None):
        self.cliente = cliente or ClienteHTTPUrllib()
        self.provedores = provedores if provedores is not None else [
            ProvedorITunes(), ProvedorMusicBrainz(), ProvedorDeezer()]
        self.limiar = limiar
        self.assistente = assistente
        self.ultimos_erros: list[str] = []

    def identificar(self, titulo_bruto: str, canal: str | None = None) -> InfoMusica | None:
        """Identifica a música; devolve ``None`` se nada confiável for achado."""
        self.ultimos_erros = []
        consulta = analisar_titulo(titulo_bruto, canal)
        if self.assistente is not None and not consulta.artista:
            try:
                via_ia = self.assistente.interpretar_titulo(titulo_bruto)
            except Exception as erro:  # IA nunca pode derrubar a identificação
                log.debug("Assistente de IA falhou: %s", erro)
                via_ia = None
            if via_ia is not None and via_ia.titulo:
                consulta = via_ia

        candidatos: list[InfoMusica] = []
        for provedor in self.provedores:
            try:
                candidatos.extend(provedor.buscar(consulta, self.cliente))
            except ErroAPI as erro:
                self.ultimos_erros.append(f"{provedor.nome}: {erro}")
                log.info("Provedor %s indisponível: %s", provedor.nome, erro)
            except Exception as erro:  # provedor inesperado não derruba os demais
                self.ultimos_erros.append(f"{provedor.nome}: {erro}")
                log.info("Provedor %s falhou: %s", provedor.nome, erro)

        if not candidatos:
            return None
        melhor = max(candidatos, key=lambda c: c.confianca)
        if melhor.confianca < self.limiar:
            log.info("Sem candidato confiável (melhor=%.2f) para %r",
                     melhor.confianca, titulo_bruto)
            return None

        # Mescla campos faltantes de outros provedores sobre a MESMA faixa.
        for outro in candidatos:
            if outro is melhor:
                continue
            if (similaridade(outro.titulo, melhor.titulo) >= 0.9
                    and similaridade(outro.artista, melhor.artista) >= 0.9):
                melhor.mesclar_faltantes(outro)
        if consulta.participacao and consulta.artista and melhor.artista:
            if normalizar(consulta.participacao) not in normalizar(melhor.artista):
                log.debug("Participação detectada no título: %s", consulta.participacao)
        return replace(melhor)  # cópia: não expõe o objeto interno dos provedores


__all__ = [
    "AssistenteHeuristico", "AssistenteIA", "AssistenteIAOpenAI", "ClienteHTTP",
    "ClienteHTTPUrllib", "ConsultaMusica", "ErroAPI", "IdentificadorMusical",
    "InfoMusica", "ProvedorDeezer", "ProvedorITunes", "ProvedorMusicBrainz",
    "analisar_titulo", "criar_assistente_padrao", "normalizar", "similaridade",
]
