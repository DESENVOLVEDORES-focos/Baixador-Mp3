"""Tradução de erros do yt-dlp em orientação útil para o usuário.

O yt-dlp devolve mensagens técnicas em inglês. Aqui elas são classificadas em
"situações" e cada situação ganha uma explicação curta em português e a ação
recomendada. Isso não substitui o erro original — a interface mostra os dois.

Regra de honestidade: mensagem desconhecida continua desconhecida (situação
``outro``), nunca é "traduzida" para algo que talvez não seja.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

SITUACAO_OK = "ok"
SITUACAO_LOGIN = "exige_login"
SITUACAO_PRIVADO = "privado"
SITUACAO_IDADE = "restricao_idade"
SITUACAO_COOKIES_VENCIDOS = "cookies_vencidos"
SITUACAO_GEO = "bloqueio_regional"
SITUACAO_REMOVIDO = "indisponivel"
SITUACAO_REDE = "rede"
SITUACAO_FORMATO = "formato_indisponivel"
SITUACAO_FERRAMENTA = "ferramenta_ausente"
SITUACAO_NAO_ENCONTRADO = "nao_encontrado"
SITUACAO_JA_EXISTE = "ja_existe"
SITUACAO_OUTRO = "outro"

# (situação, regex, explicação, ação). Ordem importa: o primeiro que casar vale.
_REGRAS: tuple[tuple[str, str, str, str], ...] = (
    (SITUACAO_JA_EXISTE,
     r"has already been downloaded|já foi baixado",
     "Este conteúdo já está na pasta e nada foi sobrescrito.",
     "Escolha outra política de sobrescrita se quiser uma cópia."),
    (SITUACAO_COOKIES_VENCIDOS,
     r"cookies.*(expired|invalid)|rotated.*cookies|"
     r"the provided cookies? (?:is|are) no longer valid",
     "Os cookies salvos não valem mais (expiraram ou foram trocados).",
     "Configurações → COOKIES DO YOUTUBE → Substituir, com um cookies.txt novo."),
    (SITUACAO_IDADE,
     r"confirm your age|age-restricted|inappropriate for some users",
     "O vídeo tem restrição de idade e o YouTube exige uma conta logada.",
     "Importe um cookies.txt de uma conta com idade verificada."),
    (SITUACAO_LOGIN,
     r"sign in to confirm|please sign in|login required|"
     r"you need to (?:sign in|log in)",
     "O conteúdo exige login para ser acessado.",
     "Importe seu cookies.txt em Configurações → COOKIES DO YOUTUBE."),
    (SITUACAO_PRIVADO,
     r"private video|this video is private|members-only|"
     r"join this channel|only available to (?:channel )?members",
     "O vídeo é privado ou exclusivo para membros do canal.",
     "Se a sua conta tem acesso, importe o cookies.txt dela; sem acesso, não há como baixar."),
    (SITUACAO_GEO,
     r"not available in your country|geo.?restrict|blocked it in your country",
     "O conteúdo não está disponível na sua região.",
     "Não há ajuste no programa que resolva isso legalmente."),
    (SITUACAO_REMOVIDO,
     r"video unavailable|has been removed|no longer available|"
     r"this video (?:has been|is) (?:removed|deleted)|account.*terminated",
     "O vídeo foi removido ou não está mais disponível.",
     "Procure outro resultado."),
    (SITUACAO_NAO_ENCONTRADO,
     r"http error 404|\b404\b|not found|does not exist|video unavailable|"
     r"this video is (?:not available|unavailable)",
     "O endereço não existe mais (ou está errado/incompleto).",
     "Copie a URL de novo do navegador."),
    (SITUACAO_REDE,
     r"unable to download|temporary failure|timed out|timeout|"
     r"ssl|certificate|connection (?:reset|refused|aborted)|"
     r"getaddrinfo|network is unreachable|name resolution|"
     r"urlopen error|tls",
     "Não foi possível falar com o servidor (rede, DNS, TLS ou bloqueio).",
     "Confira sua internet; se estiver usando VPN/proxy, tente sem ele."),
    (SITUACAO_FORMATO,
     r"requested format (?:is )?not available|no video formats found",
     "O formato pedido não existe para este conteúdo.",
     "Tente o outro formato (MP3/MP4) ou outro resultado."),
    (SITUACAO_FERRAMENTA,
     r"ffmpeg (?:is )?not (?:found|installed)|ffprobe not found|"
     r"ffmpeg não encontrado|ffmpeg nao encontrado",
     "Falta o FFmpeg, necessário para converter/ juntar áudio e vídeo.",
     "Rode configurar.bat (baixa o FFmpeg) ou coloque ffmpeg.exe em ferramentas\\."),
    # Erros do próprio núcleo (levantados antes de chamar o yt-dlp).
    (SITUACAO_FERRAMENTA,
     r"yt-dlp não encontrado|yt-dlp nao encontrado|não foi possível iniciar o yt-dlp|"
     r"nao foi possivel iniciar o yt-dlp",
     "O yt-dlp (responsável por baixar) não está instalado ou não foi encontrado.",
     "Rode configurar.bat. Se já rodou, abra o terminal e execute "
     "python -m pip install yt-dlp."),
    (SITUACAO_FORMATO,
     r"formato deve ser|informe uma url http",
     "Os dados informados para o download estão incompletos ou inválidos.",
     "Verifique o formato (MP3/MP4) e se a URL começa com http ou https."),
)

_COMPILADAS = tuple(
    (situacao, re.compile(padrao, re.I | re.S), explicacao, acao)
    for situacao, padrao, explicacao, acao in _REGRAS
)

# Trechos que nunca devem aparecer num log/arquivo (credenciais em URL).
_RE_SEGREDOS = (
    re.compile(r"((?:cookie|authorization|token|key|sig|signature|password|pass)=)[^&\s\"']+",
               re.I),
    re.compile(r"(Bearer\s+)[A-Za-z0-9._\-]+"),
)


@dataclass(frozen=True)
class Diagnostico:
    situacao: str
    explicacao: str
    acao: str
    tecnico: str = ""

    @property
    def exige_cookies(self) -> bool:
        """Situações em que cookies da própria conta podem resolver.

        Vídeo privado/membros entra aqui: o yt-dlp só o acessa com a sessão de
        quem tem permissão. Se não houver permissão, o erro continua claro.
        """
        return self.situacao in {SITUACAO_LOGIN, SITUACAO_IDADE,
                                 SITUACAO_PRIVADO, SITUACAO_COOKIES_VENCIDOS}

    @property
    def texto(self) -> str:
        partes = [self.explicacao]
        if self.acao:
            partes.append(self.acao)
        return " ".join(parte for parte in partes if parte)


def classificar(mensagem: str) -> Diagnostico:
    """Classifica a mensagem de erro e devolve explicação + ação."""
    texto = sanitizar(mensagem or "")
    for situacao, padrao, explicacao, acao in _COMPILADAS:
        if padrao.search(texto):
            return Diagnostico(situacao, explicacao, acao, tecnico=texto)
    if not texto.strip():
        return Diagnostico(SITUACAO_OUTRO, "O download falhou sem detalhe do yt-dlp.",
                           "Tente de novo; se repetir, copie a mensagem para análise.")
    return Diagnostico(SITUACAO_OUTRO, "O download falhou.",
                       "Veja a mensagem técnica abaixo para identificar a causa.",
                       tecnico=texto)


def sanitizar(texto: str) -> str:
    """Remove credenciais de uma mensagem antes de gravar/exibir.

    Cookies, tokens e assinaturas que o yt-dlp pode ecoar em URLs ficam fora de
    ``erros.jsonl`` e de qualquer log — o valor nunca é necessário para o
    diagnóstico.
    """
    limpo = str(texto or "")
    for padrao in _RE_SEGREDOS:
        limpo = padrao.sub(lambda m: m.group(1) + "***", limpo)
    return limpo


def dica_para_interface(diagnostico: Diagnostico,
                        cookies_configurados: bool) -> str:
    """Sugestão pronta para a tela, considerando se já há cookies importados."""
    if diagnostico.situacao == SITUACAO_COOKIES_VENCIDOS or (
            diagnostico.exige_cookies and cookies_configurados):
        return ("Os cookies salvos parecem não funcionar mais. Importe um "
                "cookies.txt novo em Configurações → COOKIES DO YOUTUBE.")
    if diagnostico.exige_cookies and not cookies_configurados:
        return ("Este conteúdo exige autenticação e você ainda não importou "
                "cookies. Use Configurações → COOKIES DO YOUTUBE.")
    return diagnostico.texto


__all__ = [
    "Diagnostico", "SITUACAO_COOKIES_VENCIDOS", "SITUACAO_FERRAMENTA",
    "SITUACAO_FORMATO", "SITUACAO_GEO", "SITUACAO_IDADE", "SITUACAO_JA_EXISTE",
    "SITUACAO_LOGIN", "SITUACAO_NAO_ENCONTRADO", "SITUACAO_OK", "SITUACAO_OUTRO",
    "SITUACAO_PRIVADO", "SITUACAO_REDE", "SITUACAO_REMOVIDO",
    "classificar", "dica_para_interface", "sanitizar",
]
