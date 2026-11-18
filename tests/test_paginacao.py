"""Playlists e canais com mais de 500 itens: janelas, "Listar mais" e numeração.

Sem rede: o yt-dlp é substituído por um dublê que devolve as páginas em JSON,
exatamente no formato que o extrator entrega (`--flat-playlist`).
"""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from baixador.nucleo.configuracoes import Configuracoes
from baixador.web.playlist import LIMITE_MAXIMO, PASSO_PADRAO, Playlist, construir_comando, listar, listar_mais, montar_playlist


def _pagina(titulo: str, inicio: int, quantidade: int,
            total: int) -> dict:
    """JSON de uma janela, no formato do yt-dlp."""
    return {
        "title": titulo,
        "webpage_url": "https://www.youtube.com/playlist?list=PL1",
        "channel": "Canal X",
        "playlist_count": total,
        "entries": [
            {"id": f"id{numero}", "title": f"Faixa {numero}",
             "url": f"https://www.youtube.com/watch?v=id{numero}&list=PL1",
             "duration": 200, "channel": "Canal X"}
            for numero in range(inicio, inicio + quantidade)
        ],
    }


class TestJanelaDoComando(unittest.TestCase):
    def setUp(self):
        self.config = Configuracoes(raiz=Path("/tmp/nao-existe"))

    def test_primeira_pagina_nao_tem_start(self):
        comando = construir_comando("https://y/playlist?list=1", 200, self.config)
        self.assertIn("--playlist-end", comando)
        self.assertEqual(comando[comando.index("--playlist-end") + 1], "200")
        self.assertNotIn("--playlist-start", comando)

    def test_segunda_pagina_pede_a_janela_certa(self):
        comando = construir_comando("https://y/playlist?list=1", 400,
                                    self.config, inicio=201)
        self.assertEqual(comando[comando.index("--playlist-start") + 1], "201")
        self.assertEqual(comando[comando.index("--playlist-end") + 1], "400")

    def test_limite_acima_do_teto_e_cortado(self):
        comando = construir_comando("https://y/playlist?list=1", 99999, self.config)
        self.assertEqual(comando[comando.index("--playlist-end") + 1],
                         str(LIMITE_MAXIMO))
        self.assertGreaterEqual(LIMITE_MAXIMO, 1000)

    def test_inicio_maior_que_limite_nao_gera_janela_invertida(self):
        comando = construir_comando("https://y/playlist?list=1", 10,
                                    self.config, inicio=50)
        self.assertEqual(comando[comando.index("--playlist-start") + 1], "50")
        self.assertGreaterEqual(
            int(comando[comando.index("--playlist-end") + 1]), 50)


class TestNumeracaoDasPaginas(unittest.TestCase):
    def test_segunda_pagina_comeca_no_numero_certo(self):
        playlist = montar_playlist(_pagina("Mix", 201, 200, 1200),
                                   "https://y/p", inicio=201)
        self.assertEqual(playlist.itens[0].indice, 201)
        self.assertEqual(playlist.itens[-1].indice, 400)
        self.assertTrue(playlist.truncada)
        # esta página sozinha tem 200 itens de 1.200 -> 1.000 ainda não listados
        self.assertEqual(playlist.restantes, 1000)

    def test_playlist_completa_nao_fica_truncada(self):
        playlist = montar_playlist(_pagina("Mix", 1, 50, 50), "https://y/p")
        self.assertFalse(playlist.truncada)
        self.assertEqual(playlist.restantes, 0)


