"""Testes do caminho de erro e do progresso (correções da auditoria A1–A6).

Cada teste aqui corresponde a um defeito reproduzido de verdade em
``AUDITORIA.md`` e falharia antes da correção. Sem rede: o processo do
yt-dlp é substituído por um dublê que devolve exatamente a saída real
observada (fixtures copiadas da execução com yt-dlp 2026.10.26).
"""

from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from downloader import (
    ETAPA_BAIXANDO, ETAPA_CONVERTENDO, ETAPA_MESCLANDO, ETAPA_METADADOS,
    ErroDownload, Downloader, _resumir_erro, interpretar_linha,
)
from pesquisa import _converter_item

# Saídas reais do yt-dlp (--newline) usadas como fixture.
SAIDA_FALHA_404 = (
    "[generic] Extracting URL: http://127.0.0.1:8932/naoexiste.m4a\n"
    "[generic] naoexiste: Downloading webpage\n"
    "ERROR: [generic] Unable to download webpage: HTTP Error 404: File not found\n"
)
SAIDA_PROGRESSO = (
    "[youtube] dQw4w9WgXcQ: Downloading webpage\n"
    "[download] Destination: Musicas/Queen - Bohemian Rhapsody [dQw4w9WgXcQ].m4a\n"
    "[download]  10.2% of    3.45MiB at  512.00KiB/s ETA 00:05\n"
    "[download]  55.7% of    3.45MiB at  1.20MiB/s ETA 00:02\n"
    "[download] 100% of    3.45MiB in 00:03\n"
    "[ExtractAudio] Destination: Musicas/Queen - Bohemian Rhapsody [dQw4w9WgXcQ].mp3\n"
    "[Metadata] Adding metadata to \"Music.mp3\"\n"
)


class ProcessoFalso:
    """Dublê de ``subprocess.Popen``: argv registrado, saída em linhas."""

    def __init__(self, saida: str = "", codigo: int = 0):
        self.argv: list[str] = []
        self.stdout = iter(saida.splitlines(keepends=True))
        self.returncode = codigo
        self._codigo = codigo

    def __call__(self, argv, **kwargs):
        self.argv = list(argv)
        alvo = pasta_de_trabalho(self.argv)
        if alvo is not None:
            alvo.mkdir(parents=True, exist_ok=True)
        return self

    def wait(self) -> int:
        return self._codigo

    def kill(self) -> None:
        pass


class ConfigFalsa:
    sobrescrita = "pular"

    def __init__(self, raiz: Path):
        self.raiz = raiz
        self.musicas = raiz / "Musicas"
        self.videos = raiz / "Videos"
        self.dados = raiz / ".baixador"
        self.fila = self.dados / "fila.json"
        self.historico = self.dados / "historico.jsonl"
        self.erros = self.dados / "erros.jsonl"

    def comando_yt_dlp(self):
        return ["yt-dlp"]

    def caminho_ffmpeg(self):
        return "ffmpeg"

    def preparar_diretorios(self):
        for pasta in (self.musicas, self.videos, self.dados):
            pasta.mkdir(parents=True, exist_ok=True)

    def resolver_cookies(self):
        return None


def pasta_de_trabalho(argv: list[str]) -> Path | None:
    """Pasta ``--paths`` do argv (onde o yt-dlp grava); ``None`` no ping de título."""
    if "--skip-download" in argv or "--paths" not in argv:
        return None
    return Path(argv[argv.index("--paths") + 1])


