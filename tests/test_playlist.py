"""Playlist: listar sem baixar, montar a lista e escolher o que baixar.

Cobre o pedido do usuário ("poder baixar playlist, selecionar vários vídeos"):
a listagem **não** pode baixar mídia, itens quebrados não podem derrubar a
lista e a seleção tem que respeitar índices e itens indisponíveis.
"""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import playlist
from configuracoes import Configuracoes


def _dados_youtube() -> dict:
    """JSON no formato real de ``--flat-playlist --dump-single-json``."""
    return {
        "_type": "playlist",
        "title": "Mix de Rock",
        "channel": "Canal X",
        "playlist_count": 4,
        "webpage_url": "https://www.youtube.com/playlist?list=PLx",
        "entries": [
            {"_type": "url", "id": "aaa", "title": "Song One (Official Video)",
             "duration": 205,
             "url": "https://www.youtube.com/watch?v=aaa&list=PLx&index=1"},
            {"_type": "url", "id": "bbb", "title": "Song Two (Ao Vivo)",
             "duration": 330,
             "url": "https://www.youtube.com/watch?v=bbb&list=PLx&index=2"},
            {"_type": "url", "id": "ccc", "title": "[Private video]"},
            {"_type": "url", "id": "ddd", "title": "Song Four",
             "duration": 180,
             "url": "https://www.youtube.com/watch?v=ddd&list=PLx&index=4"},
        ],
    }


class TestParecePlaylist(unittest.TestCase):
    def test_reconhece_listas(self):
        for url in (
            "https://www.youtube.com/playlist?list=PLabc",
            "https://www.youtube.com/watch?v=x&list=PLabc",
            "https://www.youtube.com/@canal/videos",
            "https://www.youtube.com/channel/UC123",
            "https://music.youtube.com/browse/MPREb_abc",
        ):
            with self.subTest(url=url):
                self.assertTrue(playlist.parece_playlist(url))

    def test_video_unico_nao_e_playlist(self):
        for url in ("https://youtu.be/abc123", "https://vimeo.com/12345",
                    "https://www.youtube.com/watch?v=abc123"):
            with self.subTest(url=url):
                self.assertFalse(playlist.parece_playlist(url))


class TestComandoDeListagem(unittest.TestCase):
    def setUp(self):
        self.raiz = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.raiz, True)
        self.config = Configuracoes(raiz=self.raiz)

    def test_nunca_baixa_midia(self):
        comando = playlist.construir_comando(
            "https://www.youtube.com/playlist?list=PLx", config=self.config)
        self.assertIn("--skip-download", comando)
        self.assertIn("--flat-playlist", comando)
        self.assertIn("--dump-single-json", comando)
        self.assertNotIn("-x", comando)
        self.assertNotIn("--audio-format", comando)

    def test_limite_e_limitado_por_cima_e_por_baixo(self):
        alto = playlist.construir_comando("u", limite=9999, config=self.config)
        baixo = playlist.construir_comando("u", limite=0, config=self.config)
        posicao = alto.index("--playlist-end")
        self.assertEqual(alto[posicao + 1], str(playlist.LIMITE_MAXIMO))
        # 0/None significa "usa o padrão", nunca "lista zero itens".
        self.assertEqual(baixo[baixo.index("--playlist-end") + 1],
                         str(playlist.LIMITE_PADRAO))

    def test_url_e_o_ultimo_argumento(self):
        comando = playlist.construir_comando(
            "https://exemplo/x", limite=5, config=self.config)
        self.assertEqual(comando[-1], "https://exemplo/x")


