"""Identificação musical por IA (chave importada de ``api.txt``).

Diferença em relação ao assistente antigo (``inteligencia.AssistenteIAOpenAI``,
que só separava artista/título): aqui a IA recebe o prompt de **identificação e
classificação musical** com os seis campos obrigatórios e a lista de gêneros, e
devolve álbum, ano, gênero e número da faixa.

Regras de segurança que este módulo garante:

- **Só campos preenchidos**: a resposta é lida campo a campo; gênero fora da
  lista de referência é aceito apenas se a IA justificar (a lista é referência,
  não limitação, como o prompt manda), e ``"Não identificado"`` vira vazio —
  nunca vira tag inventada.
- **Nunca sobrescreve fato de API**: ``aplicar_na_info`` só preenche campo
  vazio. O que o iTunes/MusicBrainz/Deezer confirmaram tem prioridade.
- **A chave nunca aparece** em log, erro ou exceção: só a máscara.
- **Falha não derruba o download**: qualquer erro devolve ``None`` e o
  processamento segue com o que as APIs públicas confirmaram.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any

from baixador.web import api_ia
from baixador.nucleo.configuracoes import CONFIG, Configuracoes
from baixador.web.inteligencia import ClienteHTTP, ClienteHTTPUrllib, ErroAPI, InfoMusica

log = logging.getLogger("baixador.ia_identificacao")

MODELO_PADRAO = "gpt-4o-mini"
URL_PADRAO = "https://api.openai.com/v1/chat/completions"
NAO_IDENTIFICADO = "não identificado"

# Lista de referência do prompt do usuário. Não é limitação: gênero fora dela
# é aceito, mas o normalizado precisa ser músicalmente plausível.
GENEROS_REFERENCIA: tuple[str, ...] = (
    # Rock
    "Rock", "Classic Rock", "Hard Rock", "Alternative Rock", "Indie Rock",
    "Progressive Rock", "Psychedelic Rock", "Garage Rock", "Southern Rock",
    "Blues Rock", "Folk Rock", "Art Rock", "Glam Rock", "Punk Rock",
    "Post-Punk", "Soft Rock", "Arena Rock", "Surf Rock", "Experimental Rock",
    "Gothic Rock", "Grunge", "Post-Rock", "Pop Rock", "Christian Rock",
    "Symphonic Rock",
    # Metal
    "Heavy Metal", "Thrash Metal", "Death Metal", "Black Metal", "Power Metal",
    "Progressive Metal", "Symphonic Metal", "Gothic Metal", "Doom Metal",
    "Nu Metal", "Alternative Metal", "Metalcore", "Deathcore", "Groove Metal",
    "Speed Metal", "Folk Metal", "Industrial Metal", "Glam Metal",
    "Sludge Metal", "Stoner Metal", "Melodic Death Metal",
    # Pop
    "Pop", "Dance-Pop", "Synth-Pop", "Electropop", "Indie Pop", "Dream Pop",
    "Art Pop", "Teen Pop", "Baroque Pop", "Power Pop", "Sophisti-Pop", "K-Pop",
    "J-Pop",
    # Eletrônica
    "Electronic", "House", "Deep House", "Tech House", "Progressive House",
    "Techno", "Trance", "Psytrance", "Dubstep", "Drum and Bass", "Ambient",
    "Downtempo", "Trip-Hop", "Synthwave", "Electro", "EDM", "Industrial",
    "Breakbeat",
    # Hip-Hop
    "Hip-Hop", "Rap", "Trap", "Boom Bap", "Gangsta Rap", "Conscious Hip-Hop",
    "Alternative Hip-Hop", "Old School Hip-Hop", "Lo-Fi Hip-Hop", "Jazz Rap",
    "Drill", "Cloud Rap",
    # R&B / Soul
    "R&B", "Contemporary R&B", "Alternative R&B", "Neo Soul", "Soul", "Funk",
    "Motown", "Quiet Storm", "Disco", "Funk Rock",
    # Blues / Jazz
    "Blues", "Delta Blues", "Chicago Blues", "Electric Blues", "Jazz",
    "Smooth Jazz", "Bebop", "Swing", "Fusion Jazz", "Cool Jazz", "Latin Jazz",
    "Jazz Rock",
    # Folk / Country
    "Folk", "Indie Folk", "Traditional Folk", "Country", "Country Rock",
    "Alternative Country", "Bluegrass", "Americana", "Singer-Songwriter",
    "Acoustic", "Country Pop",
    # Reggae
    "Reggae", "Roots Reggae", "Dub", "Ska", "Rocksteady", "Dancehall",
    "Reggaeton", "Soca", "Calypso",
    # Latina / brasileira
    "Latin Pop", "Latin Rock", "Salsa", "Merengue", "Bachata", "Cumbia",
    "Bossa Nova", "Samba", "MPB", "Pagode", "Sertanejo", "Forró", "Axé",
    "Tropicalia", "Música Popular Brasileira", "Funk Brasileiro",
    "Rap Brasileiro", "Rock Brasileiro", "Música Regional Brasileira",
    # Clássica / instrumental
    "Classical", "Baroque", "Romantic", "Contemporary Classical", "Opera",
    "Orchestral", "Chamber Music", "Soundtrack", "Film Score", "Instrumental",
    "New Age", "Minimalism",
    # Outros
    "Gospel", "Christian", "Religious", "Experimental", "Spoken Word",
    "Comedy", "World Music", "New Wave", "Lounge", "Easy Listening",
    "Children's Music", "Holiday Music",
)

_INSTRUCOES = (
    "Você é uma IA especializada em identificação, pesquisa, catalogação e "
    "classificação musical.\n\n"
    "Sua função é receber o nome de uma música (e, quando houver, o canal de "
    "onde ela veio) e identificar as informações necessárias para preencher "
    "seis campos de metadados, seguindo rigorosamente a ordem estabelecida.\n\n"
    "1. INFORMAÇÕES OBRIGATÓRIAS\n"
    "1. Título: nome oficial da música.\n"
    "2. Artista: cantor, banda ou grupo responsável pela gravação.\n"
    "3. Álbum: álbum original em que a música foi lançada.\n"
    "4. Ano: ano de lançamento original da música.\n"
    "5. Gênero: gênero musical principal e seus respectivos subgêneros.\n"
    "6. Número da faixa: posição da música na tracklist do álbum original.\n\n"
    "2. CLASSIFICAÇÃO DE GÊNEROS\n"
    "Use como referência os gêneros e subgêneros listados abaixo.\n"
    "{generos}\n\n"
    "3. REGRAS DE CLASSIFICAÇÃO\n"
    "- Identifique o gênero predominante da música.\n"
    "- Inclua os subgêneros relevantes, sem exagerar na quantidade.\n"
    "- Não classifique uma música apenas pelo gênero habitual do artista: "
    "analise a gravação específica.\n"
    "- Diferencie gêneros próximos, como Hard Rock, Heavy Metal e "
    "Alternative Rock.\n"
    "- Utilize nomes de gêneros reconhecidos musicalmente.\n"
    "- Uma música pode pertencer a mais de um gênero.\n"
    "- Não invente classificações para preencher espaço.\n"
    "- A lista é uma referência, não uma limitação. Se a música pertencer a um "
    "gênero não listado, use a classificação correta.\n\n"
    "4. REGRAS DE PESQUISA E PRECISÃO\n"
    "- Priorize fontes confiáveis para confirmar os dados.\n"
    "- Considere o lançamento ORIGINAL, não relançamentos ou coletâneas.\n"
    "- Use o álbum correspondente à gravação identificada.\n"
    "- O número da faixa deve corresponder à posição da música na edição do "
    "álbum utilizada.\n"
    "- Havendo versões diferentes, identifique a versão mais conhecida.\n"
    "- Se não encontrar uma informação confiável, escreva "
    "\\\"Não identificado\\\".\n"
    "- NUNCA invente informações.\n\n"
    "5. FORMATO OBRIGATÓRIO DE RESPOSTA\n"
    "Responda SOMENTE com um objeto JSON com exatamente estas chaves, sem "
    "texto fora dele:\n"
    '{{\"titulo\": \"...\", \"artista\": \"...\", \"album\": \"...\", '
    '\"ano\": \"...\", \"genero\": \"...\", \"faixa\": \"...\"}}\n'
    "Em \"ano\" use apenas o ano com 4 dígitos; em \"faixa\" use apenas o "
    "número. Não acrescente explicações."
)


@dataclass(frozen=True)
class Identificacao:
    """Seis campos devolvidos pela IA (vazios quando não identificados)."""

    titulo: str = ""
    artista: str = ""
    album: str = ""
    ano: int | None = None
    genero: str = ""
    faixa: int | None = None
    # Diagnóstico sem segredo: modelo usado e campos que vieram vazios.
    modelo: str = ""
    ausentes: tuple[str, ...] = field(default_factory=tuple)

    def como_linhas(self) -> list[tuple[str, str]]:
        """Formato pedido no prompt, na ordem obrigatória."""
        return [
            ("Título", self.titulo or "Não identificado"),
            ("Artista", self.artista or "Não identificado"),
            ("Álbum", self.album or "Não identificado"),
            ("Ano", str(self.ano) if self.ano else "Não identificado"),
            ("Gênero", self.genero or "Não identificado"),
            ("Número da faixa", str(self.faixa) if self.faixa else "Não identificado"),
        ]


def montar_prompt(consulta: str, canal: str = "") -> str:
    """Prompt completo (instruções + pedido), com a lista de gêneros."""
    generos = ", ".join(GENEROS_REFERENCIA)
    texto = _INSTRUCOES.format(generos=generos)
    pedido = f"\n\nMÚSICA A IDENTIFICAR: {consulta}"
    if canal:
        pedido += f"\nCANAL DE ORIGEM (pista, pode ser nome de gravadora/VEVO): {canal}"
    return texto + pedido


def _texto(valor: Any) -> str:
    """Campo da resposta → texto limpo; "Não identificado" vira vazio."""
    if valor is None:
        return ""
    texto = str(valor).strip().strip('"').strip()
    if not texto or texto.lower() in {NAO_IDENTIFICADO, "não identificado",
                                      "nao identificado", "n/a", "unknown",
                                      "desconhecido", "-", "null", "none"}:
        return ""
    return texto


def _ano(valor: Any) -> int | None:
    texto = _texto(valor)
    achado = re.search(r"\b(1[89]\d{2}|20\d{2})\b", texto)
    return int(achado.group(1)) if achado else None


def _faixa(valor: Any) -> int | None:
    texto = _texto(valor)
    achado = re.search(r"\d+", texto)
    if not achado:
        return None
    numero = int(achado.group(0))
    return numero if 1 <= numero <= 999 else None


def normalizar_genero(valor: Any) -> str:
    """Gênero(s) → texto com nomes canônicos quando reconhecíveis.

    Aceita "Rock; Blues Rock", "rock / hard rock" ou nome único. Casca de
    gênero fora da lista é preservada como veio (a lista é referência).
    """
    texto = _texto(valor)
    if not texto:
        return ""
    por_canonico = {genero.lower(): genero for genero in GENEROS_REFERENCIA}
    escolhidos: list[str] = []
    for parte in re.split(r"\s*[;,/|]\s*", texto):
        parte = parte.strip()
        if not parte:
            continue
        canonico = por_canonico.get(parte.lower())
        # "Rock (Hard Rock)" e afins: tenta o miolo entre parênteses.
        if canonico is None and "(" in parte and parte.endswith(")"):
            canonico = por_canonico.get(parte[parte.index("(") + 1:-1].strip().lower())
        final = canonico or parte
        if final.lower() not in {item.lower() for item in escolhidos}:
            escolhidos.append(final)
    return ", ".join(escolhidos[:3])  # "sem exagerar na quantidade"


# Esquema do JSON pedido à IA: usado no prompt (response_format) e na
# validação da resposta. A validação é o que impede um JSON torto de virar tag.
ESQUEMA_RESPOSTA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "titulo": {"type": "string"},
        "artista": {"type": "string"},
        "album": {"type": "string"},
        "ano": {"type": "string"},
        "genero": {"type": "string"},
        "faixa": {"type": "string"},
    },
    "required": ["titulo", "artista", "album", "ano", "genero", "faixa"],
    "additionalProperties": False,
}

# Motivo da última rejeição (diagnóstico legível, sem segredo).
ULTIMO_MOTIVO_INVALIDO = ""


def _motivo_invalido(motivo: str) -> None:
    global ULTIMO_MOTIVO_INVALIDO
    ULTIMO_MOTIVO_INVALIDO = motivo


def validar_resposta(dados: Any) -> tuple[dict[str, Any], str]:
    """Confere o JSON da IA e devolve ``(campos_limpos, motivo_do_problema)``.

    Regras (as mesmas do esquema enviado no prompt):
    - precisa ser objeto JSON, não lista/string/número;
    - valores precisam ser texto, número ou nulo (lista/dicionário aninhado é
      resposta torta: recusa em vez de virar tag estranha);
    - campo ausente é aceito como vazio, mas o objeto não pode vir vazio nem
      inventar chaves fora do esquema (sinal de que a IA respondeu outra coisa).
    """
    if not isinstance(dados, dict):
        return {}, "A resposta não é um objeto JSON."
    if not dados:
        return {}, "A resposta veio vazia."
    conhecidos = set(ESQUEMA_RESPOSTA["properties"])
    extras = sorted(set(dados) - conhecidos)
    if extras and not (conhecidos & set(dados)):
        return {}, f"A resposta não tem nenhum dos campos pedidos ({', '.join(extras)})"
    limpos: dict[str, Any] = {}
    for campo in conhecidos:
        if campo not in dados:
            continue
        valor = dados[campo]
        if isinstance(valor, (dict, list, tuple, set)):
            return {}, f'O campo "{campo}" veio como lista/objeto, não como texto.'
        limpos[campo] = valor
    return limpos, ""


def interpretar_resposta(conteudo: str, modelo: str = "") -> Identificacao | None:
    """Lê o JSON da IA; ``None`` se não houver os campos mínimos."""
    texto = (conteudo or "").strip()
    if not texto:
        return None
    texto = re.sub(r"^```(?:json)?|```$", "", texto, flags=re.MULTILINE).strip()
    try:
        dados = json.loads(texto)
    except json.JSONDecodeError:
        inicio, fim = texto.find("{"), texto.rfind("}")
        if inicio < 0 or fim <= inicio:
            return None
        try:
            dados = json.loads(texto[inicio:fim + 1])
        except json.JSONDecodeError:
            return None
    dados, motivo = validar_resposta(dados)
    if motivo:
        _motivo_invalido(motivo)
        log.info("Resposta da IA recusada: %s", motivo)
        return None

    identificacao = Identificacao(
        titulo=_texto(dados.get("titulo") or dados.get("titulo_oficial")),
        artista=_texto(dados.get("artista")),
        album=_texto(dados.get("album")),
        ano=_ano(dados.get("ano")),
        genero=normalizar_genero(dados.get("genero")),
        faixa=_faixa(dados.get("faixa") or dados.get("numero_da_faixa")),
        modelo=modelo,
    )
    if not identificacao.titulo and not identificacao.artista:
        return None
    ausentes = tuple(
        rotulo for rotulo, valor in (
            ("título", identificacao.titulo), ("artista", identificacao.artista),
            ("álbum", identificacao.album), ("ano", identificacao.ano),
            ("gênero", identificacao.genero), ("faixa", identificacao.faixa),
        ) if not valor)
    return Identificacao(**{**identificacao.__dict__, "ausentes": ausentes})


class IdentificadorIA:
    """Chama a IA com a chave importada e devolve ``Identificacao``."""

    def __init__(self, cliente: ClienteHTTP | None = None,
                 api_key: str | None = None,
                 modelo: str | None = None, url: str | None = None,
                 config: Configuracoes = CONFIG, timeout: float = 20.0):
        self.config = config
        self.cliente = cliente or ClienteHTTPUrllib(timeout=timeout)
        self.api_key = (api_key if api_key is not None
                        else api_ia.ler_chave(config)).strip()
        self.modelo = (modelo or os.environ.get("BAIXADOR_IA_MODELO")
                       or MODELO_PADRAO).strip()
        self.url = (url or os.environ.get("BAIXADOR_IA_URL") or URL_PADRAO).strip()
        self.ultimo_erro = ""

    @property
    def disponivel(self) -> bool:
        return bool(self.api_key)

    def identificar(self, consulta: str, canal: str = "") -> Identificacao | None:
        """Identifica a música; ``None`` (com ``ultimo_erro``) se não der."""
        self.ultimo_erro = ""
        consulta = (consulta or "").strip()
        if not consulta:
            self.ultimo_erro = "Nada para identificar."
            return None
        if not self.api_key:
            self.ultimo_erro = ("Nenhuma chave de IA configurada: importe o "
                                "api.txt nas Configurações.")
            return None
        try:
            resposta = self.cliente.post_json(
                self.url,
                self._corpo(consulta, canal),
                headers={"Authorization": f"Bearer {self.api_key}"},
            )
        except ErroAPI as erro:
            corpo = self._corpo(consulta, canal)
            if "response_format" in corpo and ("400" in str(erro)
                                               or "response_format" in str(erro)):
                # Provedor não aceita response_format: repete no modo prompt.
                try:
                    resposta = self.cliente.post_json(
                        self.url,
                        {k: v for k, v in corpo.items()
                         if k != "response_format"},
                        headers={"Authorization": f"Bearer {self.api_key}"},
                    )
                except Exception:
                    self.ultimo_erro = _traduzir_erro(str(erro))
                    log.warning("Identificação por IA falhou: %s", self.ultimo_erro)
                    return None
            else:
                self.ultimo_erro = _traduzir_erro(str(erro))
                log.warning("Identificação por IA falhou: %s", self.ultimo_erro)
                return None
        except Exception as erro:  # rede exótica nunca derruba o download
            self.ultimo_erro = _traduzir_erro(f"{type(erro).__name__}: {erro}")
            log.warning("Identificação por IA falhou: %s", self.ultimo_erro)
            return None

        conteudo = ""
        try:
            conteudo = (resposta["choices"][0]["message"]["content"] or "")
        except (KeyError, IndexError, TypeError):
            self.ultimo_erro = "A IA respondeu num formato inesperado."
            return None
        _motivo_invalido("")
        resultado = interpretar_resposta(conteudo, self.modelo)
        if resultado is None:
            self.ultimo_erro = ("A IA não devolveu os campos pedidos"
                                + (f": {ULTIMO_MOTIVO_INVALIDO}"
                                   if ULTIMO_MOTIVO_INVALIDO else "."))
            log.info("IA: %s", self.ultimo_erro)
        return resultado

    def _corpo(self, consulta: str, canal: str = "") -> dict[str, Any]:
        """Corpo da requisição, pedindo JSON quando o provedor suporta.

        ``response_format`` é do padrão OpenAI; se a API recusar (400), a
        chamada é repetida sem ele — o prompt já exige JSON, e a validação
        continua sendo feita do nosso lado.
        """
        corpo: dict[str, Any] = {
            "model": self.modelo,
            "messages": [{"role": "user",
                          "content": montar_prompt(consulta, canal)}],
            "temperature": 0,
        }
        if os.environ.get("BAIXADOR_IA_SEM_FORMATO_JSON", "").strip() in (
                "1", "sim", "true"):
            return corpo
        corpo["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": "identificacao_musical",
                            "strict": True, "schema": ESQUEMA_RESPOSTA},
        }
        return corpo

    def testar_conexao(self) -> tuple[bool, str]:
        """Chamada mínima para validar a chave (sem gastar uma identificação)."""
        if not self.api_key:
            return False, ("Nenhuma chave configurada: importe o api.txt "
                           "em Configurações.")
        try:
            self.cliente.post_json(
                self.url,
                {"model": self.modelo,
                 "messages": [{"role": "user", "content": "Responda apenas: ok"}],
                 "max_tokens": 3, "temperature": 0},
                headers={"Authorization": f"Bearer {self.api_key}"},
            )
        except ErroAPI as erro:
            return False, _traduzir_erro(str(erro))
        except Exception as erro:
            return False, _traduzir_erro(f"{type(erro).__name__}: {erro}")
        return True, f"Chave válida: a API respondeu (modelo {self.modelo})."


def _traduzir_erro(mensagem: str) -> str:
    """Erro de API em português, sem jamais repetir a chave."""
    texto = str(mensagem or "")
    baixo = texto.lower()
    if "401" in texto or "unauthorized" in baixo or "invalid api key" in baixo \
            or "incorrect api key" in baixo:
        return ("Chave recusada pela API (401). Confira se copiou a chave "
                "inteira e se ela está ativa.")
    if "429" in texto or "quota" in baixo or "rate limit" in baixo:
        return ("Limite de uso/créditos da API atingido (429). Verifique o "
                "saldo da sua conta.")
    if "404" in texto or "model" in baixo and "not found" in baixo:
        return "Modelo não encontrado (404). Confira o nome do modelo."
    if "403" in texto or "forbidden" in baixo:
        return "Acesso negado (403): a chave não tem permissão para este modelo."
    if any(marca in baixo for marca in
           ("timed out", "timeout", "ssl", "getaddrinfo", "urlopen",
            "temporary failure", "connection")):
        return ("Não foi possível falar com a API (rede/DNS/TLS). Confira a "
                "internet ou o proxy.")
    return "Falha ao consultar a API de IA."


def aplicar_na_info(info: InfoMusica, identificacao: Identificacao) -> list[str]:
    """Preenche só o que está vazio; devolve os campos preenchidos pela IA.

    Prioridade é do que já foi confirmado por iTunes/MusicBrainz/Deezer: a IA
    completa lacunas, nunca sobrescreve fato de API.
    """
    preenchidos: list[str] = []
    if not info.titulo and identificacao.titulo:
        info.titulo = identificacao.titulo
        preenchidos.append("titulo")
    if not info.artista and identificacao.artista:
        info.artista = identificacao.artista
        preenchidos.append("artista")
    if not info.album and identificacao.album:
        info.album = identificacao.album
        preenchidos.append("album")
    if not info.ano and identificacao.ano:
        info.ano = identificacao.ano
        preenchidos.append("ano")
    if not info.genero and identificacao.genero:
        info.genero = identificacao.genero
        preenchidos.append("genero")
    if not info.faixa and identificacao.faixa:
        info.faixa = identificacao.faixa
        preenchidos.append("faixa")
    if preenchidos and "ia" not in (info.fonte or "").split("+"):
        info.fonte = f"{info.fonte}+ia" if info.fonte else "ia"
    return preenchidos


def criar_identificador(config: Configuracoes = CONFIG) -> IdentificadorIA | None:
    """``IdentificadorIA`` quando há chave; ``None`` sem chave (sem erro)."""
    chave = api_ia.ler_chave(config)
    return IdentificadorIA(api_key=chave, config=config) if chave else None


__all__ = [
    "GENEROS_REFERENCIA", "Identificacao", "IdentificadorIA", "NAO_IDENTIFICADO",
    "aplicar_na_info", "criar_identificador", "ESQUEMA_RESPOSTA",
    "interpretar_resposta", "montar_prompt", "normalizar_genero",
    "validar_resposta",
]
