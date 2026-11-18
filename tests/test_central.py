"""Fachada ``Central``: o caminho que a interface usa, ponta a ponta.

Aqui os componentes falam entre si de verdade — seleção → fila de downloads →
biblioteca SQLite → playlist → favoritos → reprodutor — com MP3 reais quando o
FFmpeg está disponível. O download do YouTube é substituído por um dublê que
cria um arquivo no disco, porque a rede externa não existe no CI.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from central import Central
from configuracoes import Configuracoes
from metadados import ConfigMetadados
from preferencias import Preferencias
from selecao import ItemSelecao


def _ffmpeg() -> str | None:
    for candidato in (shutil.which("ffmpeg"), "/tmp/ff10/ffmpeg"):
        if candidato and Path(candidato).is_file():
            return candidato
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


class TestCentral(unittest.TestCase):
    def setUp(self):
        self.raiz = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.raiz, True)
        # Central publica escolhas em variáveis de ambiente ao abrir. Fora do
        # teste isso é o comportamento desejado; aqui seria vazamento para os
        # outros arquivos de teste, então o ambiente é restaurado no final.
        self._ambiente = patch.dict(os.environ)
        self._ambiente.start()
        self.addCleanup(self._ambiente.stop)
        self.config = Configuracoes(raiz=self.raiz,
                                    diretorio_musicas=self.raiz / "Musicas")
        self.config.musicas.mkdir(parents=True, exist_ok=True)
        self.central = Central(
            self.config,
            Preferencias(metadados_ativos=False, buscar_capas=False,
                         sincronizar_ao_abrir=False, downloads_simultaneos=1))
        self.central.ffplay = []

    def _mp3(self, nome: str, **tags) -> Path:
        ffmpeg = _ffmpeg()
        destino = self.config.musicas / nome
        if not ffmpeg:
            self.skipTest("Sem FFmpeg")
        subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-f", "lavfi",
                        "-i", "sine=frequency=440:duration=1",
                        "-c:a", "libmp3lame", str(destino)],
                       capture_output=True, check=False)
        if tags:
            from mutagen.id3 import ID3, TIT2, TPE1

            audio = ID3()
            audio.add(TIT2(encoding=3, text=tags.get("titulo", nome)))
            if tags.get("artista"):
                audio.add(TPE1(encoding=3, text=tags["artista"]))
            audio.save(destino)
        return destino

    def _dublê_de_download(self, falhar=()):
        criados: list[Path] = []
        central = self.central

        def baixar(url, formato="mp3", ao_progresso=None, politica=None,
                   contexto=None):
            if url in falhar:
                return False, "indisponível"
            destino = self._mp3(f"{url.rsplit('/', 1)[-1]}.mp3")
            criados.append(destino)
            central.aplicacao.ultimo_caminho = str(destino)
            return True, "pronto"

        central.aplicacao.baixar = baixar  # type: ignore[assignment]
        central.aplicacao.ultimo_caminho = ""
        central.gerenciador.aplicacao = central.aplicacao
        return criados

    # -- downloads → biblioteca -------------------------------------------
    def test_download_concluido_entra_na_biblioteca(self):
        self._mp3("existente.mp3", titulo="Existente", artista="Teste")
        self.assertEqual(self.central.biblioteca.sincronizar()["novos"], 1)
        self._dublê_de_download()
        self.central.adicionar_a_selecao(
            [ItemSelecao("https://y/nova", "Nova", "Artista X", 200)],
            origem="Pesquisa")
        # 1 item na cesta + 1 na fila = o que o botão relata ter iniciado
        self.assertEqual(self.central.iniciar_downloads(), 2)
        self.assertTrue(self.central.gerenciador.aguardar(30))
        self.assertEqual(self.central.resumo_downloads()["concluido"], 1)
        # o download novo foi indexado automaticamente
        self.assertEqual(self.central.biblioteca.contar(), 2)
        nova = next(m for m in self.central.biblioteca.listar()
                    if Path(m.caminho).name == "nova.mp3")
        self.assertEqual(nova.origem_url, "https://y/nova")
        self.assertAlmostEqual(nova.duracao or 0, 1.0, delta=0.6)

    def test_falha_no_download_nao_entra_na_biblioteca(self):
        self._dublê_de_download(falhar={"https://y/ruim"})
        self.central.adicionar_a_selecao(
            [ItemSelecao("https://y/ruim", "Ruim")], origem="Teste")
        self.central.iniciar_downloads()
        self.central.gerenciador.aguardar(30)
        self.assertEqual(self.central.gerenciador.resumo()["falhou"], 1)
        self.assertEqual(self.central.biblioteca.contar(), 0)
        # repetir falhas reabre o item: desta vez com o dublê que funciona
        self.assertEqual(self.central.repetir_falhas(), 1)

    def test_cesta_controla_os_botoes(self):
        self.assertTrue(self.central.selecao.vazio())
        self.central.adicionar_a_selecao(
            [ItemSelecao("https://y/1", "A", origem="P"), ItemSelecao("https://y/2", "B")])
        self.assertEqual(self.central.selecao.quantidade(), 2)
        self.assertTrue(self.central.remover_da_selecao(["https://y/1"]))
        self.assertEqual(self.central.selecao.quantidade(), 1)
        self.central.limpar_selecao()
        self.assertTrue(self.central.selecao.vazio())

    # -- biblioteca pela fachada ------------------------------------------
    def test_buscar_e_editar_metadados(self):
        caminho = self._mp3("a.mp3", titulo="Tempo Perdido", artista="Legião")
        self.central.sincronizar_biblioteca()
        musica = self.central.musicas(texto="legiao")[0]
        self.assertTrue(self.central.salvar_metadados(
            musica.id, titulo="Tempo Perdido (Remaster)",
            artista="Legião Urbana", album="Dois", ano="1986",
            genero="Rock", faixa="2"))
        atualizada = self.central.biblioteca.obter(musica.id)
        self.assertEqual(atualizada.artista, "Legião Urbana")
        from mutagen.id3 import ID3

        tags = ID3(caminho)
        self.assertEqual(str(tags["TPE1"].text[0]), "Legião Urbana")
        self.assertEqual(self.central.musicas(artista="Legião Urbana")[0].id, musica.id)

    def test_completar_metadados_nao_inventa(self):
        self._mp3("sem.mp3", titulo="Original", artista="Banda")
        self.central.sincronizar_biblioteca()
        musica = self.central.biblioteca.listar()[0]
        self.central.config_metadados = ConfigMetadados(usar_ia=False,
                                                       buscar_capa=False)
        class ProcessadorFalso:
            """Fonte externa que não sabe nada: devolve o arquivo intacto."""

            chamadas = 0

            def processar_mp3(self, caminho, dados):
                ProcessadorFalso.chamadas += 1
                self.arquivo = Path(caminho)
                return str(caminho)

        from unittest.mock import patch as _patch

        with _patch("colecoes.criar_processador_padrao",
                    return_value=ProcessadorFalso()):
            resultados = self.central.completar_metadados([musica])
        self.assertEqual(len(resultados), 1)
        self.assertEqual(ProcessadorFalso.chamadas, 1)
        sem = self.central.biblioteca.obter(musica.id)
        # sem provedor externo, nada é inventado: artista continua o real
        self.assertEqual(sem.artista, "Banda")
        self.assertIn("Nada novo", resultados[0].mensagem)

    def test_incorporar_capa_de_arquivo_local(self):
        destino = self._mp3("b.mp3", titulo="Com Capa", artista="Artista Y")
        self.central.sincronizar_biblioteca()
        imagem = self.raiz / "capa.png"
        try:
            from PIL import Image
        except Exception:
            self.skipTest("Sem Pillow")
        Image.new("RGB", (300, 300), (30, 30, 90)).save(imagem)
        musica = self.central.biblioteca.listar()[0]
        resultado = self.central.incorporar_capa(musica,
                                                 imagem.read_bytes())
        self.assertTrue(resultado.ok, resultado.mensagem)
        from mutagen.id3 import ID3

        self.assertTrue(ID3(destino).getall("APIC"))

    def test_excluir_musica_do_banco_e_do_disco(self):
        caminho = self._mp3("c.mp3", titulo="Sai")
        self.central.sincronizar_biblioteca()
        musica = self.central.biblioteca.listar()[0]
        self.assertTrue(self.central.excluir_musica(musica.id, apagar_arquivo=True))
        self.assertFalse(caminho.exists())
        self.assertEqual(self.central.biblioteca.contar(), 0)

    def test_duplicatas_e_sincronizacao_de_removidos(self):
        self._mp3("x1.mp3", titulo="Mesma", artista="Mesmo")
        self.central.sincronizar_biblioteca()
        relatorio = self.central.sincronizar_biblioteca(remover_ausentes=True)
        self.assertEqual(relatorio["removidos"], 0)
        for arquivo in self.config.musicas.glob("*.mp3"):
            arquivo.unlink()
        relatorio = self.central.sincronizar_biblioteca(remover_ausentes=True)
        self.assertEqual(relatorio["removidos"], 1)
        self.assertEqual(self.central.biblioteca.contar(), 0)

    # -- playlists, favoritos, player -------------------------------------
    def test_playlist_completa_pela_fachada(self):
        self._mp3("p1.mp3", titulo="Um", artista="A")
        self._mp3("p2.mp3", titulo="Dois", artista="B")
        self.central.sincronizar_biblioteca()
        ids = [m.id for m in self.central.musicas(ordenar="titulo")]
        playlist = self.central.criar_playlist("Viagem")
        self.assertEqual(self.central.adicionar_a_playlist(playlist, ids), 2)
        self.assertEqual(len(self.central.musicas_da_playlist(playlist)), 2)
        self.central.reordenar_playlist(playlist, list(reversed(ids)))
        self.assertEqual(self.central.musicas_da_playlist(playlist)[0].id,
                         list(reversed(ids))[0])
        self.central.renomear_playlist(playlist, "Estrada")
        self.assertEqual(self.central.playlists()[0]["nome"], "Estrada")
        self.assertEqual(self.central.remover_da_playlist(playlist, ids[0]), 1)
        self.assertTrue(self.central.excluir_playlist(playlist))

    def test_favoritos_de_musica_e_de_artista(self):
        self._mp3("f.mp3", titulo="Favorita", artista="Artista Favorito")
        self.central.sincronizar_biblioteca()
        musica = self.central.musicas()[0]
        self.assertTrue(self.central.favoritar_musica(musica.id))
        self.assertEqual(len(self.central.musicas_favoritas()), 1)
        self.assertTrue(self.central.favoritar("artista", "Artista Favorito"))
        self.assertEqual(len(self.central.favoritos("artista")), 1)
        self.assertTrue(self.central.favoritar("album", "Álbum X"))
        self.assertEqual({f["chave"] for f in self.central.favoritos("album")},
                         {"Álbum X"})

    def test_tocar_fila_e_estado_do_reprodutor(self):
        self._mp3("t.mp3", titulo="Toca", artista="Quem")
        self.central.sincronizar_biblioteca()
        musicas = self.central.musicas()
        self.assertEqual(len(musicas), 1)
        # sem ffplay no ambiente, tocar devolve False em vez de fingir
        self.assertFalse(self.central.tocar_fila(musicas))
        estado = self.central.estado_reprodutor()
        self.assertEqual(estado["faixa"], "Toca")
        self.assertEqual(estado["total"], 1)
        self.assertFalse(self.central.reprodutor.esta_rodando())

    def test_estatisticas_e_recentes(self):
        self._mp3("e1.mp3", titulo="E1", artista="A")
        self._mp3("e2.mp3", titulo="E2", artista="B")
        self.central.sincronizar_biblioteca()
        dados = self.central.estatisticas()
        self.assertEqual(dados["total"], 2)
        self.assertGreater(dados["segundos"], 0)
        self.assertEqual(len(self.central.recentes(limite=1)), 1)
        self.assertEqual(len(self.central.artistas()), 2)
        self.assertEqual(self.central.albuns(), [])  # sem álbum gravado

    # -- o que a tela mostra ----------------------------------------------
    def test_rotulos_dos_estados_existem(self):
        from gerenciador import ESTADOS, ROTULO_ESTADO

        self.assertEqual(set(ROTULO_ESTADO), set(ESTADOS))

    def test_versao_do_ytdlp_e_chave_respondem(self):
        self.assertTrue(self.central.versao_ytdlp())
        chave = self.central.status_chave()
        self.assertFalse(chave.configurada)  # nada de chave fictícia
        self.assertIsInstance(chave.mensagem, str)
        cookies = self.central.status_cookies()
        self.assertTrue(cookies.mensagem)

    def test_erro_de_rede_na_pesquisa_chega_como_excecao_clara(self):
        with patch.object(self.central.aplicacao.pesquisador, "pesquisar",
                          side_effect=RuntimeError("sem rede")):
            with self.assertRaises(RuntimeError):
                self.central.pesquisar("rock")
        # e a consulta não fica registrada como se tivesse dado certo
        self.assertEqual(self.central.pesquisas_recentes(), [])


if __name__ == "__main__":
    unittest.main()


class TestPosProcessamento(unittest.TestCase):
    """Verificação e normalização do MP3 final (com FFmpeg real)."""

    def setUp(self):
        self.raiz = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.raiz, True)
        # Central publica BAIXADOR_SEM_CAPA etc. no processo; sem restaurar,
        # os testes seguintes de metadados/capas (test_ia2) quebram.
        self._ambiente = patch.dict(os.environ)
        self._ambiente.start()
        self.addCleanup(self._ambiente.stop)
        self.config = Configuracoes(raiz=self.raiz,
                                    diretorio_musicas=self.raiz / "Musicas")
        self.config.musicas.mkdir(parents=True, exist_ok=True)

    def _mp3(self, nome: str, segundos: int = 8) -> Path:
        ffmpeg = _ffmpeg()
        if not ffmpeg:
            self.skipTest("Sem FFmpeg")
        destino = self.config.musicas / nome
        subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-f", "lavfi",
                        "-i", f"sine=frequency=440:duration={segundos}",
                        "-c:a", "libmp3lame", "-q:a", "0", str(destino)],
                       capture_output=True, check=False)
        return destino

    def test_normalizacao_muda_o_arquivo_e_mantem_audio(self):
        from audio import duracao, normalizar

        arquivo = self._mp3("norm.mp3")
        antes = arquivo.stat().st_size
        resultado = normalizar(arquivo, ffmpeg=_ffmpeg())
        self.assertTrue(resultado.ok, resultado.mensagem)
        self.assertTrue(resultado.alterado)
        self.assertGreater(arquivo.stat().st_size, antes // 2)
        self.assertAlmostEqual(duracao(arquivo, ffmpeg=_ffmpeg()) or 0, 8.0,
                               delta=0.5)

    def test_verificacao_recusa_arquivo_truncado(self):
        from audio import verificar

        arquivo = self._mp3("curto.mp3", segundos=1)
        resultado = verificar(arquivo, ffmpeg=_ffmpeg())
        self.assertFalse(resultado.ok)
        self.assertIn("mínimo", resultado.mensagem)
        bom = self._mp3("bom.mp3")
        self.assertTrue(verificar(bom, ffmpeg=_ffmpeg()).ok)

    def test_arquivo_corrompido_e_recusado(self):
        from audio import verificar

        ruim = self.config.musicas / "ruim.mp3"
        ruim.write_bytes(b"\x00" * 8192)
        resultado = verificar(ruim, ffmpeg=_ffmpeg())
        self.assertFalse(resultado.ok)

    def test_arquivo_inexistente_nao_quebra(self):
        from audio import duracao, normalizar, verificar

        inexistente = self.raiz / "nada.mp3"
        self.assertIsNone(duracao(inexistente))
        self.assertFalse(normalizar(inexistente, ffmpeg=_ffmpeg()).ok)
        self.assertFalse(verificar(inexistente, ffmpeg=_ffmpeg()).ok)

    def _com_ffmpeg_do_sandbox(self):
        """Só o que a Central consulta do ``config`` nesta etapa."""
        ffmpeg = _ffmpeg()

        class Falso:
            verificar_audio = True
            normalizar_volume = True
            replaygain = False

            def caminho_ffmpeg(self):
                return ffmpeg

        return Falso()

    def test_central_pos_processa_ao_concluir(self):
        from unittest.mock import patch as _patch

        from gerenciador import ItemDownload

        central = Central(self.config, Preferencias(
            metadados_ativos=False, buscar_capas=False,
            sincronizar_ao_abrir=False, normalizar_volume=True,
            verificar_audio=True))
        arquivo = self._mp3("pos.mp3")
        item = ItemDownload(url="https://y/pos", formato="mp3", id=1,
                            caminho=str(arquivo), estado="concluido",
                            mensagem="Concluído.")
        chamadas = []
        falso = self._com_ffmpeg_do_sandbox()
        central.config = falso  # só ``caminho_ffmpeg`` é consultado aqui
        with _patch("audio.normalizar",
                    side_effect=lambda *a, **k: chamadas.append("normalizar")
                    or __import__("audio").ResultadoAudio(arquivo, True, "ok")), \
                _patch("audio.verificar",
                       side_effect=lambda *a, **k: chamadas.append("verificar")
                       or __import__("audio").ResultadoAudio(arquivo, True,
                                                            "verificado")):
            central._pos_processar(item)
            central.biblioteca.adicionar(arquivo, origem_url=item.url)
        self.assertEqual(chamadas, ["verificar", "normalizar"])
        self.assertIn("verificado", item.mensagem)
        self.assertEqual(central.biblioteca.contar(), 1)

    def test_central_grava_replaygain_quando_ligado(self):
        """A preferência ligada faz a Central medir e gravar o ReplayGain."""
        from unittest.mock import patch as _patch

        from gerenciador import ItemDownload

        central = Central(self.config, Preferencias(
            metadados_ativos=False, buscar_capas=False,
            sincronizar_ao_abrir=False, replaygain=True))
        arquivo = self._mp3("rg.mp3")
        item = ItemDownload(url="https://y/rg", formato="mp3", id=1,
                            caminho=str(arquivo), estado="concluido",
                            mensagem="Concluído.")
        falso = self._com_ffmpeg_do_sandbox()
        falso.replaygain = True
        central.config = falso
        medidos = []

        def _falso(caminho, ffmpeg=None, **k):
            medidos.append(caminho)
            return True, "ReplayGain gravado: +1.00 dB"

        with _patch("audio.aplicar_replaygain", side_effect=_falso):
            central._pos_processar(item)
        self.assertEqual(len(medidos), 1)
        self.assertIn("ReplayGain", item.mensagem)

    def test_central_nao_grava_replaygain_desligado(self):
        from unittest.mock import patch as _patch

        from gerenciador import ItemDownload

        central = Central(self.config, Preferencias(
            metadados_ativos=False, buscar_capas=False,
            sincronizar_ao_abrir=False, replaygain=False))
        arquivo = self._mp3("sem_rg.mp3")
        item = ItemDownload(url="https://y/sem", formato="mp3", id=1,
                            caminho=str(arquivo), estado="concluido",
                            mensagem="Concluído.")
        falso = self._com_ffmpeg_do_sandbox()
        falso.replaygain = False
        central.config = falso
        with _patch("audio.aplicar_replaygain") as aplicar:
            central._pos_processar(item)
        aplicar.assert_not_called()


class TestAmbienteNaoVaza(unittest.TestCase):
    """Abrir a Central publica preferências em variáveis de ambiente.

    Isso é necessário para o núcleo respeitá-las, mas **não pode** vazar para
    o resto do processo de testes (foi o que já quebrou test_ia2 em silêncio).
    """

    def test_central_restaura_o_ambiente(self):
        with tempfile.TemporaryDirectory() as temp:
            raiz = Path(temp)
            antes = dict(os.environ)
            with patch.dict(os.environ):
                Central(Configuracoes(raiz=raiz,
                                      diretorio_musicas=raiz / "Musicas"),
                        Preferencias(metadados_ativos=False,
                                     buscar_capas=False))
            self.assertEqual(os.environ.get("BAIXADOR_SEM_CAPA"), antes.get("BAIXADOR_SEM_CAPA"))
            self.assertEqual(os.environ.get("BAIXADOR_METADATA_MODULE"),
                             antes.get("BAIXADOR_METADATA_MODULE"))
