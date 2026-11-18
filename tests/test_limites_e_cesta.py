"""Teto de duração, filtro de ao vivo e os recursos novos da cesta.

Regra de ouro da especificação: item fora do filtro **aparece com o motivo** —
nunca desaparece sem explicação.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from limites import avaliar, estimar, filtrar, tamanho_legivel, tempo_legivel
from selecao import ItemSelecao, Selecao


class TestAvaliacao(unittest.TestCase):
    def test_sem_teto_tudo_passa(self):
        resultado = avaliar("Qualquer coisa", duracao=3600,
                            duracao_maxima_min=0)
        self.assertTrue(resultado.marcar)
        self.assertEqual(resultado.motivo, "")

    def test_acima_do_teto_tem_motivo_com_numeros(self):
        resultado = avaliar("Documentário", duracao=1500,
                            duracao_maxima_min=10)
        self.assertFalse(resultado.marcar)
        self.assertTrue(resultado.acima_do_teto)
        self.assertIn("25 min", resultado.motivo)
        self.assertIn("10 min", resultado.motivo)

    def test_no_limite_exato_passa(self):
        self.assertTrue(avaliar("Na linha", duracao=600,
                                duracao_maxima_min=10).marcar)

    def test_duracao_desconhecida_nao_e_penalizada(self):
        resultado = avaliar("Sem duração", duracao=None,
                            duracao_maxima_min=5)
        self.assertTrue(resultado.marcar)

    def test_ao_vivo_so_quando_o_filtro_esta_ligado(self):
        self.assertFalse(avaliar("Show ao vivo", duracao=200,
                                 filtrar_ao_vivo=False).ao_vivo)
        resultado = avaliar("Show ao vivo", duracao=200, filtrar_ao_vivo=True)
        self.assertTrue(resultado.ao_vivo)
        self.assertIn("ao vivo", resultado.motivo)

    def test_os_dois_motivos_aparecem_juntos(self):
        resultado = avaliar("Banda ao vivo", duracao=1800,
                            duracao_maxima_min=10, filtrar_ao_vivo=True)
        self.assertIn("limite", resultado.motivo)
        self.assertIn("ao vivo", resultado.motivo)

    def test_filtrar_preserva_ordem_e_nada_some(self):
        class Item:
            def __init__(self, titulo, duracao):
                self.titulo, self.canal, self.duracao = titulo, "", duracao

        itens = [Item("Curta", 100), Item("Longa", 900), Item("Outra", 200)]
        pares = filtrar(itens, duracao_maxima_min=5)
        self.assertEqual([par[0].titulo for par in pares],
                         ["Curta", "Longa", "Outra"])
        self.assertEqual([par[1].marcar for par in pares], [True, False, True])


class TestEstimativas(unittest.TestCase):
    def test_estimar_soma_segundos_e_bytes(self):
        segundos, bytes_ = estimar([200, 300, None])
        self.assertEqual(segundos, 500)
        self.assertGreater(bytes_, 0)

    def test_formatos_legiveis(self):
        self.assertEqual(tempo_legivel(95), "1min 35s")
        self.assertEqual(tempo_legivel(3725), "1h 02min")
        self.assertEqual(tempo_legivel(0), "0s")
        self.assertIn("MB", tamanho_legivel(8_000_000))
        self.assertIn("KB", tamanho_legivel(2000))


class TestCestaAvancada(unittest.TestCase):
    def setUp(self):
        self.raiz = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.raiz, True)
        from configuracoes import Configuracoes

        self.config = Configuracoes(raiz=self.raiz)
        self.selecao = Selecao(self.config)
        for numero in range(4):
            self.selecao.adicionar(ItemSelecao(
                f"https://y/{numero}", f"Faixa {numero}", "Artista", 200,
                origem="Pesquisa"))

    def test_desfazer_remove_devolve_na_posicao_certa(self):
        self.assertEqual(self.selecao.remover_indices([1]), 1)
        self.assertEqual([i.titulo for i in self.selecao.listar()],
                         ["Faixa 0", "Faixa 2", "Faixa 3"])
        self.assertEqual(self.selecao.desfazer_remocao(), 1)
        self.assertEqual([i.titulo for i in self.selecao.listar()],
                         ["Faixa 0", "Faixa 1", "Faixa 2", "Faixa 3"])

    def test_desfazer_sem_nada_removido_devolve_zero(self):
        self.assertEqual(self.selecao.desfazer_remocao(), 0)

    def test_desfazer_nao_duplica_item_readicionado(self):
        self.selecao.remover(["https://y/2"])
        self.selecao.adicionar(ItemSelecao("https://y/2", "Faixa 2"))
        self.assertEqual(self.selecao.desfazer_remocao(), 1)
        self.assertEqual(len(self.selecao.listar()), 4)

    def test_mover_para_topo_e_fim(self):
        self.assertTrue(self.selecao.mover_para(3, 0))
        self.assertEqual(self.selecao.listar()[0].titulo, "Faixa 3")
        self.assertTrue(self.selecao.mover_para(0, -1))
        self.assertEqual(self.selecao.listar()[-1].titulo, "Faixa 3")
        self.assertFalse(self.selecao.mover_para(99, 0))

    def test_mover_persiste(self):
        self.selecao.mover_para(2, 0)
        reaberta = Selecao(self.config)
        self.assertEqual(reaberta.listar()[0].titulo, "Faixa 2")

    def test_estimativa_da_cesta(self):
        segundos, bytes_ = self.selecao.estimativa()
        self.assertEqual(segundos, 800)
        self.assertGreater(bytes_, 0)

    def test_ja_na_biblioteca_avisa_pelo_origem_url(self):
        class Musica:
            def __init__(self, url):
                self.origem_url = url

        class BibliotecaFalsa:
            def listar(self):
                return [Musica("https://y/1")]

        repetidas = self.selecao.ja_na_biblioteca(BibliotecaFalsa())
        self.assertEqual([item.url for item in repetidas], ["https://y/1"])

    def test_biblioteca_com_erro_nao_derruba_a_cesta(self):
        class Quebrada:
            def listar(self):
                raise RuntimeError("banco travado")

        self.assertEqual(self.selecao.ja_na_biblioteca(Quebrada()), [])


class TestRegraNaFachada(unittest.TestCase):
    def setUp(self):
        self.raiz = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.raiz, True)
        self._ambiente = patch.dict(os.environ)
        self._ambiente.start()
        self.addCleanup(self._ambiente.stop)
        from central import Central
        from configuracoes import Configuracoes
        from preferencias import Preferencias

        self.central = Central(
            Configuracoes(raiz=self.raiz,
                          diretorio_musicas=self.raiz / "Musicas"),
            Preferencias(metadados_ativos=False, buscar_capas=False,
                         sincronizar_ao_abrir=False,
                         duracao_maxima_min=5, filtrar_ao_vivo=True))

    def test_fachada_usa_o_teto_das_preferencias(self):
        from playlist import ItemPlaylist

        itens = [ItemPlaylist(1, "a", "Curta", "https://y/a", 120),
                 ItemPlaylist(2, "b", "Longa", "https://y/b", 1200),
                 ItemPlaylist(3, "c", "Ao Vivo", "https://y/c", 200)]
        avaliados = self.central.avaliar_itens(itens)
        self.assertEqual([av.marcar for _i, av in avaliados],
                         [True, False, False])
        self.assertIn("limite", avaliados[1][1].motivo)

    def test_preferencia_invalida_e_recusada(self):
        from preferencias import Preferencias

        with self.assertRaises(ValueError):
            Preferencias(duracao_maxima_min=601).validar()
        Preferencias(duracao_maxima_min=0).validar()
        Preferencias(duracao_maxima_min=600).validar()


if __name__ == "__main__":
    unittest.main()
