"""Chave de IA por arquivo (api.txt) e identificação musical com os 6 campos."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import api_ia
import identificacao_ia
from api_ia import ErroChave, extrair_chave, mascarar
from configuracoes import Configuracoes
from identificacao_ia import (
    GENEROS_REFERENCIA, Identificacao, IdentificadorIA, aplicar_na_info,
    ESQUEMA_RESPOSTA, interpretar_resposta, montar_prompt,
    normalizar_genero, validar_resposta,
)
from inteligencia import ErroAPI, InfoMusica


class TestImportacaoDaChave(unittest.TestCase):
    """Mesmo comportamento do cookies.txt: valida, copia, renomeia p/ api.txt."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.raiz = Path(self.temp.name)
        self.dados = tempfile.TemporaryDirectory()
        self.addCleanup(self.dados.cleanup)
        self.addCleanup(os.environ.pop, "BAIXADOR_DATA_DIR", None)
        self.addCleanup(os.environ.pop, "BAIXADOR_IA_API_KEY", None)
        os.environ["BAIXADOR_DATA_DIR"] = self.dados.name
        os.environ.pop("BAIXADOR_IA_API_KEY", None)
        self.config = Configuracoes(raiz=self.raiz)

    # -- formatos aceitos ---------------------------------------------------
    def test_reconhece_formatos_comuns(self):
        casos = {
            "sk-proj-abcdefghijklmnop123456": "openai",
            "api_key=sk-proj-ZZZZabcdefghij1234": "openai",
            "OPENAI_API_KEY: sk-abcdef1234567890": "openai",
            'export OPENAI_API_KEY="sk-abcdef1234567890"': "openai",
            "# minha chave\nsk-abcdef1234567890  # colada do site": "openai",
            '{"api_key": "sk-abcdef1234567890"}': "openai",
            "gsk_abcdefghijklmnopqrstuvwx": "groq",
        }
        for texto, provedor in casos.items():
            with self.subTest(texto=texto):
                chave, achado = extrair_chave(texto)
                self.assertTrue(chave.startswith(("sk-", "gsk_")), chave)
                self.assertEqual(achado, provedor)

    def test_recusa_texto_sem_chave(self):
        for texto in ("", "minha senha do banco", "https://api.openai.com/v1",
                      "# só comentário"):
            with self.subTest(texto=texto):
                with self.assertRaises(ErroChave):
                    extrair_chave(texto)

    # -- arquivo escolhido --------------------------------------------------
    def test_importa_arquivo_com_nome_diferente_e_renomeia_copia(self):
        origem = self.raiz / "minha chave da openai.txt"
        origem.write_text("OPENAI_API_KEY=sk-teste-1234567890abcdef\n",
                          encoding="utf-8")
        info = api_ia.importar(origem, self.config)
        self.assertTrue(info.valida)
        self.assertTrue(info.renomeado)
        self.assertEqual(info.nome_original, "minha chave da openai.txt")
        self.assertEqual(info.caminho.name, "api.txt")
        # A cópia guarda só a chave, não o arquivo inteiro.
        self.assertEqual(info.caminho.read_text(encoding="utf-8").strip(),
                         "sk-teste-1234567890abcdef")
        # No Windows o temp vem como RUNNER~1: comparar pelos diretórios reais,
        # não por prefixo de texto (o mesmo erro já apareceu antes no CI).
        self.assertTrue(os.path.samefile(info.caminho.parent, self.dados.name))

    def test_arquivo_api_txt_nao_e_marcado_como_renomeado(self):
        origem = self.raiz / "api.txt"
        origem.write_text("sk-teste-1234567890abcdef\n", encoding="utf-8")
        info = api_ia.importar(origem, self.config)
        self.assertFalse(info.renomeado)

    def test_nao_aceita_arquivo_invalido(self):
        origem = self.raiz / "errado.txt"
        origem.write_text("nada a ver\n", encoding="utf-8")
        with self.assertRaises(ErroChave):
            api_ia.importar(origem, self.config)
        self.assertFalse(api_ia.caminho_destino(self.config).exists())

    def test_arquivo_grande_demais_e_recusado(self):
        origem = self.raiz / "grande.txt"
        origem.write_bytes(b"x" * (api_ia.TAMANHO_MAXIMO + 1))
        with self.assertRaises(ErroChave):
            api_ia.importar(origem, self.config)

    # -- status/leitura -----------------------------------------------------
    def test_status_sem_chave(self):
        info = api_ia.status(self.config)
        self.assertFalse(info.configurada)
        self.assertIn("opcional", info.mensagem)

    def test_status_com_chave_mascarada(self):
        origem = self.raiz / "c.txt"
        origem.write_text("sk-teste-1234567890abcdef\n", encoding="utf-8")
        api_ia.importar(origem, self.config)
        info = api_ia.status(self.config)
        self.assertTrue(info.configurada)
        self.assertTrue(info.valida)
        self.assertNotIn("1234567890", info.mascarada)
        self.assertTrue(info.mascarada.endswith("cdef"))
        self.assertEqual(info.provedor, "openai")

    def test_status_de_arquivo_invalido_explica(self):
        api_ia.caminho_destino(self.config).parent.mkdir(parents=True, exist_ok=True)
        api_ia.caminho_destino(self.config).write_text("lixo\n", encoding="utf-8")
        info = api_ia.status(self.config)
        self.assertFalse(info.valida)
        self.assertIn("Nenhuma chave reconhecível", info.mensagem)

    def test_api_txt_na_pasta_do_programa_tambem_vale(self):
        (self.raiz / "api.txt").write_text("sk-teste-1234567890abcdef\n",
                                           encoding="utf-8")
        self.assertEqual(api_ia.ler_chave(self.config), "sk-teste-1234567890abcdef")
        self.assertTrue(api_ia.status(self.config).configurada)

    def test_remover_apaga_e_volta_ao_estado_sem_chave(self):
        origem = self.raiz / "c.txt"
        origem.write_text("sk-teste-1234567890abcdef\n", encoding="utf-8")
        api_ia.importar(origem, self.config)
        self.assertTrue(api_ia.remover(self.config))
        self.assertEqual(api_ia.ler_chave(self.config), "")
        self.assertFalse(api_ia.remover(self.config))

    def test_mascara_nunca_mostra_a_chave_inteira(self):
        self.assertEqual(mascarar(""), "")
        self.assertNotIn("abcdef", mascarar("sk-abcdefghijklmnop"))


