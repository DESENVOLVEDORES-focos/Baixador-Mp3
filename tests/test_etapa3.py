"""Testes da Etapa 3: configurações, cookies, interface e integração.

Sem rede e sem tela: downloads/pesquisas usam mocks do yt-dlp, as APIs
musicais não são chamadas de verdade e os testes de janela Tk só rodam
se houver Tkinter + display (neste ambiente são pulados, não fingidos).
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import cookies_youtube
from configuracoes import Configuracoes
from downloader import Downloader, ResultadoDownload
from interface import ControladorInterface
from metadados import ler_metadados
from pesquisa import Pesquisador
from preferencias import (
    Preferencias, carregar, mascarar_segredo, proteger_segredo,
    revelar_segredo, salvar,
)

COOKIES_V1 = (
    "# Netscape HTTP Cookie File\n"
    "#HttpOnly_.youtube.com\tTRUE\t/\tTRUE\t1893456000\tVISITOR_INFO1_LIVE\tvalor1\n"
    ".youtube.com\tTRUE\t/\tTRUE\t1893456000\tPREF\tf1=500\n"
)
COOKIES_V2 = COOKIES_V1 + ".google.com\tTRUE\t/\tTRUE\t1893456000\tNID\tvalor2\n"


class AmbienteTemporario(unittest.TestCase):
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


class TestPreferencias(AmbienteTemporario):
    def test_salvar_e_carregar_preserva_tudo(self):
        prefs = Preferencias(
            ia_api_key="sk-teste-123456", ia_modelo="modelo-x",
            diretorio_mp3="D:/Musicas", formato_padrao="mp4",
            qualidade_mp3="192K", limite_pesquisa=7,
            metadados_ativos=False, buscar_capas=False)
        salvar(prefs, self.config)
        lidas = carregar(self.config)
        self.assertEqual(lidas.ia_api_key, "sk-teste-123456")
        self.assertEqual(lidas.diretorio_mp3, "D:/Musicas")
        self.assertEqual(lidas.formato_padrao, "mp4")
        self.assertEqual(lidas.qualidade_mp3, "192K")
        self.assertEqual(lidas.limite_pesquisa, 7)
        self.assertFalse(lidas.metadados_ativos)
        self.assertFalse(lidas.buscar_capas)

    def test_chave_nao_fica_em_texto_puro_no_arquivo(self):
        salvar(Preferencias(ia_api_key="sk-segredo-98765"), self.config)
        texto = (self.config.dados / "preferencias.json").read_text(encoding="utf-8")
        self.assertNotIn("sk-segredo-98765", texto)
        self.assertEqual(carregar(self.config).ia_api_key, "sk-segredo-98765")

    def test_cofre_e_mascara_da_interface(self):
        self.assertEqual(revelar_segredo(proteger_segredo("chave-abc")), "chave-abc")
        mascara = mascarar_segredo("sk-123456789")
        self.assertTrue(mascara.endswith("6789"))
        self.assertNotIn("12345", mascara)
        self.assertEqual(mascarar_segredo(""), "")

    def test_sem_arquivo_usa_padroes_sem_quebrar(self):
        prefs = carregar(self.config)
        self.assertEqual(prefs.ia_api_key, "")
        self.assertEqual(prefs.formato_padrao, "mp3")
        self.assertTrue(prefs.metadados_ativos)

    def test_validacao_rejeita_valores_invalidos(self):
        with self.assertRaises(ValueError):
            Preferencias(formato_padrao="avi").validar()
        with self.assertRaises(ValueError):
            Preferencias(qualidade_mp3="altissima").validar()


class TestCookies(AmbienteTemporario):
    def _arquivo(self, nome: str, conteudo: str) -> Path:
        caminho = self.raiz / nome
        caminho.write_text(conteudo, encoding="utf-8")
        return caminho

    def test_importar_valida_e_armazena_copia_gerenciada(self):
        info = cookies_youtube.importar(self._arquivo("origem.txt", COOKIES_V1), self.config)
        self.assertTrue(info.valido)
        self.assertEqual((info.total, info.do_youtube), (2, 2))
        self.assertTrue(os.path.samefile(info.caminho, self.config.dados / "cookies.txt"))
        self.assertTrue(info.caminho.is_file())
        status = cookies_youtube.status(self.config)
        self.assertTrue(status.configurado and status.valido)

    def test_formato_incompativel_e_rejeitado_sem_copiar(self):
        with self.assertRaises(cookies_youtube.ErroCookies):
            cookies_youtube.importar(
                self._arquivo("ruim.txt", "isto nao e um cookies.txt"), self.config)
        self.assertFalse((self.config.dados / "cookies.txt").exists())

    def test_substituir_e_remover(self):
        cookies_youtube.importar(self._arquivo("v1.txt", COOKIES_V1), self.config)
        cookies_youtube.importar(self._arquivo("v2.txt", COOKIES_V2), self.config)
        self.assertEqual(cookies_youtube.status(self.config).total, 3)
        self.assertTrue(cookies_youtube.remover(self.config))
        self.assertFalse(cookies_youtube.status(self.config).configurado)
        self.assertFalse(cookies_youtube.remover(self.config))


class FakeConfigDownload:
    """Config mínima compatível com Downloader/Pesquisador (sem rede)."""

    def __init__(self, raiz: Path, cookies: Path | None = None):
        self.raiz = raiz
        self.musicas = raiz / "Musicas"
        self.videos = raiz / "Videos"
        self.caminho_cookies = cookies
        self.qualidade_mp3 = "0"

    def comando_yt_dlp(self):
        return ["yt-dlp"]

    def caminho_ffmpeg(self):
        return "ffmpeg"


class TestCookiesNoYtDlp(AmbienteTemporario):
    def test_download_e_pesquisa_recebem_cookiefile(self):
        cookies = self.raiz / "cookies.txt"
        cookies.write_text(COOKIES_V1, encoding="utf-8")
        config = FakeConfigDownload(self.raiz, cookies)
        args = Downloader(config).construir_argumentos("https://exemplo.test/v", "mp3")  # type: ignore[arg-type]
        self.assertIn("--cookies", args)
        self.assertEqual(args[args.index("--cookies") + 1], str(cookies))
        comando = Pesquisador(config).construir_comando("teste", 5)  # type: ignore[arg-type]
        self.assertIn("--cookies", comando)
        self.assertEqual(comando[comando.index("--cookies") + 1], str(cookies))

    def test_sem_cookies_nenhum_argumento_e_enviado(self):
        config = FakeConfigDownload(self.raiz, None)
        args = Downloader(config).construir_argumentos("https://exemplo.test/v", "mp4")  # type: ignore[arg-type]
        self.assertNotIn("--cookies", args)

    def test_config_real_resolve_cookies_da_pasta_de_dados(self):
        (self.config.dados).mkdir(parents=True, exist_ok=True)
        (self.config.dados / "cookies.txt").write_text(COOKIES_V1, encoding="utf-8")
        resolvido = self.config.resolver_cookies()
        self.assertTrue(os.path.samefile(resolvido, self.config.dados / "cookies.txt"))


class TestControladorInterface(AmbienteTemporario):
    def _controlador(self, **prefs_kwargs) -> ControladorInterface:
        return ControladorInterface(
            configuracoes=self.config,
            preferencias=Preferencias(**prefs_kwargs))

    def test_inicializa_sem_nenhuma_api_configurada(self):
        controlador = self._controlador()
        estado, _ = controlador.testar_ia()
        self.assertEqual(estado, "nao_configurada")  # opcional, sem rede
        self.assertEqual(controlador.testar_provedor_musical("inexistente")[0], "invalida")
        self.assertFalse(controlador.status_cookies().configurado)

    def test_salvar_pela_interface_reconstroi_nucleo(self):
        controlador = self._controlador()
        nova = Preferencias(formato_padrao="mp4", diretorio_mp3=str(self.raiz / "Sairam"))
        controlador.salvar_preferencias(nova)
        self.assertEqual(carregar(self.config).formato_padrao, "mp4")
        self.assertEqual(controlador.config.musicas, self.raiz / "Sairam")

    def test_importar_cookies_pela_interface_atualiza_preferencias(self):
        controlador = self._controlador()
        origem = self.raiz / "meus-cookies.txt"
        origem.write_text(COOKIES_V1, encoding="utf-8")
        info = controlador.importar_cookies(origem)
        self.assertTrue(info.valido)
        self.assertEqual(carregar(self.config).cookies_caminho, str(info.caminho))
        resolvido = controlador.aplicacao.config.resolver_cookies()
        self.assertTrue(os.path.samefile(resolvido, self.config.dados / "cookies.txt"))
        self.assertTrue(controlador.remover_cookies())
        self.assertEqual(carregar(self.config).cookies_caminho, "")

    def test_pesquisa_e_downloads_mp3_mp4_pelo_controlador(self):
        controlador = self._controlador(metadados_ativos=False)
        resultado = SimpleNamespace(
            titulo="Música", canal="Canal", duracao_formatada="1:00",
            url="https://exemplo.test/v")
        controlador.aplicacao.pesquisador = SimpleNamespace(  # type: ignore[assignment]
            pesquisar=lambda consulta, limite: [resultado])
        self.assertEqual(controlador.pesquisar("música")[0].titulo, "Música")

        def baixar_falso(url, formato):
            pasta = (controlador.config.musicas if formato == "mp3"
                     else controlador.config.videos)
            pasta.mkdir(parents=True, exist_ok=True)
            arquivo = pasta / f"arquivo.{formato}"
            arquivo.write_bytes(b"conteudo")
            return ResultadoDownload(url, formato, arquivo, "inicio", "fim")  # type: ignore[arg-type]

        controlador.aplicacao.downloader = SimpleNamespace(baixar=baixar_falso)  # type: ignore[assignment]
        self.assertTrue(controlador.baixar("https://exemplo.test/m", "mp3")[0])
        self.assertTrue(controlador.baixar("https://exemplo.test/v", "mp4")[0])
        statuses = [r["status"] for r in controlador.historico()]
        self.assertEqual(statuses.count("sucesso"), 2)

    def test_download_mp3_passa_por_metadados_e_capa_da_ia2(self):
        from integracao import AdaptadorMetadados
        from metadados import ProcessadorMusical
        from tests.test_ia2 import png_bytes

        class IdFalso:
            def identificar(self, titulo, canal=None):  # noqa: ANN001
                from inteligencia import InfoMusica
                return InfoMusica(titulo="Bohemian Rhapsody", artista="Queen",
                                  album="A Night at the Opera", ano=1975,
                                  genero="Rock", fonte="teste")

        class CapaFalsa:
            def buscar_e_baixar(self, info, url_origem=None):  # noqa: ANN001
                return png_bytes()

        controlador = self._controlador(metadados_ativos=False)
        controlador.aplicacao.metadados = AdaptadorMetadados(  # type: ignore[assignment]
            ProcessadorMusical(identificador=IdFalso(),
                               gerenciador_capas=CapaFalsa()))  # type: ignore[arg-type]

        def baixar_falso(url, formato):
            controlador.config.musicas.mkdir(parents=True, exist_ok=True)
            arquivo = controlador.config.musicas / "Queen - Bohemian Rhapsody [x].mp3"
            arquivo.write_bytes(b"\xff\xfb\x90\x00" + b"\x00" * 512)
            return ResultadoDownload(url, formato, arquivo, "inicio", "fim")  # type: ignore[arg-type]

        controlador.aplicacao.downloader = SimpleNamespace(baixar=baixar_falso)  # type: ignore[assignment]
        sucesso, _ = controlador.baixar("https://exemplo.test/m", "mp3")
        self.assertTrue(sucesso)
        mp3 = controlador.config.musicas / "Queen - Bohemian Rhapsody [x].mp3"
        tags = ler_metadados(mp3)
        self.assertEqual(tags["album"], "A Night at the Opera")
        self.assertTrue(tags["tem_capa"])


class TestJanelaTk(unittest.TestCase):
    def test_mascara_do_campo_de_chave(self):
        # Sem Tkinter/display neste ambiente, o teste de janela é pulado
        # (registrado no DEVELOPMENT_LOG); a máscara exibida é testada
        # em TestPreferencias.test_cofre_e_mascara_da_interface.
        try:
            import tkinter as tk
        except ImportError:
            self.skipTest("Tkinter indisponível neste ambiente")
        try:
            raiz = tk.Tk()
        except Exception:
            self.skipTest("Sem display gráfico neste ambiente")
        try:
            campo = tk.Entry(raiz, show="•")
            campo.insert(0, "sk-123456789")
            self.assertEqual(campo.cget("show"), "•")
            campo.configure(show="")
            self.assertEqual(campo.cget("show"), "")
        finally:
            raiz.destroy()


if __name__ == "__main__":
    unittest.main()
