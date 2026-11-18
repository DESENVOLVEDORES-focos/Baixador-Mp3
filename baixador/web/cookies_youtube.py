"""Gerenciamento seguro do ``cookies.txt`` do YouTube (Etapa 3).

O arquivo de cookies é uma **credencial privada da conta do usuário**:

- fica copiado apenas em ``<dados>/cookies.txt`` (pasta já ignorada pelo
  Git), com permissão restrita quando o sistema permite;
- nunca é enviado a APIs externas, nunca aparece em logs (só contamos
  quantos cookies existem), nunca entra em commits;
- é entregue somente ao yt-dlp local, via ``--cookies <caminho>``, nos
  downloads e pesquisas (ver ``configuracoes.argumentos_cookies``).

Formato aceito: Netscape/Mozilla ``cookies.txt`` (o exportado por
extensões de navegador) — linhas com 7 campos separados por tabulação,
aceitando o prefixo ``#HttpOnly_``. Nenhuma senha é solicitada.
"""

from __future__ import annotations

import logging
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from baixador.nucleo.configuracoes import CONFIG, Configuracoes

log = logging.getLogger("baixador.cookies")

NOME_ARQUIVO = "cookies.txt"
TAMANHO_MAXIMO = 5 * 1024 * 1024  # 5 MB: cookies.txt legítimo é bem menor


class ErroCookies(RuntimeError):
    """Arquivo de cookies ausente, ilegível ou em formato incompatível."""


@dataclass(frozen=True)
class InfoCookies:
    configurado: bool
    caminho: Path | None
    valido: bool
    total: int = 0
    do_youtube: int = 0
    mensagem: str = ""
    # Cookies com data de expiração já passada: o yt-dlp os ignora, e é a causa
    # mais comum de "importei e continuou pedindo login".
    vencidos: int = 0
    expirados_do_youtube: int = 0


def analisar_conteudo(texto: str) -> tuple[int, int]:
    """Conta cookies (total / do YouTube) validando o formato Netscape.

    Levanta ``ErroCookies`` se nenhuma linha válida for encontrada.
    O conteúdo em si nunca é retornado nem registrado.
    """
    total = 0
    youtube = 0
    for linha in texto.splitlines():
        linha = linha.strip("\r\n")
        if not linha.strip():
            continue
        if linha.startswith("#HttpOnly_"):
            linha = linha[len("#HttpOnly_"):]
        elif linha.startswith("#"):
            continue  # comentários/cabeçalho do formato Netscape
        campos = linha.split("\t")
        if len(campos) != 7:
            continue
        total += 1
        dominio = campos[0].lower()
        if "youtube.com" in dominio or "google.com" in dominio:
            youtube += 1
    if total == 0:
        raise ErroCookies(
            "Formato incompatível: nenhuma linha de cookie no formato "
            "Netscape (7 campos separados por tabulação) foi encontrada.")
    return total, youtube


def contar_vencidos(texto: str, agora: float | None = None) -> tuple[int, int]:
    """``(vencidos, vencidos_do_youtube)`` pelas datas de expiração do arquivo.

    O 5º campo Netscape é a expiração em epoch (``0`` = cookie de sessão, que
    vale enquanto o navegador está aberto e não é considerado vencido aqui).
    """
    import time

    momento = time.time() if agora is None else agora
    vencidos = do_youtube = 0
    for linha in texto.splitlines():
        linha = linha.strip("\r\n")
        if linha.startswith("#HttpOnly_"):
            linha = linha[len("#HttpOnly_"):]
        elif not linha.strip() or linha.startswith("#"):
            continue
        campos = linha.split("\t")
        if len(campos) != 7:
            continue
        try:
            expira = float(campos[4].strip())
        except ValueError:
            continue
        if expira <= 0 or expira > momento:
            continue
        vencidos += 1
        dominio = campos[0].lower()
        if "youtube.com" in dominio or "google.com" in dominio:
            do_youtube += 1
    return vencidos, do_youtube


def caminho_destino(config: Configuracoes = CONFIG) -> Path:
    return config.dados / NOME_ARQUIVO


