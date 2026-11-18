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


class TestDedupeDaPesquisa(unittest.TestCase):
    """A pesquisa esconde o mesmo vídeo repetido — e diz o que escondeu."""

    @staticmethod
    def _r(id_, titulo, canal, duracao=300, tipo="video", verificado=False):
        return pesquisa.ResultadoPesquisa(
            id=id_, titulo=titulo, canal=canal, duracao=duracao,
            url=f"https://youtu.be/{id_}", tipo=tipo,
            canal_verificado=verificado)

    def test_slug_ignora_selo_do_video_e_acento(self):
        self.assertEqual(
            pesquisa._slug("Legião Urbana - Tempo Perdido (Official Video) [4K]"),
            pesquisa._slug("LEGIAO URBANA - Tempo Perdido"))

    def test_slug_nao_junta_musicas_diferentes(self):
        self.assertNotEqual(pesquisa._slug("Tempo Perdido"),
                            pesquisa._slug("Tempo Perdido (Ao Vivo)"))

    def test_mesmo_video_mesmo_canal_e_duplicado(self):
        lista = [self._r("a", "Tempo Perdido (Official Video)", "Legião Urbana"),
                 self._r("b", "Tempo Perdido", "Legião Urbana")]
        mantidos, contagem = pesquisa.organizar_resultados(lista)
        self.assertEqual([r.id for r in mantidos], ["a"])
        self.assertEqual(contagem["duplicados"], 1)

    def test_mesmo_titulo_canal_diferente_nao_e_duplicado(self):
        lista = [self._r("a", "Tempo Perdido", "Legião Urbana"),
                 self._r("b", "Tempo Perdido", "Cover do Zé")]
        mantidos, contagem = pesquisa.organizar_resultados(lista)
        self.assertEqual(len(mantidos), 2)
        self.assertEqual(contagem["duplicados"], 0)

    def test_mesmo_id_duas_vezes_e_duplicado(self):
        lista = [self._r("a", "X", "A"), self._r("a", "Y", "B")]
        mantidos, contagem = pesquisa.organizar_resultados(lista)
        self.assertEqual([r.id for r in mantidos], ["a"])
        self.assertEqual(contagem["duplicados"], 1)

    def test_dedupe_pode_ser_desligado(self):
        lista = [self._r("a", "Tempo Perdido (Official Video)", "Legião Urbana"),
                 self._r("b", "Tempo Perdido", "Legião Urbana")]
        mantidos, contagem = pesquisa.organizar_resultados(
            lista, remover_equivalentes=False)
        self.assertEqual(len(mantidos), 2)
        self.assertEqual(contagem["duplicados"], 0)

    def test_compilados_so_saem_quando_pedido(self):
        lista = [self._r("a", "Música", "X", duracao=240),
                 self._r("b", "Mega mix", "Y", duracao=7200)]
        mantidos, contagem = pesquisa.organizar_resultados(lista)
        self.assertEqual(len(mantidos), 2)
        self.assertEqual(contagem["compilados"], 0)
        mantidos, contagem = pesquisa.organizar_resultados(
            lista, esconder_compilados=True)
        self.assertEqual([r.id for r in mantidos], ["a"])
        self.assertEqual(contagem["compilados"], 1)

    def test_exigir_duracao_remove_video_sem_duracao(self):
        lista = [self._r("a", "Música", "X", duracao=240),
                 self._r("b", "Sem duração", "Y", duracao=None)]
        mantidos, contagem = pesquisa.organizar_resultados(lista, exigir_duracao=True)
        self.assertEqual([r.id for r in mantidos], ["a"])
        self.assertEqual(contagem["sem_duracao"], 1)

    def test_ordem_video_playlist_canal_e_verificado_primeiro(self):
        lista = [self._r("c", "Canal", "Z", tipo="canal"),
                 self._r("p", "Playlist", "Y", tipo="playlist"),
                 self._r("v2", "Vídeo 2", "B"),
                 self._r("v1", "Vídeo 1", "A", verificado=True)]
        mantidos, _ = pesquisa.organizar_resultados(lista)
        self.assertEqual([r.id for r in mantidos], ["v1", "v2", "p", "c"])

    def test_descricao_do_filtro_e_honesta(self):
        self.assertEqual(pesquisa.descrever_filtro({}), "")
        texto = pesquisa.descrever_filtro(
            {"duplicados": 2, "compilados": 1, "sem_duracao": 0})
        self.assertIn("2 duplicado(s)", texto)
        self.assertIn("1 compilado(s)", texto)
        self.assertNotIn("sem duração", texto)