class Base(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config = ConfigFalsa(Path(self.temp.name))
        self.config.preparar_diretorios()


class PopenDuplo:
    """Consulta de título (ok) + download (falha), como no fluxo real."""

    def __init__(self, saida_download: str, codigo: int = 1):
        self.saida_download = saida_download
        self.codigo = codigo
        self.chamadas: list[list[str]] = []

    def __call__(self, argv, **kwargs):
        self.chamadas.append(list(argv))
        if "--skip-download" in argv:
            return ProcessoFalso("faixa [abc]\n", 0)
        return ProcessoFalso(self.saida_download, self.codigo)


class TestResumoDeErro(Base):
    """A1: o bug que transformava qualquer falha em NameError."""

    def test_resume_linha_de_erro_real_sem_estourar(self):
        self.assertIn("HTTP Error 404", _resumir_erro(SAIDA_FALHA_404))

    def test_saida_vazia_tem_mensagem_generica(self):
        self.assertIn("sem detalhes", _resumir_erro(""))

    def test_falha_de_download_vira_erro_tratado_e_nao_traceback(self):
        downloader = Downloader(self.config)  # type: ignore[arg-type]
        with patch("downloader.subprocess.Popen",
                   PopenDuplo(SAIDA_FALHA_404, 1)):
            with self.assertRaises(ErroDownload) as contexto:
                downloader.baixar("https://example.org/naoexiste", "mp3")
        erro = contexto.exception
        self.assertEqual(erro.codigo, 1)
        self.assertIn("HTTP Error 404", str(erro))
        # A saída completa é preservada para diagnóstico/registro.
        self.assertIn("Downloading webpage", erro.saida)

    def test_erro_vai_para_o_historico_como_erro_e_nao_derruba_o_app(self):
        from historico import Historico
        from musica import Aplicacao

        app = Aplicacao(self.config)  # type: ignore[arg-type]
        app.downloader = Downloader(self.config)  # type: ignore[arg-type]
        with patch("downloader.subprocess.Popen",
                   PopenDuplo(SAIDA_FALHA_404, 1)):
            sucesso, mensagem = app.baixar("https://example.org/x", "mp3")
        self.assertFalse(sucesso)
        self.assertIn("HTTP Error 404", mensagem)
        registros = Historico(self.config).listar(10, incluir_erros=True)  # type: ignore[arg-type]
        self.assertEqual(registros[0]["status"], "erro")
        self.assertEqual(registros[0]["formato"], "mp3")


class TestProgresso(Base):
    """A6: progresso por etapa, sem inventar números."""

    def test_interpreta_percentual_velocidade_e_eta(self):
        p = interpretar_linha("[download]  55.7% of    3.45MiB at  1.20MiB/s ETA 00:02")
        self.assertIsNotNone(p)
        self.assertEqual(p.etapa, ETAPA_BAIXANDO)
        self.assertAlmostEqual(p.percentual, 55.7)
        self.assertEqual(p.total, "3.45MiB")
        self.assertEqual(p.velocidade, "1.20MiB/s")
        self.assertEqual(p.eta, "00:02")

    def test_interpreta_percentual_sem_velocidade_conhecida(self):
        p = interpretar_linha("[download] 100% of    3.45MiB in 00:03")
        self.assertIsNotNone(p)
        self.assertEqual(p.percentual, 100.0)
        self.assertEqual(p.velocidade, "")

    def test_identifica_etapas_de_pos_processamento(self):
        self.assertEqual(
            interpretar_linha("[ExtractAudio] Destination: x.mp3").etapa,  # type: ignore[union-attr]
            ETAPA_CONVERTENDO)
        self.assertEqual(
            interpretar_linha("[Merger] Merging formats into \"x.mp4\"").etapa,  # type: ignore[union-attr]
            ETAPA_MESCLANDO)
        self.assertEqual(
            interpretar_linha("[Metadata] Adding metadata to \"x.mp3\"").etapa,  # type: ignore[union-attr]
            ETAPA_METADADOS)

    def test_linha_irrelevante_nao_gera_progresso_inventado(self):
        self.assertIsNone(interpretar_linha("[youtube] dQw4w9WgXcQ: Downloading webpage"))
        self.assertIsNone(interpretar_linha(""))

    def test_baixar_emite_progresso_crescente_e_etapas(self):
        eventos = []
        criado: list[Path] = []

        def fake_popen(argv, **kwargs):
            trabalho = pasta_de_trabalho(argv)
            if trabalho is None:  # ping de título
                return ProcessoFalso("faixa [abc]\n", 0)
            arquivo = trabalho / "Queen - Bohemian Rhapsody [dQw4w9WgXcQ].mp3"
            arquivo.write_bytes(b"\xff\xfb\x90\x00" + b"\x00" * 256)
            criado.append(arquivo)
            return ProcessoFalso(SAIDA_PROGRESSO + f"{arquivo}\n", 0)

        downloader = Downloader(self.config)  # type: ignore[arg-type]
        with patch("downloader.subprocess.Popen", fake_popen):
            resultado = downloader.baixar(
                "https://example.org/v", "mp3", ao_progresso=eventos.append)
        self.assertFalse(resultado.pulado)
        percentuais = [e.percentual for e in eventos if e.percentual is not None]
        self.assertEqual(percentuais, [10.2, 55.7, 100.0])
        # Publicado na pasta final com o nome limpo, sem intermediários.
        self.assertEqual(resultado.caminho.parent, self.config.musicas.resolve())
        self.assertEqual(list(self.config.musicas.iterdir()), [resultado.caminho])
        etapas = {e.etapa for e in eventos}
        self.assertIn(ETAPA_CONVERTENDO, etapas)
        self.assertIn(ETAPA_METADADOS, etapas)

    def test_callback_quebrado_nao_derruba_download(self):
        def fake_popen(argv, **kwargs):
            trabalho = pasta_de_trabalho(argv)
            if trabalho is None:
                return ProcessoFalso("faixa [x]\n", 0)
            arquivo = trabalho / "faixa [x].mp3"
            arquivo.write_bytes(b"\xff\xfb\x90\x00" + b"\x00" * 64)
            return ProcessoFalso(SAIDA_PROGRESSO + f"{arquivo}\n", 0)

        def callback_ruim(_progresso):
            raise RuntimeError("interface quebrou")

        downloader = Downloader(self.config)  # type: ignore[arg-type]
        with patch("downloader.subprocess.Popen", fake_popen):
            resultado = downloader.baixar(
                "https://example.org/v", "mp3", ao_progresso=callback_ruim)
        self.assertEqual(resultado.caminho.name, "faixa [x].mp3")


class TestPoliticaDeSobrescrita(Base):
    """A3: o arquivo existente não pode ser regravado sem autorização."""

    def _baixar_duas_vezes(self, politica: str):
        self.config.sobrescrita = politica
        downloader = Downloader(self.config)  # type: ignore[arg-type]
        existente = self.config.musicas / "faixa [abc].mp3"
        existente.write_bytes(b"original")

        # Consulta de título devolve o mesmo nome do arquivo existente.
        consulta = ProcessoFalso("faixa [abc]\n", 0)
        criados: list[Path] = []

        def fake_popen(argv, **kwargs):
            if "--skip-download" in argv:
                return consulta
            alvo = self.config.musicas / (
                "faixa [abc] (rebaixado).mp3" if politica == "renomear"
                else "faixa [abc].mp3")
            alvo.write_bytes(b"novo")
            criados.append(alvo)
            return ProcessoFalso(f"{alvo}\n", 0)

        with patch("downloader.subprocess.Popen", fake_popen):
            resultado = downloader.baixar("https://example.org/a", "mp3")
        return resultado, existente, criados

    def test_pular_nao_baixa_nem_toca_no_arquivo(self):
        resultado, existente, criados = self._baixar_duas_vezes("pular")
        self.assertTrue(resultado.pulado)
        self.assertIsNone(resultado.caminho)
        self.assertEqual(existente.read_bytes(), b"original")
        self.assertEqual(criados, [])

    def test_renomear_gera_arquivo_novo_sem_tocar_no_existente(self):
        resultado, existente, criados = self._baixar_duas_vezes("renomear")
        self.assertFalse(resultado.pulado)
        self.assertEqual(existente.read_bytes(), b"original")
        self.assertEqual(len(criados), 1)
        self.assertNotEqual(criados[0], existente)

    def test_sobrescrever_usa_force_overwrites_so_quando_autorizado(self):
        downloader = Downloader(self.config)  # type: ignore[arg-type]
        self.config.sobrescrita = "pular"
        self.assertNotIn("--force-overwrites",
                         downloader.construir_argumentos("https://e.org/a", "mp3"))
        self.config.sobrescrita = "sobrescrever"
        self.assertIn("--force-overwrites",
                      downloader.construir_argumentos("https://e.org/a", "mp3"))

    def test_pular_aparece_no_historico_como_pulado(self):
        from historico import Historico
        from musica import Aplicacao

        self.config.sobrescrita = "pular"
        (self.config.musicas / "faixa [abc].mp3").write_bytes(b"original")
        app = Aplicacao(self.config)  # type: ignore[arg-type]
        app.downloader = Downloader(self.config)  # type: ignore[arg-type]
        consulta = ProcessoFalso("faixa [abc]\n", 0)
        with patch("downloader.subprocess.Popen", consulta):
            sucesso, mensagem = app.baixar("https://example.org/a", "mp3")
        self.assertTrue(sucesso)
        self.assertIn("já existe", mensagem)
        registro = Historico(self.config).listar(5, incluir_erros=True)[0]  # type: ignore[arg-type]
        self.assertEqual(registro["status"], "pulado")


class TestArquivoDestaExecucao(Base):
    """A5: sucesso só com arquivo gerado/atualizado nesta execução."""

    def test_arquivo_antigo_apontado_pelo_stdout_nao_vira_sucesso(self):
        antigo = self.config.musicas / "velho [old].mp3"
        antigo.write_bytes(b"conteudo antigo")
        antes = time.time() - 3600
        os.utime(antigo, (antes, antes))

        downloader = Downloader(self.config)  # type: ignore[arg-type]
        with patch("downloader.subprocess.Popen", ProcessoFalso(f"{antigo}\n", 0)):
            with self.assertRaises(ErroDownload):
                downloader.baixar("https://example.org/a", "mp3")

    def test_intermediarios_nao_chegam_a_pasta_final(self):
        def fake_popen(argv, **kwargs):
            trabalho = pasta_de_trabalho(argv)
            if trabalho is None:
                return ProcessoFalso("faixa [abc]\n", 0)
            (trabalho / "faixa [abc].m4a").write_bytes(b"audio original")
            (trabalho / "faixa [abc].mp3.part").write_bytes(b"parcial")
            final = trabalho / "faixa [abc].mp3"
            final.write_bytes(b"\xff\xfb\x90\x00" + b"\x00" * 128)
            return ProcessoFalso(f"{final}\n", 0)

        downloader = Downloader(self.config)  # type: ignore[arg-type]
        with patch("downloader.subprocess.Popen", fake_popen):
            resultado = downloader.baixar("https://example.org/a", "mp3")
        self.assertEqual(resultado.caminho.name, "faixa [abc].mp3")
        # Só o MP3 final na pasta de músicas: nenhum .m4a/.part/resíduo.
        self.assertEqual([a.name for a in self.config.musicas.iterdir()],
                         ["faixa [abc].mp3"])

    def test_residuo_preexistente_de_outra_faixa_nao_e_apagado(self):
        outro = self.config.musicas / "outra musica.m4a"
        outro.write_bytes(b"de outro download")

        def fake_popen(argv, **kwargs):
            trabalho = pasta_de_trabalho(argv)
            if trabalho is None:
                return ProcessoFalso("outra musica\n", 0)
            final = trabalho / "faixa [abc].mp3"
            final.write_bytes(b"\xff\xfb\x90\x00" + b"\x00" * 64)
            return ProcessoFalso(f"{final}\n", 0)

        downloader = Downloader(self.config)  # type: ignore[arg-type]
        with patch("downloader.subprocess.Popen", fake_popen):
            downloader.baixar("https://example.org/a", "mp3")
        self.assertTrue(outro.is_file())


class TestThumbnailNaPesquisa(unittest.TestCase):
    """B2: a interface precisa de thumbnail; o dado vem do yt-dlp."""

    def test_escolhe_a_maior_thumbnail_disponivel(self):
        item = _converter_item({
            "id": "dQw4w9WgXcQ", "title": "Faixa",
            "thumbnails": [
                {"url": "https://i.ytimg.com/vi/dQw4w9WgXcQ/default.jpg", "width": 120},
                {"url": "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg", "width": 480},
                {"url": "https://i.ytimg.com/vi/dQw4w9WgXcQ/sd.jpg", "width": 640},
            ]})
        self.assertEqual(item.thumbnail, "https://i.ytimg.com/vi/dQw4w9WgXcQ/sd.jpg")

    def test_usa_thumbnail_simples_quando_nao_ha_lista(self):
        item = _converter_item({"id": "a", "title": "T", "thumbnail": "https://x/t.jpg"})
        self.assertEqual(item.thumbnail, "https://x/t.jpg")

    def test_sem_dado_nao_inventa_thumbnail(self):
        item = _converter_item({"id": "a", "title": "T"})
        self.assertEqual(item.thumbnail, "")


if __name__ == "__main__":
    unittest.main()
