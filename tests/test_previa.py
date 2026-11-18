"""Pré-visualização: análise de faixa, comandos do yt-dlp e ciclo do trecho.

Os testes com yt-dlp só usam ``subprocess.run`` simulado (o runner do CI não
tem rede); o comportamento real foi validado à parte com FFmpeg e mídia local
(ver DEVELOPMENT_LOG.md).
"""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from configuracoes import Configuracoes
from previa import (
    SEGUNDOS_MAXIMO, SEGUNDOS_PADRAO, AnaliseFaixa, DadosVideo, ErroPrevia,
    Previa, analisar, limpar, pasta_para_tocar,
)


class TestAnaliseDeFaixa(unittest.TestCase):
    """Detectar show/versão errada pelo título, canal e duração."""

    def test_estudio_comum_nao_alerta(self):
        analise = analisar("Queen - Bohemian Rhapsody (Official Video)",
                           "Queen Official", 355)
        self.assertFalse(analise.alerta)
        self.assertFalse(analise.possivel_ao_vivo)
        self.assertIn("Nenhum indício", analise.resumo())

    def test_ao_vivo_no_titulo(self):
        analise = analisar("Tempo Perdido (Ao Vivo no Morumbi)", "Legiao Urbana", 320)
        self.assertTrue(analise.alerta)
        self.assertTrue(analise.possivel_ao_vivo)
        self.assertIn("ao vivo", analise.resumo())

    def test_live_em_ingles(self):
        analise = analisar("Believer (Live at the Hollywood Bowl)", "Imagine Dragons")
        self.assertTrue(analise.possivel_ao_vivo)

    def test_festival_e_show_inteiro(self):
        analise = analisar("Rock in Rio 2024 - Full Show", "Festival", 5400)
        self.assertTrue(analise.alerta)
        self.assertIn("90 min", analise.resumo())

    def test_versao_estendida_e_remix(self):
        for titulo in ("Song (Extended Version)", "Song - Remix"):
            self.assertTrue(analisar(titulo).alerta, titulo)

    def test_cover_e_slowed_alertam(self):
        for titulo in ("Song (Cover)", "Song (Slowed + Reverb)", "Song (Karaoke)"):
            self.assertTrue(analisar(titulo).alerta, titulo)

    def test_duracao_longa_alerta_mesmo_sem_palavra_chave(self):
        analise = analisar("Sessao da tarde", "Canal", 20 * 60)
        self.assertTrue(analise.alerta)
        self.assertIn("20 min", analise.resumo())

    def test_canal_de_show_alerta(self):
        self.assertTrue(analisar("Show completo", "Rock ao Vivo").alerta)

    def test_transmissao_ao_vigente_alerta(self):
        analise = analisar("Ao vivo agora", "", None, ao_vivo=True)
        self.assertTrue(analise.alerta)
        self.assertIn("transmissao", analise.indicios)

    def test_sem_acento_nao_engana(self):
        self.assertTrue(analisar("Musica (Ao Vivo)").alerta)

    def test_motivos_explicam_o_alerta(self):
        analise = analisar("Song (Live)", "Banda")
        self.assertEqual(len(analise.motivos), len(analise.indicios))
        self.assertIsInstance(analise, AnaliseFaixa)


