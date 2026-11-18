"""Pesquisa no próprio programa: vídeos **e** playlists, sem colar link.

Pedido do usuário: "o yt-dlp tem que pesquisar vídeos e playlist e mostrar lá,
a pesquisa é feita no próprio baixador, por acaso eu tenho que ficar colando
links?".
"""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pesquisa
from configuracoes import Configuracoes


def _saida(entries: list[dict]) -> str:
    return json.dumps({"title": "x", "_type": "playlist", "entries": entries})


class TestComandoDaBusca(unittest.TestCase):
    def setUp(self):
        self.raiz = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.raiz, True)
        self.pesquisador = pesquisa.Pesquisador(Configuracoes(raiz=self.raiz))

    def test_videos_usam_a_busca_nativa(self):
        comando = self.pesquisador.construir_comando("legião", 5, "videos")
        self.assertEqual(comando[-1], "ytsearch5:legião")
        self.assertIn("--skip-download", comando)

    def test_playlists_usam_a_pagina_de_resultados_com_filtro(self):
        comando = self.pesquisador.construir_comando("rock mix", 4, "playlists")
        alvo = comando[-1]
        self.assertIn("youtube.com/results?search_query=rock+mix", alvo)
        self.assertIn("sp=EgIQAw", alvo)  # filtro de playlist do YouTube
        self.assertNotIn("ytsearch", alvo)

    def test_tudo_nao_usa_ytsearch_somente(self):
        comando = self.pesquisador.construir_comando("rock", 3, "tudo")
        self.assertIn("youtube.com/results?search_query=rock", comando[-1])

    def test_acentos_sao_codificados_na_url(self):
        comando = self.pesquisador.construir_comando("legião urbana", 3, "tudo")
        self.assertNotIn(" ", comando[-1])

    def test_tipo_invalido_e_recusado(self):
        with self.assertRaises(ValueError):
            self.pesquisador.construir_comando("x", 3, "podcasts")


class TestMesclagem(unittest.TestCase):
    def setUp(self):
        self.raiz = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.raiz, True)
        self.pesquisador = pesquisa.Pesquisador(Configuracoes(raiz=self.raiz))

    def _itens(self, *tipos: str):
        """Monta resultados com tipo/rótulo controlados (sem tocar na rede)."""

        def criar(tipo: str, n: int) -> pesquisa.ResultadoPesquisa:
            return pesquisa.ResultadoPesquisa(
                id=f"{tipo}{n}", titulo=f"{tipo} {n}", canal="Canal",
                duracao=100, url=f"https://exemplo/{tipo}{n}", tipo=tipo,
                quantidade=10 if tipo == "playlist" else None)

        return [criar(tipo, n) for n, tipo in enumerate(tipos)]

    def test_tudo_junta_videos_e_playlists_e_nao_duplica(self):
        videos = self._itens("video", "video")
        playlists = self._itens("playlist", "playlist")
        playlists.append(videos[0])  # mesmo id vindo das duas buscas

        def falso(consulta, limite, tipo="tudo"):
            return videos if tipo == "videos" else playlists

        with patch.object(self.pesquisador, "_pesquisar_uma", side_effect=falso):
            encontrados = self.pesquisador.pesquisar("rock", 10, "tudo")
        tipos = [r.tipo for r in encontrados]
        self.assertEqual(tipos[:2], ["video", "video"], "vídeos vêm primeiro")
        self.assertIn("playlist", tipos)
        self.assertEqual(len({r.id for r in encontrados}), len(encontrados))

    def test_se_a_busca_de_playlists_falhar_os_videos_aparecem(self):
        videos = self._itens("video")

        def falso(consulta, limite, tipo="tudo"):
            if tipo == "playlists":
                raise pesquisa.ErroPesquisa("playlist search quebrou")
            return videos

        with patch.object(self.pesquisador, "_pesquisar_uma", side_effect=falso):
            encontrados = self.pesquisador.pesquisar("rock", 10, "tudo")
        self.assertEqual([r.tipo for r in encontrados], ["video"])

    def test_se_a_busca_de_videos_falhar_as_playlists_aparecem(self):
        listas = self._itens("playlist")

        def falso(consulta, limite, tipo="tudo"):
            if tipo == "videos":
                raise pesquisa.ErroPesquisa("ytsearch quebrou")
            return listas

        with patch.object(self.pesquisador, "_pesquisar_uma", side_effect=falso):
            encontrados = self.pesquisador.pesquisar("rock", 10, "tudo")
        self.assertEqual([r.tipo for r in encontrados], ["playlist"])

    def test_se_as_duas_falharem_o_erro_chega_em_portugues(self):
        def falso(*_a, **_k):
            raise pesquisa.ErroPesquisa("Não foi possível completar a pesquisa")

        with patch.object(self.pesquisador, "_pesquisar_uma", side_effect=falso):
            with self.assertRaises(pesquisa.ErroPesquisa) as contexto:
                self.pesquisador.pesquisar("rock", 10, "tudo")
        self.assertIn("pesquisa", str(contexto.exception))


class TestTiposDoResultado(unittest.TestCase):
    def setUp(self):
        self.raiz = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.raiz, True)
        self.pesquisador = pesquisa.Pesquisador(Configuracoes(raiz=self.raiz))

    def _pesquisar_saida(self, entries):
        concluido = type("P", (), {"returncode": 0, "stdout": _saida(entries),
                                   "stderr": ""})()
        with patch("pesquisa.subprocess.run", return_value=concluido):
            return self.pesquisador._pesquisar_uma("rock", 10, "tudo")

    def test_playlist_da_busca_e_reconhecida(self):
        itens = self._pesquisar_saida([{
            "_type": "url", "id": "PL1", "title": "Rock Mix",
            "url": "https://www.youtube.com/playlist?list=PL1",
            "playlist_count": 42}])
        self.assertEqual(itens[0].tipo, "playlist")
        self.assertTrue(itens[0].eh_playlist)
        self.assertEqual(itens[0].quantidade, 42)
        self.assertIn("42", itens[0].tipo_legivel)

    def test_canal_da_busca_e_reconhecido(self):
        itens = self._pesquisar_saida([{
            "_type": "url", "id": "UC1", "title": "Canal X",
            "ie_key": "YoutubeTab",
            "url": "https://www.youtube.com/@canalx"}])
        self.assertEqual(itens[0].tipo, "canal")
        self.assertEqual(itens[0].tipo_legivel, "Canal")

    def test_video_comum(self):
        itens = self._pesquisar_saida([{
            "_type": "url", "id": "abc", "title": "Música",
            "url": "https://www.youtube.com/watch?v=abc"}])
        self.assertEqual(itens[0].tipo, "video")
        self.assertEqual(itens[0].tipo_legivel, "Vídeo")


if __name__ == "__main__":
    unittest.main()
