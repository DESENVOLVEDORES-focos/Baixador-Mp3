from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from baixador.nucleo.configuracoes import Configuracoes
from baixador.web.downloader import Downloader, ErroDownload, _encontrar_saida, validar_url
from baixador.nucleo.fila import FilaDownloads
from baixador.nucleo.historico import Historico
from baixador.nucleo.integracao import AdaptadorMetadados
from baixador.web.pesquisa import Pesquisador, _converter_item, _carregar_json


class ProcessoFalso:
    """Substitui ``subprocess.Popen`` nos testes: argv, saída e código."""

    def __init__(self, saida: str = "", codigo: int = 0):
        self.argv: list[str] = []
        self.stdout = iter(saida.splitlines(keepends=True))
        self.returncode = codigo
        self._codigo = codigo

    def __call__(self, argv, **kwargs):  # simula subprocess.Popen(argv, ...)
        self.argv = list(argv)
        return self

    def wait(self) -> int:
        return self._codigo

    def kill(self) -> None:
        pass


class FakeConfig:
    def __init__(self, root: Path):
        self.raiz = root
        self.musicas = root / "Musicas"
        self.videos = root / "Videos"
        self.dados = root / ".baixador"
        self.fila = self.dados / "fila.json"
        self.historico = self.dados / "historico.jsonl"
        self.erros = self.dados / "erros.jsonl"

    def comando_yt_dlp(self):
        return ["yt-dlp"]

    def caminho_ffmpeg(self):
        return "ffmpeg"

    def preparar_diretorios(self):
        for path in (self.musicas, self.videos, self.dados):
            path.mkdir(parents=True, exist_ok=True)


class TestDownloader(unittest.TestCase):
    def test_diagnostico_lista_todas_as_dependencias_ausentes(self):
        with tempfile.TemporaryDirectory() as temp:
            config = Configuracoes(Path(temp))
            with patch("baixador.nucleo.configuracoes.shutil.which", return_value=None), patch(
                "baixador.nucleo.configuracoes.importlib.util.find_spec", return_value=None
            ):
                with self.assertRaises(FileNotFoundError) as contexto:
                    config.verificar_dependencias()
            self.assertIn("yt-dlp", str(contexto.exception))
            self.assertIn("FFmpeg", str(contexto.exception))

    def test_valida_url_http_e_rejeita_esquema_inseguro(self):
        self.assertEqual(validar_url(" https://example.com/video "), "https://example.com/video")
        with self.assertRaises(ValueError):
            validar_url("file:///etc/passwd")
        with self.assertRaises(ValueError):
            validar_url("javascript:alert(1)")

    def test_comandos_mp3_mp4_usam_qualidade_e_nao_sobrescrevem(self):
        with tempfile.TemporaryDirectory() as temp:
            config = FakeConfig(Path(temp))
            downloader = Downloader(config)  # type: ignore[arg-type]
            mp3 = downloader.construir_argumentos("https://example.org/a", "mp3")
            mp4 = downloader.construir_argumentos("https://example.org/b", "mp4")
            self.assertIn("--audio-quality", mp3)
            self.assertEqual(mp3[mp3.index("--audio-quality") + 1], "0")
            self.assertIn("--no-overwrites", mp3)
            self.assertIn("bestaudio/best", mp3)
            self.assertIn("bestvideo+bestaudio/best[ext=mp4]/best", mp4)
            self.assertIn("--merge-output-format", mp4)
            self.assertIn("--remux-video", mp4)
            self.assertIn("[%(id)s]", mp4[mp4.index("--output") + 1])

    def test_nao_considera_download_sem_arquivo_final_concluido(self):
        with tempfile.TemporaryDirectory() as temp:
            config = FakeConfig(Path(temp))
            config.preparar_diretorios()
            downloader = Downloader(config)  # type: ignore[arg-type]
            with patch("baixador.web.downloader.subprocess.Popen", ProcessoFalso("", 0)):
                with self.assertRaises(ErroDownload):
                    downloader.baixar("https://example.org/a", "mp3")

    def test_download_so_e_confirmado_com_arquivo_mp3_real(self):
        with tempfile.TemporaryDirectory() as temp:
            config = FakeConfig(Path(temp))
            config.preparar_diretorios()
            downloader = Downloader(config)  # type: ignore[arg-type]

            class PopenQueCria(ProcessoFalso):
                def __call__(self, argv, **kwargs):  # cria o MP3 na pasta --paths
                    if "--paths" not in argv:  # ping de título
                        self.stdout = iter(["faixa [abc]\n"])
                        return self
                    pasta = Path(argv[argv.index("--paths") + 1])
                    pasta.mkdir(parents=True, exist_ok=True)
                    alvo = pasta / "faixa [abc].mp3"
                    alvo.write_bytes(b"audio")
                    self.stdout = iter([str(alvo) + "\n"])
                    return self

            with patch("baixador.web.downloader.subprocess.Popen", PopenQueCria("", 0)):
                resultado = downloader.baixar("https://example.org/a", "mp3")
            self.assertTrue(os.path.samefile(
                resultado.caminho, config.musicas / "faixa [abc].mp3"))

    def test_localizador_ignora_arquivo_vazio_e_extensao_errada(self):
        with tempfile.TemporaryDirectory() as temp:
            pasta = Path(temp)
            vazio = pasta / "vazio.mp4"
            vazio.touch()
            outro = pasta / "audio.webm"
            outro.write_bytes(b"x")
            self.assertIsNone(_encontrar_saida(f"{vazio}\n{outro}", pasta, "mp4"))