class TestComandosDaPrevia(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config = Configuracoes(raiz=Path(self.temp.name))
        self.previa = Previa(self.config)

    def test_info_nao_baixa_midia(self):
        comando = self.previa.construir_comando_info("https://youtu.be/abc")
        self.assertIn("--skip-download", comando)
        self.assertIn("-J", comando)
        self.assertEqual(comando[-1], "https://youtu.be/abc")

    def test_amostra_corta_trecho_e_limita_segundos(self):
        destino = Path(self.temp.name) / "p"
        comando = self.previa.construir_comando_amostra(
            "https://youtu.be/abc", destino, SEGUNDOS_PADRAO)
        self.assertIn("--download-sections", comando)
        self.assertIn(f"*0-{SEGUNDOS_PADRAO}", comando)
        self.assertIn("bestaudio/best", comando)

        comando = self.previa.construir_comando_amostra(
            "https://youtu.be/abc", destino, 9999)
        self.assertIn(f"*0-{SEGUNDOS_MAXIMO}", comando)

    def test_amostra_passa_ffmpeg_de_ferramentas(self):
        ferramentas = self.config.ferramentas
        ferramentas.mkdir(parents=True, exist_ok=True)
        executavel = ferramentas / "ffmpeg.exe"
        executavel.write_bytes(b"x")
        comando = self.previa.construir_comando_amostra(
            "https://youtu.be/abc", Path(self.temp.name) / "p")
        self.assertIn("--ffmpeg-location", comando)
        self.assertIn(str(executavel), comando)

    def test_amostra_nao_quebra_sem_ffmpeg(self):
        # O teste não pode depender de existir um ffmpeg no PATH da máquina:
        # isola o "sem FFmpeg" de verdade, senão passa no CI e falha em quem tem.
        with patch.object(Configuracoes, "caminho_ffmpeg",
                          side_effect=FileNotFoundError("sem ffmpeg")):
            comando = self.previa.construir_comando_amostra(
                "https://youtu.be/abc", Path(self.temp.name) / "p")
        self.assertNotIn("--ffmpeg-location", comando)
        # A prévia continua montada: o yt-dlp decide se consegue cortar.
        self.assertIn("--download-sections", comando)


class TestExecucaoDaPrevia(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.raiz = Path(self.temp.name)
        self.config = Configuracoes(raiz=self.raiz)
        self.previa = Previa(self.config)

    def _processo(self, stdout="", stderr="", codigo=0):
        return subprocess.CompletedProcess(args=[], returncode=codigo,
                                           stdout=stdout, stderr=stderr)

    def test_preparar_le_dados_e_analisa(self):
        import json

        saida = json.dumps({
            "title": "Tempo Perdido (Ao Vivo)", "channel": "Legiao Urbana",
            "duration": 312, "is_live": False,
            "formats": [{"acodec": "mp4a", "vcodec": "none"}],
        })
        with patch("previa.subprocess.run", return_value=self._processo(saida)):
            dados = self.previa.preparar("https://youtu.be/abc")
        self.assertIsInstance(dados, DadosVideo)
        self.assertEqual(dados.titulo, "Tempo Perdido (Ao Vivo)")
        self.assertEqual(dados.duracao, 312)
        self.assertTrue(dados.analise.alerta)

    def test_preparar_detecta_live_e_sem_audio(self):
        import json

        saida = json.dumps({"title": "Stream", "live_status": "is_live",
                            "formats": [{"acodec": "none"}]})
        with patch("previa.subprocess.run", return_value=self._processo(saida)):
            dados = self.previa.preparar("https://youtu.be/abc")
        self.assertTrue(dados.ao_vivo)
        self.assertFalse(dados.tem_audio)

    def test_preparar_falha_com_mensagem_do_ytdlp(self):
        with patch("previa.subprocess.run",
                   return_value=self._processo(stderr="ERROR: Video unavailable",
                                               codigo=1)):
            with self.assertRaises(ErroPrevia) as contexto:
                self.previa.preparar("https://youtu.be/abc")
        self.assertIn("Video unavailable", str(contexto.exception))

    def test_preparar_sem_saida_avisa(self):
        with patch("previa.subprocess.run", return_value=self._processo("")):
            with self.assertRaises(ErroPrevia):
                self.previa.preparar("https://youtu.be/abc")

    def test_baixar_amostra_devolve_o_arquivo_maior(self):
        destino = self.raiz / "p"

        def criar(*_a, **_k):
            destino.mkdir(parents=True, exist_ok=True)
            (destino / "previa.m4a").write_bytes(b"\x00" * 4096)
            (destino / "previa.part").write_bytes(b"\x00" * 10)
            return self._processo()

        with patch("previa.subprocess.run", side_effect=criar):
            arquivo = self.previa.baixar_amostra("https://youtu.be/abc", destino)
        self.assertEqual(arquivo.name, "previa.m4a")
        self.assertLessEqual(arquivo.stat().st_size, 4 * 1024 * 1024)

    def test_amostra_vazia_e_recusada(self):
        destino = self.raiz / "p"

        def criar(*_a, **_k):
            destino.mkdir(parents=True, exist_ok=True)
            (destino / "previa.m4a").write_bytes(b"\x00" * 331)  # corte inválido
            return self._processo()

        with patch("previa.subprocess.run", side_effect=criar):
            with self.assertRaises(ErroPrevia) as contexto:
                self.previa.baixar_amostra("https://youtu.be/abc", destino)
        self.assertIn("vazia", str(contexto.exception))
        self.assertFalse((destino / "previa.m4a").exists())  # não deixa lixo

    def test_amostra_acima_do_limite_e_descartada(self):
        destino = self.raiz / "p"

        def criar(*_a, **_k):
            destino.mkdir(parents=True, exist_ok=True)
            with open(destino / "previa.m4a", "wb") as arquivo:
                arquivo.write(b"\x00" * (4 * 1024 * 1024 + 10))
            return self._processo()

        with patch("previa.subprocess.run", side_effect=criar):
            with self.assertRaises(ErroPrevia) as contexto:
                self.previa.baixar_amostra("https://youtu.be/abc", destino)
        self.assertIn("limite", str(contexto.exception))
        self.assertFalse((destino / "previa.m4a").exists())

    def test_limpar_apaga_a_pasta(self):
        pasta = self.raiz / "previa-x"
        pasta.mkdir()
        (pasta / "previa.mp3").write_bytes(b"x")
        limpar(pasta)
        self.assertFalse(pasta.exists())
        limpar(pasta)  # idempotente, não estoura

    def test_pasta_para_tocar_devolve_original_sem_ffmpeg(self):
        arquivo = self.raiz / "previa.webm"
        arquivo.write_bytes(b"x")
        with patch("previa.shutil.which", return_value=None):
            self.assertEqual(pasta_para_tocar(arquivo, self.raiz), arquivo)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