class TestPromptEParsing(unittest.TestCase):
    def test_prompt_tem_os_seis_campos_e_a_lista_de_generos(self):
        prompt = montar_prompt("Tempo Perdido", "Legião Urbana")
        for campo in ("Título", "Artista", "Álbum", "Ano", "Gênero",
                      "Número da faixa"):
            self.assertIn(campo, prompt)
        for genero in ("Hard Rock", "Sertanejo", "Bossa Nova", "Neo Soul",
                       "Psytrance", "Bebop"):
            self.assertIn(genero, prompt)
        self.assertIn("NUNCA invente", prompt)
        self.assertIn("Não identificado", prompt)

    def test_lista_de_generos_cobre_as_familias_pedidas(self):
        texto = " ".join(GENEROS_REFERENCIA).lower()
        for familia in ("rock", "metal", "pop", "electronic", "hip-hop", "r&b",
                        "blues", "jazz", "folk", "country", "reggae", "salsa",
                        "samba", "mpb", "sertanejo", "classical", "opera",
                        "gospel", "soundtrack"):
            self.assertIn(familia, texto)

    def test_interpreta_json_puro(self):
        resultado = interpretar_resposta(json.dumps({
            "titulo": "Tempo Perdido", "artista": "Legião Urbana",
            "album": "Dois", "ano": "1986", "genero": "Rock; Pós-Punk",
            "faixa": "2"}, ensure_ascii=False))
        self.assertEqual(resultado.ano, 1986)
        self.assertEqual(resultado.faixa, 2)
        self.assertEqual(resultado.genero, "Rock, Pós-Punk")
        self.assertEqual(resultado.ausentes, ())
        linhas = dict(resultado.como_linhas())
        self.assertEqual(list(linhas), ["Título", "Artista", "Álbum", "Ano",
                                        "Gênero", "Número da faixa"])

    def test_interpreta_json_dentro_de_texto_e_craseras(self):
        for texto in ('```json\n{"titulo":"X","artista":"Y"}\n```',
                      'Aqui está:\n{"titulo":"X","artista":"Y"}\nFim.'):
            with self.subTest(texto=texto):
                resultado = interpretar_resposta(texto)
                self.assertEqual(resultado.titulo, "X")

    def test_nao_identificado_vira_campo_vazio(self):
        resultado = interpretar_resposta(json.dumps({
            "titulo": "X", "artista": "Y", "album": "Não identificado",
            "ano": "Não identificado", "genero": "Não identificado",
            "faixa": "0"}))
        self.assertEqual(resultado.album, "")
        self.assertIsNone(resultado.ano)
        self.assertEqual(resultado.genero, "")
        self.assertIsNone(resultado.faixa)
        self.assertIn("álbum", resultado.ausentes)

    def test_resposta_invalida_nao_estoura(self):
        for texto in ("", "nada", '{"foo": 1}', "[]"):
            with self.subTest(texto=texto):
                self.assertIsNone(interpretar_resposta(texto))

    def test_genero_normaliza_e_limita_a_tres(self):
        self.assertEqual(normalizar_genero("rock / hard rock"), "Rock, Hard Rock")
        self.assertEqual(normalizar_genero("Rock (Hard Rock)"), "Hard Rock")
        self.assertEqual(normalizar_genero("a; b; c; d; e"), "a, b, c")
        self.assertEqual(normalizar_genero("sertanejo universitário"),
                         "sertanejo universitário")


