"""Todo botão da Central tem de funcionar — sem música, sem rede, sem arquivo.

O teste anterior (em ``test_central_app.py``) só conferia se o método existia.
Este **executa** cada ``command`` numa janela recém-aberta, com:

- biblioteca vazia, cesta vazia, fila vazia;
- pesquisa que falha (sem rede) e download que falha;
- ``filedialog``/``messagebox``/``simpledialog`` dublados (ninguém fica preso);
- ``_executar`` síncrono, para o efeito acontecer dentro do teste.

Nenhum comando pode levantar exceção. Se levantar, o teste falha com o nome do
botão — é exatamente o "botão morto" que a especificação proíbe.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from tests.test_central_app import TestCentralApp, _widgets_criados


class TestNenhumBotaoMorto(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        TestCentralApp.setUpClass()
        cls.modulo = TestCentralApp.modulo
        cls.central = TestCentralApp.central
        cls.app = TestCentralApp.app

    @classmethod
    def tearDownClass(cls):
        TestCentralApp.tearDownClass()

    def _todos_os_botoes(self) -> list:
        """Abre todas as páginas numa janela nova e coleta cada botão real."""
        del _widgets_criados[:]
        janela = self.modulo.CentralApp(self.central)
        for chave, _rotulo, _icone in self.modulo.PAGINAS:
            janela.mostrar(chave)
        return [w for w in _widgets_criados
                if getattr(w, "tipo", "") == "Button"
                and callable(w.kwargs.get("command"))]

    def test_há_botões_em_todas_as_páginas(self):
        botoes = self._todos_os_botoes()
        self.assertGreaterEqual(len(botoes), 45)

    def test_executar_todos_os_botoes_sem_dados_nem_rede(self):
        """O teste que importa: cada botão é clicado de verdade."""
        app = self.app
        # estado limpo e sem rede
        self.central.selecao.limpar()
        with patch.object(self.central.gerenciador, "_itens", []), \
                patch.object(self.central, "pesquisar",
                             side_effect=RuntimeError("sem rede")), \
                patch.object(self.central, "listar_playlist",
                             side_effect=RuntimeError("sem rede")), \
                patch.object(self.central, "listar_mais_playlist",
                             side_effect=RuntimeError("sem rede")), \
                patch.object(self.central.aplicacao, "baixar",
                             return_value=(False, "sem rede")), \
                patch.object(app, "_executar",
                             side_effect=lambda trabalho, concluir=None, falhar=None:
                             (concluir(trabalho()) if concluir else trabalho())), \
                patch.object(app, "_abrir_no_sistema"), \
                patch.object(self.modulo, "filedialog") as dialogo, \
                patch.object(self.modulo, "simpledialog") as simples, \
                patch.object(self.modulo, "messagebox") as caixa:
            dialogo.askopenfilename.return_value = ""
            dialogo.askdirectory.return_value = ""
            simples.askstring.return_value = ""
            caixa.askyesno.return_value = False
            falhas = []
            for botao in self._todos_os_botoes():
                rotulo = botao.kwargs.get("text", "?")
                try:
                    botao.kwargs["command"]()
                except Exception as erro:  # botão morto
                    falhas.append(f"{rotulo!r}: {type(erro).__name__}: {erro}")
        self.assertEqual(falhas, [], "botões que estouraram ao clicar:\n"
                                     + "\n".join(falhas))

    def test_executar_botoes_em_ordem_diferente(self):
        """Clicar fora de ordem (usuário não segue manual) também não pode quebrar."""
        app = self.app
        botoes = list(reversed(self._todos_os_botoes()))
        with patch.object(app, "_executar",
                          side_effect=lambda trabalho, concluir=None, falhar=None:
                          (concluir(trabalho()) if concluir else trabalho())), \
                patch.object(app, "_abrir_no_sistema"), \
                patch.object(self.central, "pesquisar",
                             side_effect=RuntimeError("sem rede")), \
                patch.object(self.modulo, "filedialog") as dialogo, \
                patch.object(self.modulo, "simpledialog") as simples, \
                patch.object(self.modulo, "messagebox") as caixa:
            dialogo.askopenfilename.return_value = ""
            dialogo.askdirectory.return_value = ""
            simples.askstring.return_value = ""
            caixa.askyesno.return_value = False
            falhas = []
            for botao in botoes:
                try:
                    botao.kwargs["command"]()
                except Exception as erro:
                    falhas.append(f"{botao.kwargs.get('text')!r}: {erro}")
        self.assertEqual(falhas, [])

    def test_botoes_da_barra_de_navegacao_abrem_as_paginas(self):
        app = self.app
        for chave, botao in app._botoes_nav.items():
            botao.kwargs["command"]()
            self.assertEqual(app.pagina_atual, chave)

    def test_botoes_do_player_nao_estouram_sem_audio(self):
        app = self.app
        from reprodutor import Faixa

        self.central.reprodutor.parar(silencioso=True)
        self.central.reprodutor.fila = []
        with patch.object(self.central, "ffplay", []):
            for acao in (app._player_tocar, app._player_pausar,
                         app._player_proxima, app._player_anterior,
                         app._player_aleatorio, app._player_repeticao,
                         app._player_volume):
                acao()  # nenhuma pode levantar
        # com fila inexistente, o usuário recebe explicação, não silêncio
        self.assertTrue(app.player_titulo.get())
        self.central.reprodutor.definir_fila([Faixa("/tmp/nao_existe.mp3", "X")])

    def test_botoes_de_configuracao_sem_chave_nem_cookie(self):
        app = self.app
        app.mostrar("config")
        with patch.object(self.modulo, "filedialog") as dialogo, \
                patch.object(self.modulo, "messagebox") as caixa:
            dialogo.askopenfilename.return_value = ""
            caixa.askyesno.return_value = False
            for acao in (app._importar_chave, app._testar_chave,
                         app._remover_chave, app._importar_cookies,
                         app._remover_cookies, app._atualizar_ytdlp,
                         app._testar_dependencias, app._limpar_temporarios,
                         app._salvar_config):
                acao()


if __name__ == "__main__":
    unittest.main()
