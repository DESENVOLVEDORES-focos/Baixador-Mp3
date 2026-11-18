"""Gerenciador de downloads: estados, concorrência, pausar/retomar/cancelar.

Os downloads são dublês determinísticos (o download real é exercitado em
``tests/test_lote.py`` e ``tests/test_integracao_real.py`` quando há FFmpeg).
"""

from __future__ import annotations

import shutil
import tempfile
import time
import unittest
from pathlib import Path

from baixador.nucleo.configuracoes import Configuracoes
from baixador.nucleo.gerenciador import ESTADOS, GerenciadorDownloads, ROTULO_ESTADO


class _AplicacaoFalsa:
    """Imita ``Aplicacao.baixar`` com controle de tempo e falha."""

    def __init__(self, atraso: float = 0.02, falhar: set[str] | None = None):
        self.chamadas: list[tuple[str, str]] = []
        self.atraso = atraso
        self.falhar = falhar or set()
        self.ultimo_caminho = ""
        self.cancelados = 0

    def baixar(self, url, formato, ao_progresso=None, politica=None, contexto=None):
        self.chamadas.append((url, formato))
        if ao_progresso is not None:
            from baixador.web.downloader import Progresso

            ao_progresso(Progresso(percentual=40.0, etapa="Baixando"))
        time.sleep(self.atraso)
        if url in self.falhar:
            return False, "vídeo privado"
        self.ultimo_caminho = f"/tmp/{url.rsplit('/', 1)[-1]}.mp3"
        return True, "MP3 concluído"

    def cancelar_download(self) -> bool:
        self.cancelados += 1
        return True


