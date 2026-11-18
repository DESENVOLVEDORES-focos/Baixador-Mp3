"""Atualização do yt-dlp: mensagens honestas, sem inventar sucesso."""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import atualizacao
from configuracoes import Configuracoes


class _Processo:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class TestVersao(unittest.TestCase):
    def setUp(self):
        self.raiz = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.raiz, True)
        (self.raiz / "ferramentas").mkdir(exist_ok=True)
        self.config = Configuracoes(raiz=self.raiz)

    def test_le_a_primeira_linha_do_version(self):
        with patch("atualizacao.subprocess.run",
                   return_value=_Processo(stdout="2026.10.31\n")):
            self.assertEqual(atualizacao.versao_instalada(self.config), "2026.10.31")

    def test_falha_devolve_string_vazia(self):
        with patch("atualizacao.subprocess.run",
                   return_value=_Processo(returncode=2, stderr="erro")):
            self.assertEqual(atualizacao.versao_instalada(self.config), "")

    def test_timeout_nao_quebra(self):
        with patch("atualizacao.subprocess.run",
                   side_effect=atualizacao.subprocess.TimeoutExpired("x", 1)):
            self.assertEqual(atualizacao.versao_instalada(self.config), "")


class TestAtualizar(unittest.TestCase):
    def setUp(self):
        self.raiz = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.raiz, True)
        (self.raiz / "ferramentas").mkdir(exist_ok=True)
        self.config = Configuracoes(raiz=self.raiz)

    def _rodar(self, versoes, pip=None):
        """``versoes`` em ordem: primeira chamada = antes, segunda = depois."""
        sequencia = iter(versoes)

        def falso_run(comando, **kwargs):
            if comando[-1] == "--version":
                return _Processo(stdout=next(sequencia, ""))
            return pip or _Processo()

        with patch("atualizacao.subprocess.run", side_effect=falso_run):
            return atualizacao.atualizar(self.config)

    def test_atualiza_e_confirma_a_versao_nova(self):
        resultado = self._rodar(["2024.01.01", "2026.11.01"])
        self.assertTrue(resultado.ok)
        self.assertTrue(resultado.mudou)
        self.assertEqual(resultado.versao_depois, "2026.11.01")
        self.assertIn("atualizado", resultado.mensagem)

    def test_ja_na_ultima_versao_nao_mente_dizendo_que_atualizou(self):
        resultado = self._rodar(["2026.11.01", "2026.11.01"])
        self.assertTrue(resultado.ok)
        self.assertFalse(resultado.mudou)
        self.assertIn("Já estava", resultado.mensagem)

    def test_pip_falhou_mantem_programa_funcionando(self):
        resultado = self._rodar(
            ["2024.01.01", "2024.01.01"],
            pip=_Processo(returncode=1, stderr="ERROR: sem internet"))
        self.assertFalse(resultado.ok)
        self.assertIn("falhou", resultado.mensagem)
        self.assertIn("continua funcionando", resultado.mensagem)

    def test_exe_separado_nao_e_sobrescrito(self):
        (self.raiz / "ferramentas" / "yt-dlp.exe").write_text("")
        resultado = self._rodar(["2024.01.01"])
        self.assertFalse(resultado.ok)
        self.assertIn("programa separado", resultado.mensagem)
        self.assertIn("github.com/yt-dlp/yt-dlp/releases", resultado.mensagem)

    def test_sem_versao_confirmada_nao_declara_sucesso(self):
        resultado = self._rodar(["2024.01.01", ""])
        self.assertFalse(resultado.ok)
        self.assertIn("não consegui confirmar", resultado.mensagem)

    def test_comando_do_pip_sem_shell(self):
        chamadas = []

        def falso_run(comando, **kwargs):
            chamadas.append((comando, kwargs))
            if comando[-1] == "--version":
                return _Processo(stdout="2024.01.01")
            return _Processo()

        with patch("atualizacao.subprocess.run", side_effect=falso_run):
            atualizacao.atualizar(self.config)
        pip = [c for c, _k in chamadas if "-m" in c and "pip" in c][0]
        self.assertIn("--upgrade", pip)
        self.assertIn("yt-dlp", pip)
        self.assertNotIn("shell", chamadas[0][1])


if __name__ == "__main__":
    unittest.main()