class TestPesquisa(unittest.TestCase):
    def test_converte_item_flat_e_formata_duracao(self):
        item = _converter_item({"id": "id1", "title": "Título", "uploader": "Canal", "duration": 61.9})
        self.assertIsNotNone(item)
        self.assertEqual(item.url, "https://www.youtube.com/watch?v=id1")
        self.assertEqual(item.canal, "Canal")
        self.assertEqual(item.duracao_formatada, "1:01")

    def test_parseia_json_e_nao_fabrica_item_sem_titulo(self):
        payload = _carregar_json('{"entries": [{"id": "x"}]}')
        self.assertEqual(payload["entries"][0]["id"], "x")
        self.assertIsNone(_converter_item({"id": "x"}))

    def test_marca_verificacao_apenas_com_evidencia_explicita(self):
        verificado = _converter_item({"id": "a", "title": "A", "channel_is_verified": True})
        sem_evidencia = _converter_item({"id": "b", "title": "B", "channel": "Canal oficial"})
        self.assertTrue(verificado.canal_verificado)
        self.assertFalse(sem_evidencia.canal_verificado)

    def test_validacao_da_consulta_e_limite(self):
        with tempfile.TemporaryDirectory() as temp:
            pesquisador = Pesquisador(FakeConfig(Path(temp)))  # type: ignore[arg-type]
            with self.assertRaises(ValueError):
                pesquisador.pesquisar("  ")
            with self.assertRaises(ValueError):
                pesquisador.pesquisar("música", 100)


class TestFilaEHistorico(unittest.TestCase):
    def test_fila_persiste_deduplica_e_tenta_novamente(self):
        with tempfile.TemporaryDirectory() as temp:
            config = FakeConfig(Path(temp))
            fila = FilaDownloads(config)  # type: ignore[arg-type]
            item = fila.adicionar("https://example.org/a", "mp3")
            duplicado = fila.adicionar("https://example.org/a", "mp3")
            self.assertEqual(item.id, duplicado.id)
            reivindicado = fila.reivindicar()
            self.assertEqual(reivindicado.tentativas, 1)
            fila.falhar(item.id, "erro de teste", max_tentativas=2)
            self.assertEqual(fila.listar()[0].status, "pendente")
            revendicado = fila.reivindicar()
            self.assertEqual(revendicado.tentativas, 2)
            fila.falhar(item.id, "erro final", max_tentativas=2)
            self.assertEqual(fila.listar(todos=True)[0].status, "falhou")
            self.assertEqual(fila.reabrir_falhas(), 1)
            self.assertEqual(fila.listar()[0].tentativas, 0)
            # JSON continua legível após gravação atômica.
            self.assertIsInstance(json.loads(config.fila.read_text(encoding="utf-8")), list)

    def test_recupera_item_processando_antigo(self):
        with tempfile.TemporaryDirectory() as temp:
            config = FakeConfig(Path(temp))
            fila = FilaDownloads(config)  # type: ignore[arg-type]
            item = fila.adicionar("https://example.org/a", "mp3")
            fila.reivindicar()
            dados = json.loads(config.fila.read_text(encoding="utf-8"))
            dados[0]["atualizado_em"] = "2020-01-01T00:00:00+00:00"
            config.fila.write_text(json.dumps(dados), encoding="utf-8")
            self.assertEqual(fila.reabrir_interrompidos(), 1)
            recuperado = fila.listar()[0]
            self.assertEqual(recuperado.id, item.id)
            self.assertEqual(recuperado.status, "pendente")

    def test_historico_e_erros_separados_com_leitura_recente(self):
        with tempfile.TemporaryDirectory() as temp:
            config = FakeConfig(Path(temp))
            historico = Historico(config)  # type: ignore[arg-type]
            historico.registrar(url="https://example.org/a", formato="mp3", status="sucesso")
            historico.registrar(url="https://example.org/b", formato="mp4", status="erro", mensagem="falhou")
            self.assertEqual(len(historico.listar()), 1)
            todos = historico.listar(incluir_erros=True)
            self.assertEqual(len(todos), 2)


