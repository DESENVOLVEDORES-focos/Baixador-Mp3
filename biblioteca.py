"""Biblioteca musical local (SQLite): músicas, playlists, favoritos, pesquisas.

É a fonte de verdade do aplicativo: o que está no disco em ``Musicas/`` é
indexado aqui com as tags reais do arquivo (lidas com Mutagen), e o banco guarda
o que o disco não guarda — playlists locais, favoritos, histórico de pesquisas e
as datas de cada operação.

Regras:
- **Nada inventado**: campo que o arquivo não tem fica vazio no banco. A
  identificação com IA/APIs continua sendo feita por ``metadados.py`` e o que ela
  confirmar é que entra aqui.
- O caminho é a chave única: reindexar a mesma pasta não duplica música.
- Uma conexão SQLite por operação, com ``check_same_thread=False`` e um lock:
  a interface usa threads de download e de interface ao mesmo tempo.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import unicodedata
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator

from configuracoes import CONFIG, Configuracoes

log = logging.getLogger("baixador.biblioteca")

EXTENSOES = (".mp3",)
ORDENACOES = {
    "titulo": "titulo COLLATE NOCASE",
    "artista": "artista COLLATE NOCASE, titulo COLLATE NOCASE",
    "album": "album COLLATE NOCASE, faixa, titulo COLLATE NOCASE",
    "ano": "ano DESC, titulo COLLATE NOCASE",
    "genero": "genero COLLATE NOCASE, artista COLLATE NOCASE",
    "adicionada": "adicionada_em DESC",
    "duracao": "duracao DESC",
    "duracao_curta": "duracao ASC",
    "recentes": "adicionada_em DESC",
    "favoritos": "favorito DESC, titulo COLLATE NOCASE",
    "artista_ano": "artista COLLATE NOCASE, ano DESC, titulo COLLATE NOCASE",
}

_ESQUEMA = """
CREATE TABLE IF NOT EXISTS musicas (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    caminho       TEXT NOT NULL UNIQUE,
    titulo        TEXT NOT NULL DEFAULT '',
    artista       TEXT NOT NULL DEFAULT '',
    album         TEXT NOT NULL DEFAULT '',
    ano           TEXT NOT NULL DEFAULT '',
    genero        TEXT NOT NULL DEFAULT '',
    faixa         TEXT NOT NULL DEFAULT '',
    duracao       REAL,
    tamanho       INTEGER,
    tem_capa      INTEGER NOT NULL DEFAULT 0,
    favorito      INTEGER NOT NULL DEFAULT 0,
    origem_url    TEXT NOT NULL DEFAULT '',
    chave_titulo  TEXT NOT NULL DEFAULT '',
    chave_artista TEXT NOT NULL DEFAULT '',
    chave_album   TEXT NOT NULL DEFAULT '',
    adicionada_em TEXT NOT NULL,
    atualizada_em TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_musicas_artista ON musicas(artista);
CREATE INDEX IF NOT EXISTS idx_musicas_chave ON musicas(chave_titulo, chave_artista, chave_album);
CREATE INDEX IF NOT EXISTS idx_musicas_album ON musicas(album);

CREATE TABLE IF NOT EXISTS playlists (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    nome       TEXT NOT NULL UNIQUE COLLATE NOCASE,
    criada_em  TEXT NOT NULL,
    atualizada_em TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS playlist_itens (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    playlist_id INTEGER NOT NULL REFERENCES playlists(id) ON DELETE CASCADE,
    musica_id   INTEGER NOT NULL REFERENCES musicas(id) ON DELETE CASCADE,
    posicao     INTEGER NOT NULL DEFAULT 0,
    UNIQUE(playlist_id, musica_id)
);

CREATE TABLE IF NOT EXISTS favoritos (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    tipo      TEXT NOT NULL,
    chave     TEXT NOT NULL,
    criado_em TEXT NOT NULL,
    UNIQUE(tipo, chave)
);

CREATE TABLE IF NOT EXISTS pesquisas (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    consulta TEXT NOT NULL,
    tipo    TEXT NOT NULL DEFAULT 'tudo',
    quando  TEXT NOT NULL
);
"""


def agora() -> str:
    return datetime.now(timezone.utc).isoformat()


def _dias_atras(dias: int) -> str:
    """Data ISO de ``dias`` atrás (usada no filtro "adicionadas nos últimos N")."""
    momento = datetime.now(timezone.utc) - timedelta(days=max(0, int(dias)))
    return momento.isoformat()


def chave_busca(texto: str) -> str:
    """Busca tolerante: "Legiao" acha "Legião", "AC/DC" acha "ACDC"."""
    decomposto = unicodedata.normalize("NFKD", texto or "")
    return "".join(c for c in decomposto if not unicodedata.combining(c)).casefold()


@dataclass(frozen=True)
class Musica:
    """Uma linha da biblioteca (o arquivo no disco + o que sabemos dele)."""

    id: int
    caminho: str
    titulo: str
    artista: str
    album: str
    ano: str
    genero: str
    faixa: str
    duracao: float | None
    tamanho: int | None
    tem_capa: bool
    favorito: bool
    origem_url: str
    adicionada_em: str
    atualizada_em: str

    @property
    def arquivo(self) -> Path:
        return Path(self.caminho)

    @property
    def existe(self) -> bool:
        return self.arquivo.is_file()

    @property
    def duracao_formatada(self) -> str:
        if not self.duracao:
            return "--:--"
        minutos, segundos = divmod(int(self.duracao), 60)
        horas, minutos = divmod(minutos, 60)
        return (f"{horas}:{minutos:02}:{segundos:02}" if horas
                else f"{minutos}:{segundos:02}")

    @property
    def titulo_exibicao(self) -> str:
        return self.titulo or self.arquivo.stem


def _linha_para_musica(linha: sqlite3.Row) -> Musica:
    return Musica(
        id=int(linha["id"]),
        caminho=str(linha["caminho"]),
        titulo=str(linha["titulo"] or ""),
        artista=str(linha["artista"] or ""),
        album=str(linha["album"] or ""),
        ano=str(linha["ano"] or ""),
        genero=str(linha["genero"] or ""),
        faixa=str(linha["faixa"] or ""),
        duracao=float(linha["duracao"]) if linha["duracao"] is not None else None,
        tamanho=int(linha["tamanho"]) if linha["tamanho"] is not None else None,
        tem_capa=bool(linha["tem_capa"]),
        favorito=bool(linha["favorito"]),
        origem_url=str(linha["origem_url"] or ""),
        adicionada_em=str(linha["adicionada_em"] or ""),
        atualizada_em=str(linha["atualizada_em"] or ""),
    )


def ler_tags(caminho: Path) -> dict[str, Any]:
    """Lê tags e duração reais do arquivo; ``{}`` quando não dá para ler."""
    caminho = Path(caminho)
    dados: dict[str, Any] = {}
    try:
        from metadados import ler_metadados

        dados.update(ler_metadados(caminho))
    except Exception as erro:  # arquivo corrompido não derruba a indexação
        log.info("Tags ilegíveis em %s: %s", caminho.name, erro)
    try:
        import mutagen

        arquivo = mutagen.File(str(caminho))
        if arquivo is not None and getattr(arquivo.info, "length", None):
            dados["duracao"] = float(arquivo.info.length)
    except Exception:
        pass
    return dados


class Biblioteca:
    """Índice local de músicas, playlists, favoritos e pesquisas."""

    def __init__(self, configuracoes: Configuracoes = CONFIG,
                 caminho: Path | None = None):
        self.config = configuracoes
        self._caminho = Path(caminho) if caminho else configuracoes.dados / "biblioteca.db"
        self._lock = threading.RLock()
        self._caminho.parent.mkdir(parents=True, exist_ok=True)
        self._criar_esquema()

    # -- infraestrutura -----------------------------------------------------
    @property
    def caminho(self) -> Path:
        return self._caminho

    @contextmanager
    def _conexao(self) -> Iterator[sqlite3.Connection]:
        conexao = sqlite3.connect(str(self._caminho), timeout=10,
                                  check_same_thread=False)
        conexao.row_factory = sqlite3.Row
        conexao.execute("PRAGMA foreign_keys = ON")
        try:
            yield conexao
            conexao.commit()
        except Exception:
            conexao.rollback()
            raise
        finally:
            conexao.close()

    def _criar_esquema(self) -> None:
        with self._lock, self._conexao() as conexao:
            conexao.executescript(_ESQUEMA)

    # -- músicas ------------------------------------------------------------
    def adicionar(self, caminho: str | Path, *, dados: dict[str, Any] | None = None,
                  origem_url: str = "") -> Musica:
        """Insere ou atualiza uma música pela tags do arquivo.

        ``dados`` sobrescreve o que vier das tags (usado quando a identificação
        acabou de gravar os metadados e já sabemos o resultado).
        """
        caminho = Path(caminho).resolve()
        tags = ler_tags(caminho) if caminho.is_file() else {}
        if dados:
            tags.update({chave: valor for chave, valor in dados.items()
                         if valor not in (None, "")})
        tamanho = caminho.stat().st_size if caminho.is_file() else None
        momento = agora()
        campos = {
            "caminho": str(caminho),
            "titulo": str(tags.get("titulo") or "").strip(),
            "artista": str(tags.get("artista") or "").strip(),
            "album": str(tags.get("album") or "").strip(),
            "ano": str(tags.get("ano") or "").strip(),
            "genero": str(tags.get("genero") or "").strip(),
            "faixa": str(tags.get("faixa") or "").strip(),
            "duracao": tags.get("duracao"),
            "tamanho": tamanho,
            "tem_capa": 1 if tags.get("tem_capa") else 0,
            "origem_url": origem_url,
            # Chaves sem acento/minúsculas: permitem buscar "legiao" e achar
            # "Legião" direto no SQL (antes a busca dependia de acento exato).
            "chave_titulo": chave_busca(str(tags.get("titulo") or "")),
            "chave_artista": chave_busca(str(tags.get("artista") or "")),
            "chave_album": chave_busca(str(tags.get("album") or "")),
            "atualizada_em": momento,
        }
        with self._lock, self._conexao() as conexao:
            existente = conexao.execute(
                "SELECT id FROM musicas WHERE caminho = ?", (campos["caminho"],)
            ).fetchone()
            if existente:
                partes = ", ".join(f"{chave} = ?" for chave in campos)
                conexao.execute(
                    f"UPDATE musicas SET {partes} WHERE id = ?",
                    (*campos.values(), int(existente["id"])))
                identidade = int(existente["id"])
            else:
                campos["adicionada_em"] = momento
                colunas = ", ".join(campos)
                marcas = ", ".join("?" for _ in campos)
                cursor = conexao.execute(
                    f"INSERT INTO musicas ({colunas}) VALUES ({marcas})",
                    tuple(campos.values()))
                identidade = int(cursor.lastrowid or 0)
        return self.obter(identidade)  # type: ignore[return-value]

    def obter(self, musica_id: int) -> Musica | None:
        with self._lock, self._conexao() as conexao:
            linha = conexao.execute(
                "SELECT * FROM musicas WHERE id = ?", (int(musica_id),)).fetchone()
        return _linha_para_musica(linha) if linha else None

    def por_caminho(self, caminho: str | Path) -> Musica | None:
        with self._lock, self._conexao() as conexao:
            linha = conexao.execute(
                "SELECT * FROM musicas WHERE caminho = ?",
                (str(Path(caminho).resolve()),)).fetchone()
        return _linha_para_musica(linha) if linha else None

    def listar(self, *, ordenar: str = "titulo", texto: str = "",
               artista: str = "", album: str = "", genero: str = "",
               somente_favoritos: bool = False, limite: int | None = None,
               ano: str = "", sem_capa: bool = False,
               sem_metadados: bool = False, dias: int = 0,
               duracao_min: int = 0, duracao_max: int = 0,
               ) -> list[Musica]:
        """Lista com busca tolerante a acento e filtros combináveis."""
        ordenacao = ORDENACOES.get(ordenar, ORDENACOES["titulo"])
        partes = ["1 = 1"]
        valores: list[Any] = []
        if texto:
            alvo = f"%{chave_busca(texto)}%"
            partes.append("(chave_titulo LIKE ? OR chave_artista LIKE ?"
                          " OR chave_album LIKE ?)")
            valores.extend([alvo, alvo, alvo])
        if artista:
            partes.append("artista = ?")
            valores.append(artista)
        if album:
            partes.append("album = ?")
            valores.append(album)
        if genero:
            partes.append("genero LIKE ?")
            valores.append(f"%{genero}%")
        if somente_favoritos:
            partes.append("favorito = 1")
        if ano:
            partes.append("ano = ?")
            valores.append(str(ano))
        if sem_capa:
            partes.append("tem_capa = 0")
        if sem_metadados:
            partes.append("(artista = '' OR album = '' OR artista IS NULL"
                          " OR album IS NULL)")
        if dias:
            partes.append("adicionada_em >= ?")
            valores.append(_dias_atras(int(dias)))
        if duracao_min:
            partes.append("duracao >= ?")
            valores.append(int(duracao_min))
        if duracao_max:
            partes.append("duracao <= ?")
            valores.append(int(duracao_max))
        consulta = ("SELECT * FROM musicas WHERE "
                    f"{' AND '.join(partes)} ORDER BY {ordenacao}")
        if limite:
            consulta += f" LIMIT {int(limite)}"
        with self._lock, self._conexao() as conexao:
            linhas = conexao.execute(consulta, valores).fetchall()
        return [_linha_para_musica(linha) for linha in linhas]

    def atualizar(self, musica_id: int, **campos: Any) -> Musica | None:
        """Atualiza colunas conhecidas (metadados editados na tela)."""
        permitidos = {"titulo", "artista", "album", "ano", "genero", "faixa",
                      "origem_url", "favorito", "tem_capa", "duracao",
                      "tamanho"}
        dados = {c: v for c, v in campos.items() if c in permitidos}
        if not dados:
            return self.obter(musica_id)
        dados["atualizada_em"] = agora()
        partes = ", ".join(f"{chave} = ?" for chave in dados)
        with self._lock, self._conexao() as conexao:
            conexao.execute(f"UPDATE musicas SET {partes} WHERE id = ?",
                            (*dados.values(), int(musica_id)))
        return self.obter(musica_id)

    def remover(self, musica_id: int, *, apagar_arquivo: bool = False) -> bool:
        musica = self.obter(musica_id)
        if musica is None:
            return False
        with self._lock, self._conexao() as conexao:
            conexao.execute("DELETE FROM musicas WHERE id = ?", (int(musica_id),))
        if apagar_arquivo:
            try:
                musica.arquivo.unlink(missing_ok=True)
            except OSError as erro:
                log.info("Não foi possível apagar %s: %s", musica.caminho, erro)
                return False
        return True

    def alternar_favorito(self, musica_id: int) -> bool:
        musica = self.obter(musica_id)
        if musica is None:
            return False
        novo = 0 if musica.favorito else 1
        with self._lock, self._conexao() as conexao:
            conexao.execute(
                "UPDATE musicas SET favorito = ?, atualizada_em = ? WHERE id = ?",
                (novo, agora(), int(musica_id)))
        return bool(novo)

    def contar(self) -> int:
        with self._lock, self._conexao() as conexao:
            linha = conexao.execute("SELECT COUNT(*) AS total FROM musicas").fetchone()
        return int(linha["total"] if linha else 0)

    # -- indexação do disco -------------------------------------------------
    def pastas(self) -> list[Path]:
        return [self.config.musicas]

    def sincronizar(self, *, remover_ausentes: bool = False) -> dict[str, int]:
        """Indexa os MP3 das pastas do programa, lendo as tags reais.

        Não apaga nada do disco. ``remover_ausentes`` só tira do banco as
        entradas cujo arquivo não existe mais.
        """
        encontrados = 0
        novos = 0
        atualizados = 0
        vistos: set[str] = set()
        for pasta in self.pastas():
            if not pasta.is_dir():
                continue
            for arquivo in sorted(pasta.rglob("*.mp3")):
                if not arquivo.is_file():
                    continue
                encontrados += 1
                caminho = str(arquivo.resolve())
                vistos.add(caminho)
                antes = self.por_caminho(caminho)
                self.adicionar(caminho)
                if antes is None:
                    novos += 1
                else:
                    atualizados += 1
        removidos = 0
        if remover_ausentes:
            with self._lock, self._conexao() as conexao:
                linhas = conexao.execute("SELECT id, caminho FROM musicas").fetchall()
                ausentes = [int(l["id"]) for l in linhas
                            if str(l["caminho"]) not in vistos
                            and not Path(str(l["caminho"])).is_file()]
                for identidade in ausentes:
                    conexao.execute("DELETE FROM musicas WHERE id = ?", (identidade,))
                removidos = len(ausentes)
        log.info("Biblioteca: %d arquivo(s), %d novo(s), %d atualizado(s), %d removido(s).",
                 encontrados, novos, atualizados, removidos)
        return {"encontrados": encontrados, "novos": novos,
                "atualizados": atualizados, "removidos": removidos}

    # -- agregações ---------------------------------------------------------
    def artistas(self) -> list[dict[str, Any]]:
        return self._agregar("artista")

    def albuns(self) -> list[dict[str, Any]]:
        with self._lock, self._conexao() as conexao:
            linhas = conexao.execute(
                "SELECT album, artista, COUNT(*) AS total,"
                " COALESCE(SUM(duracao), 0) AS duracao,"
                " MAX(ano) AS ano FROM musicas WHERE album <> ''"
                " GROUP BY album, artista ORDER BY album COLLATE NOCASE"
            ).fetchall()
        return [dict(linha) for linha in linhas]

    def generos(self) -> list[dict[str, Any]]:
        return self._agregar("genero")

    def _agregar(self, coluna: str) -> list[dict[str, Any]]:
        with self._lock, self._conexao() as conexao:
            linhas = conexao.execute(
                f"SELECT {coluna} AS nome, COUNT(*) AS total,"
                f" COALESCE(SUM(duracao), 0) AS duracao FROM musicas"
                f" WHERE {coluna} <> '' GROUP BY {coluna}"
                f" ORDER BY {coluna} COLLATE NOCASE").fetchall()
        return [dict(linha) for linha in linhas]

    def duplicatas(self) -> list[list[Musica]]:
        """Mesmo título + artista em arquivos diferentes (para o usuário decidir)."""
        with self._lock, self._conexao() as conexao:
            linhas = conexao.execute(
                "SELECT * FROM musicas WHERE titulo <> '' AND artista <> ''"
                " ORDER BY titulo, artista").fetchall()
        grupos: dict[tuple[str, str], list[Musica]] = {}
        for linha in linhas:
            musica = _linha_para_musica(linha)
            chave = (chave_busca(musica.titulo).strip(),
                     chave_busca(musica.artista).strip())
            grupos.setdefault(chave, []).append(musica)
        return [grupo for grupo in grupos.values() if len(grupo) > 1]

    def contar_filtrado(self, **filtros: Any) -> int:
        """Quantas músicas o filtro pega (a tela mostra antes de listar)."""
        return len(self.listar(**filtros))

    def facetas(self) -> dict[str, list[dict[str, Any]]]:
        """Valores para os menus de filtro, com contagem, em uma consulta cada."""
        def agrupar(coluna: str, ordem: str = "") -> list[dict[str, Any]]:
            # Consulta separada por faceta: a conexão vive só dentro do bloco
            # (reutilizá-la depois do ``with`` fecha o cursor silenciosamente).
            with self._lock, self._conexao() as conexao:
                linhas = conexao.execute(
                    f"SELECT {coluna} AS valor, COUNT(*) AS total FROM musicas"
                    f" WHERE {coluna} IS NOT NULL AND {coluna} != ''"
                    f" GROUP BY {coluna}"
                    f" ORDER BY {ordem or f'{coluna} COLLATE NOCASE'}"
                ).fetchall()
            return [{"valor": str(linha["valor"]), "total": int(linha["total"])}
                    for linha in linhas]

        return {
            "artistas": agrupar("artista"),
            "albuns": agrupar("album"),
            "generos": agrupar("genero"),
            "anos": agrupar("ano", "ano DESC"),
        }

    def estatisticas(self) -> dict[str, Any]:
        with self._lock, self._conexao() as conexao:
            linha = conexao.execute(
                "SELECT COUNT(*) AS total,"
                " COALESCE(SUM(duracao), 0) AS segundos,"
                " COALESCE(SUM(tamanho), 0) AS bytes,"
                " SUM(CASE WHEN favorito = 1 THEN 1 ELSE 0 END) AS favoritos,"
                " SUM(CASE WHEN tem_capa = 1 THEN 1 ELSE 0 END) AS com_capa,"
                " SUM(CASE WHEN tem_capa = 0 THEN 1 ELSE 0 END) AS sem_capa"
                " FROM musicas").fetchone()
            playlists = conexao.execute(
                "SELECT COUNT(*) AS total FROM playlists").fetchone()
        total = int(linha["total"] or 0)
        return {
            "total": total,
            "segundos": float(linha["segundos"] or 0),
            "bytes": int(linha["bytes"] or 0),
            "favoritos": int(linha["favoritos"] or 0),
            "com_capa": int(linha["com_capa"] or 0),
            "sem_capa": int(linha["sem_capa"] or 0),
            "playlists": int(playlists["total"] or 0),
        }

    def recentes(self, limite: int = 10) -> list[Musica]:
        return self.listar(ordenar="adicionada", limite=limite)

    def sem_capa(self) -> list[Musica]:
        with self._lock, self._conexao() as conexao:
            linhas = conexao.execute(
                "SELECT * FROM musicas WHERE tem_capa = 0"
                " ORDER BY artista COLLATE NOCASE, album COLLATE NOCASE").fetchall()
        return [_linha_para_musica(linha) for linha in linhas]

    # -- playlists locais ---------------------------------------------------
    def criar_playlist(self, nome: str) -> int:
        nome = (nome or "").strip()
        if not nome:
            raise ValueError("Dê um nome à playlist.")
        momento = agora()
        with self._lock, self._conexao() as conexao:
            existente = conexao.execute(
                "SELECT id FROM playlists WHERE nome = ? COLLATE NOCASE",
                (nome,)).fetchone()
            if existente:
                return int(existente["id"])
            cursor = conexao.execute(
                "INSERT INTO playlists (nome, criada_em, atualizada_em)"
                " VALUES (?, ?, ?)", (nome, momento, momento))
            return int(cursor.lastrowid or 0)

    def renomear_playlist(self, playlist_id: int, novo_nome: str) -> bool:
        novo_nome = (novo_nome or "").strip()
        if not novo_nome:
            raise ValueError("Dê um nome à playlist.")
        with self._lock, self._conexao() as conexao:
            cursor = conexao.execute(
                "UPDATE playlists SET nome = ?, atualizada_em = ? WHERE id = ?",
                (novo_nome, agora(), int(playlist_id)))
        return cursor.rowcount > 0

    def excluir_playlist(self, playlist_id: int) -> bool:
        with self._lock, self._conexao() as conexao:
            conexao.execute("DELETE FROM playlist_itens WHERE playlist_id = ?",
                            (int(playlist_id),))
            cursor = conexao.execute("DELETE FROM playlists WHERE id = ?",
                                     (int(playlist_id),))
        return cursor.rowcount > 0

    def listar_playlists(self) -> list[dict[str, Any]]:
        with self._lock, self._conexao() as conexao:
            linhas = conexao.execute(
                "SELECT p.id, p.nome, p.criada_em, p.atualizada_em,"
                " COUNT(i.musica_id) AS total,"
                " COALESCE(SUM(m.duracao), 0) AS duracao"
                " FROM playlists p"
                " LEFT JOIN playlist_itens i ON i.playlist_id = p.id"
                " LEFT JOIN musicas m ON m.id = i.musica_id"
                " GROUP BY p.id ORDER BY p.nome COLLATE NOCASE").fetchall()
        return [dict(linha) for linha in linhas]

    def adicionar_a_playlist(self, playlist_id: int, musica_ids: Iterable[int]) -> int:
        adicionados = 0
        with self._lock, self._conexao() as conexao:
            proxima = conexao.execute(
                "SELECT COALESCE(MAX(posicao), 0) + 1 AS proxima"
                " FROM playlist_itens WHERE playlist_id = ?", (int(playlist_id),)
            ).fetchone()
            posicao = int(proxima["proxima"] if proxima else 1)
            for musica_id in musica_ids:
                try:
                    conexao.execute(
                        "INSERT INTO playlist_itens (playlist_id, musica_id, posicao)"
                        " VALUES (?, ?, ?)",
                        (int(playlist_id), int(musica_id), posicao))
                    posicao += 1
                    adicionados += 1
                except sqlite3.IntegrityError:
                    continue  # já estava na playlist
            conexao.execute("UPDATE playlists SET atualizada_em = ? WHERE id = ?",
                            (agora(), int(playlist_id)))
        return adicionados

    def remover_da_playlist(self, playlist_id: int, musica_id: int) -> bool:
        with self._lock, self._conexao() as conexao:
            cursor = conexao.execute(
                "DELETE FROM playlist_itens WHERE playlist_id = ? AND musica_id = ?",
                (int(playlist_id), int(musica_id)))
            conexao.execute("UPDATE playlists SET atualizada_em = ? WHERE id = ?",
                            (agora(), int(playlist_id)))
        return cursor.rowcount > 0

    def musicas_da_playlist(self, playlist_id: int) -> list[Musica]:
        with self._lock, self._conexao() as conexao:
            linhas = conexao.execute(
                "SELECT m.* FROM playlist_itens i JOIN musicas m ON m.id = i.musica_id"
                " WHERE i.playlist_id = ? ORDER BY i.posicao, i.id",
                (int(playlist_id),)).fetchall()
        return [_linha_para_musica(linha) for linha in linhas]

    def reordenar_playlist(self, playlist_id: int, ordem: Iterable[int]) -> None:
        """Grava a nova ordem (lista de ``musica_id`` na sequência desejada)."""
        with self._lock, self._conexao() as conexao:
            for posicao, musica_id in enumerate(ordem, start=1):
                conexao.execute(
                    "UPDATE playlist_itens SET posicao = ?"
                    " WHERE playlist_id = ? AND musica_id = ?",
                    (posicao, int(playlist_id), int(musica_id)))
            conexao.execute("UPDATE playlists SET atualizada_em = ? WHERE id = ?",
                            (agora(), int(playlist_id)))

    # -- favoritos (músicas usam a coluna; os outros tipos ficam aqui) ------
    TIPOS_FAVORITO = ("artista", "album", "playlist", "genero")

    def favoritar(self, tipo: str, chave: str) -> bool:
        tipo = (tipo or "").strip().lower()
        chave = (chave or "").strip()
        if tipo not in self.TIPOS_FAVORITO or not chave:
            return False
        with self._lock, self._conexao() as conexao:
            try:
                conexao.execute(
                    "INSERT INTO favoritos (tipo, chave, criado_em) VALUES (?, ?, ?)",
                    (tipo, chave, agora()))
            except sqlite3.IntegrityError:
                return True  # já era favorito
        return True

    def desfavoritar(self, tipo: str, chave: str) -> bool:
        with self._lock, self._conexao() as conexao:
            cursor = conexao.execute(
                "DELETE FROM favoritos WHERE tipo = ? AND chave = ?",
                ((tipo or "").strip().lower(), (chave or "").strip()))
        return cursor.rowcount > 0

    def eh_favorito(self, tipo: str, chave: str) -> bool:
        with self._lock, self._conexao() as conexao:
            linha = conexao.execute(
                "SELECT 1 FROM favoritos WHERE tipo = ? AND chave = ?",
                ((tipo or "").strip().lower(), (chave or "").strip())).fetchone()
        return linha is not None

    def favoritos(self, tipo: str | None = None) -> list[dict[str, Any]]:
        with self._lock, self._conexao() as conexao:
            if tipo:
                linhas = conexao.execute(
                    "SELECT tipo, chave, criado_em FROM favoritos WHERE tipo = ?"
                    " ORDER BY chave COLLATE NOCASE", (tipo.lower(),)).fetchall()
            else:
                linhas = conexao.execute(
                    "SELECT tipo, chave, criado_em FROM favoritos"
                    " ORDER BY tipo, chave COLLATE NOCASE").fetchall()
        return [dict(linha) for linha in linhas]

    def musicas_favoritas(self) -> list[Musica]:
        return self.listar(ordenar="artista", somente_favoritos=True)

    # -- histórico de pesquisas --------------------------------------------
    def registrar_pesquisa(self, consulta: str, tipo: str = "tudo") -> None:
        consulta = (consulta or "").strip()
        if not consulta:
            return
        with self._lock, self._conexao() as conexao:
            conexao.execute(
                "DELETE FROM pesquisas WHERE consulta = ? COLLATE NOCASE",
                (consulta,))
            conexao.execute(
                "INSERT INTO pesquisas (consulta, tipo, quando) VALUES (?, ?, ?)",
                (consulta, tipo, agora()))

    def pesquisas_recentes(self, limite: int = 15) -> list[dict[str, Any]]:
        with self._lock, self._conexao() as conexao:
            linhas = conexao.execute(
                "SELECT consulta, tipo, quando FROM pesquisas"
                " ORDER BY quando DESC LIMIT ?", (int(limite),)).fetchall()
        return [dict(linha) for linha in linhas]

    def limpar_pesquisas(self) -> None:
        with self._lock, self._conexao() as conexao:
            conexao.execute("DELETE FROM pesquisas")


__all__ = ["Biblioteca", "Musica", "ORDENACOES", "chave_busca", "ler_tags"]