class TestMontarPlaylist(unittest.TestCase):
    def test_le_titulo_itens_e_totais(self):
        lista = playlist.montar_playlist(_dados_youtube(), "https://x", 10)
        self.assertEqual(lista.titulo, "Mix de Rock")
        self.assertEqual(lista.canal, "Canal X")
        self.assertEqual(lista.quantidade, 4)
        self.assertEqual(lista.duracao_total, 205 + 330 + 180)
        self.assertEqual(lista.restantes, 0)
        self.assertFalse(lista.truncada)

    def test_item_privado_fica_indisponivel_e_nao_derruba_a_lista(self):
        lista = playlist.montar_playlist(_dados_youtube(), "https://x", 10)
        privado = lista.itens[2]
        self.assertFalse(privado.disponivel)
        self.assertEqual(privado.duracao_formatada, "--:--")
        self.assertTrue(all(i.disponivel for i in lista.itens[:2]))

    def test_url_do_item_perde_o_list(self):
        """Sem isso, baixar um item da playlist baixaria a playlist inteira."""
        lista = playlist.montar_playlist(_dados_youtube(), "https://x", 10)
        self.assertEqual(lista.itens[0].url,
                         "https://www.youtube.com/watch?v=aaa")

    def test_item_sem_url_monta_a_partir_do_id(self):
        dados = {"title": "x", "entries": [{"id": "zzz", "title": "Z"}]}
        lista = playlist.montar_playlist(dados, "https://x", 10)
        self.assertEqual(lista.itens[0].url,
                         "https://www.youtube.com/watch?v=zzz")

    def test_playlist_truncada_informa_quanto_faltou(self):
        dados = {"title": "Grande", "playlist_count": 120,
                 "entries": [{"id": f"i{n}", "title": f"T{n}"} for n in range(3)]}
        lista = playlist.montar_playlist(dados, "https://x", 3)
        self.assertTrue(lista.truncada)
        self.assertEqual(lista.restantes, 117)

    def test_video_unico_vira_lista_de_um_item(self):
        dados = {"id": "solo", "title": "Só um vídeo", "duration": 60}
        lista = playlist.montar_playlist(dados, "https://x", 10)
        self.assertEqual(lista.quantidade, 1)
        self.assertEqual(lista.itens[0].url,
                         "https://www.youtube.com/watch?v=solo")

    def test_duracao_formatada_com_horas(self):
        dados = {"entries": [{"id": "a", "title": "Longa", "duration": 3725}]}
        lista = playlist.montar_playlist(dados, "https://x", 10)
        self.assertEqual(lista.itens[0].duracao_formatada, "1:02:05")


class TestCarregarJson(unittest.TestCase):
    def test_lixo_antes_do_json_e_tolerado(self):
        dados = playlist.carregar_json(
            "AVISO qualquer\n" + json.dumps({"title": "x", "entries": []}))
        self.assertEqual(dados["title"], "x")

    def test_sem_json_vira_erro_em_portugues(self):
        with self.assertRaises(playlist.ErroPlaylist):
            playlist.carregar_json("nada aqui")

    def test_saida_vazia_vira_erro(self):
        with self.assertRaises(playlist.ErroPlaylist):
            playlist.carregar_json("   ")


class TestSelecionar(unittest.TestCase):
    def setUp(self):
        self.lista = playlist.montar_playlist(_dados_youtube(), "https://x", 10)

    def test_indices_1_based(self):
        escolhidos = playlist.selecionar(self.lista, [1, 4])
        self.assertEqual([item.titulo for item in escolhidos],
                         ["Song One (Official Video)", "Song Four"])

    def test_sem_indices_escolhe_todos_os_disponiveis(self):
        escolhidos = playlist.selecionar(self.lista)
        self.assertEqual(len(escolhidos), 3)
        self.assertNotIn("[Private video]", [item.titulo for item in escolhidos])

    def test_indisponivel_nunca_entra(self):
        escolhidos = playlist.selecionar(self.lista, [3])
        self.assertEqual(escolhidos, [])

    def test_indice_inexistente_e_ignorado(self):
        escolhidos = playlist.selecionar(self.lista, [1, 99])
        self.assertEqual(len(escolhidos), 1)