class TestIntegracao(unittest.TestCase):
    def test_adaptador_opcional_sem_modulo_preserva_caminho(self):
        adaptador = AdaptadorMetadados()
        self.assertFalse(adaptador.disponivel)
        self.assertEqual(adaptador.processar_mp3(Path("faixa.mp3"), {}), Path("faixa.mp3"))

    def test_processador_recebe_mp3_e_metadados(self):
        with tempfile.TemporaryDirectory() as temp:
            arquivo = Path(temp) / "faixa.mp3"
            arquivo.write_bytes(b"mp3")

            class Processador:
                def __init__(self):
                    self.chamada = None

                def processar_mp3(self, caminho, metadados):
                    self.chamada = (caminho, metadados)
                    return None

            processador = Processador()
            adaptador = AdaptadorMetadados(processador)  # type: ignore[arg-type]
            saida = adaptador.processar_mp3(arquivo, {"url": "https://example.org"})
            self.assertEqual(saida, arquivo)
            self.assertEqual(processador.chamada[1]["url"], "https://example.org")


if __name__ == "__main__":
    unittest.main()


class TestRaizDoProjeto(unittest.TestCase):
    """A raiz não pode ser a pasta do módulo, e sim a do projeto.

    Regressão real: ao mover os módulos para ``baixador/nucleo/``, ``raiz``
    passou a apontar para dentro do pacote — o programa deixava de achar
    ``ferramentas/ffmpeg.exe`` (que já existia) e criava ``Musicas/`` no lugar
    errado. Este teste trava isso.
    """

    def test_raiz_e_a_pasta_do_projeto_e_nao_do_pacote(self):
        from baixador.nucleo.configuracoes import Configuracoes

        raiz = Configuracoes().raiz
        self.assertTrue((raiz / "main.py").is_file(),
                        f"raiz inesperada: {raiz}")
        self.assertTrue((raiz / "baixador").is_dir())
        self.assertNotEqual(raiz.name, "nucleo")

    def test_pastas_derivam_da_raiz(self):
        from baixador.nucleo.configuracoes import Configuracoes

        config = Configuracoes()
        self.assertEqual(config.musicas, config.raiz / "Musicas")
        self.assertEqual(config.videos, config.raiz / "Videos")
        self.assertEqual(config.ferramentas, config.raiz / "ferramentas")
        self.assertEqual(config.dados, config.raiz / ".baixador")

    def test_acha_o_ffmpeg_que_esta_na_pasta_ferramentas(self):
        """Com ``ferramentas/ffmpeg`` presente, não pode dizer que não achou."""
        import tempfile

        from baixador.nucleo.configuracoes import Configuracoes

        with tempfile.TemporaryDirectory() as pasta:
            raiz = Path(pasta)
            (raiz / "ferramentas").mkdir()
            (raiz / "ferramentas" / "ffmpeg").write_bytes(b"x")
            config = Configuracoes(raiz=raiz)
            self.assertEqual(config.caminho_ffmpeg(),
                             str(raiz / "ferramentas" / "ffmpeg"))
