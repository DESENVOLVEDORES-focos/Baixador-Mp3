"""Fila de seleção acumulativa (o coração do fluxo de vários artistas).

O usuário pesquisa "Guns N' Roses", marca 3 músicas; pesquisa "Queen", marca 2;
pesquisa "Led Zeppelin", marca 4. **Tudo fica junto**, numa única lista que
sobrevive à navegação entre páginas e ao fechamento do programa.

Independe da fila de downloads (``fila.py``, do núcleo): aqui é a "cesta" que o
usuário monta e revisa antes de mandar processar. Persistência: JSON na pasta de
dados, gravação atômica.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from biblioteca import chave_busca
from configuracoes import CONFIG, Configuracoes

log = logging.getLogger("baixador.selecao")

ARQUIVO = "selecao.json"


@dataclass
class ItemSelecao:
    """Um vídeo escolhido, antes de virar download."""

    url: str
    titulo: str = ""
    canal: str = ""
    duracao: int | None = None
    formato: str = "mp3"
    thumbnail: str = ""
    origem: str = ""            # "pesquisa", "playlist: <nome>", "url"
    adicionado_em: str = ""
    id: str = ""

    @property
    def chave(self) -> str:
        """Identidade para detectar duplicata (mesmo vídeo, mesmo formato)."""
        return f"{self.url}|{self.formato}"

    @property
    def titulo_exibicao(self) -> str:
        return self.titulo or self.url

    @property
    def duracao_formatada(self) -> str:
        if not self.duracao:
            return "--:--"
        minutos, segundos = divmod(int(self.duracao), 60)
        horas, minutos = divmod(minutos, 60)
        return (f"{horas}:{minutos:02}:{segundos:02}" if horas
                else f"{minutos}:{segundos:02}")

    def como_dicionario(self) -> dict[str, Any]:
        return asdict(self)


def _agora() -> str:
    return datetime.now(timezone.utc).isoformat()


class Selecao:
    """Lista persistente de vídeos escolhidos, sem duplicatas acidentais."""

    def __init__(self, configuracoes: Configuracoes = CONFIG,
                 caminho: Path | None = None):
        self.config = configuracoes
        self._caminho = Path(caminho) if caminho else configuracoes.dados / ARQUIVO
        self._lock = threading.RLock()
        self._itens: list[ItemSelecao] = []
        self._removidos: list[tuple[int, ItemSelecao]] = []
        self._carregar()

    # -- persistência -------------------------------------------------------
    def _carregar(self) -> None:
        if not self._caminho.is_file():
            return
        try:
            dados = json.loads(self._caminho.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as erro:
            log.info("Seleção ilegível (%s): começando vazia.", erro)
            return
        itens = dados.get("itens") if isinstance(dados, dict) else dados
        for bruto in itens or []:
            if not isinstance(bruto, dict) or not bruto.get("url"):
                continue
            campos = {chave: valor for chave, valor in bruto.items()
                      if chave in ItemSelecao.__dataclass_fields__}
            self._itens.append(ItemSelecao(**campos))

    def _gravar(self) -> None:
        self._caminho.parent.mkdir(parents=True, exist_ok=True)
        temporario = self._caminho.with_suffix(".tmp")
        dados = {"atualizado_em": _agora(),
                 "itens": [item.como_dicionario() for item in self._itens]}
        try:
            temporario.write_text(json.dumps(dados, ensure_ascii=False, indent=1),
                                  encoding="utf-8")
            os.replace(temporario, self._caminho)
        except OSError as erro:
            log.info("Não foi possível salvar a seleção: %s", erro)

    # -- consulta -----------------------------------------------------------
    def listar(self) -> list[ItemSelecao]:
        with self._lock:
            return list(self._itens)

    def quantidade(self) -> int:
        return len(self._itens)

    def vazio(self) -> bool:
        return not self._itens

    def duracao_total(self) -> int:
        return sum(item.duracao or 0 for item in self._itens)

    def duracao_formatada(self) -> str:
        segundos = self.duracao_total()
        horas, resto = divmod(segundos, 3600)
        minutos, _ = divmod(resto, 60)
        return f"{horas}h{minutos:02}" if horas else f"{minutos} min"

    def contem(self, url: str, formato: str = "mp3") -> bool:
        alvo = f"{url}|{formato}"
        return any(item.chave == alvo for item in self._itens)

    def duplicados_na_lista(self) -> list[str]:
        """URLs repetidas (proteção para dados antigos/editados à mão)."""
        vistos: set[str] = set()
        repetidos: list[str] = []
        for item in self._itens:
            if item.chave in vistos:
                repetidos.append(item.url)
            vistos.add(item.chave)
        return repetidos

    # -- alterações ---------------------------------------------------------
    def adicionar(self, item: ItemSelecao) -> tuple[bool, int]:
        """Adiciona; devolve ``(entrou, total)``. Duplicata não entra de novo."""
        with self._lock:
            if not item.url:
                raise ValueError("Item sem URL não pode ser selecionado.")
            if self.contem(item.url, item.formato):
                return False, len(self._itens)
            if not item.adicionado_em:
                item.adicionado_em = _agora()
            if not item.id:
                item.id = f"{len(self._itens) + 1}-{_agora()}"
            self._itens.append(item)
            self._gravar()
            return True, len(self._itens)

    def adicionar_varios(self, itens: Iterable[ItemSelecao]) -> tuple[int, int]:
        """Adiciona em lote; devolve ``(adicionados, ignorados_por_duplicata)``."""
        adicionados = ignorados = 0
        with self._lock:
            for item in itens:
                entrou, _total = self.adicionar(item)
                if entrou:
                    adicionados += 1
                else:
                    ignorados += 1
        return adicionados, ignorados

    def remover(self, urls: Iterable[str]) -> int:
        alvos = set(urls)
        with self._lock:
            self._lembrar_remocao([(posicao, item)
                                   for posicao, item in enumerate(self._itens)
                                   if item.url in alvos])
            antes = len(self._itens)
            self._itens = [item for item in self._itens if item.url not in alvos]
            removidos = antes - len(self._itens)
            if removidos:
                self._gravar()
            return removidos

    def remover_indices(self, indices: Iterable[int]) -> int:
        alvos = {int(i) for i in indices}
        with self._lock:
            self._lembrar_remocao([(posicao, item)
                                   for posicao, item in enumerate(self._itens)
                                   if posicao in alvos])
            restantes = [item for posicao, item in enumerate(self._itens)
                         if posicao not in alvos]
            removidos = len(self._itens) - len(restantes)
            self._itens = restantes
            if removidos:
                self._gravar()
            return removidos

    def _lembrar_remocao(self, pares: list[tuple[int, Any]]) -> None:
        """Guarda (posição, item) para o ``desfazer_remocao`` — só a última."""
        self._removidos = sorted(pares, key=lambda par: par[0])

    def limpar(self) -> int:
        with self._lock:
            quantidade = len(self._itens)
            self._itens = []
            self._gravar()
            return quantidade

    def reordenar(self, origem: int, destino: int) -> bool:
        """Move um item (arrastar e soltar na tela)."""
        with self._lock:
            if not (0 <= origem < len(self._itens)):
                return False
            destino = max(0, min(destino, len(self._itens) - 1))
            item = self._itens.pop(origem)
            self._itens.insert(destino, item)
            self._gravar()
            return True

    def definir_formato(self, urls: Iterable[str], formato: str) -> int:
        if formato not in ("mp3", "mp4"):
            raise ValueError("Formato deve ser 'mp3' ou 'mp4'.")
        alvos = set(urls)
        alterados = 0
        with self._lock:
            for item in self._itens:
                if item.url in alvos and item.formato != formato:
                    item.formato = formato
                    alterados += 1
            if alterados:
                self._gravar()
        return alterados

    def ja_na_biblioteca(self, biblioteca: Any) -> list[Any]:
        """Itens cuja URL de origem já está na biblioteca (não baixar de novo).

        Compara ``origem_url`` gravada no banco, então não depende de o arquivo
        ter o mesmo nome. Serve para avisar antes de gastar download.
        """
        try:
            conhecidas = {m.origem_url for m in biblioteca.listar()
                          if getattr(m, "origem_url", "")}
        except Exception:
            return []
        return [item for item in self._itens if item.url in conhecidas]

    def estimativa(self) -> tuple[int, int]:
        """``(segundos, bytes aproximados)`` do que está na cesta."""
        from limites import estimar

        return estimar(item.duracao for item in self._itens)

    def desfazer_remocao(self) -> int:
        """Devolve os itens da última remoção (o "Desfazer" da tela).

        Guardar o que saiu e por qual posição evita o clássico "removi sem
        querer e agora não sei qual era".
        """
        removidos = list(getattr(self, "_removidos", []))
        if not removidos:
            return 0
        for posicao, item in removidos:
            if self.contem(item.url, item.formato):
                continue
            posicao = max(0, min(int(posicao), len(self._itens)))
            self._itens.insert(posicao, item)
        self._removidos = []
        self._gravar()
        return len(removidos)

    def mover_para(self, indice: int, destino: int) -> bool:
        """Move um item para o topo (0) ou para o fim (-1)."""
        with self._lock:
            if not 0 <= indice < len(self._itens):
                return False
            item = self._itens.pop(indice)
            if destino < 0 or destino >= len(self._itens):
                self._itens.append(item)
            else:
                self._itens.insert(destino, item)
            self._gravar()
            return True

    def agrupado_por_origem(self) -> dict[str, int]:
        """Quantos itens vieram de cada pesquisa/playlist (a tela mostra)."""
        grupos: dict[str, int] = {}
        for item in self._itens:
            rotulo = item.origem or "Sem origem"
            grupos[rotulo] = grupos.get(rotulo, 0) + 1
        return grupos

    def pesquisar(self, texto: str) -> list[ItemSelecao]:
        alvo = chave_busca(texto)
        return [item for item in self._itens
                if alvo in chave_busca(item.titulo)
                or alvo in chave_busca(item.canal)]

    def para_download(self) -> list[tuple[str, str]]:
        """``[(url, formato), ...]`` na ordem da tela, pronta para a fila."""
        return [(item.url, item.formato) for item in self._itens]


__all__ = ["ItemSelecao", "Selecao", "ARQUIVO"]