class TestListarSemBaixar(unittest.TestCase):
    def setUp(self):
        self.raiz = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.raiz, True)
        self.config = Configuracoes(raiz=self.raiz)

    def test_url_invalida_falha_antes_de_chamar_ytdlp(self):
        with patch("playlist.subprocess.run") as executar:
            with self.assertRaises(playlist.ErroPlaylist):
                playlist.listar("minha musica", config=self.config)
        executar.assert_not_called()

    def test_le_saida_do_ytdlp_e_devolve_itens(self):
        saida = json.dumps(_dados_youtube())
        concluido = type("P", (), {"returncode": 0, "stdout": saida,
                                   "stderr": ""})()
        with patch("playlist.subprocess.run", return_value=concluido) as executar:
            lista = playlist.listar("https://www.youtube.com/playlist?list=PLx",
                                   config=self.config)
        self.assertEqual(lista.quantidade, 4)
        comando = executar.call_args[0][0]
        self.assertIn("--skip-download", comando)

    def test_playlist_vazia_vira_erro_claro(self):
        saida = json.dumps({"title": "Vazia", "entries": []})
        concluido = type("P", (), {"returncode": 0, "stdout": saida,
                                   "stderr": ""})()
        with patch("playlist.subprocess.run", return_value=concluido):
            with self.assertRaises(playlist.ErroPlaylist) as contexto:
                playlist.listar("https://www.youtube.com/playlist?list=PLv",
                                config=self.config)
        self.assertIn("não tem itens", str(contexto.exception))

    def test_falha_do_ytdlp_mostra_a_ultima_linha(self):
        falhou = type("P", (), {
            "returncode": 1, "stdout": "",
            "stderr": "WARNING: bla\nERROR: [youtube] Playlist privada"})()
        with patch("playlist.subprocess.run", return_value=falhou):
            with self.assertRaises(playlist.ErroPlaylist) as contexto:
                playlist.listar("https://www.youtube.com/playlist?list=PLp",
                                config=self.config)
        self.assertIn("Playlist privada", str(contexto.exception))

    def test_timeout_vira_erro_em_portugues(self):
        with patch("playlist.subprocess.run",
                   side_effect=playlist.subprocess.TimeoutExpired("yt-dlp", 1)):
            with self.assertRaises(playlist.ErroPlaylist) as contexto:
                playlist.listar("https://www.youtube.com/playlist?list=PLt",
                                config=self.config)
        self.assertIn("listar a playlist", str(contexto.exception))


if __name__ == "__main__":
    unittest.main()


class TestResumoDaPlaylist(unittest.TestCase):
    """A tela precisa dizer o que tem na playlist antes de baixar."""

    @staticmethod
    def _item(indice, titulo, duracao=200, disponivel=True):
        from playlist import ItemPlaylist

        return ItemPlaylist(indice=indice, id=f"id{indice}", titulo=titulo,
                            url=f"https://youtu.be/id{indice}",
                            duracao=duracao, disponivel=disponivel)

    def test_conta_disponiveis_e_privados(self):
        from playlist import analisar

        resumo = analisar([self._item(1, "A"), self._item(2, "B"),
                           self._item(3, "Privada", disponivel=False)])
        self.assertEqual((resumo.quantidade, resumo.disponiveis,
                          resumo.indisponiveis), (3, 2, 1))

    def test_soma_duracao_total_e_dos_disponiveis(self):
        from playlist import analisar

        resumo = analisar([self._item(1, "A", 200), self._item(2, "B", 100),
                           self._item(3, "C", 999, disponivel=False)])
        self.assertEqual(resumo.duracao_total, 1299)
        self.assertEqual(resumo.duracao_disponivel, 300)

    def test_acha_repetido_pelo_titulo_normalizado(self):
        from playlist import analisar

        resumo = analisar([self._item(1, "Faixa A (Official Video)"),
                           self._item(2, "FAIXA A"),
                           self._item(3, "Outra")])
        self.assertEqual(resumo.duplicados, 1)

    def test_privado_nao_conta_como_repetido_duplicado(self):
        from playlist import analisar

        resumo = analisar([self._item(1, "A"),
                           self._item(2, "A", disponivel=False)])
        self.assertEqual(resumo.duplicados, 0)
        self.assertEqual(resumo.indisponiveis, 1)

    def test_texto_do_resumo_e_honesto(self):
        from playlist import analisar

        resumo = analisar([self._item(1, "A", 3600),
                           self._item(2, "B", 1200, disponivel=False)])
        texto = resumo.como_texto()
        self.assertIn("2 item(ns)", texto)
        self.assertIn("1 h 20 min", texto)   # 3600 + 1200 s
        self.assertIn("1 privado/removido", texto)

    def test_playlist_vazia_nao_quebra(self):
        from playlist import analisar

        resumo = analisar([])
        self.assertEqual(resumo.quantidade, 0)
        self.assertEqual(resumo.como_texto(), "0 item(ns)")

    def test_nada_e_removido_pela_analise(self):
        itens = [self._item(1, "A"), self._item(2, "A")]
        from playlist import analisar

        analisar(itens)
        self.assertEqual(len(itens), 2)


