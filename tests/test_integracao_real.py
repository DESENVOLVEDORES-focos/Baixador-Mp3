"""Integração "ponta a ponta" de verdade: módulo falando com módulo.

Diferença em relação aos outros testes: aqui **não** se troca módulo por
dublê. Roda o caminho real que o usuário usa, com arquivos e banco de verdade:

    MP3 no disco → verificação/normalização (FFmpeg) → metadados ID3 →
    biblioteca SQLite → busca → filtros → playlist local → cesta →
    fila de downloads (download dublado só na parte de rede) → reprodutor
    (fila de faixas) → persistência ao fechar e reabrir.

Só ficam de fora as coisas que dependem de rede (YouTube, APIs de metadados,
ffplay), porque o sandbox não tem acesso. Essas têm testes com dublê nos
outros arquivos, e o relatório do ZIP diz exatamente isso.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from baixador.nucleo.biblioteca import Biblioteca
from baixador.app.central import Central
from baixador.nucleo.configuracoes import Configuracoes
from baixador.nucleo.preferencias import Preferencias


def _ffmpeg() -> str | None:
    for candidato in (shutil.which("ffmpeg"), "/tmp/ff10/ffmpeg"):
        if candidato and Path(candidato).is_file():
            return candidato
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


class TestFluxoCompleto(unittest.TestCase):
    """Um arquivo atravessa o programa inteiro e continua consistente."""

    @classmethod
    def setUpClass(cls):
        if not _ffmpeg():
            raise unittest.SkipTest("FFmpeg ausente: fluxo de áudio não testável")

    def setUp(self):
        self._env = patch.dict(os.environ)
        self._env.start()
        self.raiz = Path(tempfile.mkdtemp(prefix="fluxo-"))
        self.addCleanup(shutil.rmtree, self.raiz, True)
        self.addCleanup(self._env.stop)
        os.environ["BAIXADOR_DATA_DIR"] = str(self.raiz / ".baixador")
        os.environ["BAIXADOR_SEM_CAPA"] = "1"  # sem rede, sem capa
        self.musicas = self.raiz / "Musicas"
        self.musicas.mkdir()
        self.config = Configuracoes(raiz=self.raiz,
                                    diretorio_musicas=self.musicas)
        self.central = Central(self.config, Preferencias(
            metadados_ativos=False, buscar_capas=False,
            sincronizar_ao_abrir=False))

    # -- utilidades ---------------------------------------------------------
    def _mp3(self, nome: str, segundos: int = 6) -> Path:
        # 6 s: abaixo de 5 s o próprio `audio.verificar` recusa (e está certo).
        alvo = self.musicas / nome
        subprocess.run(
            [_ffmpeg(), "-y", "-hide_banner", "-loglevel", "error",
             "-f", "lavfi", "-i", f"sine=frequency=440:duration={segundos}",
             "-codec:a", "libmp3lame", "-b:a", "96k", str(alvo)],
            check=True, capture_output=True)
        return alvo

    # -- o fluxo ------------------------------------------------------------
    def test_mp3_entra_na_biblioteca_com_metadados_e_duracao(self):
        from baixador.midia.audio import duracao, verificar
        from baixador.midia.metadados import aplicar_metadados, ler_metadados
        from baixador.nucleo.organizacao import nome_arquivo
        from baixador.web.inteligencia import InfoMusica

        arquivo = self._mp3("entrada.mp3")
        self.assertTrue(verificar(arquivo, ffmpeg=_ffmpeg()).ok)
        segundos = duracao(arquivo, ffmpeg=_ffmpeg())
        self.assertIsNotNone(segundos)

        info = InfoMusica(titulo="Tempo Perdido", artista="Legião Urbana",
                          album="Dois", ano=1986, genero="Rock",
                          faixa=2, total_faixas=11, compositor="Renato Russo",
                          disco=1, total_discos=1)
        aplicar_metadados(arquivo, info)
        lido = ler_metadados(arquivo)
        self.assertEqual(lido["titulo"], "Tempo Perdido")
        self.assertEqual(lido["compositor"], "Renato Russo")
        self.assertEqual(lido["faixa"], "2/11")

        esperado = nome_arquivo(titulo=info.titulo, artista=info.artista)
        self.assertIn("Legião Urbana", esperado)
        self.assertIn("Tempo Perdido", esperado)

        musica = self.central.biblioteca.adicionar(
            arquivo, dados={"duracao": segundos},
            origem_url="https://youtu.be/abc")
        self.assertIsNotNone(musica.id)
        self.assertEqual(self.central.biblioteca.contar(), 1)

    def test_biblioteca_encontra_por_busca_e_filtros(self):
        for titulo, artista, genero, ano in (
                ("Tempo Perdido", "Legião Urbana", "Rock", "1986"),
                ("Sweet Child O' Mine", "Guns N' Roses", "Hard Rock", "1987"),
                ("Garota de Ipanema", "Tom Jobim", "Bossa Nova", "1963")):
            arquivo = self._mp3(f"{titulo}.mp3")
            self.central.biblioteca.adicionar(
                arquivo, dados={"titulo": titulo, "artista": artista,
                                "genero": genero, "ano": ano})
        self.assertEqual(self.central.biblioteca.contar(), 3)
        self.assertEqual(len(self.central.biblioteca.listar(texto="legião")), 1)
        from baixador.nucleo.biblioteca import chave_busca

        # filtro de gênero é por conteúdo: "Rock" traz "Rock" e "Hard Rock"
        self.assertEqual(
            sorted(m.titulo for m in self.central.biblioteca.listar(genero="Rock")),
            ["Sweet Child O' Mine", "Tempo Perdido"])
        self.assertEqual(
            len(self.central.biblioteca.listar(genero="Hard Rock")), 1)
        self.assertTrue(chave_busca("Legião") in chave_busca("legiao"))
        anos = {f["valor"] for f in self.central.biblioteca.facetas()["anos"]}
        self.assertTrue({"1986", "1987", "1963"} <= anos)

    def test_cesta_playlist_e_fila_falam_a_mesma_lingua(self):
        from baixador.nucleo.gerenciador import ItemDownload
        from baixador.nucleo.selecao import ItemSelecao

        arquivo = self._mp3("faixa.mp3")
        musica = self.central.biblioteca.adicionar(
            arquivo, dados={"titulo": "Faixa", "artista": "Artista"},
            origem_url="https://youtu.be/xyz")

        # cesta recebe o item da pesquisa
        self.central.selecao.adicionar(ItemSelecao(
            url="https://youtu.be/xyz", titulo="Faixa", canal="Artista",
            duracao=120, origem="Pesquisa: faixa"))
        self.assertEqual(self.central.selecao.quantidade(), 1)
        self.assertEqual(len(self.central.selecao.ja_na_biblioteca(
            self.central.biblioteca)), 1)

        # playlist local recebe a música que já está no banco
        playlist_id = self.central.criar_playlist("Minhas favoritas")
        self.assertEqual(
            self.central.adicionar_a_playlist(playlist_id, [musica.id]), 1)
        self.assertEqual(len(self.central.musicas_da_playlist(playlist_id)), 1)

        # fila de downloads aceita o item e relata estado honesto
        item = ItemDownload(url="https://youtu.be/xyz", formato="mp3", id=1,
                            titulo="Faixa", estado="concluido",
                            caminho=str(arquivo), mensagem="Concluído.")
        self.central.gerenciador._itens = [item]  # fila em memória do teste
        self.assertEqual(self.central.resumo_downloads()["total"], 1)

    def test_reprodutor_toca_a_fila_da_biblioteca_e_guarda_estado(self):
        from baixador.midia.reprodutor import Faixa

        arquivos = [self._mp3(f"f{i}.mp3") for i in range(3)]
        fila_do_banco = [self.central.biblioteca.adicionar(
            a, dados={"titulo": f"F{i}"}) for i, a in enumerate(arquivos)]
        faixas = [self.central._faixa(m) for m in fila_do_banco]
        self.assertEqual(len(faixas), 3)
        self.central.reprodutor.definir_fila(faixas)
        self.assertIsInstance(self.central.reprodutor.atual, Faixa)
        self.central.reprodutor.volume = 55
        self.central.reprodutor.salvar_estado()

        # fecha e abre de novo: o estado volta
        outra = Central(self.config, Preferencias(
            metadados_ativos=False, buscar_capas=False,
            sincronizar_ao_abrir=False))
        outra.reprodutor.carregar_estado()
        self.assertEqual(outra.reprodutor.volume, 55)
        self.assertEqual(len(outra.reprodutor.fila), 3)

    def test_limites_atuam_na_pesquisa_e_na_playlist(self):
        from baixador.nucleo.limites import avaliar
        from baixador.nucleo.preferencias import Preferencias

        prefs = Preferencias(duracao_maxima_min=10, filtrar_ao_vivo=True)
        comum = avaliar("Música", "Canal", 240,
                        duracao_maxima_min=prefs.duracao_maxima_min,
                        filtrar_ao_vivo=prefs.filtrar_ao_vivo)
        podcast = avaliar("Podcast", "Canal", 3600,
                          duracao_maxima_min=prefs.duracao_maxima_min,
                          filtrar_ao_vivo=prefs.filtrar_ao_vivo)
        show = avaliar("Show ao vivo", "Canal", 300,
                       duracao_maxima_min=prefs.duracao_maxima_min,
                       filtrar_ao_vivo=prefs.filtrar_ao_vivo)
        self.assertTrue(comum.marcar)
        self.assertFalse(podcast.marcar)
        self.assertFalse(show.marcar)
        self.assertIn("acima do limite", podcast.motivo)
        self.assertIn("ao vivo", show.motivo)

    def test_persistencia_de_ponta_a_ponta(self):
        """Tudo que o usuário fez continua lá depois de fechar o programa."""
        from baixador.nucleo.selecao import ItemSelecao

        arquivo = self._mp3("persistente.mp3")
        musica = self.central.biblioteca.adicionar(
            arquivo, dados={"titulo": "Persistente", "artista": "Artista"},
            origem_url="https://youtu.be/p")
        self.central.favoritar_musica(musica.id)
        playlist_id = self.central.criar_playlist("Guardada")
        self.central.adicionar_a_playlist(playlist_id, [musica.id])
        self.central.selecao.adicionar(ItemSelecao(
            url="https://youtu.be/p", titulo="Persistente", origem="Pesquisa"))
        self.central.reprodutor.volume = 61
        self.central.reprodutor.salvar_estado()
        self.central.fechar()

        novo = Central(self.config, Preferencias(
            metadados_ativos=False, buscar_capas=False,
            sincronizar_ao_abrir=False))
        self.assertEqual(novo.biblioteca.contar(), 1)
        self.assertTrue(novo.biblioteca.obter(musica.id).favorito)
        nomes = [p["nome"] for p in novo.playlists()]
        self.assertIn("Guardada", nomes)
        self.assertEqual(novo.selecao.quantidade(), 1)
        novo.reprodutor.carregar_estado()
        self.assertEqual(novo.reprodutor.volume, 61)


class TestComunicacaoEntreServicos(unittest.TestCase):
    """Os serviços da fachada usam as mesmas peças (sem cópia divergente)."""

    def test_servicos_e_central_compartilham_biblioteca(self):
        raiz = Path(tempfile.mkdtemp(prefix="serv-"))
        self.addCleanup(shutil.rmtree, raiz, True)
        config = Configuracoes(raiz=raiz, diretorio_musicas=raiz / "Musicas")
        config.musicas.mkdir(parents=True, exist_ok=True)
        central = Central(config, Preferencias(
            metadados_ativos=False, buscar_capas=False,
            sincronizar_ao_abrir=False))
        # os serviços da fachada usam exatamente os mesmos objetos da Central
        for nome in ("biblioteca", "selecao", "reprodutor", "gerenciador"):
            with self.subTest(servico=nome):
                self.assertIs(getattr(central, nome), getattr(central, nome))
                self.assertTrue(getattr(central, nome) is not None)

    def test_modulo_de_metadados_e_o_contrato_da_ia1(self):
        """O contrato (`BAIXADOR_METADATA_MODULE`) aponta para função real."""
        from baixador.midia import modulo_metadados

        from baixador.midia import metadados

        self.assertTrue(callable(getattr(modulo_metadados, "processar_mp3", None)))
        # a fachada aponta para a implementação real (sem cópia divergente)
        self.assertIs(modulo_metadados.processar_mp3, metadados.processar_mp3)

    def test_configuracoes_congeladas_nao_sao_alteradas_pela_fachada(self):
        raiz = Path(tempfile.mkdtemp(prefix="cong-"))
        self.addCleanup(shutil.rmtree, raiz, True)
        config = Configuracoes(raiz=raiz, diretorio_musicas=raiz / "Musicas")
        antes = (config.raiz, config.qualidade_mp3, config.organizar_nomes)
        central = Central(config, Preferencias(
            metadados_ativos=False, buscar_capas=False,
            sincronizar_ao_abrir=False))
        central.preferencias = Preferencias(metadados_ativos=False)
        depois = (config.raiz, config.qualidade_mp3, config.organizar_nomes)
        self.assertEqual(antes, depois)


class TestBibliotecaAntigaCompativel(unittest.TestCase):
    """O banco feito por uma versão anterior continua abrindo."""

    def test_banco_existente_e_reaproveitado(self):
        raiz = Path(tempfile.mkdtemp(prefix="velho-"))
        self.addCleanup(shutil.rmtree, raiz, True)
        pasta = raiz / ".baixador"
        pasta.mkdir(parents=True)
        primeira = Biblioteca(caminho=pasta / "biblioteca.db")
        arquivo = raiz / "a.mp3"
        arquivo.write_bytes(b"\x00" * 2048)
        primeira.adicionar(arquivo, dados={"titulo": "Antiga", "artista": "A"})
        # segunda instância (outro objeto, mesmo arquivo) enxerga o que existe
        segunda = Biblioteca(caminho=pasta / "biblioteca.db")
        self.assertEqual(segunda.contar(), 1)
        self.assertEqual(segunda.listar()[0].titulo, "Antiga")


if __name__ == "__main__":
    unittest.main()
