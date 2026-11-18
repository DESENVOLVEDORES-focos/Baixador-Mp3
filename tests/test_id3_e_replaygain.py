"""ID3 estendido + ReplayGain medido de verdade (com MP3 real do FFmpeg).

Cobre o que a especificação pede além do básico (título/artista/álbum):
compositor (TCOM), disco/total (TPOS), ISRC (TSRC), frames TXXX com a origem
da identificação e ``REPLAYGAIN_*`` calculado a partir de medição ``ebur128``.

Se o FFmpeg não estiver disponível, os testes que dependem dele são pulados
com motivo — nunca passam fingindo que mediram algo.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from audio import (
    ALVO_PADRAO,
    aplicar_replaygain,
    ganho_replaygain,
    medir_volume,
)
from inteligencia import InfoMusica
from metadados import (
    aplicar_metadados,
    gravar_txxx,
    ler_metadados,
    ler_txxx,
)

FFMPEG = shutil.which("ffmpeg")


def _gerar_mp3(destino: Path, volume: str = "0.4", segundos: int = 3) -> bool:
    if not FFMPEG:
        return False
    subprocess.run(
        [FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
         "-f", "lavfi", "-i", f"sine=frequency=440:duration={segundos}",
         "-af", f"volume={volume}", "-codec:a", "libmp3lame",
         "-b:a", "96k", str(destino)],
        check=True, capture_output=True)
    return destino.is_file() and destino.stat().st_size > 0


class BaseComMp3(unittest.TestCase):
    def setUp(self):
        self.pasta = Path(tempfile.mkdtemp(prefix="id3-"))
        self.mp3 = self.pasta / "faixa.mp3"
        if not _gerar_mp3(self.mp3):
            self.skipTest("FFmpeg ausente: não dá para gerar MP3 real")

    def tearDown(self):
        shutil.rmtree(self.pasta, ignore_errors=True)


class TestId3Estendido(BaseComMp3):
    def test_compositor_vira_TCOM(self):
        aplicar_metadados(self.mp3, InfoMusica(
            titulo="Canção", artista="Artista", compositor="Compositor X"))
        self.assertEqual(ler_metadados(self.mp3)["compositor"], "Compositor X")

    def test_disco_vira_TPOS_com_total(self):
        aplicar_metadados(self.mp3, InfoMusica(
            titulo="T", artista="A", disco=2, total_discos=3))
        self.assertEqual(ler_metadados(self.mp3)["disco"], "2/3")

    def test_disco_sem_total(self):
        aplicar_metadados(self.mp3, InfoMusica(
            titulo="T", artista="A", disco=1))
        self.assertEqual(ler_metadados(self.mp3)["disco"], "1")

    def test_sem_disco_nao_inventa_TPOS(self):
        aplicar_metadados(self.mp3, InfoMusica(titulo="T", artista="A"))
        self.assertNotIn("disco", ler_metadados(self.mp3))

    def test_isrc_gravado_e_lido(self):
        aplicar_metadados(self.mp3, InfoMusica(
            titulo="T", artista="A", isrc="BRABC2500001"))
        self.assertEqual(ler_metadados(self.mp3)["isrc"], "BRABC2500001")

    def test_faixa_com_total(self):
        aplicar_metadados(self.mp3, InfoMusica(
            titulo="T", artista="A", faixa=4, total_faixas=10))
        self.assertEqual(ler_metadados(self.mp3)["faixa"], "4/10")

    def test_txxx_grava_e_le(self):
        gravados = gravar_txxx(self.mp3, {"fonte": "musicbrainz",
                                          "origem_url": "https://youtu.be/x"})
        self.assertEqual(gravados, ["fonte", "origem_url"])
        lido = ler_txxx(self.mp3)
        self.assertEqual(lido["fonte"], "musicbrainz")
        self.assertEqual(lido["origem_url"], "https://youtu.be/x")

    def test_txxx_nao_duplica_ao_repetir(self):
        for valor in ("a", "b"):
            gravar_txxx(self.mp3, {"fonte": valor})
        self.assertEqual(ler_txxx(self.mp3)["fonte"], "b")

    def test_txxx_vazio_nao_faz_nada(self):
        self.assertEqual(gravar_txxx(self.mp3, {}), [])
        self.assertEqual(ler_txxx(self.mp3), {})

    def test_txxx_preserva_as_tags_normais(self):
        aplicar_metadados(self.mp3, InfoMusica(titulo="T", artista="A",
                                              album="Alb"))
        gravar_txxx(self.mp3, {"fonte": "itunes"})
        lido = ler_metadados(self.mp3)
        self.assertEqual((lido["titulo"], lido["artista"], lido["album"]),
                         ("T", "A", "Alb"))

    def test_arquivo_invalido_levanta(self):
        from metadados import ErroMetadados

        vazio = self.pasta / "vazio.mp3"
        vazio.write_bytes(b"")
        with self.assertRaises(ErroMetadados):
            gravar_txxx(vazio, {"fonte": "x"})


class TestReplayGain(BaseComMp3):
    def test_mede_volume_real(self):
        medicao = medir_volume(self.mp3)
        self.assertTrue(medicao.ok, medicao.mensagem)
        self.assertLess(medicao.loudness, 0.0)
        self.assertIsNotNone(medicao.pico)

    def test_ganho_leva_ao_alvo(self):
        medicao = medir_volume(self.mp3)
        ganho = ganho_replaygain(medicao.loudness)
        self.assertAlmostEqual(medicao.loudness + ganho, ALVO_PADRAO, places=2)

    def test_ganho_limitado(self):
        self.assertEqual(ganho_replaygain(-90.0), 24.0)
        self.assertEqual(ganho_replaygain(20.0), -24.0)

    def test_ganho_sem_medicao_e_none(self):
        self.assertIsNone(ganho_replaygain(None))

    def test_aplicar_grava_as_tags(self):
        ok, mensagem = aplicar_replaygain(self.mp3)
        self.assertTrue(ok, mensagem)
        tags = ler_txxx(self.mp3)
        self.assertIn("REPLAYGAIN_TRACK_GAIN", tags)
        self.assertRegex(tags["REPLAYGAIN_TRACK_GAIN"], r"^[+-]\d+\.\d\d dB$")
        self.assertIn("REPLAYGAIN_TRACK_PEAK", tags)
        self.assertIn("REPLAYGAIN_REFERENCE_LOUDNESS", tags)

    def test_pico_e_um_fator_positivo(self):
        aplicar_replaygain(self.mp3)
        pico = float(ler_txxx(self.mp3)["REPLAYGAIN_TRACK_PEAK"])
        self.assertGreater(pico, 0.0)
        self.assertLessEqual(pico, 4.0)

    def test_arquivo_inexistente_nao_mente(self):
        medicao = medir_volume(self.pasta / "nao_existe.mp3")
        self.assertFalse(medicao.ok)
        self.assertIn("não encontrado", medicao.mensagem)

    def test_sem_ffmpeg_devolve_motivo(self):
        medicao = medir_volume(self.mp3, ffmpeg="/caminho/que/nao/existe")
        self.assertFalse(medicao.ok)
        self.assertTrue(medicao.mensagem)


class TestReplayGainSemFfmpeg(unittest.TestCase):
    """Sem FFmpeg, nada é fingido: as funções dizem que não deu."""

    def test_aplicar_sem_ffmpeg(self):
        pasta = Path(tempfile.mkdtemp(prefix="rg-"))
        try:
            alvo = pasta / "x.mp3"
            alvo.write_bytes(b"\x00" * 2048)
            ok, mensagem = aplicar_replaygain(alvo, ffmpeg="/nao/existe")
            self.assertFalse(ok)
            self.assertIn("FFmpeg", mensagem)
        finally:
            shutil.rmtree(pasta, ignore_errors=True)

    def test_ganho_com_valor_invalido(self):
        self.assertIsNone(ganho_replaygain("abc"))  # type: ignore[arg-type]


class TestIntegracaoComPreferencias(unittest.TestCase):
    def test_replaygain_chega_na_configuracao(self):
        from dataclasses import replace

        from configuracao_de_teste import configuracao_de_teste
        from preferencias import Preferencias, derivar_configuracoes

        base = configuracao_de_teste()
        prefs = replace(Preferencias(), replaygain=True,
                        diretorio_mp3=str(base.musicas))
        config = derivar_configuracoes(prefs, base)
        self.assertTrue(config.replaygain)

    def test_padrao_desligado(self):
        from configuracao_de_teste import configuracao_de_teste

        self.assertFalse(configuracao_de_teste().replaygain)


if __name__ == "__main__":
    unittest.main()


class TestBitrateExplicito(unittest.TestCase):
    """A tela mostra bitrate com nome claro e o núcleo recebe o código certo."""

    def test_descricao_de_cada_opcao(self):
        from preferencias import OPCOES_BITRATE, descrever_bitrate

        self.assertEqual(len(OPCOES_BITRATE), len({c for c, _d in OPCOES_BITRATE}))
        self.assertIn("320", descrever_bitrate("320K"))
        self.assertIn("Melhor", descrever_bitrate("0"))
        self.assertIn("personalizado", descrever_bitrate("999K"))

    def test_codigo_do_bitrate_na_tela(self):
        from tests.test_central_app import TestCentralApp

        TestCentralApp.setUpClass()
        try:
            app = TestCentralApp.app
            app.mostrar("config")
            from preferencias import descrever_bitrate

            app.config_qualidade.set(descrever_bitrate("192K"))
            self.assertEqual(app._codigo_do_bitrate(), "192K")
            app.config_qualidade.set(descrever_bitrate("0"))
            self.assertEqual(app._codigo_do_bitrate(), "0")
            app.config_qualidade.set("256K")     # valor digitado por fora
            self.assertEqual(app._codigo_do_bitrate(), "256K")
        finally:
            TestCentralApp.tearDownClass()

    def test_valor_que_chega_ao_yt_dlp(self):
        from downloader import Downloader

        class Falso:
            qualidade_mp3 = "192K"
            organizar_nomes = False
            organizar_por_album = False
            sobrescrita = "pular"
            caminho_cookies = None

            @property
            def musicas(self):
                from pathlib import Path
                return Path("/tmp")

            @property
            def videos(self):
                from pathlib import Path
                return Path("/tmp")

            def comando_yt_dlp(self):
                return ["yt-dlp"]

            def caminho_ffmpeg(self):
                return "/tmp/ff10/ffmpeg"

            def argumentos_cookies(self):
                return []

        argumentos = Downloader(Falso()).construir_argumentos(
            "https://youtu.be/x", "mp3", politica="pular")
        posicao = argumentos.index("--audio-quality")
        self.assertEqual(argumentos[posicao + 1], "192K")

    def test_preferencia_invalida_e_recusada(self):
        from dataclasses import replace

        from preferencias import Preferencias

        with self.assertRaises(ValueError):
            replace(Preferencias(), qualidade_mp3="muito").validar()
