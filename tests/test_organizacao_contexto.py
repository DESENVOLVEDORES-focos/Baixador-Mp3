"""Testes de organização de nomes, contexto da pesquisa e diagnóstico de erros."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from contexto import ContextoMidia
from diagnostico import (
    SITUACAO_COOKIES_VENCIDOS, SITUACAO_JA_EXISTE, SITUACAO_LOGIN,
    SITUACAO_NAO_ENCONTRADO, SITUACAO_OUTRO, SITUACAO_PRIVADO, SITUACAO_REDE,
    classificar, dica_para_interface, sanitizar,
)
from downloader import Downloader
from organizacao import (
    caminho_disponivel, limpar_componente, nome_arquivo, subpasta,
    titulo_e_artista_do_arquivo,
)


class TestNomes(unittest.TestCase):
    def test_artista_e_titulo(self):
        self.assertEqual(
            nome_arquivo(titulo="Bohemian Rhapsody", artista="Queen"),
            "Queen - Bohemian Rhapsody")

    def test_nao_repete_o_artista_no_titulo(self):
        self.assertEqual(
            nome_arquivo(titulo="Queen - Bohemian Rhapsody", artista="Queen"),
            "Queen - Bohemian Rhapsody")

    def test_remove_caracteres_proibidos_no_windows(self):
        nome = nome_arquivo(titulo='A/B: C? "D"', artista="E*F|G")
        for proibido in '<>:"/\\|?*':
            self.assertNotIn(proibido, nome)

    def test_nomes_reservados_do_windows_recebem_sufixo(self):
        self.assertEqual(limpar_componente("CON"), "_CON")
        self.assertEqual(limpar_componente("nul"), "_nul")

    def test_ponto_e_espaco_no_fim_somem(self):
        self.assertEqual(limpar_componente("  nome ...  "), "nome")

    def test_limite_de_comprimento(self):
        nome = limpar_componente("a" * 400)
        self.assertLessEqual(len(nome), 150)

    def test_nunca_devolve_vazio(self):
        self.assertEqual(nome_arquivo(titulo="", artista=""), "Conteúdo baixado")

    def test_extrai_artista_e_titulo_do_nome_do_ytdlp(self):
        self.assertEqual(
            titulo_e_artista_do_arquivo("Queen - Bohemian Rhapsody [dQw4w9WgXcQ].mp3"),
            ("Bohemian Rhapsody", "Queen"))
        self.assertEqual(
            titulo_e_artista_do_arquivo("So Um Titulo [abc123].mp3"),
            ("So Um Titulo", ""))

    def test_subpasta_usa_apenas_dados_confirmados(self):
        # Comparar partes: no Windows o separador é "\\".
        self.assertEqual(
            subpasta({"artista": "Queen", "album": "A Night at the Opera"}).parts,
            ("Queen", "A Night at the Opera"))
        self.assertEqual(subpasta({"artista": "Queen"}).parts, ("Queen",))
        self.assertIsNone(subpasta({"artista": "", "album": ""}))

    def test_caminho_disponivel_acrescenta_contador(self):
        with tempfile.TemporaryDirectory() as temp:
            pasta = Path(temp)
            (pasta / "faixa.mp3").write_bytes(b"x")
            (pasta / "faixa (2).mp3").write_bytes(b"x")
            self.assertEqual(caminho_disponivel(pasta, "faixa.mp3").name,
                             "faixa (3).mp3")


class ConfigComOrganizacao:
    organizar_nomes = True

    def __init__(self, raiz: Path):
        self.raiz = raiz
        self.musicas = raiz / "Musicas"
        self.videos = raiz / "Videos"
        self.dados = raiz / ".baixador"
        self.sobrescrita = "pular"

    def comando_yt_dlp(self):
        return ["yt-dlp"]

    def caminho_ffmpeg(self):
        return "ffmpeg"

    def preparar_diretorios(self):
        for pasta in (self.musicas, self.videos, self.dados):
            pasta.mkdir(parents=True, exist_ok=True)

    def resolver_cookies(self):
        return None


class Processo:
    def __init__(self, saida=(), codigo=0, ao_chamar=None):
        self.stdout = iter(list(saida))
        self._codigo = codigo
        self._ao_chamar = ao_chamar

    def __call__(self, argv, **kwargs):
        if self._ao_chamar is not None:
            self._ao_chamar(list(argv))
        return self

    def wait(self):
        return self._codigo

    def kill(self):
        pass


class TestPublicacaoComNomeOrganizado(unittest.TestCase):
    def _baixar(self, contexto, nome_ytdlp="Queen - Bohemian Rhapsody [dQw4w9WgXcQ].mp3"):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        config = ConfigComOrganizacao(Path(temp.name))
        downloader = Downloader(config)  # type: ignore[arg-type]

        def criar(argv):
            if "--skip-download" in argv:
                return
            pasta = Path(argv[argv.index("--paths") + 1])
            (pasta / nome_ytdlp).write_bytes(b"\xff\xfb\x90\x00" + b"\x00" * 64)

        with patch("downloader.subprocess.Popen", Processo([], 0, criar)):
            return downloader.baixar("https://example.org/v", "mp3",
                                     contexto=contexto), config

    def test_sem_contexto_usa_o_nome_do_arquivo(self):
        resultado, config = self._baixar(None)
        self.assertEqual(resultado.caminho.name, "Queen - Bohemian Rhapsody.mp3")
        self.assertTrue(os.path.samefile(resultado.caminho.parent, config.musicas))

    def test_contexto_da_pesquisa_da_nome_artista_titulo(self):
        contexto = ContextoMidia(titulo="Bohemian Rhapsody (Official Video)",
                                 canal="QueenVEVO")
        resultado, _ = self._baixar(contexto)
        # O nome organizado vem do nome do arquivo (tem separador) — e nunca
        # contém o ID do vídeo entre colchetes.
        self.assertEqual(resultado.caminho.name, "Queen - Bohemian Rhapsody.mp3")
        self.assertNotIn("[", resultado.caminho.name)

    def test_titulo_sem_separador_usa_o_canal_como_artista(self):
        contexto = ContextoMidia(titulo="Bohemian Rhapsody", canal="Queen Official")
        resultado, _ = self._baixar(contexto, nome_ytdlp="Bohemian Rhapsody [dQw4w9WgXcQ].mp3")
        # "Queen Official" vira "Queen": o sufixo é do canal, não do artista.
        self.assertEqual(resultado.caminho.name,
                         "Queen - Bohemian Rhapsody.mp3")

    def test_nome_organizado_ignorado_quando_desligado(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        config = ConfigComOrganizacao(Path(temp.name))
        config.organizar_nomes = False  # type: ignore[misc]
        downloader = Downloader(config)  # type: ignore[arg-type]
        nome = "Queen - Bohemian Rhapsody [dQw4w9WgXcQ].mp3"

        def criar(argv):
            if "--skip-download" in argv:
                return
            pasta = Path(argv[argv.index("--paths") + 1])
            (pasta / nome).write_bytes(b"\xff\xfb\x90\x00" + b"\x00" * 64)

        with patch("downloader.subprocess.Popen", Processo([], 0, criar)):
            resultado = downloader.baixar("https://example.org/v", "mp3")
        self.assertEqual(resultado.caminho.name, nome)

    def test_colisao_nao_sobrescreve_com_nome_organizado(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        config = ConfigComOrganizacao(Path(temp.name))
        config.sobrescrita = "renomear"
        existente = config.musicas / "Queen - Bohemian Rhapsody.mp3"
        config.preparar_diretorios()
        existente.write_bytes(b"original")
        downloader = Downloader(config)  # type: ignore[arg-type]
        nome = "Queen - Bohemian Rhapsody [dQw4w9WgXcQ].mp3"

        def criar(argv):
            if "--skip-download" in argv:
                return
            pasta = Path(argv[argv.index("--paths") + 1])
            (pasta / nome).write_bytes(b"\xff\xfb\x90\x00" + b"\x00" * 64)

        with patch("downloader.subprocess.Popen", Processo([], 0, criar)):
            resultado = downloader.baixar("https://example.org/v", "mp3")
        self.assertEqual(resultado.caminho.name, "Queen - Bohemian Rhapsody (2).mp3")
        self.assertEqual(existente.read_bytes(), b"original")


class TestOrganizacaoPorAlbum(unittest.TestCase):
    """Movimentação para Artista/Álbum só com dados confirmados."""

    def _app(self, resumo):  # noqa: ANN001
        from configuracoes import Configuracoes
        from musica import Aplicacao

        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        config = Configuracoes(raiz=Path(temp.name))
        config = config.__class__(**{**config.__dict__, "organizar_por_album": True})
        app = Aplicacao(config)
        # Contrato atual: o adaptador expõe `processador_real` (antes o teste
        # montava apenas `_processador`, atributo privado).
        app.metadados = SimpleNamespace(
            _processador=SimpleNamespace(ultimo_resumo=resumo),
            processador_real=SimpleNamespace(ultimo_resumo=resumo),
        )  # type: ignore[assignment]
        config.preparar_diretorios()
        return app, config

    def test_move_para_artista_album(self):
        app, config = self._app({"artista": "Queen", "album": "A Night at the Opera"})
        arquivo = config.musicas / "Queen - Bohemian Rhapsody.mp3"
        arquivo.write_bytes(b"x")
        destino = app._organizar_em_subpasta(arquivo, "mp3")
        # No Windows o temp pode vir como RUNNER~1 (8.3): comparar por arquivo.
        self.assertTrue(os.path.samefile(
            destino.parent, config.musicas / "Queen" / "A Night at the Opera"))
        self.assertTrue(destino.is_file())
        self.assertFalse(arquivo.exists())

    def test_sem_album_nao_move(self):
        app, config = self._app({"artista": "", "album": None})
        arquivo = config.musicas / "faixa.mp3"
        arquivo.write_bytes(b"x")
        self.assertEqual(app._organizar_em_subpasta(arquivo, "mp3"), arquivo)

    def test_nao_move_video_nem_quando_desligado(self):
        app, config = self._app({"artista": "Queen", "album": "ANATO"})
        video = config.videos / "clipe.mp4"
        video.write_bytes(b"x")
        self.assertEqual(app._organizar_em_subpasta(video, "mp4"), video)

    def test_colisao_nao_sobrescreve(self):
        app, config = self._app({"artista": "Queen", "album": "ANATO"})
        pasta = config.musicas / "Queen" / "ANATO"
        pasta.mkdir(parents=True)
        (pasta / "faixa.mp3").write_bytes(b"antigo")
        novo = config.musicas / "faixa.mp3"
        novo.write_bytes(b"novo")
        destino = app._organizar_em_subpasta(novo, "mp3")
        self.assertEqual(destino.name, "faixa (2).mp3")
        self.assertEqual((pasta / "faixa.mp3").read_bytes(), b"antigo")


class TestLimpezaDeNome(unittest.TestCase):
    """Casos encontrados em teste real com ffmpeg + yt-dlp."""

    def test_ruido_de_publicacao_sai_do_nome(self):
        from downloader import Downloader

        d = Downloader.__new__(Downloader)
        nome = "Queen - Bohemian Rhapsody (Official Video) " \
               "[2sQ7n1uVbDA].mp3"
        self.assertEqual(d._nome_organizado(Path(nome)),
                         "Queen - Bohemian Rhapsody.mp3")

    def test_cauda_com_titulo_repetido_sai(self):
        from downloader import Downloader

        d = Downloader.__new__(Downloader)
        nome = ("Queen - Bohemian Rhapsody (Official Video) "
                "[Queen - Bohemian Rhapsody (Official Video)].mp3")
        self.assertEqual(d._nome_organizado(Path(nome)),
                         "Queen - Bohemian Rhapsody.mp3")

    def test_tags_de_versao_ficam(self):
        from downloader import Downloader

        d = Downloader.__new__(Downloader)
        for entrada, esperado in (
            ("Song [Remix].mp3", "Song Remix.mp3"),
            ("Faixa [Ao Vivo].mp3", "Faixa Ao Vivo.mp3"),
        ):
            self.assertEqual(d._nome_organizado(Path(entrada)), esperado)

    def test_contexto_com_canal_vevo_nao_duplica_artista(self):
        from downloader import Downloader

        d = Downloader.__new__(Downloader)
        contexto = ContextoMidia(titulo="Bohemian Rhapsody (Official Video)",
                                canal="QueenVEVO")
        self.assertEqual(d._nome_organizado(Path("Song [abc123def].mp3"), contexto),
                         "Queen - Song.mp3")


class TestCookiesNaPasta(unittest.TestCase):
    """Quem baixa cookies.txt do navegador costuma deixá-lo na pasta do app."""

    def _status(self, montar):
        from configuracoes import Configuracoes
        from cookies_youtube import status

        dados = tempfile.TemporaryDirectory()
        self.addCleanup(dados.cleanup)
        os.environ["BAIXADOR_DATA_DIR"] = dados.name
        self.addCleanup(os.environ.pop, "BAIXADOR_DATA_DIR", None)
        antigo = os.environ.pop("BAIXADOR_COOKIES", None)
        if antigo is not None:
            self.addCleanup(os.environ.__setitem__, "BAIXADOR_COOKIES", antigo)
        raiz = Path(tempfile.mkdtemp())
        self.addCleanup(__import__("shutil").rmtree, raiz, True)
        montar(raiz)
        config = Configuracoes(raiz=raiz)
        return config, status(config)

    def test_cookies_solto_na_pasta_do_programa_e_aceito(self):
        from configuracoes import argumentos_cookies

        def montar(raiz):
            (raiz / "cookies.txt").write_text(
                "# Netscape HTTP Cookie File\n"
                ".youtube.com\tTRUE\t/\tTRUE\t1999999999\tSID\tabc\n",
                encoding="utf-8")

        config, info = self._status(montar)
        self.assertTrue(info.configurado)
        self.assertTrue(info.valido)
        self.assertIn("--cookies", argumentos_cookies(config))

    def test_arquivo_invalido_nao_e_aceito_em_silencio(self):
        def montar(raiz):
            (raiz / "cookies.txt").write_text("lixo\nqualquer\n", encoding="utf-8")

        _, info = self._status(montar)
        self.assertTrue(info.configurado)
        self.assertFalse(info.valido)
        self.assertIn("Formato incompatível", info.mensagem)

    def test_sem_cookies_nao_passa_a_flag(self):
        from configuracoes import argumentos_cookies

        config, info = self._status(lambda raiz: None)
        self.assertFalse(info.configurado)
        self.assertEqual(argumentos_cookies(config), [])


class TestCookiesVencidos(unittest.TestCase):
    """Cookies expirados são a causa nº 1 de 'importei e continuou pedindo login'."""

    def _texto(self, expira_youtube, expira_google=None, agora=None):
        import time

        base = int(time.time()) if agora is None else int(agora)
        linhas = ["# Netscape HTTP Cookie File"]
        for i, expira in enumerate(expira_youtube):
            linhas.append(f".youtube.com\tTRUE\t/\tTRUE\t{base + expira}\tSID{i}\tv")
        if expira_google is not None:
            linhas.append(f".google.com\tTRUE\t/\tTRUE\t{base + expira_google}\tNID\tv")
        return "\n".join(linhas) + "\n"

    def test_conta_vencidos(self):
        from cookies_youtube import contar_vencidos

        texto = self._texto([-86400, -100, 86400])
        self.assertEqual(contar_vencidos(texto), (2, 2))

    def test_cookie_de_sessao_nao_conta_como_vencido(self):
        from cookies_youtube import contar_vencidos

        texto = ".youtube.com\tTRUE\t/\tTRUE\t0\tSID\tv\n"
        self.assertEqual(contar_vencidos(texto), (0, 0))

    def test_status_avisa_quando_tudo_venceu(self):
        from configuracoes import Configuracoes
        from cookies_youtube import status

        raiz = Path(tempfile.mkdtemp())
        self.addCleanup(__import__("shutil").rmtree, raiz, True)
        raiz.joinpath("cookies.txt").write_text(self._texto([-5000], -5000),
                                                encoding="utf-8")
        dados = tempfile.TemporaryDirectory()
        self.addCleanup(dados.cleanup)
        os.environ["BAIXADOR_DATA_DIR"] = dados.name
        self.addCleanup(os.environ.pop, "BAIXADOR_DATA_DIR", None)

        info = status(Configuracoes(raiz=raiz))
        self.assertTrue(info.valido)  # formato bom; o problema é a validade
        self.assertEqual(info.expirados_do_youtube, 2)
        self.assertIn("venceram", info.mensagem)

    def test_status_sem_vencimento_diz_que_esta_pronto(self):
        from configuracoes import Configuracoes
        from cookies_youtube import status

        raiz = Path(tempfile.mkdtemp())
        self.addCleanup(__import__("shutil").rmtree, raiz, True)
        raiz.joinpath("cookies.txt").write_text(self._texto([86400]),
                                                encoding="utf-8")
        dados = tempfile.TemporaryDirectory()
        self.addCleanup(dados.cleanup)
        os.environ["BAIXADOR_DATA_DIR"] = dados.name
        self.addCleanup(os.environ.pop, "BAIXADOR_DATA_DIR", None)

        info = status(Configuracoes(raiz=raiz))
        self.assertEqual(info.expirados_do_youtube, 0)
        self.assertIn("pronto", info.mensagem)


class TestRelatoDaIdentificacao(unittest.TestCase):
    """O usuário precisa saber o que foi confirmado e o que faltou."""

    def _app(self, resumo):
        from configuracoes import Configuracoes
        from musica import Aplicacao

        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        app = Aplicacao(Configuracoes(raiz=Path(temp.name)))
        app.metadados = SimpleNamespace(
            _processador=SimpleNamespace(ultimo_resumo=resumo),
            processador_real=SimpleNamespace(ultimo_resumo=resumo),
        )  # type: ignore[assignment]
        return app

    def test_tudo_confirmado_nao_gera_aviso(self):
        app = self._app({"identificado": True, "album": "ANATO", "ano": 1975,
                         "genero": "Rock", "capa_incorporada": True,
                         "campos_confirmados": ["album", "ano", "genero"],
                         "provedores_com_erro": []})
        texto = app._relato_da_identificacao()
        self.assertIn("Identificado", texto)
        self.assertIn("Capa incorporada", texto)

    def test_sem_confirmacao_diz_que_usa_so_o_video(self):
        app = self._app({"identificado": False, "campos_confirmados": [],
                         "capa_incorporada": False, "provedores_com_erro": []})
        texto = app._relato_da_identificacao()
        self.assertIn("Não confirmado", texto)
        self.assertIn("título e o canal do vídeo", texto)
        self.assertIn("Sem capa", texto)

    def test_apis_fora_do_ar_sao_nomeadas(self):
        app = self._app({"identificado": False, "campos_confirmados": [],
                         "provedores_com_erro": ["itunes: timeout",
                                                 "deezer: rede"]})
        texto = app._relato_da_identificacao()
        self.assertIn("itunes", texto)
        self.assertIn("deezer", texto)

    def test_sem_resumo_nao_quebra(self):
        app = self._app({})
        self.assertEqual(app._relato_da_identificacao(), "")


class TestContextoMidia(unittest.TestCase):
    def test_a_partir_de_resultado_de_pesquisa(self):
        resultado = SimpleNamespace(titulo="Faixa", canal="Canal", duracao=210,
                                    thumbnail="https://x/t.jpg", url="https://x/v")
        contexto = ContextoMidia.de_resultado(resultado)
        self.assertEqual(contexto.titulo, "Faixa")
        self.assertEqual(contexto.duracao, 210)
        self.assertEqual(contexto.como_metadados()["canal"], "Canal")

    def test_normaliza_dicionario_string_e_none(self):
        self.assertEqual(ContextoMidia.normalizar({"titulo": "T"}).titulo, "T")
        self.assertEqual(ContextoMidia.normalizar("https://x/v").url, "https://x/v")
        self.assertEqual(ContextoMidia.normalizar(None).como_metadados(), {})

    def test_metadados_nao_incluem_campos_vazios(self):
        dados = ContextoMidia(titulo="T").como_metadados()
        self.assertEqual(set(dados), {"titulo"})


class TestDiagnostico(unittest.TestCase):
    def test_classifica_situacoes_reais_do_ytdlp(self):
        casos = {
            "ERROR: [youtube] x: Sign in to confirm your age": "restricao_idade",
            "ERROR: [youtube] x: Private video": SITUACAO_PRIVADO,
            "ERROR: HTTP Error 404: File not found": SITUACAO_NAO_ENCONTRADO,
            "ERROR: TLS/SSL connection has been closed": SITUACAO_REDE,
            "ERROR: The provided cookies are no longer valid": SITUACAO_COOKIES_VENCIDOS,
            "[download] arquivo.mp3 has already been downloaded": SITUACAO_JA_EXISTE,
            "ERROR: Please sign in to continue": SITUACAO_LOGIN,
            "mensagem totalmente nova": SITUACAO_OUTRO,
        }
        for mensagem, esperado in casos.items():
            with self.subTest(mensagem=mensagem):
                self.assertEqual(classificar(mensagem).situacao, esperado)

    def test_mensagem_para_o_usuario_e_em_portugues_e_tem_acao(self):
        diagnostico = classificar("ERROR: HTTP Error 404: File not found")
        self.assertIn("não existe", diagnostico.explicacao)
        self.assertTrue(diagnostico.acao)

    def test_sanitiza_credenciais(self):
        texto = sanitizar("https://x/v?token=SEGREDO&cookie=abc123 e Bearer xyz.123")
        self.assertNotIn("SEGREDO", texto)
        self.assertNotIn("abc123", texto)
        self.assertNotIn("xyz.123", texto)

    def test_dica_considera_se_ja_existem_cookies(self):
        login = classificar("ERROR: Please sign in to continue")
        sem = dica_para_interface(login, cookies_configurados=False)
        com = dica_para_interface(login, cookies_configurados=True)
        self.assertIn("ainda não importou", sem)
        self.assertIn("não funcionar mais", com)

    def test_historico_nunca_grava_token(self):
        from configuracoes import Configuracoes
        from historico import Historico

        with tempfile.TemporaryDirectory() as temp:
            config = Configuracoes(raiz=Path(temp))
            historico = Historico(config)
            historico.registrar(
                url="https://x/v?token=SEGREDO123",
                formato="mp3", status="erro",
                mensagem="falhou com sig=ASSINATURA e Authorization=Bearer chave")
            historico.listar(5, incluir_erros=True)
            bruto = config.erros.read_text(encoding="utf-8")
            for segredo in ("SEGREDO123", "ASSINATURA", "Bearer chave"):
                self.assertNotIn(segredo, bruto)


if __name__ == "__main__":
    unittest.main()
