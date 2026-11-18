"""Seleção acumulativa persistente e reprodutor (fila, pausa, repetição)."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

import reprodutor as modulo_reprodutor
from configuracoes import Configuracoes
from reprodutor import MODOS_REPETICAO, Faixa, Reprodutor
from selecao import ItemSelecao, Selecao


class TestSelecao(unittest.TestCase):
    def setUp(self):
        self.raiz = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.raiz, True)
        self.config = Configuracoes(raiz=self.raiz)
        self.selecao = Selecao(self.config)

    def test_acumula_itens_de_varias_pesquisas(self):
        self.selecao.adicionar(ItemSelecao("https://y/1", "A", "Guns", 200,
                                           origem="Guns N' Roses"))
        self.selecao.adicionar(ItemSelecao("https://y/2", "B", "Queen", 300,
                                           origem="Queen"))
        self.selecao.adicionar(ItemSelecao("https://y/3", "C", "Led", 400,
                                           origem="Led Zeppelin"))
        self.assertEqual(self.selecao.quantidade(), 3)
        self.assertEqual(self.selecao.agrupado_por_origem(),
                         {"Guns N' Roses": 1, "Queen": 1, "Led Zeppelin": 1})
        self.assertEqual(self.selecao.duracao_total(), 900)

    def test_duplicata_nao_entra_duas_vezes(self):
        item = ItemSelecao("https://y/1", "A", "Guns", 200)
        self.assertTrue(self.selecao.adicionar(item)[0])
        self.assertFalse(self.selecao.adicionar(item)[0])
        self.assertEqual(self.selecao.quantidade(), 1)
        # mesmo vídeo em outro formato é outro download
        self.assertTrue(self.selecao.adicionar(ItemSelecao("https://y/1", "A",
                                                           "Guns", 200,
                                                           formato="mp4"))[0])
        self.assertEqual(self.selecao.quantidade(), 2)

    def test_persiste_entre_execucoes(self):
        self.selecao.adicionar(ItemSelecao("https://y/1", "A", "Guns", 200,
                                           origem="Guns"))
        reaberta = Selecao(self.config)
        self.assertEqual(reaberta.quantidade(), 1)
        self.assertEqual(reaberta.listar()[0].titulo, "A")
        self.assertEqual(reaberta.listar()[0].origem, "Guns")

    def test_reordenar_remove_limpar(self):
        for numero in range(3):
            self.selecao.adicionar(ItemSelecao(f"https://y/{numero}", f"T{numero}"))
        self.assertTrue(self.selecao.reordenar(2, 0))
        self.assertEqual([i.titulo for i in self.selecao.listar()],
                         ["T2", "T0", "T1"])
        self.assertEqual(self.selecao.remover_indices([1]), 1)
        self.assertEqual([i.titulo for i in self.selecao.listar()], ["T2", "T1"])
        self.assertEqual(self.selecao.remover(["https://y/2"]), 1)
        self.assertEqual(self.selecao.limpar(), 1)
        self.assertTrue(self.selecao.vazio())

    def test_para_download_na_ordem_da_tela(self):
        for numero in range(2):
            self.selecao.adicionar(ItemSelecao(f"https://y/{numero}", f"T{numero}"))
        self.assertEqual(self.selecao.para_download(), [
            ("https://y/0", "mp3"), ("https://y/1", "mp3")])

    def test_arquivo_corrompido_nao_derruba_o_programa(self):
        (self.config.dados).mkdir(parents=True, exist_ok=True)
        (self.config.dados / "selecao.json").write_text("{lixo", encoding="utf-8")
        reaberta = Selecao(self.config)
        self.assertTrue(reaberta.vazio())

    def test_arquivo_vazio_nao_quebra(self):
        with self.assertRaises(ValueError):
            self.selecao.adicionar(ItemSelecao("", "sem url"))


class TestReprodutor(unittest.TestCase):
    def setUp(self):
        self.raiz = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.raiz, True)
        self.config = Configuracoes(raiz=self.raiz,
                                    diretorio_musicas=self.raiz / "Musicas")
        self.config.musicas.mkdir(parents=True, exist_ok=True)
        self.arquivo = self.config.musicas / "a.mp3"
        ffmpeg = shutil.which("ffmpeg") or "/tmp/ff10/ffmpeg"
        if Path(ffmpeg).is_file():
            subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-f", "lavfi",
                            "-i", "sine=frequency=440:duration=2",
                            "-c:a", "libmp3lame", str(self.arquivo)],
                           capture_output=True, check=False)
        if not self.arquivo.is_file():
            self.skipTest("Sem FFmpeg para gerar o MP3 de teste")
        self._original = modulo_reprodutor.localizar_ffplay

    def tearDown(self):
        modulo_reprodutor.localizar_ffplay = self._original

    def _com_player_falso(self) -> tuple[Reprodutor, list]:
        comandos: list = []

        class Processo:
            def __init__(self):
                self.codigo = None

            def poll(self):
                return self.codigo

            def terminate(self):
                self.codigo = 0

            def wait(self, timeout=None):
                return 0

            def kill(self):
                pass

        modulo_reprodutor.localizar_ffplay = lambda config=None: ["/usr/bin/ffplay"]
        reprodutor = Reprodutor(
            self.config, executar=lambda cmd, **kw: (comandos.append(cmd),
                                                     Processo())[1])
        return reprodutor, comandos

    def test_toca_pausa_e_retoma_de_onde_parou(self):
        player, comandos = self._com_player_falso()
        player.definir_fila([Faixa(str(self.arquivo), "A")])
        self.assertTrue(player.tocar(0))
        self.assertTrue(player.esta_rodando())
        time.sleep(0.2)
        player.pausar()
        self.assertTrue(player.pausado)
        posicao = player._posicao_salva
        self.assertGreaterEqual(posicao, 0.15)
        self.assertTrue(player.tocar())  # retoma
        self.assertIn("-ss", comandos[-1])
        self.assertAlmostEqual(float(comandos[-1][comandos[-1].index("-ss") + 1]),
                               posicao, places=1)
        player.parar()
        self.assertFalse(player.tocando)

    def test_sem_ffplay_avisa_em_vez_de_fingir(self):
        modulo_reprodutor.localizar_ffplay = lambda config=None: []
        eventos: list[str] = []
        player = Reprodutor(self.config, ao_mudar=eventos.append)
        player.definir_fila([Faixa(str(self.arquivo), "A")])
        self.assertFalse(player.tocar())
        self.assertIn("sem_ffplay", eventos)

    def test_proxima_anterior_e_fim_da_fila(self):
        player, _ = self._com_player_falso()
        player.definir_fila([Faixa(str(self.arquivo), "A"),
                             Faixa(str(self.arquivo), "B")])
        self.assertTrue(player.tocar(0))
        self.assertTrue(player.proxima())
        self.assertEqual(player.indice, 1)
        self.assertFalse(player.proxima(automatico=True))  # fim, sem repetir
        self.assertTrue(player.anterior())

    def test_repeticao_e_aleatorio(self):
        player, _ = self._com_player_falso()
        player.definir_fila([Faixa(str(self.arquivo), f"T{n}") for n in range(3)])
        player.tocar(2)
        self.assertEqual(player.repeticao, "off")
        self.assertEqual(player.ciclo_repeticao(), "musica")
        self.assertEqual(player.ciclo_repeticao(), "fila")
        self.assertTrue(player.proxima(automatico=True))  # volta ao início
        self.assertEqual(player.indice, 0)
        self.assertEqual(player.ciclo_repeticao(), "off")
        self.assertEqual(len(MODOS_REPETICAO), 3)
        self.assertTrue(player.alternar_aleatorio())
        self.assertTrue(player.proxima())

    def test_volume_e_estado(self):
        player, _ = self._com_player_falso()
        player.definir_fila([Faixa(str(self.arquivo), "A", "Artista", "Álbum",
                                   tem_capa=True, musica_id=7)])
        self.assertEqual(player.mudar_volume(150), 100)
        self.assertEqual(player.mudar_volume(-5), 0)
        estado = player.estado()
        self.assertEqual(estado["faixa"], "A")
        self.assertEqual(estado["subtitulo"], "Artista — Álbum")
        self.assertTrue(estado["capa"])
        self.assertEqual(player.descricao_repeticao(), "Repetir: desligado")

    def test_arquivo_ausente_nao_quebra(self):
        player, _ = self._com_player_falso()
        player.definir_fila([Faixa("/nao/existe.mp3", "Fantasma")])
        self.assertFalse(player.tocar(0))


if __name__ == "__main__":
    unittest.main()
