"""Histórico durável de conclusões e log estruturado de falhas (JSON Lines)."""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from configuracoes import CONFIG, Configuracoes


class Historico:
    def __init__(self, configuracoes: Configuracoes = CONFIG):
        self.config = configuracoes
        self._lock = threading.Lock()

    def registrar(self, *, url: str, formato: str, status: str,
                  caminho: str | Path | None = None, mensagem: str = "",
                  inicio: str | None = None) -> dict[str, Any]:
        """Grava um registro; ``data_hora`` é a data do registro (a exibida)."""
        registro: dict[str, Any] = {
            "data_hora": datetime.now(timezone.utc).isoformat(),
            "url": url,
            "formato": formato,
            "status": status,
            "caminho": str(caminho) if caminho is not None else None,
            "mensagem": mensagem,
            "inicio": inicio,
        }
        destino = self.config.erros if status.startswith("erro") else self.config.historico
        destino.parent.mkdir(parents=True, exist_ok=True)
        linha = json.dumps(registro, ensure_ascii=False)
        with self._lock, destino.open("a", encoding="utf-8") as arquivo:
            arquivo.write(linha + "\n")
            arquivo.flush()
        return registro

    def listar(self, limite: int = 50, *, incluir_erros: bool = False) -> list[dict[str, Any]]:
        if limite < 1:
            raise ValueError("O limite precisa ser maior que zero.")
        arquivos = [self.config.historico]
        if incluir_erros:
            arquivos.append(self.config.erros)
        registros: list[dict[str, Any]] = []
        for arquivo in arquivos:
            if not arquivo.is_file():
                continue
            try:
                for linha in arquivo.read_text(encoding="utf-8").splitlines():
                    try:
                        valor = json.loads(linha)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(valor, dict):
                        registros.append(valor)
            except OSError:
                continue
        registros.sort(key=lambda r: str(r.get("data_hora", "")), reverse=True)
        return registros[:limite]