class TestPesquisaComFiltros(unittest.TestCase):
    """`Pesquisador.pesquisar` aplica os filtros e guarda a contagem."""

    def setUp(self):
        self.raiz = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.raiz, True)
        self.pesquisador = pesquisa.Pesquisador(Configuracoes(raiz=self.raiz))
        self.itens = [
            pesquisa.ResultadoPesquisa(
                id="a", titulo="Faixa (Official Video)", canal="Artista",
                duracao=200, url="https://youtu.be/a"),
            pesquisa.ResultadoPesquisa(
                id="b", titulo="Faixa", canal="Artista",
                duracao=200, url="https://youtu.be/b"),
            pesquisa.ResultadoPesquisa(
                id="c", titulo="Mix de 2 horas", canal="Outro",
                duracao=7200, url="https://youtu.be/c"),
        ]

    def _rodar(self, **opcoes):
        with patch.object(self.pesquisador, "_pesquisar_uma",
                          side_effect=lambda consulta, limite, tipo:
                          [r for r in self.itens
                           if (tipo == "playlists") == (r.tipo == "playlist")]):
            return self.pesquisador.pesquisar("faixa", 10, "tudo", **opcoes)

    def test_filtros_padrao_deduplicam(self):
        resultados = self._rodar()
        self.assertEqual([r.id for r in resultados], ["a", "c"])
        self.assertEqual(self.pesquisador.ultima_contagem["duplicados"], 1)

    def test_sem_compilados(self):
        resultados = self._rodar(esconder_compilados=True)
        self.assertEqual([r.id for r in resultados], ["a"])
        self.assertEqual(self.pesquisador.ultima_contagem["compilados"], 1)

    def test_sem_dedupe_mostra_os_dois(self):
        resultados = self._rodar(remover_equivalentes=False)
        self.assertEqual([r.id for r in resultados], ["a", "b", "c"])


class TestFiltrosDePesquisaNaTela(unittest.TestCase):
    """As caixas de filtro da tela refiltram sem repetir a busca na rede."""

    @classmethod
    def setUpClass(cls):
        from tests.test_central_app import _instalar_tk_falso
        from configuracoes import Configuracoes
        from preferencias import Preferencias
        import sys
        import os

        cls._env = patch.dict(os.environ)
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
        cls._temp.cleanup()
        cls._env.stop()
        import sys

        for modulo in list(sys.modules):
            if modulo.startswith("tkinter"):
                sys.modules.pop(modulo, None)
        for modulo in ("central_app", "central", "central_servicos"):
            sys.modules.pop(modulo, None)

    @staticmethod
    def _resultados():
        return [
            pesquisa.ResultadoPesquisa(
                id="a", titulo="Faixa (Official Video)", canal="Artista",
                duracao=200, url="https://youtu.be/a"),
            pesquisa.ResultadoPesquisa(
                id="b", titulo="Faixa", canal="Artista",
                duracao=200, url="https://youtu.be/b"),
            pesquisa.ResultadoPesquisa(
                id="c", titulo="Mix longo", canal="Outro",
                duracao=7200, url="https://youtu.be/c"),
        ]

    def test_pesquisar_preenche_e_resume(self):
        with patch.object(self.app, "_executar",
                          side_effect=lambda trabalho, concluir=None, falhar=None:
                          concluir(trabalho()) if concluir else trabalho()), \
                patch.object(self.central, "pesquisar",
                             return_value=self._resultados()), \
                patch.object(self.central, "ultima_contagem_pesquisa",
                             {"duplicados": 1, "compilados": 0,
                              "sem_duracao": 0}, create=True):
            self.app.pesquisa_var.set("faixa")
            self.app._pesquisar()
        self.assertEqual(len(self.app.arvore_resultados.get_children()), 3)
        self.assertIn("3 resultado(s)", self.app.pesquisa_dica.get())

    def test_caixa_sem_compilados_refiltra_sem_nova_busca(self):
        self.app._resultados_brutos = self._resultados()
        self.app.pesq_deduplicar.set(True)
        self.app.pesq_sem_compilados.set(True)
        with patch.object(self.central, "pesquisar") as buscar:
            self.app._aplicar_filtros_pesquisa()
        buscar.assert_not_called()
        linhas = [self.app.arvore_resultados.item(i) for i in
                  self.app.arvore_resultados.get_children()]
        self.assertEqual(len(linhas), 1)
        self.assertIn("compilado(s)", self.app.pesquisa_filtro_dica.get())

    def test_duracao_longa_aparece_marcada(self):
        self.app._resultados_brutos = self._resultados()
        self.app.pesq_sem_compilados.set(False)
        self.app._aplicar_filtros_pesquisa()
        textos = " ".join(str(self.app.arvore_resultados.item(i))
                          for i in self.app.arvore_resultados.get_children())
        self.assertIn("compilado/mix", textos)

    def test_filtros_ficam_salvos_nas_preferencias(self):
        self.app._resultados_brutos = self._resultados()
        self.app.pesq_deduplicar.set(False)
        self.app.pesq_sem_compilados.set(True)
        self.app.pesq_so_com_duracao.set(True)
        with patch.object(self.central, "salvar_preferencias") as salvar:
            self.app._aplicar_filtros_pesquisa()
        salvar.assert_called_once()
        prefs = self.central.preferencias
        self.assertFalse(prefs.pesquisa_deduplicar)
        self.assertTrue(prefs.pesquisa_sem_compilados)
        self.assertTrue(prefs.pesquisa_so_com_duracao)