class TestIdentificadorIA(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config = Configuracoes(raiz=Path(self.temp.name))

    def _cliente(self, resposta=None, erro=None):
        class Cliente:
            def __init__(self):
                self.chamadas = []

            def post_json(self, url, payload, headers=None):
                self.chamadas.append((url, payload, headers))
                if erro is not None:
                    raise erro
                return resposta
        return Cliente()

    def test_sem_chave_nao_chama_api(self):
        identificador = IdentificadorIA(api_key="", config=self.config)
        self.assertFalse(identificador.disponivel)
        self.assertIsNone(identificador.identificar("X"))
        self.assertIn("api.txt", identificador.ultimo_erro)

    def test_identifica_e_usa_bearer_com_a_chave(self):
        cliente = self._cliente(resposta={"choices": [{"message": {
            "content": '{"titulo":"Tempo Perdido","artista":"Legião Urbana",'
                       '"album":"Dois","ano":"1986","genero":"MPB","faixa":"2"}'}}]})
        identificador = IdentificadorIA(cliente=cliente, api_key="sk-teste-123",
                                        config=self.config)
        resultado = identificador.identificar("Tempo Perdido", "Legião Urbana")
        self.assertEqual(resultado.album, "Dois")
        url, payload, headers = cliente.chamadas[0]
        self.assertEqual(headers["Authorization"], "Bearer sk-teste-123")
        self.assertIn("MÚSICA A IDENTIFICAR: Tempo Perdido",
                      payload["messages"][0]["content"])
        self.assertEqual(payload["temperature"], 0)

    def test_erro_401_vira_mensagem_clara_sem_vazar_chave(self):
        cliente = self._cliente(erro=ErroAPI("HTTP 401 Unauthorized"))
        identificador = IdentificadorIA(cliente=cliente,
                                        api_key="sk-segredo-123", config=self.config)
        self.assertIsNone(identificador.identificar("X"))
        self.assertIn("401", identificador.ultimo_erro)
        self.assertNotIn("sk-segredo-123", identificador.ultimo_erro)

    def test_erro_de_rede_e_traduzido(self):
        cliente = self._cliente(erro=ErroAPI("urlopen error TLS handshake"))
        identificador = IdentificadorIA(cliente=cliente, api_key="sk-teste-123",
                                        config=self.config)
        identificador.identificar("X")
        self.assertIn("rede", identificador.ultimo_erro)

    def test_resposta_sem_campos_avisa(self):
        cliente = self._cliente(resposta={"choices": [{"message": {"content": ""}}]})
        identificador = IdentificadorIA(cliente=cliente, api_key="sk-teste-123",
                                        config=self.config)
        self.assertIsNone(identificador.identificar("X"))
        self.assertIn("campos", identificador.ultimo_erro)

    def test_testar_conexao(self):
        ok = IdentificadorIA(cliente=self._cliente(resposta={"choices": []}),
                             api_key="sk-teste-123", config=self.config)
        self.assertTrue(ok.testar_conexao()[0])
        ruim = IdentificadorIA(cliente=self._cliente(erro=ErroAPI("HTTP 401")),
                               api_key="sk-teste-123", config=self.config)
        self.assertFalse(ruim.testar_conexao()[0])


class TestPrioridadeDosDados(unittest.TestCase):
    """Fato de API nunca é sobrescrito pela IA."""

    def test_ia_so_preenche_campos_vazios(self):
        info = InfoMusica(titulo="Tempo Perdido", artista="Legião Urbana",
                          album="Dois", fonte="itunes", confianca=0.9)
        identificacao = Identificacao(titulo="Outro", artista="Outro",
                                      album="Outro álbum", ano=1986,
                                      genero="MPB", faixa=2)
        preenchidos = aplicar_na_info(info, identificacao)
        self.assertEqual(info.album, "Dois")          # API manda
        self.assertEqual(info.titulo, "Tempo Perdido")
        self.assertEqual(info.ano, 1986)               # lacuna preenchida
        self.assertEqual(sorted(preenchidos), ["ano", "faixa", "genero"])
        self.assertIn("ia", info.fonte)

    def test_sem_nada_preenchido_nao_mexe_na_fonte(self):
        info = InfoMusica(titulo="T", artista="A", fonte="deezer")
        preenchidos = aplicar_na_info(info, Identificacao())
        self.assertEqual(preenchidos, [])
        self.assertEqual(info.fonte, "deezer")


class TestIntegracaoNoProcessamento(unittest.TestCase):
    """metadados.py usa a IA quando há chave e deixa claro de onde veio."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.raiz = Path(self.temp.name)
        dados = tempfile.TemporaryDirectory()
        self.addCleanup(dados.cleanup)
        os.environ["BAIXADOR_DATA_DIR"] = dados.name
        self.addCleanup(os.environ.pop, "BAIXADOR_DATA_DIR", None)
        self.addCleanup(os.environ.pop, "BAIXADOR_IA_API_KEY", None)
        os.environ.pop("BAIXADOR_IA_API_KEY", None)
        self.config = Configuracoes(raiz=self.raiz)
        # A chave vem do processador recem-criado, nao do ambiente global:
        # outro teste pode ter deixado BAIXADOR_IA_API_KEY vazio.
        os.environ["BAIXADOR_IA_API_KEY"] = "sk-teste-1234567890abcdef"

    def _processador(self, identificacao):
        from metadados import ConfigMetadados

        class Identificador:
            ultimos_erros: list[str] = []

            def identificar(self, *_a, **_k):
                return None  # APIs públicas sem resposta

        class Gerenciador:
            def buscar_e_baixar(self, *_a, **_k):
                return None

        from metadados import ProcessadorMusical

        processador = ProcessadorMusical(
            identificador=Identificador(), gerenciador_capas=Gerenciador(),
            config=ConfigMetadados(buscar_capa=False, usar_ia=True))
        processador._config_nucleo = self.config

        class IdentificadorFalso:
            ultimo_erro = ""

            def identificar(self, consulta, canal=""):
                return identificacao

        # patch fica no teste (o `with` dentro do helper sairia de escopo
        # antes da chamada a processar_mp3).
        self._falso = IdentificadorFalso()
        return processador

    def test_ia_preenche_tags_do_mp3_real(self):
        from metadados import ler_metadados
        try:
            import mutagen  # noqa: F401
        except ImportError:  # pragma: no cover
            self.skipTest("mutagen indisponível")
        del mutagen
        mp3 = self.raiz / "faixa.mp3"
        mp3.write_bytes(_mp3_minimo())
        identificacao = Identificacao(
            titulo="Tempo Perdido", artista="Legião Urbana", album="Dois",
            ano=1986, genero="Rock, Pós-Punk, MPB", faixa=2)
        processador = self._processador(identificacao)
        with patch.object(identificacao_ia, "criar_identificador",
                          return_value=self._falso):
            processador.processar_mp3(
                mp3, {"url": "https://youtu.be/x",
                      "titulo": "Legiao Urbana - Tempo Perdido"})
        lidos = ler_metadados(mp3)
        self.assertEqual(lidos["album"], "Dois")
        self.assertEqual(lidos["genero"], "Rock, Pós-Punk, MPB")
        self.assertEqual(lidos["faixa"], "2")
        self.assertEqual(lidos["ano"], "1986")
        self.assertTrue(processador.ultimo_resumo["ia_usada"])
        self.assertIn("ia", processador.ultimo_resumo["fonte"])


def _mp3_minimo() -> bytes:
    """Pequeno MP3 válido para o Mutagen conseguir gravar tags."""
    silencio = b"\xff\xfb\x90\x00" + b"\x00" * 100
    return silencio * 40


if __name__ == "__main__":  # pragma: no cover
    unittest.main()


class TestJsonDaIAValidado(unittest.TestCase):
    """A resposta da IA é conferida antes de virar tag — JSON torto não passa."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config = Configuracoes(raiz=Path(self.temp.name))

    def _cliente(self, respostas):
        """Cliente que devolve respostas em sequência (última se repetir)."""
        class Cliente:
            def __init__(self):
                self.chamadas = []

            def post_json(self, url, payload, headers=None):
                self.chamadas.append((url, payload, headers))
                item = respostas[min(len(self.chamadas) - 1, len(respostas) - 1)]
                if isinstance(item, Exception):
                    raise item
                return item
        return Cliente()

    @staticmethod
    def _resposta(conteudo):
        return {"choices": [{"message": {"content": conteudo}}]}

    def test_pede_json_estruturado(self):
        cliente = self._cliente([self._resposta('{"titulo":"X","artista":"Y"}')])
        IdentificadorIA(cliente=cliente, api_key="sk-1",
                        config=self.config).identificar("X")
        formato = cliente.chamadas[0][1]["response_format"]
        self.assertEqual(formato["type"], "json_schema")
        self.assertEqual(formato["json_schema"]["schema"]["required"],
                         ["titulo", "artista", "album", "ano", "genero", "faixa"])

    def test_provedor_sem_response_format_e_repetido_sem_ele(self):
        """Provedor que recusa o formato: a segunda chamada não pode falhar."""
        cliente = self._cliente([
            ErroAPI("HTTP 400 invalid response_format"),
            self._resposta('{"titulo":"X","artista":"Y","album":"A"}'),
        ])
        identificador = IdentificadorIA(cliente=cliente, api_key="sk-1",
                                        config=self.config)
        resultado = identificador.identificar("X")
        self.assertIsNotNone(resultado, identificador.ultimo_erro)
        self.assertEqual(resultado.album, "A")
        self.assertEqual(len(cliente.chamadas), 2)
        self.assertNotIn("response_format", cliente.chamadas[1][1])

    def test_erro_400_sem_json_tambem_cai_para_prompt(self):
        cliente = self._cliente([
            ErroAPI("HTTP 400 response_format json_schema unsupported"),
            self._resposta("Aqui está: {\"titulo\":\"X\",\"artista\":\"Y\"}"),
        ])
        resultado = IdentificadorIA(cliente=cliente, api_key="sk-1",
                                    config=self.config).identificar("X")
        self.assertIsNotNone(resultado)

    def test_erro_de_rede_nao_repete_chamada(self):
        cliente = self._cliente([ErroAPI("urlopen error timed out")])
        identificador = IdentificadorIA(cliente=cliente, api_key="sk-1",
                                        config=self.config)
        self.assertIsNone(identificador.identificar("X"))
        self.assertEqual(len(cliente.chamadas), 1)

    def test_lista_valores_e_objetos_sao_recusados(self):
        for conteudo in ('{"titulo":["a","b"],"artista":"Y"}',
                         '{"genero":{"a":1},"titulo":"X","artista":"Y"}',
                         '[]', '"texto"', 'null'):
            with self.subTest(conteudo=conteudo):
                identificador = IdentificadorIA(
                    cliente=self._cliente([self._resposta(conteudo)]),
                    api_key="sk-1", config=self.config)
                self.assertIsNone(identificador.identificar("X"))

    def test_chaves_desconhecidas_sem_campos_pedidos_avisam(self):
        identificador = IdentificadorIA(
            cliente=self._cliente([self._resposta('{"resposta":"não sei"}')]),
            api_key="sk-1", config=self.config)
        self.assertIsNone(identificador.identificar("X"))
        self.assertIn("não tem nenhum dos campos", identificador.ultimo_erro)

    def test_chaves_extras_junto_com_campos_validos_sao_ignoradas(self):
        identificador = IdentificadorIA(
            cliente=self._cliente([self._resposta(
                '{"titulo":"X","artista":"Y","confianca":0.9,"obs":"ok"}')]),
            api_key="sk-1", config=self.config)
        resultado = identificador.identificar("X")
        self.assertEqual(resultado.titulo, "X")

    def test_validar_resposta_direto(self):
        limpos, motivo = validar_resposta({"titulo": "X", "artista": "Y"})
        self.assertEqual(limpos, {"titulo": "X", "artista": "Y"})
        self.assertEqual(motivo, "")
        self.assertEqual(validar_resposta({})[1], "A resposta veio vazia.")
        self.assertIn("objeto JSON", validar_resposta([1, 2])[1])

    def test_esquema_nao_aceita_campo_extra(self):
        self.assertFalse(ESQUEMA_RESPOSTA["additionalProperties"])
        self.assertEqual(len(ESQUEMA_RESPOSTA["properties"]), 6)