class TestVisualizacaoDePlaylistNaTela(unittest.TestCase):
    """Resumo, marcação só do disponível e "salvar na biblioteca"."""

    @classmethod
    def setUpClass(cls):
        import os
        import sys

        from unittest.mock import patch as _patch

        from tests.test_central_app import _instalar_tk_falso

        cls._env = _patch.dict(os.environ)
        cls._env.start()
        _instalar_tk_falso()
        cls._temp = tempfile.TemporaryDirectory()
        raiz = Path(cls._temp.name)
        os.environ["BAIXADOR_DATA_DIR"] = str(raiz / ".baixador")
        (raiz / "Musicas").mkdir(exist_ok=True)
        (raiz / "ferramentas").mkdir(exist_ok=True)
        for modulo in ("central_app", "central", "central_servicos"):
            sys.modules.pop(modulo, None)
        import central_app
        from central import Central
        from configuracoes import Configuracoes
        from preferencias import Preferencias

        cls.modulo = central_app
        cls.central = Central(
            Configuracoes(raiz=raiz, diretorio_musicas=raiz / "Musicas"),
            Preferencias(metadados_ativos=False, buscar_capas=False,
                         sincronizar_ao_abrir=False))
        cls.central.ffplay = []
        cls.app = central_app.CentralApp(cls.central, raiz=central_app.tk.Tk())
        cls.app.mostrar("pesquisar")

    @classmethod
    def tearDownClass(cls):
        import sys

        cls._temp.cleanup()
        cls._env.stop()
        for modulo in list(sys.modules):
            if modulo.startswith("tkinter"):
                sys.modules.pop(modulo, None)
        for modulo in ("central_app", "central", "central_servicos"):
            sys.modules.pop(modulo, None)

    def _playlist(self, quantidade=3):
        from playlist import ItemPlaylist, Playlist

        itens = tuple(
            ItemPlaylist(indice=i, id=f"id{i}", titulo=f"Faixa {i}",
                         url=f"https://youtu.be/id{i}", duracao=200,
                         disponivel=(i != 3))
            for i in range(1, quantidade + 1))
        return Playlist(titulo="Minha lista", url="https://y/l",
                        itens=itens, total_informado=quantidade)

    def test_abrir_mostra_resumo_e_marca_so_o_disponivel(self):
        playlist = self._playlist()
        with patch.object(self.app, "_executar",
                          side_effect=lambda trabalho, concluir=None, falhar=None:
                          concluir(trabalho()) if concluir else trabalho()), \
                patch.object(self.central, "listar_playlist",
                             return_value=playlist), \
                patch.object(self.app, "_resultados",
                             [type("R", (), {"eh_playlist": True, "url": "https://y/l",
                                             "titulo": "Minha lista"})()],
                             create=True):
            self.app.arvore_resultados.selection_set = lambda *a: None
            with patch.object(self.app, "_indices_selecionados", return_value=[0]):
                self.app._abrir_playlist_selecionada()
        self.assertIn("3 item(ns)", self.app.playlist_resumo_var.get())
        self.assertIn("1 privado/removido", self.app.playlist_resumo_var.get())

    def test_marcar_disponiveis_pula_privado(self):
        self.app._playlist_aberta = self._playlist()
        self.app._preencher_playlist(self.app._playlist_aberta)
        self.app._marcar_disponiveis()
        self.assertEqual(sorted(self.app.arvore_playlist.selection()),
                         ["1", "2"])
        self.assertIn("privado/removido", self.app.status_var.get())

    def test_salvar_playlist_aberta_sem_baixado_avisa(self):
        self.app._playlist_aberta = self._playlist()
        with patch.object(self.central, "criar_playlist") as criar, \
                patch.object(self.app, "notificar") as notificar, \
                patch.object(self.modulo, "simpledialog") as simples:
            simples.askstring.return_value = "Minha lista"
            self.app._salvar_playlist_aberta()
        criar.assert_not_called()
        self.assertIn("Nenhum item", notificar.call_args[0][1])

    def test_salvar_playlist_aberta_guarda_so_o_que_existe(self):
        from biblioteca import Musica

        self.app._playlist_aberta = self._playlist()
        musicas = []
        for indice in (1, 2):
            musicas.append(Musica(
                id=indice, caminho=f"/tmp/{indice}.mp3", titulo=f"Faixa {indice}",
                artista="A", album="", ano="", genero="", faixa="",
                duracao=200.0, tamanho=10, tem_capa=False, favorito=False,
                origem_url=f"https://youtu.be/id{indice}",
                adicionada_em="", atualizada_em=""))
        with patch.object(self.central.biblioteca, "listar", return_value=musicas), \
                patch.object(self.central, "criar_playlist", return_value=7) as criar, \
                patch.object(self.central, "adicionar_a_playlist",
                             return_value=2) as adicionar, \
                patch.object(self.modulo, "simpledialog") as simples, \
                patch.object(self.app, "_atualizar_fila"):
            simples.askstring.return_value = "Minha lista"
            self.app._salvar_playlist_aberta()
        criar.assert_called_once_with("Minha lista")
        self.assertEqual(sorted(adicionar.call_args[0][1]), [1, 2])
        self.assertIn("2 música(s)", self.app.status_var.get())

    def test_ver_o_que_ja_tenho_sem_nada_avisa(self):
        self.app._playlist_aberta = self._playlist()
        with patch.object(self.central.biblioteca, "listar", return_value=[]), \
                patch.object(self.app, "notificar") as notificar:
            self.app._ver_o_que_ja_tenho()
        self.assertIn("Nenhum dos 3", notificar.call_args[0][1])

    def test_ver_o_que_ja_tenho_lista_os_meus(self):
        from biblioteca import Musica

        self.app._playlist_aberta = self._playlist()
        minha = Musica(id=1, caminho="/tmp/1.mp3", titulo="Faixa 1", artista="A",
                       album="", ano="", genero="", faixa="", duracao=200.0,
                       tamanho=10, tem_capa=False, favorito=False,
                       origem_url="https://youtu.be/id1",
                       adicionada_em="", atualizada_em="")
        with patch.object(self.central.biblioteca, "listar", return_value=[minha]), \
                patch.object(self.app, "notificar") as notificar:
            self.app._ver_o_que_ja_tenho()
        texto = notificar.call_args[0][1]
        self.assertIn("1 de 3", texto)
        self.assertIn("Faixa 1", texto)
