"""Contrato opcional entre o núcleo de downloads e a inteligência musical (IA 2).

Um módulo externo pode expor ``processar_mp3(caminho, metadados)``. O núcleo
não duplica pesquisa de capas nem edição de tags: apenas encaminha o MP3 final.
"""

from __future__ import annotations

import importlib
import os
from pathlib import Path
from typing import Any, Mapping, Protocol


class ProcessadorMetadados(Protocol):
    def processar_mp3(self, caminho: Path, metadados: Mapping[str, Any]) -> Path | None:
        """Enriquece o MP3 no local ou retorna o caminho final alternativo."""


class AdaptadorMetadados:
    """Carrega opcionalmente o módulo indicado por ``BAIXADOR_METADATA_MODULE``."""

    def __init__(self, processador: ProcessadorMetadados | None = None):
        self._processador = processador or self._carregar_configurado()

    @property
    def disponivel(self) -> bool:
        return self._processador is not None

    @property
    def processador_real(self) -> ProcessadorMetadados | None:
        """Processador real, quando o módulo é importado por nome.

        ``_AdaptadorFuncao`` embrulha uma função sem estado; já o
        ``ProcessadorMusical`` guarda ``ultimo_resumo`` (o que foi confirmado e
        quais APIs falharam), que a interface/histórico precisam relatar.
        """
        if self._processador is None:
            return None
        # `_AdaptadorFuncao` guarda o processador com estado em `.real`
        interno = getattr(self._processador, "real", None)
        return interno if interno is not None else self._processador

    def processar_mp3(self, caminho: Path, metadados: Mapping[str, Any]) -> Path:
        if self._processador is None:
            return caminho
        resultado = self._processador.processar_mp3(caminho, metadados)
        final = Path(resultado) if resultado is not None else caminho
        if not final.is_file() or final.stat().st_size == 0:
            raise RuntimeError(f"O processador de metadados não produziu um MP3 válido: {final}")
        return final

    @staticmethod
    def _carregar_configurado() -> ProcessadorMetadados | None:
        nome_modulo = os.environ.get("BAIXADOR_METADATA_MODULE", "").strip()
        if not nome_modulo:
            return None
        modulo = importlib.import_module(nome_modulo)
        funcao = getattr(modulo, "processar_mp3", None)
        if not callable(funcao):
            raise ImportError(
                f"O módulo {nome_modulo!r} precisa expor a função processar_mp3(caminho, metadados)."
            )

        # Reaproveita o processador do módulo quando existir, para preservar
        # ``ultimo_resumo`` (relato de identificação e erros de API).
        interno = (getattr(modulo, "criar_processador_padrao", None)
                   or getattr(modulo, "ProcessadorMusical", None))

        class _AdaptadorFuncao:
            def __init__(self) -> None:
                # O módulo já expõe um processador com ``ultimo_resumo``:
                # usá-lo evita recriar cliente HTTP e perder o relato.
                self.real = interno() if callable(interno) else None

            def processar_mp3(self, caminho: Path, metadados: Mapping[str, Any]) -> Path | None:
                if self.real is not None:
                    return self.real.processar_mp3(caminho, metadados)
                return funcao(caminho, metadados)

        return _AdaptadorFuncao()
