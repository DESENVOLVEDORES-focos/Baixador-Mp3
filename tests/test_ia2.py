"""Testes da IA 2: identificação, capas, metadados e integração com a IA 1.

Nenhum teste acessa a rede: clientes HTTP falsos devolvem fixtures no
formato real das APIs (iTunes/MusicBrainz/Deezer) ou levantam ``ErroAPI``
para exercitar o tratamento de falhas. As imagens são PNG/JPEG reais
gerados no próprio teste e os MP3 são arquivos temporários com tags ID3
gravadas/lidas de verdade pelo Mutagen.
"""

from __future__ import annotations

import os
import struct
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest.mock import patch

from capas import (
    GerenciadorCapas, extrair_id_youtube, processar_imagem, validar_imagem,
)
from inteligencia import (
    AssistenteIAOpenAI, ConsultaMusica, ErroAPI, IdentificadorMusical,
    InfoMusica, ProvedorDeezer, ProvedorITunes, ProvedorMusicBrainz,
    analisar_titulo,
)
from integracao import AdaptadorMetadados
from metadados import ProcessadorMusical, aplicar_metadados, ler_metadados


# ---------------------------------------------------------------------------
# Utilidades / fixtures
# ---------------------------------------------------------------------------


def png_bytes(largura: int = 600, altura: int = 600) -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        corpo = struct.pack(">I", len(data)) + tag + data
        return corpo + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", largura, altura, 8, 2, 0, 0, 0)
    bruto = b"".join(b"\x00" + b"\x11\x22\x33" * largura for _ in range(altura))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(bruto)) + chunk(b"IEND", b""))


def jpeg_bytes(largura: int = 800, altura: int = 800) -> bytes:
    # JPEG mínimo aceito pelo validador: SOI + SOF0 com as dimensões + EOI.
    sof = b"\xff\xc0" + struct.pack(">H", 17) + b"\x08" + struct.pack(">HH", altura, largura)
    sof += b"\x03\x01\x22\x00\x02\x11\x01\x03\x11\x01"
    comentario = b"\xff\xfe" + struct.pack(">H", 202) + b"\x00" * 200
    return b"\xff\xd8\xff\xe0" + struct.pack(">H", 16) + b"\x00" * 14 + comentario + sof + b"\xff\xd9"


def mp3_falso(pasta: Path, nome: str = "Queen - Bohemian Rhapsody [abc123].mp3") -> Path:
    arquivo = pasta / nome
    arquivo.write_bytes(b"\xff\xfb\x90\x00" + b"\x00" * 1024)
    return arquivo


class ClienteFalso:
    """Roteia ``get_json`` por trecho da URL; trechos em ``falhas`` explodem."""

    def __init__(self, rotas: dict[str, object] | None = None,
                 falhas: tuple[str, ...] = ()):  # noqa: B006
        self.rotas = rotas or {}
        self.falhas = falhas
        self.urls: list[str] = []

    def get_json(self, url: str, headers=None):  # noqa: ANN001
        self.urls.append(url)
        if any(trecho in url for trecho in self.falhas):
            raise ErroAPI(f"falha simulada em {url}")
        for trecho, resposta in self.rotas.items():
            if trecho in url:
                return resposta
        raise ErroAPI(f"sem rota de teste para {url}")

    def post_json(self, url: str, payload, headers=None):  # noqa: ANN001
        return self.get_json(url, headers)


class ClienteCapasFalso(ClienteFalso):
    def __init__(self, imagens: dict[str, bytes] | None = None, **kwargs):  # noqa: ANN001
        super().__init__(**kwargs)
        self.imagens = imagens or {}

    def get_bytes(self, url: str, limite: int = 15 * 1024 * 1024) -> bytes:
        for trecho, dados in self.imagens.items():
            if trecho in url:
                return dados
        raise ErroAPI(f"sem imagem de teste para {url}")


ITUNES_QUEEN = {"results": [{
    "trackName": "Bohemian Rhapsody", "artistName": "Queen",
    "collectionName": "A Night at the Opera", "releaseDate": "1975-11-21T08:00:00Z",
    "primaryGenreName": "Rock", "trackNumber": 11, "trackCount": 12,
    "artworkUrl100": "https://exemplo.test/queen/100x100bb.jpg",
}]}
MUSICBRAINZ_QUEEN = {"recordings": [{
    "title": "Bohemian Rhapsody", "score": 100,
    "first-release-date": "1975-10-31",
    "artist-credit": [{"name": "Queen", "joinphrase": ""}],
    "tags": [{"name": "rock", "count": 5}, {"name": "pop", "count": 1}],
    "releases": [{"id": "rel-123", "title": "A Night at the Opera",
                  "label-info": [{"label": {"name": "EMI"}}]}],
}]}
DEEZER_QUEEN = {"data": [{
    "title": "Bohemian Rhapsody", "artist": {"name": "Queen"},
    "album": {"id": 42, "title": "A Night at the Opera"},
}]}
DEEZER_ALBUM = {
    "label": "EMI", "release_date": "1975-11-21", "nb_tracks": 12,
    "genres": {"data": [{"name": "Rock"}]},
    "cover_xl": "https://exemplo.test/deezer/cover_xl.jpg",
}