class TestGerenciador(unittest.TestCase):
    def setUp(self):
        self.raiz = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.raiz, True)
        self.config = Configuracoes(raiz=self.raiz)
        self.mudancas: list = []
        self.concluidos: list = []

    def _gerenciador(self, aplicacao=None, simultaneos: int = 2):
        return GerenciadorDownloads(
            aplicacao or _AplicacaoFalsa(), simultaneos=simultaneos,
            # o dublê precisa copiar o estado na hora: o item é mutável e
            # segue vivo depois do callback (a UI real copia para a fila)
            ao_mudar=lambda item: self.mudancas.append((item.id, item.estado)),
            ao_concluir=self.concluidos.append)

    def test_processa_todos_e_conta(self):
        aplicacao = _AplicacaoFalsa()
        gerenciador = self._gerenciador(aplicacao)
        gerenciador.adicionar_varios([(f"https://y/{n}", "mp3") for n in range(5)])
        self.assertEqual(gerenciador.iniciar(), 5)
        self.assertTrue(gerenciador.aguardar(20))
        resumo = gerenciador.resumo()
        self.assertEqual(resumo["concluido"], 5)
        self.assertEqual(len(aplicacao.chamadas), 5)
        self.assertEqual(len(self.concluidos), 5)

    def test_estados_passam_por_processando_e_concluido(self):
        gerenciador = self._gerenciador()
        gerenciador.adicionar("https://y/a", "mp3", titulo="Música")
        gerenciador.iniciar()
        gerenciador.aguardar(20)
        vistos = {estado for _id, estado in self.mudancas}
        self.assertIn("aguardando", vistos)
        self.assertIn("processando", vistos)
        self.assertIn("concluido", vistos)
        self.assertEqual(rotulo := ROTULO_ESTADO["concluido"], "Concluído")
        self.assertTrue(rotulo)

    def test_falha_marca_erro_e_motivo(self):
        aplicacao = _AplicacaoFalsa(falhar={"https://y/ruim"})
        gerenciador = self._gerenciador(aplicacao)
        gerenciador.adicionar_varios([("https://y/ok", "mp3"),
                                      ("https://y/ruim", "mp3")])
        gerenciador.iniciar()
        gerenciador.aguardar(20)
        ruim = next(i for i in gerenciador.listar() if i.url == "https://y/ruim")
        self.assertEqual(ruim.estado, "falhou")
        self.assertIn("privado", ruim.detalhe_erro)
        self.assertEqual(gerenciador.repetir_falhas(), 1)
        self.assertTrue(gerenciador.aguardar(20))

    def test_pausar_para_de_iniciar_e_retomar_continua(self):
        aplicacao = _AplicacaoFalsa(atraso=0.15)
        gerenciador = self._gerenciador(aplicacao, simultaneos=1)
        gerenciador.adicionar_varios([(f"https://y/{n}", "mp3") for n in range(4)])
        gerenciador.iniciar()
        time.sleep(0.05)
        pausados = gerenciador.pausar()
        self.assertGreaterEqual(pausados, 1)
        self.assertTrue(gerenciador.pausado)
        gerenciador.aguardar(20)
        self.assertLess(gerenciador.resumo()["concluido"], 4)
        retomados = gerenciador.retomar()
        self.assertGreaterEqual(retomados, 1)
        self.assertTrue(gerenciador.aguardar(30))
        self.assertEqual(gerenciador.resumo()["concluido"], 4)

    def test_cancelar_item_e_tudo(self):
        aplicacao = _AplicacaoFalsa(atraso=0.2)
        gerenciador = self._gerenciador(aplicacao, simultaneos=1)
        gerenciador.adicionar_varios([(f"https://y/{n}", "mp3") for n in range(3)])
        gerenciador.iniciar()
        time.sleep(0.05)
        primeiro = gerenciador.listar()[0]
        self.assertTrue(gerenciador.cancelar(primeiro.id))
        self.assertEqual(gerenciador.obter(primeiro.id).estado, "cancelado")
        cancelados = gerenciador.cancelar_tudo()
        self.assertGreaterEqual(cancelados, 1)
        gerenciador.aguardar(20)
        self.assertEqual(gerenciador.resumo()["concluido"], 0)
        self.assertGreaterEqual(aplicacao.cancelados, 1)

    def test_ignora_duplicata_ativa(self):
        gerenciador = self._gerenciador()
        self.assertEqual(gerenciador.adicionar_varios(
            [("https://y/a", "mp3"), ("https://y/a", "mp3")]), 1)
        # depois de falhar, pode entrar de novo
        aplicacao = _AplicacaoFalsa(falhar={"https://y/a"})
        outro = GerenciadorDownloads(aplicacao, simultaneos=1)
        outro.adicionar_varios([("https://y/a", "mp3")])
        outro.iniciar()
        outro.aguardar(20)
        self.assertEqual(outro.adicionar_varios([("https://y/a", "mp3")]), 1)

    def test_remover_finalizados_e_limpar(self):
        gerenciador = self._gerenciador()
        gerenciador.adicionar_varios([(f"https://y/{n}", "mp3") for n in range(2)])
        gerenciador.iniciar()
        gerenciador.aguardar(20)
        self.assertEqual(gerenciador.remover_finalizados(), 2)
        self.assertEqual(gerenciador.listar(), [])
        gerenciador.adicionar("https://y/z", "mp3")
        self.assertEqual(gerenciador.limpar(), 1)

    def test_excecao_inesperada_vira_falha(self):
        class Quebra:
            ultimo_caminho = ""

            def baixar(self, *a, **k):
                raise RuntimeError("estourou")

            def cancelar_download(self):
                return False

        gerenciador = self._gerenciador(Quebra())
        gerenciador.adicionar("https://y/x", "mp3")
        gerenciador.iniciar()
        self.assertTrue(gerenciador.aguardar(20))
        item = gerenciador.listar()[0]
        self.assertEqual(item.estado, "falhou")
        self.assertIn("estourou", item.detalhe_erro)

    def test_estados_conhecidos(self):
        self.assertIn("pausado", ESTADOS)
        self.assertIn("metadados", ESTADOS)
        self.assertEqual(len(ESTADOS), 8)


if __name__ == "__main__":
    unittest.main()
