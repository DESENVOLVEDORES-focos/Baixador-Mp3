"""Biblioteca SQLite: indexar disco, buscar, playlists, favoritos, persistir."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from baixador.nucleo.biblioteca import Biblioteca, chave_busca
from baixador.nucleo.configuracoes import Configuracoes


def _ffmpeg() -> str | None:
    """FFmpeg de teste (o programa já exige FFmpeg; aqui é só para gerar MP3)."""
    for candidato in (shutil.which("ffmpeg"), "/tmp/ff10/ffmpeg"):
        if candidato and Path(candidato).is_file():
            return candidato
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def _criar_mp3(caminho: Path, *, titulo: str, artista: str = "",
               album: str = "", ano: str = "", genero: str = "",
               faixa: str = "", capa: bytes | None = None) -> bool:
    """MP3 real com tags ID3 (pula o teste se não houver FFmpeg/Mutagen)."""
    ffmpeg = _ffmpeg()
    if ffmpeg is None:
        return False
    caminho.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-f", "lavfi",
                    "-i", "sine=frequency=440:duration=2",
                    "-c:a", "libmp3lame", str(caminho)],
                   capture_output=True, check=False)
    if not caminho.is_file():
        return False
    from mutagen.id3 import ID3, TALB, TCON, TDRC, TIT2, TPE1, TRCK

    audio = ID3()
    audio.add(TIT2(encoding=3, text=titulo))
    if artista:
        audio.add(TPE1(encoding=3, text=artista))
    if album:
        audio.add(TALB(encoding=3, text=album))
    if ano:
        audio.add(TDRC(encoding=3, text=ano))
    if genero:
        audio.add(TCON(encoding=3, text=genero))
    if faixa:
        audio.add(TRCK(encoding=3, text=faixa))
    if capa:
        from mutagen.id3 import APIC

        audio.add(APIC(encoding=3, mime="image/jpeg", type=3, desc="Capa",
                       data=capa))
    audio.save(caminho)
    return True


class TestBiblioteca(unittest.TestCase):
    def setUp(self):
        self.raiz = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.raiz, True)
        self.config = Configuracoes(raiz=self.raiz,
                                    diretorio_musicas=self.raiz / "Musicas")
        self.config.musicas.mkdir(parents=True, exist_ok=True)
        self.biblioteca = Biblioteca(self.config)

    def _musicas_de_teste(self) -> list:
        criadas = []
        if _criar_mp3(self.config.musicas / "legiao.mp3", titulo="Tempo Perdido",
                      artista="Legião Urbana", album="Dois", ano="1986",
                      genero="Rock", faixa="2"):
            criadas.append("legiao")
        if _criar_mp3(self.config.musicas / "queen.mp3",
                      titulo="Bohemian Rhapsody", artista="Queen",
                      album="A Night at the Opera", ano="1975",
                      genero="Rock", faixa="11"):
            criadas.append("queen")
        if _criar_mp3(self.config.musicas / "sub" / "dupla.mp3",
                      titulo="Tempo Perdido", artista="Legião Urbana",
                      album="Acústico", ano="1992", genero="Rock"):
            criadas.append("dupla")
        return criadas

    def test_indexa_tags_reais_e_nao_duplica(self):
        if not self._musicas_de_teste():
            self.skipTest("Sem FFmpeg/Mutagen para gerar MP3 de teste")
        resultado = self.biblioteca.sincronizar()
        self.assertEqual(resultado["encontrados"], 3)
        self.assertEqual(resultado["novos"], 3)
        self.assertEqual(self.biblioteca.contar(), 3)
        # reindexar não duplica (caminho é chave única)
        self.biblioteca.sincronizar()
        self.assertEqual(self.biblioteca.contar(), 3)
        musica = next(m for m in self.biblioteca.listar() if m.artista == "Queen")
        self.assertEqual(musica.album, "A Night at the Opera")
        self.assertEqual(musica.ano, "1975")
        self.assertGreater(musica.duracao or 0, 1.0)

    def test_busca_sem_acento_e_por_campo(self):
        if not self._musicas_de_teste():
            self.skipTest("Sem FFmpeg/Mutagen")
        self.biblioteca.sincronizar()
        for consulta in ("legiao", "Legião", "LEGIÃO", "urbana"):
            with self.subTest(consulta=consulta):
                self.assertTrue(self.biblioteca.listar(texto=consulta))
        self.assertEqual(len(self.biblioteca.listar(artista="Queen")), 1)
        self.assertEqual(len(self.biblioteca.listar(album="Dois")), 1)

    def test_ordenacoes(self):
        if not self._musicas_de_teste():
            self.skipTest("Sem FFmpeg/Mutagen")
        self.biblioteca.sincronizar()
        por_titulo = [m.titulo for m in self.biblioteca.listar(ordenar="titulo")]
        self.assertEqual(por_titulo[0], "Bohemian Rhapsody")
        por_ano = [m.ano for m in self.biblioteca.listar(ordenar="ano")]
        self.assertEqual(por_ano[0], "1992")

    def test_agregacoes_e_duplicatas(self):
        if not self._musicas_de_teste():
            self.skipTest("Sem FFmpeg/Mutagen")
        self.biblioteca.sincronizar()
        artistas = {a["nome"]: a["total"] for a in self.biblioteca.artistas()}
        self.assertEqual(artistas["Legião Urbana"], 2)
        self.assertEqual(len(self.biblioteca.albuns()), 3)
        duplicatas = self.biblioteca.duplicatas()
        self.assertEqual(len(duplicatas), 1)
        self.assertEqual(len(duplicatas[0]), 2)

    def test_favoritos_alternam_e_persistem(self):
        if not self._musicas_de_teste():
            self.skipTest("Sem FFmpeg/Mutagen")
        self.biblioteca.sincronizar()
        musica = self.biblioteca.listar()[0]
        self.assertTrue(self.biblioteca.alternar_favorito(musica.id))
        reaberta = Biblioteca(self.config)
        self.assertTrue(reaberta.obter(musica.id).favorito)
        self.assertEqual(len(reaberta.musicas_favoritas()), 1)
        self.assertFalse(reaberta.alternar_favorito(musica.id))

    def test_playlist_crud_e_ordem(self):
        if not self._musicas_de_teste():
            self.skipTest("Sem FFmpeg/Mutagen")
        self.biblioteca.sincronizar()
        ids = [m.id for m in self.biblioteca.listar(ordenar="titulo")]
        playlist = self.biblioteca.criar_playlist("Minha Mix")
        self.assertEqual(self.biblioteca.adicionar_a_playlist(playlist, ids), 3)
        # adicionar de novo não duplica
        self.assertEqual(self.biblioteca.adicionar_a_playlist(playlist, ids), 0)
        self.biblioteca.reordenar_playlist(playlist, list(reversed(ids)))
        self.assertEqual([m.id for m in self.biblioteca.musicas_da_playlist(playlist)],
                         list(reversed(ids)))
        self.assertEqual(self.biblioteca.remover_da_playlist(playlist, ids[0]), True)
        self.assertEqual(len(self.biblioteca.musicas_da_playlist(playlist)), 2)
        self.biblioteca.renomear_playlist(playlist, "Rock")
        self.assertEqual(self.biblioteca.listar_playlists()[0]["nome"], "Rock")
        self.assertTrue(self.biblioteca.excluir_playlist(playlist))
        self.assertEqual(self.biblioteca.listar_playlists(), [])

    def test_favoritos_de_artista_album_e_pesquisas(self):
        self.assertTrue(self.biblioteca.favoritar("artista", "Queen"))
        self.assertTrue(self.biblioteca.eh_favorito("artista", "Queen"))
        self.assertEqual(self.biblioteca.favoritos("artista")[0]["chave"], "Queen")
        self.biblioteca.registrar_pesquisa("rock")
        self.biblioteca.registrar_pesquisa("queen")
        self.biblioteca.registrar_pesquisa("rock")  # move para o topo
        recentes = self.biblioteca.pesquisas_recentes()
        self.assertEqual(recentes[0]["consulta"], "rock")
        self.assertEqual(len(recentes), 2)  # não repete
        self.biblioteca.limpar_pesquisas()
        self.assertEqual(self.biblioteca.pesquisas_recentes(), [])

    def test_remover_com_arquivo(self):
        if not self._musicas_de_teste():
            self.skipTest("Sem FFmpeg/Mutagen")
        self.biblioteca.sincronizar()
        musica = self.biblioteca.listar()[1]
        caminho = Path(musica.caminho)
        self.assertTrue(self.biblioteca.remover(musica.id, apagar_arquivo=True))
        self.assertFalse(caminho.exists())
        self.assertEqual(self.biblioteca.contar(), 2)

    def test_sem_capa_lista_arquivos_sem_imagem(self):
        if not self._musicas_de_teste():
            self.skipTest("Sem FFmpeg/Mutagen")
        self.biblioteca.sincronizar()
        self.assertEqual(len(self.biblioteca.sem_capa()), 3)

    def test_chave_busca_remove_acento_e_caixa(self):
        self.assertEqual(chave_busca("Legião URBANA"), chave_busca("legiao urbana"))
        self.assertEqual(chave_busca("AC/DC"), "ac/dc")


if __name__ == "__main__":
    unittest.main()


class TestFiltrosDaBiblioteca(unittest.TestCase):
    """Filtros combináveis, facetas e contagens — o que a tela oferece."""

    def setUp(self):
        self.raiz = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.raiz, True)
        self.config = Configuracoes(raiz=self.raiz,
                                    diretorio_musicas=self.raiz / "Musicas")
        self.config.musicas.mkdir(parents=True, exist_ok=True)
        self.biblioteca = Biblioteca(self.config)
        criadas = [
            ("a.mp3", "Alpha", "Artista Um", "Álbum X", "1999", "Rock", 120),
            ("b.mp3", "Beta", "Artista Um", "Álbum X", "2005", "Pop", 400),
            ("c.mp3", "Gama", "Artista Dois", "Álbum Y", "2005", "Rock", 250),
        ]
        self.ids = {}
        for nome, titulo, artista, album, ano, genero, segundos in criadas:
            if not _criar_mp3(self.config.musicas / nome, titulo=titulo,
                              artista=artista, album=album, ano=ano,
                              genero=genero):
                self.skipTest("Sem FFmpeg/Mutagen")
            musica = self.biblioteca.adicionar(self.config.musicas / nome)
            self.ids[titulo] = musica.id
            # duração real do arquivo é 2 s; grava a duração usada nos filtros
            self.biblioteca.atualizar(musica.id, duracao=segundos)

    def test_filtro_por_ano(self):
        self.assertEqual(len(self.biblioteca.listar(ano="2005")), 2)
        self.assertEqual(len(self.biblioteca.listar(ano="1999")), 1)

    def test_filtro_por_duracao(self):
        self.assertEqual(len(self.biblioteca.listar(duracao_min=300)), 1)
        self.assertEqual(len(self.biblioteca.listar(duracao_max=200)), 1)
        self.assertEqual(len(self.biblioteca.listar(duracao_min=100,
                                                   duracao_max=300)), 2)

    def test_filtros_combinados(self):
        resultado = self.biblioteca.listar(artista="Artista Um", genero="Pop")
        self.assertEqual([m.titulo for m in resultado], ["Beta"])

    def test_sem_metadados_e_sem_capa(self):
        # nenhuma das três tem artista vazio: nenhuma deve ser marcada como
        # "sem metadados" (o filtro existe para achar arquivo sem tag)
        self.assertEqual(self.biblioteca.listar(sem_metadados=True), [])
        self.assertEqual(len(self.biblioteca.listar(sem_capa=True)), 3)
        self.biblioteca.atualizar(self.ids["Alpha"], tem_capa=True)
        self.assertEqual(len(self.biblioteca.listar(sem_capa=True)), 2)

    def test_recentes_por_dias(self):
        self.assertEqual(len(self.biblioteca.listar(dias=7)), 3)
        self.assertEqual(len(self.biblioteca.listar(dias=0)), 3)

    def test_favoritos_ordenacao(self):
        self.biblioteca.alternar_favorito(self.ids["Gama"])
        primeiro = self.biblioteca.listar(ordenar="favoritos")[0]
        self.assertEqual(primeiro.titulo, "Gama")

    def test_ordenacoes_novas_existem(self):
        for nome in ("duracao_curta", "recentes", "favoritos", "artista_ano"):
            with self.subTest(ordenacao=nome):
                self.assertTrue(self.biblioteca.listar(ordenar=nome))

    def test_facetas_trazem_valores_e_contagem(self):
        facetas = self.biblioteca.facetas()
        artistas = {f["valor"]: f["total"] for f in facetas["artistas"]}
        self.assertEqual(artistas["Artista Um"], 2)
        self.assertEqual([f["valor"] for f in facetas["anos"]], ["2005", "1999"])
        self.assertEqual(len(facetas["generos"]), 2)

    def test_contar_filtrado(self):
        self.assertEqual(self.biblioteca.contar_filtrado(artista="Artista Um"), 2)
        self.assertEqual(self.biblioteca.contar_filtrado(), 3)
