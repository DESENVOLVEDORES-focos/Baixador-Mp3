"""A fila de downloads não pode desaparecer quando o programa fecha.

Regra que o usuário cobra: nada de "baixar amanhã do zero". Aqui um
``GerenciadorDownloads`` real é fechado (objeto novo) e reaberto lendo o
``fila.json``, com aplicação falsa para não depender de rede.
"""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from gerenciador import GerenciadorDownloads, ItemDownload


class _AplicacaoFalsa:
    def __init__(self, falhar: set[str] | None = None):
        self.chamadas: list[str] = []
        self.falhar = falhar or set()
        self.ultimo_caminho = ""

    def baixar(self, url, formato, ao_progresso=None, politica=None, contexto=None):
        self.chamadas.append(url)
        if url in self.falhar:
            return False, "vídeo privado"
        return True, "pronto"

    def cancelar_download(self):
        return True


class TestPersistenciaDaFila(unittest.TestCase):
    def setUp(self):
        self.raiz = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.raiz, True)
        self.fila = self.raiz / "fila.json"

    def _novo(self, aplicacao=None) -> GerenciadorDownloads:
        gerenciador = GerenciadorDownloads(aplicacao or _AplicacaoFalsa(),
                                           simultaneos=1)
        gerenciador.usar_arquivo(self.fila)
        return gerenciador

    def test_sem_arquivo_carregar_nao_quebra(self):
        gerenciador = self._novo()
        self.assertEqual(gerenciador.carregar(), {})
        self.assertEqual(gerenciador.listar(), [])

    def test_item_aguardando_volta_aguardando(self):
        primeiro = self._novo()
        primeiro.adicionar("https://y/a", "mp3", titulo="Faixa A",
                           origem="Playlist X")
        segundo = self._novo()
        self.assertEqual(segundo.carregar(), {"aguardando": 1})
        item = segundo.listar()[0]
        self.assertEqual(item.titulo, "Faixa A")
        self.assertEqual(item.origem, "Playlist X")
        self.assertEqual(item.estado, "aguardando")
        self.assertEqual(item.id, 1)

    def test_item_no_meio_vira_pausado_com_motivo(self):
        gerenciador = self._novo()
        gerenciador.adicionar("https://y/b", "mp3")
        item = gerenciador.listar()[0]
        item.estado = "processando"
        gerenciador.salvar(forcar=True)

        outro = self._novo()
        contagem = outro.carregar()
        self.assertEqual(contagem["pausado"], 1)
        recarregado = outro.listar()[0]
        self.assertEqual(recarregado.estado, "pausado")
        self.assertIn("fechar o programa", recarregado.mensagem)
        self.assertEqual(recarregado.percentual, 0.0)

    def test_concluido_e_cancelado_nao_voltam(self):
        gerenciador = self._novo()
        gerenciador.adicionar("https://y/ok", "mp3")
        gerenciador.adicionar("https://y/xis", "mp3")
        itens = gerenciador.listar()
        itens[0].estado = "concluido"
        itens[1].estado = "cancelado"
        gerenciador.salvar(forcar=True)

        outro = self._novo()
        self.assertEqual(outro.carregar(), {})
        self.assertEqual(outro.listar(), [])

    def test_falhou_pode_ser_tentado_de_novo(self):
        gerenciador = self._novo(_AplicacaoFalsa(falhar={"https://y/ruim"}))
        gerenciador.adicionar("https://y/ruim", "mp3")
        gerenciador.iniciar()
        gerenciador.aguardar(20)
        self.assertEqual(gerenciador.listar()[0].estado, "falhou")

        outro = self._novo(_AplicacaoFalsa())
        self.assertEqual(outro.carregar().get("falhou"), 1)
        self.assertEqual(outro.repetir_falhas(), 1)
        outro.iniciar()
        self.assertTrue(outro.aguardar(20))
        self.assertEqual(outro.listar()[0].estado, "concluido")

    def test_nada_inicia_sozinho_ao_carregar(self):
        primeiro = self._novo()
        primeiro.adicionar("https://y/c", "mp3")
        aplicacao = _AplicacaoFalsa()
        segundo = self._novo(aplicacao)
        segundo.carregar()
        self.assertEqual(aplicacao.chamadas, [])  # só o usuário decide
        self.assertTrue(segundo.tem_pendentes())

    def test_arquivo_corrompido_nao_derruba_a_abertura(self):
        self.fila.write_text("{isso não é json", encoding="utf-8")
        gerenciador = self._novo()
        self.assertEqual(gerenciador.carregar(), {})
        self.assertEqual(gerenciador.listar(), [])
        # e continua funcionando normalmente
        gerenciador.adicionar("https://y/d", "mp3")
        self.assertTrue(self.fila.is_file())

    def test_arquivo_com_lixo_no_meio_aproveita_o_que_da(self):
        dados = [
            {"url": "https://y/bom", "formato": "mp3", "estado": "aguardando"},
            {"sem_url": True},
            "texto solto",
            {"url": "https://y/bom2", "formato": "mp3", "estado": "processando",
             "id": 7},
        ]
        self.fila.write_text(json.dumps(dados), encoding="utf-8")
        gerenciador = self._novo()
        contagem = gerenciador.carregar()
        self.assertEqual(len(gerenciador.listar()), 2)
        self.assertEqual(contagem["aguardando"], 1)
        self.assertEqual(contagem["pausado"], 1)
        # id novo não colide com o que voltou
        novo = gerenciador.adicionar("https://y/novo", "mp3")
        self.assertEqual(novo.id, 8)

    def test_gravacao_nao_repete_estado_igual(self):
        gerenciador = self._novo()
        gerenciador.adicionar("https://y/e", "mp3")
        self.assertFalse(gerenciador.salvar())  # nada mudou desde a última
        item = gerenciador.listar()[0]
        item.estado = "pausado"
        self.assertTrue(gerenciador.salvar())

    def test_json_nao_guarda_caminho_de_maquina_errada(self):
        gerenciador = self._novo()
        gerenciador.adicionar("https://y/f", "mp3")
        dados = json.loads(self.fila.read_text(encoding="utf-8"))
        self.assertEqual(dados[0]["url"], "https://y/f")
        self.assertNotIn("_iniciado_em", dados[0])
        self.assertIn("criado_em", dados[0])


