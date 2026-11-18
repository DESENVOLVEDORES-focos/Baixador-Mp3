"""Testes da lógica da interface (sem abrir janela) e das miniaturas.

Este ambiente Linux não tem Tkinter instalado, então a janela real não é
aberta aqui (registrado no DEVELOPMENT_LOG). O que é testado é justamente a
camada que a auditoria apontou como defeituosa: data do histórico, resumo
musical na tela, mensagem de "já existe", detecção de falta de login,
miniaturas e formatação do progresso.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import thumbs
from configuracoes import Configuracoes
from interface import (
    ControladorInterface, _data_legivel, _parece_falta_de_login, _resumo_texto,
)
from preferencias import Preferencias, carregar

def jpeg_valido() -> bytes:
    """JPEG real 2x2 gerado com Pillow (dependência de teste, não do app)."""
    from io import BytesIO

    try:
        from PIL import Image  # type: ignore
    except ImportError:  # pragma: no cover
        raise unittest.SkipTest("Pillow não instalado para gerar a fixture")
    buffer = BytesIO()
    Image.new("RGB", (2, 2), (200, 30, 30)).save(buffer, format="JPEG")
    return buffer.getvalue()


# JPEG mínimo válido (fallback fixo) e um HTML que não é imagem.
JPEG_1X1 = bytes.fromhex(
    "ffd8ffe000104a46494600010100000100010000ffdb0043000806060706050807"
    "070909090a0c140d0c0b0b0c1912130f141d1a1f1e1d1a1c1c20242e2720222c23"
    "1c1c2837292c30313434341f27393d38323c2e333432ffc0000b0800010001010111"
    "00ffc4001f0000010501010101010100000000000000000102030405060708090a0b"
    "ffc400b5100002010303020403050504040000017d01020300041105122131410613"
    "516107227114328191a1082342b1c11552d1f02433627282090a161718191a252627"
    "28292a3435363738393a434445464748494a535455565758595a636465666768696a"
    "737475767778797a838485868788898a92939495969798999aa2a3a4a5a6a7a8a9aa"
    "b2b3b4b5b6b7b8b9bac2c3c4c5c6c7c8c9cad2d3d4d5d6d7d8d9dae1e2e3e4e5e6e7"
    "e8e9eaf1f2f3f4f5f6f7f8f9faffda0008010100003f00fbfa28a2803fffd9"
)


class AmbienteTemp(unittest.TestCase):
    def setUp(self):
        self._env = patch.dict(os.environ)
        self._env.start()
        for nome in list(os.environ):
            if nome.startswith("BAIXADOR_"):
                os.environ.pop(nome, None)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.raiz = Path(self.temp.name)
        self.config = Configuracoes(raiz=self.raiz)

    def tearDown(self):
        self._env.stop()


class TestFormatacao(unittest.TestCase):
    def test_data_legivel_em_formato_brasileiro(self):
        self.assertEqual(_data_legivel("2026-11-17T21:35:12+00:00")[:10], "17/11/2026")
        self.assertEqual(_data_legivel(""), "")
        self.assertEqual(_data_legivel(None), "")

    def test_data_invalida_nao_quebra_a_tabela(self):
        self.assertEqual(_data_legivel("qualquer coisa")[:13], "qualquer cois")

    def test_resumo_musical_completo(self):
        texto = _resumo_texto({
            "artista": "Queen", "titulo": "Bohemian Rhapsody",
            "album": "A Night at the Opera", "ano": 1975,
            "fonte": "itunes", "capa_incorporada": True})
        self.assertIn("Queen — Bohemian Rhapsody", texto)
        self.assertIn("A Night at the Opera (1975)", texto)
        self.assertIn("capa incorporada", texto)
        self.assertIn("itunes", texto)

    def test_resumo_sem_confirmacao_diz_isso_explicitamente(self):
        texto = _resumo_texto({"titulo": "faixa", "artista": "",
                               "fonte": "nome_do_arquivo", "capa_incorporada": False})
        self.assertIn("não confirmada", texto)
        self.assertIn("sem capa", texto)

    def test_detecta_sinais_de_conteudo_que_exige_login(self):
        self.assertTrue(_parece_falta_de_login(
            "ERROR: [youtube] abc: Sign in to confirm your age"))
        self.assertTrue(_parece_falta_de_login("This video is private"))
        self.assertFalse(_parece_falta_de_login("HTTP Error 404: File not found"))


class TestControlador(AmbienteTemp):
    def _controlador(self, **prefs) -> ControladorInterface:
        return ControladorInterface(configuracoes=self.config,
                                    preferencias=Preferencias(**prefs))

    def test_download_repassa_progresso_e_politica(self):
        controlador = self._controlador(metadados_ativos=False)
        recebido = {}

        def baixar_falso(url, formato, ao_progresso=None, politica=None):
            recebido.update(url=url, formato=formato,
                            tem_callback=callable(ao_progresso), politica=politica)
            if ao_progresso:
                from downloader import Progresso

                ao_progresso(Progresso(percentual=42.0))
            return True, "ok"

        controlador.aplicacao.downloader = SimpleNamespace(baixar=baixar_falso)  # type: ignore[assignment]
        eventos = []
        ok, _ = controlador.baixar("https://exemplo.test/x", "mp3",
                                   ao_progresso=eventos.append,
                                   politica="renomear")
        self.assertTrue(ok)
        self.assertTrue(recebido["tem_callback"])
        self.assertEqual(recebido["politica"], "renomear")
        self.assertEqual(eventos[0].percentual, 42.0)

    def test_resumo_musical_exposto_sem_inventar(self):
        controlador = self._controlador(metadados_ativos=False)
        self.assertEqual(controlador.resumo_musical(), {})
        controlador.aplicacao.metadados = SimpleNamespace(  # type: ignore[assignment]
            _processador=SimpleNamespace(ultimo_resumo={
                "titulo": "T", "artista": "A", "album": "B", "ano": 2000,
                "fonte": "deezer", "capa_incorporada": True}))
        resumo = controlador.resumo_musical()
        self.assertEqual(resumo["album"], "B")

    def test_politica_perguntar_nao_sobrescreve_no_nucleo(self):
        controlador = self._controlador(sobrescrita="perguntar")
        self.assertEqual(controlador.config.sobrescrita, "pular")

    def test_preferencia_de_sobrescrita_persiste_e_valida(self):
        from preferencias import salvar

        controlador = self._controlador()
        novas = Preferencias(sobrescrita="renomear")
        controlador.salvar_preferencias(novas)
        self.assertEqual(carregar(self.config).sobrescrita, "renomear")
        with self.assertRaises(ValueError):
            salvar(Preferencias(sobrescrita="apagar tudo"), self.config)

    def test_historico_mostra_data_do_registro(self):
        controlador = self._controlador(metadados_ativos=False)
        controlador.aplicacao.historico.registrar(
            url="https://e/x", formato="mp3", status="sucesso", caminho="a.mp3")
        registro = controlador.historico()[0]
        self.assertTrue(_data_legivel(registro.get("data_hora")))
        self.assertEqual(_data_legivel(registro.get("registrado_em")), "")


class TestMiniaturas(AmbienteTemp):
    def test_imagem_valida_e_guardada_em_cache(self):
        from contextlib import contextmanager

        dados = jpeg_valido()

        @contextmanager
        def resposta_falsa(*_args, **_kwargs):
            yield SimpleNamespace(read=lambda n=None: dados)

        with patch("thumbs.urllib.request.urlopen", resposta_falsa):
            caminho = thumbs.obter("https://i.ytimg.com/vi/x/hq.jpg", self.config.dados)
        self.assertIsNotNone(caminho)
        self.assertTrue(Path(caminho).is_file())
        # Segunda chamada não vai à rede (cache).
        with patch("thumbs.urllib.request.urlopen") as abrir2:
            novo = thumbs.obter("https://i.ytimg.com/vi/x/hq.jpg", self.config.dados)
            abrir2.assert_not_called()
        self.assertEqual(Path(caminho), Path(novo))

    def test_html_nao_e_aceito_como_imagem(self):
        from contextlib import contextmanager

        @contextmanager
        def resposta_falsa(*_args, **_kwargs):
            yield SimpleNamespace(read=lambda n=None: b"<html>nao e imagem</html>")

        with patch("thumbs.urllib.request.urlopen", resposta_falsa):
            self.assertIsNone(thumbs.obter("https://x/y.jpg", self.config.dados))

    def test_falha_de_rede_nao_derruba_nada(self):
        with patch("thumbs.urllib.request.urlopen", side_effect=OSError("sem rede")):
            self.assertIsNone(thumbs.obter("https://x/y.jpg", self.config.dados))

    def test_url_insegura_e_ignorada(self):
        self.assertIsNone(thumbs.obter("file:///etc/passwd", self.config.dados))


if __name__ == "__main__":
    unittest.main()
