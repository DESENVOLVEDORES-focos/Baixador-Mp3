"""Download em lote: playlist inteira e vários vídeos sem parar no 1º erro.

Regra de ouro do lote: **um item quebrado não pode derrubar os outros** — o
usuário quer baixar 30 músicas e receber 28 + o motivo das 2 falhas.
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from baixador.nucleo.configuracoes import Configuracoes
from baixador.web.downloader import Downloader, ErroDownload, ResultadoDownload
from baixador.web.playlist import ItemPlaylist, Playlist


def _playlist(*itens: ItemPlaylist) -> Playlist:
    return Playlist(titulo="Mix", url="https://youtube.com/playlist?list=X",
                    itens=itens, total_informado=len(itens))


class TestBaixarPlaylist(unittest.TestCase):
    def setUp(self):
        self.raiz = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.raiz, True)
        (self.raiz / "ferramentas").mkdir(exist_ok=True)
        self.config = Configuracoes(raiz=self.raiz)
        self.baixador = Downloader(self.config)

    def _rodar(self, playlist, resultados_por_url=None, falhas=()):
        """Substitui ``baixar`` por um dublê e devolve o que foi pedido."""
        pedidos: list[str] = []

        def falso_baixar(url, formato, ao_progresso=None, politica=None,
                         contexto=None, _destino_forcado=None):
            pedidos.append(url)
            if url in falhas:
                raise ErroDownload("vídeo indisponível nesta região")
            return ResultadoDownload(
                url=url, formato=formato, caminho=Path(f"/tmp/{url[-4:]}.mp3"),
                iniciado_em="", finalizado_em="", motivo="",
                pulado=False)

        with patch("baixador.web.downloader.listar", create=True, return_value=playlist), \
                patch("baixador.web.playlist.listar", return_value=playlist), \
                patch.object(Downloader, "baixar", side_effect=falso_baixar):
            lista = self.baixador.baixar_playlist(
                "https://www.youtube.com/playlist?list=X", "mp3")
        return lista, pedidos

    def test_baixa_todos_os_itens_disponiveis(self):
        alvo = _playlist(
            ItemPlaylist(1, "a", "Um", "https://youtu.be/aaaa"),
            ItemPlaylist(2, "b", "Dois", "https://youtu.be/bbbb"),
        )
        resultados, pedidos = self._rodar(alvo)
        self.assertEqual(pedidos, ["https://youtu.be/aaaa", "https://youtu.be/bbbb"])
        self.assertEqual(len(resultados), 2)
        self.assertTrue(all(not r.pulado for r in resultados))

    def test_item_privado_aparece_pulado_e_nao_e_baixado(self):
        alvo = _playlist(
            ItemPlaylist(1, "a", "Um", "https://youtu.be/aaaa"),
            ItemPlaylist(2, "c", "[Private video]", "https://youtu.be/cccc",
                         disponivel=False),
        )
        resultados, pedidos = self._rodar(alvo)
        self.assertEqual(pedidos, ["https://youtu.be/aaaa"])
        self.assertEqual(len(resultados), 2)
        self.assertTrue(resultados[1].pulado)
        self.assertIn("indisponível", resultados[1].motivo)

    def test_falha_de_um_item_nao_interrompe_o_lote(self):
        alvo = _playlist(
            ItemPlaylist(1, "a", "Um", "https://youtu.be/aaaa"),
            ItemPlaylist(2, "b", "Dois", "https://youtu.be/quebrado"),
            ItemPlaylist(3, "c", "Três", "https://youtu.be/cccc"),
        )
        resultados, pedidos = self._rodar(alvo, falhas={"https://youtu.be/quebrado"})
        self.assertEqual(len(pedidos), 3, "os três deveriam ter sido tentados")
        self.assertEqual(len(resultados), 3)
        self.assertIsNone(resultados[1].caminho)
        self.assertIn("indisponível", resultados[1].motivo)
        self.assertIsNotNone(resultados[2].caminho)

    def test_avisa_a_posicao_de_cada_item(self):
        alvo = _playlist(
            ItemPlaylist(1, "a", "Um", "https://youtu.be/aaaa"),
            ItemPlaylist(2, "b", "Dois", "https://youtu.be/bbbb"),
        )
        vistos: list[tuple[int, int, str]] = []
        with patch("baixador.web.playlist.listar", return_value=alvo), \
                patch.object(Downloader, "baixar", side_effect=lambda *a, **k:
                             ResultadoDownload(url="u", formato="mp3",
                                               caminho=None, iniciado_em="",
                                               finalizado_em="")):
            self.baixador.baixar_playlist(
                "https://www.youtube.com/playlist?list=X", "mp3",
                ao_item=lambda p, t, titulo: vistos.append((p, t, titulo)))
        self.assertEqual(vistos, [(1, 2, "Um"), (2, 2, "Dois")])

    def test_callback_quebrado_nao_derruba_o_lote(self):
        alvo = _playlist(ItemPlaylist(1, "a", "Um", "https://youtu.be/aaaa"))

        def explode(_p, _t, _titulo):
            raise RuntimeError("interface fechou")

        with patch("baixador.web.playlist.listar", return_value=alvo), \
                patch.object(Downloader, "baixar", side_effect=lambda *a, **k:
                             ResultadoDownload(url="u", formato="mp3",
                                               caminho=None, iniciado_em="",
                                               finalizado_em="")):
            resultados = self.baixador.baixar_playlist(
                "https://www.youtube.com/playlist?list=X", "mp3", ao_item=explode)
        self.assertEqual(len(resultados), 1)

    def test_url_invalida_falha_antes_de_listar(self):
        with patch("baixador.web.playlist.listar") as listar:
            with self.assertRaises(Exception):
                self.baixador.baixar_playlist("não é url", "mp3")
        listar.assert_not_called()


class TestBaixarVarios(unittest.TestCase):
    def setUp(self):
        self.raiz = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.raiz, True)
        self.config = Configuracoes(raiz=self.raiz)
        self.baixador = Downloader(self.config)

    def test_devolve_sucesso_ou_falha_na_ordem_recebida(self):
        urls = ["https://youtu.be/a", "https://youtu.be/b", "https://youtu.be/c"]
        falhas = {"https://youtu.be/b"}

        def falso_baixar(url, formato, ao_progresso=None, politica=None,
                         contexto=None, _destino_forcado=None):
            if url in falhas:
                return False, "vídeo privado"
            return True, "MP3 concluído"

        from baixador.app.musica import Aplicacao
        aplicacao = Aplicacao.__new__(Aplicacao)
        aplicacao.baixar = falso_baixar  # type: ignore[assignment]
        resumo = Aplicacao.baixar_varios(aplicacao, urls, "mp3")
        self.assertEqual([url for url, _ok, _m in resumo], urls)
        self.assertEqual([ok for _u, ok, _m in resumo], [True, False, True])
        self.assertEqual(resumo[1][2], "vídeo privado")

    def test_excecao_num_item_nao_para_o_lote(self):
        urls = ["https://youtu.be/a", "https://youtu.be/b", "https://youtu.be/c"]
        chamadas: list[str] = []

        def falso_baixar(url, formato, **kwargs):
            chamadas.append(url)
            if url.endswith("/b"):
                raise ErroDownload("falhou de propósito")
            return True, "ok"

        from baixador.app.musica import Aplicacao
        aplicacao = Aplicacao.__new__(Aplicacao)
        aplicacao.baixar = falso_baixar  # type: ignore[assignment]
        resumo = Aplicacao.baixar_varios(aplicacao, urls, "mp3")
        self.assertEqual(chamadas, urls)
        self.assertEqual([ok for _u, ok, _m in resumo], [True, False, True])
        self.assertIn("falhou de propósito", resumo[1][2])

    def test_avisa_cada_item(self):
        from baixador.app.musica import Aplicacao
        aplicacao = Aplicacao.__new__(Aplicacao)
        aplicacao.baixar = lambda url, formato, **k: (True, "ok")  # type: ignore
        avisos: list[tuple[int, int, str]] = []
        resumo = Aplicacao.baixar_varios(
            aplicacao, ["https://youtu.be/a", "https://youtu.be/b"], "mp3",
            ao_item=lambda p, t, u: avisos.append((p, t, u)))
        self.assertEqual([p for p, _t, _u in avisos], [1, 2])
        self.assertTrue(all(t == 2 for _p, t, _u in avisos))
        self.assertEqual(len(resumo), 2)

    def test_lista_vazia_nao_quebra(self):
        from baixador.app.musica import Aplicacao
        aplicacao = Aplicacao.__new__(Aplicacao)
        self.assertEqual(Aplicacao.baixar_varios(aplicacao, [], "mp3"), [])


class TestArgumentosPlaylist(unittest.TestCase):
    def setUp(self):
        self.raiz = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.raiz, True)
        (self.raiz / "ferramentas").mkdir(exist_ok=True)
        # Só os argumentos importam aqui: o ffmpeg não precisa existir.
        (self.raiz / "ferramentas" / "ffmpeg").write_text("")
        self.baixador = Downloader(Configuracoes(raiz=self.raiz))

    def test_no_playlist_por_padrao(self):
        """Um vídeo dentro de playlist deve baixar **só ele**."""
        comando = self.baixador.construir_argumentos(
            "https://www.youtube.com/watch?v=a&list=X", "mp3")
        self.assertIn("--no-playlist", comando)
        self.assertNotIn("--yes-playlist", comando)

    def test_playlist_so_quando_pedido(self):
        comando = self.baixador.construir_argumentos(
            "https://www.youtube.com/playlist?list=X", "mp3", playlist=True)
        self.assertNotIn("--no-playlist", comando)
        self.assertIn("--yes-playlist", comando)


if __name__ == "__main__":
    unittest.main()
