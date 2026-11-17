"""Fila persistente, protegida contra gravações parciais e duplicatas ativas."""

from __future__ import annotations

import json
import os
import threading
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal

from configuracoes import CONFIG, Configuracoes
from downloader import validar_url


@dataclass
class ItemFila:
    id: str
    url: str
    formato: Literal["mp3", "mp4"]
    tentativas: int = 0
    status: str = "pendente"
    criado_em: str = ""
    atualizado_em: str = ""
    ultimo_erro: str = ""


class FilaDownloads:
    def __init__(self, configuracoes: Configuracoes = CONFIG):
        self.config = configuracoes
        self._lock = threading.RLock()

    def listar(self, *, todos: bool = False) -> list[ItemFila]:
        with self._lock:
            itens = self._ler()
            return itens if todos else [item for item in itens if item.status == "pendente"]

    def adicionar(self, url: str, formato: Literal["mp3", "mp4"]) -> ItemFila:
        url = validar_url(url)
        if formato not in ("mp3", "mp4"):
            raise ValueError("Formato deve ser 'mp3' ou 'mp4'.")
        with self._lock:
            itens = self._ler()
            existente = next((i for i in itens if i.url == url and i.formato == formato
                              and i.status in {"pendente", "processando"}), None)
            if existente:
                return existente
            agora = datetime.now(timezone.utc).isoformat()
            item = ItemFila(uuid.uuid4().hex, url, formato, criado_em=agora, atualizado_em=agora)
            itens.append(item)
            self._gravar(itens)
            return item

    def reivindicar(self) -> ItemFila | None:
        with self._lock:
            itens = self._ler()
            for item in itens:
                if item.status == "pendente":
                    item.status = "processando"
                    item.tentativas += 1
                    item.atualizado_em = datetime.now(timezone.utc).isoformat()
                    self._gravar(itens)
                    return item
            return None

    def concluir(self, item_id: str) -> None:
        self._atualizar(item_id, status="concluido", ultimo_erro="")

    def falhar(self, item_id: str, mensagem: str, *, max_tentativas: int = 3) -> None:
        if max_tentativas < 1:
            raise ValueError("max_tentativas deve ser pelo menos 1.")
        with self._lock:
            itens = self._ler()
            item = self._obter(itens, item_id)
            item.status = "pendente" if item.tentativas < max_tentativas else "falhou"
            item.ultimo_erro = mensagem
            item.atualizado_em = datetime.now(timezone.utc).isoformat()
            self._gravar(itens)

    def reabrir_falhas(self) -> int:
        with self._lock:
            itens = self._ler()
            reabertos = 0
            for item in itens:
                if item.status == "falhou":
                    item.status = "pendente"
                    item.tentativas = 0
                    item.ultimo_erro = ""
                    item.atualizado_em = datetime.now(timezone.utc).isoformat()
                    reabertos += 1
            if reabertos:
                self._gravar(itens)
            return reabertos

    def reabrir_interrompidos(self, idade_minima_segundos: int = 6 * 60 * 60) -> int:
        """Recupera leases antigos deixados por um worker encerrado abruptamente."""
        if idade_minima_segundos < 0:
            raise ValueError("A idade mínima não pode ser negativa.")
        limite = datetime.now(timezone.utc) - timedelta(seconds=idade_minima_segundos)
        with self._lock:
            itens = self._ler()
            reabertos = 0
            for item in itens:
                if item.status != "processando":
                    continue
                try:
                    atualizado = datetime.fromisoformat(item.atualizado_em)
                    if atualizado.tzinfo is None:
                        atualizado = atualizado.replace(tzinfo=timezone.utc)
                except ValueError:
                    continue
                if atualizado <= limite:
                    item.status = "pendente"
                    item.ultimo_erro = "Worker interrompido; item recuperado automaticamente."
                    item.atualizado_em = datetime.now(timezone.utc).isoformat()
                    reabertos += 1
            if reabertos:
                self._gravar(itens)
            return reabertos

    def _atualizar(self, item_id: str, **campos: str) -> None:
        with self._lock:
            itens = self._ler()
            item = self._obter(itens, item_id)
            for nome, valor in campos.items():
                setattr(item, nome, valor)
            item.atualizado_em = datetime.now(timezone.utc).isoformat()
            self._gravar(itens)

    @staticmethod
    def _obter(itens: list[ItemFila], item_id: str) -> ItemFila:
        for item in itens:
            if item.id == item_id:
                return item
        raise KeyError(f"Item não encontrado na fila: {item_id}")

    def _ler(self) -> list[ItemFila]:
        caminho = self.config.fila
        if not caminho.is_file():
            return []
        try:
            dados = json.loads(caminho.read_text(encoding="utf-8"))
            if not isinstance(dados, list):
                raise ValueError("A raiz do arquivo de fila precisa ser uma lista.")
            return [ItemFila(**item) for item in dados if isinstance(item, dict)]
        except (OSError, json.JSONDecodeError, TypeError) as erro:
            raise RuntimeError(f"Não foi possível ler a fila {caminho}: {erro}") from erro

    def _gravar(self, itens: list[ItemFila]) -> None:
        caminho = self.config.fila
        caminho.parent.mkdir(parents=True, exist_ok=True)
        temporario = caminho.with_name(caminho.name + ".tmp")
        try:
            temporario.write_text(
                json.dumps([asdict(item) for item in itens], ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            os.replace(temporario, caminho)
        finally:
            try:
                temporario.unlink(missing_ok=True)
            except OSError:
                pass