class TestItemDownloadCompativel(unittest.TestCase):
    def test_campo_novo_nao_quebra_arquivo_antigo(self):
        antigo = {"url": "https://y/velho", "formato": "mp3", "estado": "aguardando"}
        item = ItemDownload(**antigo)
        self.assertEqual(item.id, 0)
        self.assertEqual(item.titulo, "")


if __name__ == "__main__":
    unittest.main()


class TestRetomadaPelaCentral(unittest.TestCase):
    """O caminho real: fecha a Central, abre de novo, a fila está lá."""

    def setUp(self):
        import os
        from unittest.mock import patch as _patch

        from configuracoes import Configuracoes
        from preferencias import Preferencias

        self.raiz = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.raiz, True)
        self._ambiente = _patch.dict(os.environ)
        self._ambiente.start()
        self.addCleanup(self._ambiente.stop)
        self.config = Configuracoes(raiz=self.raiz,
                                    diretorio_musicas=self.raiz / "Musicas")
        self.config.musicas.mkdir(parents=True, exist_ok=True)
        self.prefs = Preferencias(metadados_ativos=False, buscar_capas=False,
                                  sincronizar_ao_abrir=False,
                                  downloads_simultaneos=1)

    def _abrir(self):
        from central import Central

        central = Central(self.config, self.prefs)
        central.aplicacao.baixar = lambda *a, **k: (True, "ok")
        return central

    def test_fila_sobrevive_ao_fechamento(self):
        primeira = self._abrir()
        primeira.gerenciador.adicionar("https://y/1", "mp3", titulo="Um")
        primeira.gerenciador.adicionar("https://y/2", "mp3", titulo="Dois")
        primeira.fechar()

        self.assertTrue((self.config.dados / "fila.json").is_file())
        segunda = self._abrir()
        self.assertEqual(len(segunda.downloads()), 2)
        self.assertEqual(segunda.fila_salva(), {"aguardando": 2})
        self.assertEqual([i.titulo for i in segunda.downloads()],
                         ["Um", "Dois"])
        # nada começou sozinho
        self.assertFalse(segunda.gerenciador.rodando)

    def test_interrompido_vira_pausado_e_retoma(self):
        primeira = self._abrir()
        item = primeira.gerenciador.adicionar("https://y/3", "mp3")
        item.estado = "processando"
        primeira.gerenciador.salvar(forcar=True)
        primeira.fechar()

        segunda = self._abrir()
        self.assertEqual(segunda.fila_salva(), {"pausado": 1})
        self.assertIn("fechar o programa", segunda.downloads()[0].mensagem)
        # o botão da tela chama exatamente isto
        self.assertEqual(segunda.retomar_fila_salva(), 1)
        segunda.gerenciador.aguardar(20)
        self.assertEqual(segunda.downloads()[0].estado, "concluido")

    def test_sem_fila_salva_a_abertura_e_normal(self):
        central = self._abrir()
        self.assertEqual(central.fila_salva(), {})
        self.assertEqual(central.downloads(), [])

    def test_fila_ilegivel_nao_impede_abrir(self):
        self.config.dados.mkdir(parents=True, exist_ok=True)
        (self.config.dados / "fila.json").write_text("{{{", encoding="utf-8")
        central = self._abrir()
        self.assertEqual(central.downloads(), [])
        central.gerenciador.adicionar("https://y/9", "mp3")
        self.assertEqual(len(central.downloads()), 1)
