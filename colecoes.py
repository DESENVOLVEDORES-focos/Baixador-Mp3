"""Cobertura musical da biblioteca: completar metadados e capas em lote.

Duas operações, ambas sobre arquivos que **já estão no disco**:

- :func:`completar_metadados` — usa o processador musical existente
  (``metadados.ProcessadorMusical``: APIs públicas + IA opcional) e regrava as
  tags ID3. Nunca inventa: o processador só preenche o que uma fonte confirmou.
- :func:`incorporar_capa` — busca capa de álbum em ``capas.GerenciadorCapas``
  (iTunes/Cover Art Archive/Deezer) e grava no próprio MP3 com
  ``metadados.aplicar_metadados``.

O resultado por arquivo é sempre um dicionário com ``caminho``, ``ok``,
``mensagem`` e o que mudou — a interface mostra isso linha a linha, sem inventar
sucesso para arquivo que não foi confirmado.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

from biblioteca import Biblioteca, Musica
from capas import ErroCapa, GerenciadorCapas, validar_imagem
from metadados import (
    ConfigMetadados, InfoMusica, aplicar_metadados, criar_processador_padrao,
    ler_metadados,
)

log = logging.getLogger("baixador.colecoes")

CAMPOS_TEXTO = ("titulo", "artista", "album", "ano", "genero", "faixa")


@dataclass
class ResultadoCobertura:
    """O que aconteceu com um arquivo (honesto, campo por campo)."""

    caminho: str
    ok: bool
    mensagem: str
    campos: dict[str, str] = field(default_factory=dict)
    capa: bool = False


def _info_do_banco(musica: Musica) -> dict[str, Any]:
    return {
        "titulo": musica.titulo,
        "artista": musica.artista,
        "album": musica.album,
        "ano": musica.ano,
        "genero": musica.genero,
        "faixa": musica.faixa,
        "duracao": musica.duracao,
        "url": musica.origem_url,
        "caminho": musica.caminho,
    }


def completar_metadados(biblioteca: Biblioteca,
                        musicas: Iterable[Musica] | None = None,
                        *,
                        processador: Any | None = None,
                        ao_arquivo: Callable[[int, int, str], None] | None = None,
                        ) -> list[ResultadoCobertura]:
    """Roda a identificação musical nos arquivos e regrava as tags.

    ``musicas`` vazio = todas as que estão sem capa ou com artista/álbum vazios.
    """
    alvo = list(musicas) if musicas is not None else [
        m for m in biblioteca.listar()
        if not m.artista or not m.album or not m.tem_capa]
    processador = processador or criar_processador_padrao()
    resultados: list[ResultadoCobertura] = []
    total = len(alvo)
    for posicao, musica in enumerate(alvo, start=1):
        if callable(ao_arquivo):
            try:
                ao_arquivo(posicao, total, musica.titulo_exibicao)
            except Exception:
                pass
        caminho = Path(musica.caminho)
        if not caminho.is_file():
            resultados.append(ResultadoCobertura(
                caminho=str(caminho), ok=False,
                mensagem="Arquivo não encontrado no disco."))
            continue
        antes = ler_metadados(caminho)
        try:
            dados = _info_do_banco(musica)
            dados.update({"formato": "mp3", "titulo": dados.get("titulo") or caminho.stem})
            novo = processador.processar_mp3(caminho, dados)
            destino = Path(novo) if novo else caminho
        except Exception as erro:
            log.info("Metadados falharam em %s: %s", caminho.name, erro)
            resultados.append(ResultadoCobertura(
                caminho=str(caminho), ok=False,
                mensagem=f"Não foi possível completar os metadados: {erro}"))
            continue
        depois = ler_metadados(destino)
        mudancas = {
            campo: str(depois.get(campo, ""))
            for campo in CAMPOS_TEXTO
            if str(depois.get(campo, "")) != str(antes.get(campo, ""))
            and str(depois.get(campo, "")).strip()
        }
        ganhou_capa = bool(depois.get("tem_capa")) and not antes.get("tem_capa")
        # O banco acompanha o que foi realmente gravado (fonte de verdade: disco).
        biblioteca.adicionar(destino, dados={
            campo: depois.get(campo) for campo in CAMPOS_TEXTO
            if depois.get(campo)}, origem_url=musica.origem_url)
        partes = []
        if mudancas:
            partes.append("Campos preenchidos: " + ", ".join(sorted(mudancas)))
        if ganhou_capa:
            partes.append("capa incorporada")
        resultados.append(ResultadoCobertura(
            caminho=str(destino), ok=True,
            mensagem="; ".join(partes) or "Nada novo confirmado pelas fontes.",
            campos=mudancas, capa=ganhou_capa))
    return resultados


def _info_para_capa(musica: Musica) -> InfoMusica:
    return InfoMusica(
        titulo=musica.titulo or Path(musica.caminho).stem,
        artista=musica.artista,
        album=musica.album,
        ano=musica.ano,
    )


def incorporar_capa(biblioteca: Biblioteca, musica: Musica, *,
                    gerenciador: GerenciadorCapas | None = None,
                    imagem: bytes | None = None,
                    ) -> ResultadoCobertura:
    """Incorpora a capa do álbum (ou a imagem escolhida pelo usuário)."""
    caminho = Path(musica.caminho)
    if not caminho.is_file():
        return ResultadoCobertura(caminho=str(caminho), ok=False,
                                  mensagem="Arquivo não encontrado no disco.")
    if not musica.artista and not musica.album:
        return ResultadoCobertura(
            caminho=str(caminho), ok=False,
            mensagem=("Sem artista/álbum identificado: a capa não pode ser "
                      "confirmada. Rode a identificação musical antes."))
    try:
        if imagem is None:
            gerenciador = gerenciador or GerenciadorCapas()
            imagem = gerenciador.buscar_e_baixar(
                _info_para_capa(musica), musica.origem_url or None)
        if not imagem:
            return ResultadoCobertura(
                caminho=str(caminho), ok=False,
                mensagem="Nenhuma capa válida encontrada nas fontes consultadas.")
        validar_imagem(imagem)
        aplicar_metadados(caminho, _info_para_capa(musica), capa=imagem)
    except (ErroCapa, OSError) as erro:
        return ResultadoCobertura(caminho=str(caminho), ok=False,
                                  mensagem=f"Capa não incorporada: {erro}")
    except Exception as erro:
        return ResultadoCobertura(caminho=str(caminho), ok=False,
                                  mensagem=f"Falha ao incorporar a capa: {erro}")
    biblioteca.adicionar(caminho, origem_url=musica.origem_url)
    return ResultadoCobertura(caminho=str(caminho), ok=True,
                              mensagem="Capa incorporada ao MP3.", capa=True)


def incorporar_capas(biblioteca: Biblioteca,
                     musicas: Iterable[Musica] | None = None, *,
                     gerenciador: GerenciadorCapas | None = None,
                     ao_arquivo: Callable[[int, int, str], None] | None = None,
                     ) -> list[ResultadoCobertura]:
    """Busca e incorpora capa em vários arquivos (só onde há dado confirmado)."""
    alvo = list(musicas) if musicas is not None else biblioteca.sem_capa()
    gerenciador = gerenciador or GerenciadorCapas()
    resultados: list[ResultadoCobertura] = []
    total = len(alvo)
    for posicao, musica in enumerate(alvo, start=1):
        if callable(ao_arquivo):
            try:
                ao_arquivo(posicao, total, musica.titulo_exibicao)
            except Exception:
                pass
        resultados.append(incorporar_capa(
            biblioteca, musica, gerenciador=gerenciador))
    return resultados


def config_metadados_para(preferencias: Any) -> ConfigMetadados:
    """Liga/desliga IA e capas conforme a tela de configurações."""
    base = ConfigMetadados.from_env()
    return ConfigMetadados(
        buscar_capa=bool(getattr(preferencias, "buscar_capas", base.buscar_capa)),
        timeout=base.timeout,
        usar_ia=bool(getattr(preferencias, "metadados_ativos", base.usar_ia)),
    )


__all__ = [
    "ResultadoCobertura", "completar_metadados", "incorporar_capa",
    "incorporar_capas", "config_metadados_para",
]