def importar(origem: Path | str, config: Configuracoes = CONFIG) -> InfoCookies:
    """Valida e copia o ``cookies.txt`` escolhido para a pasta de dados.

    Substitui a cópia anterior atomicamente. A origem não é alterada.
    """
    origem = Path(origem).expanduser()
    if not origem.is_file():
        raise ErroCookies(f"Arquivo não encontrado: {origem}")
    if origem.stat().st_size > TAMANHO_MAXIMO:
        raise ErroCookies("Arquivo maior que 5 MB; não parece um cookies.txt válido.")
    try:
        texto = origem.read_bytes().decode("utf-8", errors="strict")
    except (OSError, UnicodeDecodeError) as erro:
        raise ErroCookies(f"Não foi possível ler o arquivo de cookies: {erro}") from erro
    total, youtube = analisar_conteudo(texto)  # valida antes de copiar qualquer coisa

    destino = caminho_destino(config)
    destino.parent.mkdir(parents=True, exist_ok=True)
    temporario = destino.with_suffix(".txt.tmp")
    try:
        shutil.copyfile(origem, temporario)
        try:
            os.chmod(temporario, 0o600)
        except OSError:
            pass
        temporario.replace(destino)
    except OSError as erro:
        raise ErroCookies(f"Não foi possível armazenar os cookies: {erro}") from erro
    # Registra apenas metadados — jamais o conteúdo dos cookies.
    log.info("Cookies importados: %d no total, %d do YouTube/Google.", total, youtube)
    vencidos, vencidos_youtube = contar_vencidos(texto)
    if vencidos_youtube:
        log.info("Cookies do YouTube já vencidos: %d de %d.", vencidos_youtube, youtube)
        mensagem = (
            f"Arquivo importado, mas {vencidos_youtube} cookie(s) do YouTube já "
            "venceram. Exporte de novo pelo navegador se o YouTube pedir login.")
    else:
        mensagem = "Arquivo importado e válido."
    return InfoCookies(True, destino, True, total, youtube, mensagem,
                       vencidos, vencidos_youtube)


def remover(config: Configuracoes = CONFIG) -> bool:
    """Apaga a cópia gerenciada; devolve ``True`` se havia arquivo."""
    destino = caminho_destino(config)
    try:
        if destino.is_file():
            destino.unlink()
            log.info("Arquivo de cookies removido pelo usuário.")
            return True
    except OSError as erro:
        raise ErroCookies(f"Não foi possível remover os cookies: {erro}") from erro
    return False


def status(config: Configuracoes = CONFIG) -> InfoCookies:
    """Estado atual sem vazar conteúdo: existe? acessível? formato ok?"""
    destino = caminho_destino(config)
    configurado = destino.is_file()
    explicito = getattr(config, "caminho_cookies", None)
    candidato = Path(explicito).expanduser() if explicito else destino
    if candidato.is_file():
        destino, configurado = candidato, True
    else:
        # Arquivo solto na pasta do programa (sem passar pela interface).
        resolver = getattr(config, "resolver_cookies", None)
        if callable(resolver):
            try:
                achado = resolver()
            except Exception:
                achado = None
            if achado is not None:
                destino, configurado = Path(achado), True
    if not configurado:
        return InfoCookies(False, None, False, mensagem="Nenhum cookies.txt configurado.")
    try:
        texto = destino.read_bytes().decode("utf-8", errors="strict")
    except (OSError, UnicodeDecodeError):
        return InfoCookies(True, destino, False,
                           mensagem="Arquivo configurado, mas não foi possível lê-lo.")
    try:
        total, youtube = analisar_conteudo(texto)
    except ErroCookies as erro:
        return InfoCookies(True, destino, False, mensagem=str(erro))
    vencidos, vencidos_youtube = contar_vencidos(texto)
    if youtube and vencidos_youtube >= youtube:
        mensagem = (
            "Arquivo válido, mas TODOS os cookies do YouTube já venceram: "
            "o yt-dlp vai ignorá-los. Exporte o cookies.txt de novo pelo "
            "navegador (logado no YouTube) e importe outra vez.")
    elif vencidos_youtube:
        mensagem = (
            f"Arquivo válido, mas {vencidos_youtube} cookie(s) do YouTube já "
            "venceram. Se aparecer pedido de login, exporte novamente.")
    else:
        mensagem = ("Arquivo válido e pronto: o yt-dlp já vai usá-lo nos "
                    "próximos downloads e pesquisas.")
    return InfoCookies(True, destino, True, total, youtube, mensagem,
                       vencidos, vencidos_youtube)


__all__ = [
    "ErroCookies", "InfoCookies", "analisar_conteudo", "caminho_destino",
    "contar_vencidos", "importar", "remover", "status",
]