class TestListarMais(unittest.TestCase):
    def setUp(self):
        self.config = Configuracoes(raiz=Path("/tmp/nao-existe"))
        self.paginas: list[dict] = []

    def _dublê(self, total: int, tamanho_pagina: int = 200):
        def falso(url, limite=200, config=None, timeout=120, inicio=1):
            fim = min(int(limite), total)
            quantidade = max(0, fim - inicio + 1)
            return montar_playlist(_pagina("Mix", inicio, quantidade, total),
                                   url, limite, inicio=inicio)
        return falso

    def test_200_mais_200_chega_a_400_sem_duplicar(self):
        primeira = self._dublê(1200)(self._URL, 200, self.config)
        self.assertEqual(len(primeira.itens), 200)
        with patch("baixador.web.playlist.listar", side_effect=self._dublê(1200)):
            segunda = listar_mais(primeira, 200, self.config)
        self.assertEqual(len(segunda.itens), 400)
        ids = [item.id for item in segunda.itens]
        self.assertEqual(len(set(ids)), 400)  # nada repetido
        self.assertEqual(segunda.itens[199].id, "id200")
        self.assertEqual(segunda.itens[200].id, "id201")
        self.assertEqual(segunda.total_informado, 1200)
        self.assertEqual(segunda.restantes, 800)

    def test_numeracao_final_fica_sequencial(self):
        primeira = self._dublê(600)(self._URL, 200, self.config)
        with patch("baixador.web.playlist.listar", side_effect=self._dublê(600)):
            segunda = listar_mais(primeira, 200, self.config)
        self.assertEqual([i.indice for i in segunda.itens[:3]], [1, 2, 3])
        self.assertEqual(segunda.itens[-1].indice, 400)

    def test_quando_acaba_nao_chama_o_yt_dlp_de_novo(self):
        completa = self._dublê(150)(self._URL, 200, self.config)
        self.assertFalse(completa.truncada)
        with patch("baixador.web.playlist.listar") as chamada:
            resultado = listar_mais(completa, 200, self.config)
        chamada.assert_not_called()
        self.assertEqual(resultado.quantidade, 150)

    def test_pagina_repetida_nao_entra_duas_vezes(self):
        primeira = montar_playlist(_pagina("Mix", 1, 200, 1200), self._URL)

        def teimoso(url, limite=200, config=None, timeout=120, inicio=1):
            # devolve a mesma página de novo (comportamento de cache do yt-dlp)
            return montar_playlist(_pagina("Mix", 1, 200, 1200), url,
                                   limite, inicio=inicio)

        with patch("baixador.web.playlist.listar", side_effect=teimoso):
            resultado = listar_mais(primeira, 200, self.config)
        self.assertEqual(resultado.quantidade, 200)  # nada duplicado

    def test_playlist_sem_url_recusa(self):
        from baixador.web.playlist import ErroPlaylist

        vazia = Playlist(titulo="x", url="", itens=())
        with self.assertRaises(ErroPlaylist):
            listar_mais(vazia, 200, self.config)

    def test_passo_padrao_e_razoavel(self):
        self.assertGreaterEqual(PASSO_PADRAO, 100)
        self.assertLessEqual(PASSO_PADRAO, 500)

    def test_500_mais_500_atravessa_o_antigo_teto(self):
        primeira = self._dublê(2000)(self._URL, 500, self.config)
        with patch("baixador.web.playlist.listar", side_effect=self._dublê(2000)):
            segunda = listar_mais(primeira, 500, self.config)
        self.assertEqual(segunda.quantidade, 1000)
        self.assertEqual(segunda.itens[-1].id, "id1000")

    _URL = "https://www.youtube.com/playlist?list=PL1"


class TestListarComJanela(unittest.TestCase):
    def test_listar_passa_inicio_para_o_comando(self):
        visto = {}

        class Processo:
            returncode = 0
            stdout = '{"title": "Mix", "entries": []}'
            stderr = ""

        def falso(comando, **kwargs):
            visto["comando"] = comando
            return Processo()

        with patch("baixador.web.playlist.subprocess.run", side_effect=falso):
            try:
                listar("https://y/p", 300, Configuracoes(raiz=Path("/tmp")),
                       inicio=101)
            except Exception:
                pass  # playlist vazia levanta ErroPlaylist depois de montar
        comando = visto["comando"]
        self.assertEqual(comando[comando.index("--playlist-start") + 1], "101")
        self.assertEqual(comando[comando.index("--playlist-end") + 1], "300")


if __name__ == "__main__":
    unittest.main()