# ---------------------------------------------------------------------------
# Identificação
# ---------------------------------------------------------------------------


class TestAnaliseTitulo(unittest.TestCase):
    def test_artista_titulo_com_ruido_e_id_do_arquivo(self):
        consulta = analisar_titulo("Queen - Bohemian Rhapsody (Official Video) [dQw4w9WgXcQ]")
        self.assertEqual(consulta.artista, "Queen")
        self.assertEqual(consulta.titulo, "Bohemian Rhapsody")

    def test_feat_vira_participacao(self):
        consulta = analisar_titulo("Artista - Música Nova (feat. Convidada) [HD]")
        self.assertEqual(consulta.titulo, "Música Nova")
        self.assertEqual(consulta.participacao, "Convidada")

    def test_canal_topic_vira_artista(self):
        consulta = analisar_titulo("Bohemian Rhapsody (Official Music Video)", "Queen - Topic")
        self.assertEqual(consulta.artista, "Queen")
        self.assertEqual(consulta.titulo, "Bohemian Rhapsody")


class TestProvedores(unittest.TestCase):
    def setUp(self):
        self.consulta = ConsultaMusica(titulo="Bohemian Rhapsody", artista="Queen")

    def test_itunes_preenche_album_ano_genero_faixa(self):
        achados = ProvedorITunes().buscar(self.consulta, ClienteFalso({"itunes": ITUNES_QUEEN}))
        self.assertEqual(len(achados), 1)
        info = achados[0]
        self.assertEqual((info.album, info.ano, info.genero, info.faixa, info.total_faixas),
                         ("A Night at the Opera", 1975, "Rock", 11, 12))

    def test_musicbrainz_preenche_gravadora_e_id_para_capa(self):
        achados = ProvedorMusicBrainz().buscar(
            self.consulta, ClienteFalso({"musicbrainz": MUSICBRAINZ_QUEEN}))
        info = achados[0]
        self.assertEqual(info.gravadora, "EMI")
        self.assertEqual(info.musicbrainz_id, "rel-123")
        self.assertEqual(info.genero, "Rock")

    def test_deezer_enriquece_com_album(self):
        cliente = ClienteFalso({"api.deezer.com/search": DEEZER_QUEEN,
                                "api.deezer.com/album/42": DEEZER_ALBUM})
        achados = ProvedorDeezer().buscar(self.consulta, cliente)
        info = achados[0]
        self.assertEqual((info.genero, info.gravadora, info.ano), ("Rock", "EMI", 1975))

    def test_identificador_mescla_campos_da_mesma_faixa(self):
        cliente = ClienteFalso({"itunes": ITUNES_QUEEN,
                                "musicbrainz": MUSICBRAINZ_QUEEN,
                                "api.deezer.com/search": DEEZER_QUEEN,
                                "api.deezer.com/album/42": DEEZER_ALBUM})
        info = IdentificadorMusical(cliente=cliente).identificar(
            "Queen - Bohemian Rhapsody (Official Video)")
        self.assertIsNotNone(info)
        self.assertEqual(info.album, "A Night at the Opera")
        self.assertEqual(info.ano, 1975)
        self.assertEqual(info.gravadora, "EMI")  # veio do MusicBrainz/Deezer
        self.assertEqual(info.musicbrainz_id, "rel-123")

    def test_falha_de_todas_as_apis_retorna_none_e_registra_erros(self):
        identificador = IdentificadorMusical(
            cliente=ClienteFalso(falhas=("itunes", "musicbrainz", "deezer")))
        self.assertIsNone(identificador.identificar("Queen - Bohemian Rhapsody"))
        self.assertEqual(len(identificador.ultimos_erros), 3)

    def test_candidato_irrelevante_e_rejeitado_pelo_limiar(self):
        estranho = {"results": [{"trackName": "Outra Coisa", "artistName": "Desconhecido",
                                 "collectionName": "X", "releaseDate": "2020-01-01",
                                 "primaryGenreName": "Pop", "trackNumber": 1,
                                 "trackCount": 1, "artworkUrl100": ""}]}
        cliente = ClienteFalso({"itunes": estranho}, falhas=("musicbrainz", "deezer"))
        self.assertIsNone(IdentificadorMusical(cliente=cliente).identificar(
            "Queen - Bohemian Rhapsody"))


