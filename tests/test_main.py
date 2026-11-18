"""``main.py``: a porta de entrada escolhe a tela certa e não mente no erro."""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import main as entrada
from main import Escolha, escolher_modo

RAIZ = Path(__file__).resolve().parents[1]


class TestLinhaDeComando(unittest.TestCase):
    def test_sem_argumento_abre_a_central(self):
        self.assertEqual(escolher_modo([]), Escolha("central"))

    def test_bandeira_classica(self):
        for bandeira in ("--classica", "-c", "--antiga", "--classic"):
            with self.subTest(bandeira=bandeira):
                self.assertEqual(escolher_modo([bandeira]).modo, "classica")

    def test_flags_explicitas(self):
        self.assertEqual(escolher_modo(["--central"]).modo, "central")
        self.assertEqual(escolher_modo(["--versao"]).modo, "versao")
        self.assertEqual(escolher_modo(["-h"]).modo, "ajuda")

    def test_argumento_desconhecido_recusa_em_vez_de_abrir_tela_errada(self):
        with self.assertRaises(SystemExit) as erro:
            escolher_modo(["--converter-tudo"])
        self.assertIn("Opção desconhecida", str(erro.exception.code))

    def test_abre_janela(self):
        self.assertTrue(Escolha("central").abre_janela)
        self.assertTrue(Escolha("classica").abre_janela)
        self.assertFalse(Escolha("ajuda").abre_janela)

    def test_main_versao_e_ajuda_nao_abrem_tk(self):
        with patch("main._avisar") as avisar:
            self.assertEqual(entrada.main(["--versao"]), 0)
            self.assertEqual(entrada.main(["--ajuda"]), 0)
            avisar.assert_not_called()

    def test_sem_tkinter_explica_e_sai_com_erro(self):
        with patch.dict(sys.modules, {"tkinter": None}), \
                patch("main._avisar") as avisar:
            self.assertEqual(entrada.main([]), 1)
            mensagem = avisar.call_args[0][1]
            self.assertIn("Tkinter", mensagem)
            self.assertIn("configurar.bat", mensagem)

    def test_falha_ao_abrir_mostra_o_motivo(self):
        falso = type(sys)("tkinter")
        with patch.dict(sys.modules, {"tkinter": falso}), \
                patch("baixador.app.central_app.iniciar", side_effect=RuntimeError("banco travado")), \
                patch("main._avisar") as avisar:
            self.assertEqual(entrada.main([]), 1)
            self.assertIn("banco travado", avisar.call_args[0][1])

    def test_classica_delega_para_interface(self):
        falso = type(sys)("tkinter")
        interface = type(sys)("baixador.app.interface")
        interface.main = lambda: 0
        with patch.dict(sys.modules, {"tkinter": falso,
                                      "baixador.app.interface": interface}):
            self.assertEqual(entrada.main(["--classica"]), 0)

    def test_versao_bate_com_o_modulo(self):
        resultado = subprocess.run([sys.executable, str(RAIZ / "main.py"),
                                    "--versao"], capture_output=True, text=True,
                                   cwd=RAIZ)
        self.assertEqual(resultado.returncode, 0)
        self.assertIn(entrada.VERSAO, resultado.stdout)


class TestAtalhosDoWindows(unittest.TestCase):
    """O usuário abre o programa pelo ``iniciar.bat``: ele precisa chamar a Central."""

    def test_iniciar_abre_o_main(self):
        conteudo = (RAIZ / "iniciar.bat").read_text(encoding="utf-8",
                                                   errors="replace")
        self.assertIn("main.py", conteudo)
        self.assertNotIn("interface.py", conteudo)

    def test_atalho_da_interface_antiga_continua_existindo(self):
        conteudo = (RAIZ / "iniciar_interface.bat").read_text(
            encoding="utf-8", errors="replace")
        self.assertIn("main.py --classica", conteudo)


if __name__ == "__main__":
    unittest.main()
