"""Importação da chave de IA a partir de um arquivo (``api.txt``).

Mesmo padrão do ``cookies.txt``: o usuário escolhe um arquivo pela interface,
o programa **valida** se há uma chave utilizável, guarda uma **cópia
gerenciada** em ``<dados>/api.txt`` (fora do Git, permissão 0600) e passa a
usá-la automaticamente. O conteúdo nunca é exibido, registrado em log nem
enviado a lugar nenhum além do serviço de IA configurado.

Formatos aceitos (nada de senha, nada de OAuth):

- a chave sozinha: ``sk-proj-...``;
- ``chave=sk-...``, ``api_key: sk-...``, ``OPENAI_API_KEY=sk-...``;
- ``sk-...   # comentário`` (o que vem depois de ``#`` é ignorado);
- arquivo com várias linhas: vale a primeira linha com chave reconhecível.

A chave é considerada **válida pelo formato** quando tem cara de chave da
OpenAI (``sk-``…) ou de outro provedor compatível (20+ caracteres sem espaços).
A validade *real* só se confirma com uma chamada de teste — que a interface
oferece à parte, sem nunca exibir a chave.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from configuracoes import CONFIG, Configuracoes

log = logging.getLogger("baixador.api")

NOME_ARQUIVO = "api.txt"
NOMES_ACEITOS = ("api.txt", "api_key.txt", "apikey.txt", "chave.txt",
                 "chave_api.txt", "openai.txt", ".env", ".api")
TAMANHO_MAXIMO = 64 * 1024  # chave + comentários nunca chega perto disso

# Prefixos conhecidos de chaves de provedores compatíveis com OpenAI.
_PREFIXOS = ("sk-", "sk_", "sess-", "gsk_", "or-", "xai-")
# Nomes de variável que podem preceder a chave no arquivo.
_ROTULOS = re.compile(
    r"^\s*(?:export\s+)?(?:api[_-]?key|openai[_-]?api[_-]?key|chave|"
    r"key|token|secret|bearer|authorization)\s*[:=]\s*", re.IGNORECASE)
_JSON_CHAVE = re.compile(r'"(?:api_?key|key|token)"\s*:\s*"([^"]{8,})"',
                         re.IGNORECASE)
_MINIMO_GENERICO = 20


class ErroChave(RuntimeError):
    """Arquivo ausente, ilegível ou sem uma chave reconhecível."""


@dataclass(frozen=True)
class InfoChave:
    configurada: bool
    caminho: Path | None = None
    valida: bool = False
    mascarada: str = ""
    provedor: str = ""
    mensagem: str = ""
    # Nome original do arquivo escolhido (a cópia vira sempre api.txt).
    nome_original: str = ""
    renomeado: bool = False
    origem: str = ""


def mascarar(chave: str) -> str:
    """Forma exibida na interface: nunca revela a chave inteira."""
    chave = (chave or "").strip()
    if not chave:
        return ""
    if len(chave) <= 4:
        return "••••"
    return "••••••••" + chave[-4:]


def _limpar_linha(linha: str) -> str:
    linha = linha.strip().strip("\ufeff")
    # Remove comentários (mas não dentro de aspas simples — raro e inofensivo).
    for marca in (" #", "\t#"):
        corte = linha.find(marca)
        if corte > 0:
            linha = linha[:corte]
    return linha.strip().strip('"').strip("'").strip()


def extrair_chave(texto: str) -> tuple[str, str]:
    """Devolve ``(chave, provedor)``; levanta ``ErroChave`` se não houver.

    Reconhece chave pura, ``CHAVE=valor``, ``api_key: valor``, JSON e ``.env``.
    Um texto que não parece chave (senha, frase, URL) é recusado — melhor
    errar na importação do que quebrar o download depois.
    """
    if not (texto or "").strip():
        raise ErroChave("O arquivo está vazio.")

    achado_json = _JSON_CHAVE.search(texto)
    if achado_json:
        chave = achado_json.group(1).strip()
        if chave:
            return chave, _provedor_da_chave(chave)

    candidatos: list[str] = []
    for linha_bruta in texto.splitlines():
        linha = _limpar_linha(linha_bruta)
        if not linha:
            continue
        if linha.startswith("#"):
            continue
        # Ignora nomes de hosts/URLs explícitos: só interessa a chave.
        if linha.lower().startswith(("http://", "https://")):
            continue
        sem_rotulo = _ROTULOS.sub("", linha).strip()
        for possivel in (sem_rotulo, linha):
            possivel = _limpar_linha(possivel)
            if possivel and possivel not in candidatos:
                candidatos.append(possivel)

    for candidato in candidatos:
        if _parece_chave(candidato):
            return candidato, _provedor_da_chave(candidato)

    raise ErroChave(
        "Nenhuma chave reconhecível encontrada. O arquivo deve conter a chave "
        "sozinha (ex.: sk-...) ou no formato api_key=sk-...")


def _parece_chave(valor: str) -> bool:
    if not valor or any(caractere.isspace() for caractere in valor):
        return False
    if valor.lower().startswith(("http://", "https://")):
        return False
    if any(valor.startswith(prefixo) for prefixo in _PREFIXOS):
        return len(valor) >= 12
    # Provedor compatível com outro formato: exige longo e alfanumérico.
    if len(valor) < _MINIMO_GENERICO:
        return False
    if not re.fullmatch(r"[A-Za-z0-9_\-\.]+", valor):
        return False
    # Evita aceitar caminhos de arquivo ou frases comuns como "chave".
    return any(caractere.isdigit() for caractere in valor) or len(valor) >= 30


def _provedor_da_chave(chave: str) -> str:
    if chave.startswith(("sk-proj-", "sk-svcacct-", "sk-", "sk_")):
        return "openai"
    if chave.startswith("gsk_"):
        return "groq"
    if chave.startswith("xai-"):
        return "xai"
    if chave.startswith(("sess-", "or-")):
        return "openrouter"
    return "compativel"


def caminho_destino(config: Configuracoes = CONFIG) -> Path:
    return config.dados / NOME_ARQUIVO


def ler_chave(config: Configuracoes = CONFIG) -> str:
    """Chave ativa, sem expor nada: ambiente > cópia gerenciada.

    Ordem: ``BAIXADOR_IA_API_KEY`` (definida pelas preferências ao abrir o
    programa), a cópia em ``<dados>/api.txt`` e um ``api.txt`` deixado na pasta
    do programa (mesma tolerância do ``cookies.txt``).
    """
    ambiente = os.environ.get("BAIXADOR_IA_API_KEY", "").strip()
    if ambiente:
        return ambiente
    for candidato in (caminho_destino(config), Path(config.raiz) / NOME_ARQUIVO):
        try:
            if candidato.is_file():
                chave, _ = extrair_chave(
                    candidato.read_bytes().decode("utf-8", errors="replace"))
                return chave
        except (OSError, ErroChave):
            continue
    return ""


def importar(origem: Path | str, config: Configuracoes = CONFIG) -> InfoChave:
    """Valida e copia o arquivo escolhido para ``<dados>/api.txt``.

    - nome diferente de ``api.txt`` é registrado como renomeado (a cópia
      gerenciada é sempre ``api.txt``);
    - nada de segredo em log: registra apenas provedor e máscara;
    - substitui a cópia anterior atomicamente.
    """
    origem = Path(str(origem)).expanduser()
    if not origem.is_file():
        raise ErroChave(f"Arquivo não encontrado: {origem.name}")
    if origem.stat().st_size > TAMANHO_MAXIMO:
        raise ErroChave("Arquivo grande demais para uma chave de API.")
    try:
        texto = origem.read_bytes().decode("utf-8-sig", errors="strict")
    except (OSError, UnicodeDecodeError) as erro:
        raise ErroChave(f"Não foi possível ler o arquivo: {erro}") from erro

    chave, provedor = extrair_chave(texto)  # valida ANTES de copiar
    destino = caminho_destino(config)
    destino.parent.mkdir(parents=True, exist_ok=True)
    temporario = destino.with_suffix(".txt.tmp")
    try:
        # Guarda só a chave (uma linha), não o arquivo inteiro: comentários e
        # eventuais restos do export não têm por que ficar no disco.
        temporario.write_text(chave + "\n", encoding="utf-8")
        try:
            os.chmod(temporario, 0o600)
        except OSError:
            pass
        temporario.replace(destino)
    except OSError as erro:
        raise ErroChave(f"Não foi possível guardar a chave: {erro}") from erro

    renomeado = origem.name.lower() != NOME_ARQUIVO
    log.info("Chave de IA importada (provedor=%s, %s)%s.", provedor,
             mascarar(chave), " renomeada para api.txt" if renomeado else "")
    return InfoChave(
        configurada=True, caminho=destino, valida=True,
        mascarada=mascarar(chave), provedor=provedor,
        mensagem="Chave importada e pronta para uso.",
        nome_original=origem.name, renomeado=renomeado, origem="arquivo")


def status(config: Configuracoes = CONFIG) -> InfoChave:
    """Estado sem vazar conteúdo: existe? legível? formato aceitável?"""
    chave = ler_chave(config)
    if chave:
        destino = caminho_destino(config)
        caminho = destino if destino.is_file() else None
        return InfoChave(
            configurada=True, caminho=caminho, valida=True,
            mascarada=mascarar(chave), provedor=_provedor_da_chave(chave),
            mensagem="Chave configurada e no formato esperado.",
            origem="ambiente" if os.environ.get("BAIXADOR_IA_API_KEY", "").strip()
            else "arquivo")
    for candidato in (caminho_destino(config), Path(config.raiz) / NOME_ARQUIVO):
        if not candidato.is_file():
            continue
        try:
            texto = candidato.read_bytes().decode("utf-8", errors="replace")
            chave, _ = extrair_chave(texto)
        except ErroChave as erro:
            return InfoChave(False, candidato, False,
                             mensagem=f"Arquivo encontrado, mas {erro}")
        except OSError:
            continue
        return InfoChave(True, candidato, True, mascarar(chave),
                         _provedor_da_chave(chave),
                         "Chave configurada e no formato esperado.",
                         origem="arquivo")
    return InfoChave(False, None, False,
                     mensagem="Nenhuma chave de IA configurada (opcional).")


def remover(config: Configuracoes = CONFIG) -> bool:
    """Apaga a cópia gerenciada; ``True`` se algo foi removido."""
    alvo = caminho_destino(config)
    try:
        if alvo.is_file():
            alvo.unlink()
            log.info("Chave de IA removida da pasta de dados.")
            return True
    except OSError as erro:
        raise ErroChave(f"Não foi possível remover a chave: {erro}") from erro
    return False


def copiar_de_onde_veio(origem: Path | str, config: Configuracoes = CONFIG) -> None:
    """Utilitário p/ testes: copia o arquivo como está (sem validar)."""
    shutil.copyfile(str(origem), str(caminho_destino(config)))


__all__ = [
    "ErroChave", "InfoChave", "NOME_ARQUIVO", "NOMES_ACEITOS",
    "caminho_destino", "extrair_chave", "importar", "ler_chave", "mascarar",
    "remover", "status",
]