class TestAssistenteIA(unittest.TestCase):
    def test_ia_so_interpreta_titulo_e_descarta_fatos(self):
        resposta = {"choices": [{"message": {"content":
                    '{"artista": "Queen", "titulo": "Bohemian Rhapsody",'
                    ' "participacao": null, "album": "INVENTADO", "ano": 9999}'}}]}
        assistente = AssistenteIAOpenAI(ClienteFalso({"openai": resposta}), "chave-teste")
        consulta = assistente.interpretar_titulo("video qualquer")
        self.assertIsNotNone(consulta)
        self.assertEqual((consulta.artista, consulta.titulo), ("Queen", "Bohemian Rhapsody"))
        self.assertFalse(hasattr(consulta, "album"))  # ConsultaMusica não carrega fatos

    def test_ia_indisponivel_retorna_none(self):
        assistente = AssistenteIAOpenAI(
            ClienteFalso(falhas=("openai",)), "chave-teste")
        self.assertIsNone(assistente.interpretar_titulo("qualquer título"))


# ---------------------------------------------------------------------------
# Capas
# ---------------------------------------------------------------------------


class TestCapas(unittest.TestCase):
    def test_valida_png_e_jpeg_reais_e_rejeita_html_e_placeholder(self):
        self.assertEqual(validar_imagem(png_bytes()).formato, "png")
        self.assertEqual(validar_imagem(jpeg_bytes()).largura, 800)
        with self.assertRaises(Exception):
            validar_imagem(b"<html>nao encontrado</html>" * 10)
        with self.assertRaises(Exception):
            validar_imagem(png_bytes(120, 90)[:0] or jpeg_bytes(10, 10))

    def test_processar_mantem_imagem_valida(self):
        processada = processar_imagem(png_bytes(600, 600))
        info = validar_imagem(processada)
        self.assertLessEqual(max(info.largura, info.altura), 1200)

    def test_baixa_capa_do_itunes_em_alta_resolucao(self):
        cliente = ClienteCapasFalso(
            rotas={"itunes": ITUNES_QUEEN},
            falhas=("deezer", "coverartarchive"),
            imagens={"1200x1200bb.jpg": png_bytes(1200, 1200)})
        info = InfoMusica(titulo="Bohemian Rhapsody", artista="Queen")
        capa = GerenciadorCapas(cliente=cliente).buscar_e_baixar(info)
        self.assertIsNotNone(capa)
        self.assertEqual(validar_imagem(capa).largura, 1200)

    def test_capa_invalida_cai_para_proxima_fonte(self):
        cliente = ClienteCapasFalso(
            rotas={"itunes": ITUNES_QUEEN, "api.deezer.com/album": DEEZER_ALBUM},
            imagens={"1200x1200bb.jpg": b"isto nao e imagem" * 20,
                     "cover_xl.jpg": png_bytes(1000, 1000)})
        info = InfoMusica(titulo="Bohemian Rhapsody", artista="Queen", deezer_album_id=42)
        capa = GerenciadorCapas(cliente=cliente).buscar_e_baixar(info)
        self.assertEqual(validar_imagem(capa).largura, 1000)

    def test_sem_fonte_valida_retorna_none(self):
        cliente = ClienteCapasFalso(falhas=("itunes", "deezer", "coverartarchive"))
        info = InfoMusica(titulo="X", artista="Y", musicbrainz_id="rel-1")
        self.assertIsNone(GerenciadorCapas(cliente=cliente).buscar_e_baixar(info))

    def test_id_youtube_e_thumbnail_como_ultimo_recurso(self):
        self.assertEqual(extrair_id_youtube("https://www.youtube.com/watch?v=dQw4w9WgXcQ"),
                         "dQw4w9WgXcQ")
        self.assertIsNone(extrair_id_youtube("https://exemplo.test/video"))
        cliente = ClienteCapasFalso(
            falhas=("itunes", "deezer"),
            imagens={"maxresdefault.jpg": jpeg_bytes(1280, 720)})
        info = InfoMusica(titulo="Bohemian Rhapsody", artista="Queen")
        capa = GerenciadorCapas(cliente=cliente).buscar_e_baixar(
            info, url_origem="https://youtu.be/dQw4w9WgXcQ")
        self.assertEqual(validar_imagem(capa).formato, "jpeg")


# ---------------------------------------------------------------------------
# Metadados + integração com o núcleo da IA 1
# ---------------------------------------------------------------------------


class TestMetadados(unittest.TestCase):
    def test_grava_tags_e_incorpora_capa_no_mp3(self):
        with tempfile.TemporaryDirectory() as temp:
            mp3 = mp3_falso(Path(temp))
            info = InfoMusica(titulo="Bohemian Rhapsody", artista="Queen",
                              album="A Night at the Opera", ano=1975, genero="Rock",
                              faixa=11, total_faixas=12, gravadora="EMI")
            aplicar_metadados(mp3, info, png_bytes())
            lidos = ler_metadados(mp3)
            self.assertEqual(lidos["titulo"], "Bohemian Rhapsody")
            self.assertEqual(lidos["artista"], "Queen")
            self.assertEqual(lidos["album"], "A Night at the Opera")
            self.assertEqual(lidos["ano"], "1975")
            self.assertEqual(lidos["genero"], "Rock")
            self.assertEqual(lidos["faixa"], "11/12")
            self.assertEqual(lidos["gravadora"], "EMI")
            self.assertTrue(lidos["tem_capa"])
            self.assertEqual(lidos["capa_mime"], "image/png")

    def test_campos_desconhecidos_nao_sao_inventados(self):
        with tempfile.TemporaryDirectory() as temp:
            mp3 = mp3_falso(Path(temp))
            aplicar_metadados(mp3, InfoMusica(titulo="Só Título", artista=""))
            lidos = ler_metadados(mp3)
            self.assertEqual(lidos["titulo"], "Só Título")
            self.assertNotIn("album", lidos)
            self.assertNotIn("ano", lidos)
            self.assertFalse(lidos["tem_capa"])


class _IdentificadorFalso:
    def __init__(self, info):  # noqa: ANN001
        self.info = info

    def identificar(self, titulo, canal=None):  # noqa: ANN001
        return self.info


class _CapasFalsas:
    def __init__(self, capa):  # noqa: ANN001
        self.capa = capa

    def buscar_e_baixar(self, info, url_origem=None):  # noqa: ANN001
        return self.capa


class TestIntegracaoComNucleo(unittest.TestCase):
    def _processador(self, info):  # noqa: ANN001
        return ProcessadorMusical(
            identificador=_IdentificadorFalso(info),
            gerenciador_capas=_CapasFalsas(png_bytes()))

    def test_processar_mp3_no_proprio_caminho_via_adaptador_da_ia1(self):
        with tempfile.TemporaryDirectory() as temp:
            mp3 = mp3_falso(Path(temp))
            info = InfoMusica(titulo="Bohemian Rhapsody", artista="Queen",
                              album="A Night at the Opera", ano=1975, genero="Rock")
            adaptador = AdaptadorMetadados(self._processador(info))  # type: ignore[arg-type]
            saida = adaptador.processar_mp3(mp3, {"url": "https://youtu.be/dQw4w9WgXcQ",
                                                  "formato": "mp3"})
            self.assertEqual(saida, mp3)  # contrato: mesmo caminho, retorno None interno
            self.assertEqual(ler_metadados(mp3)["album"], "A Night at the Opera")
            self.assertTrue(ler_metadados(mp3)["tem_capa"])

    def test_falha_das_apis_usa_nome_do_arquivo_sem_inventar(self):
        with tempfile.TemporaryDirectory() as temp:
            mp3 = mp3_falso(Path(temp))
            processador = ProcessadorMusical(
                identificador=_IdentificadorFalso(None),
                gerenciador_capas=_CapasFalsas(None))
            self.assertIsNone(processador.processar_mp3(
                mp3, {"url": "https://exemplo.test/x", "formato": "mp3"}))
            lidos = ler_metadados(mp3)
            self.assertEqual(lidos["titulo"], "Bohemian Rhapsody")
            self.assertEqual(lidos["artista"], "Queen")
            self.assertNotIn("album", lidos)

    def test_modulo_carregavel_por_baixador_metadata_module(self):
        with tempfile.TemporaryDirectory() as temp:
            mp3 = mp3_falso(Path(temp))
            info = InfoMusica(titulo="Bohemian Rhapsody", artista="Queen", ano=1975)
            processador = self._processador(info)
            with patch.dict(os.environ, {"BAIXADOR_METADATA_MODULE": "modulo_metadados"}), \
                    patch("metadados.criar_processador_padrao", return_value=processador):
                adaptador = AdaptadorMetadados()  # carrega modulo_metadados pela env
                self.assertTrue(adaptador.disponivel)
                adaptador.processar_mp3(mp3, {"url": "https://youtu.be/x", "formato": "mp3"})
            self.assertEqual(ler_metadados(mp3)["ano"], "1975")


if __name__ == "__main__":
    unittest.main()
