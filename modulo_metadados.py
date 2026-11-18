"""Módulo de metadados da IA 2 para o núcleo da IA 1 (ver INTEGRATION.md).

Uso (a partir da raiz do projeto):

    # Windows PowerShell
    $env:BAIXADOR_METADATA_MODULE = "modulo_metadados"
    python musica.py download "https://..." --formato mp3

    # Linux/macOS
    BAIXADOR_METADATA_MODULE=modulo_metadados python musica.py download "https://..." --formato mp3

Sem a variável, o núcleo funciona normalmente, sem enriquecimento.
Este arquivo é só a fachada do contrato: a implementação vive em
``metadados.py`` (tags/capa), ``inteligencia.py`` (identificação) e
``capas.py`` (capas oficiais).
"""

from __future__ import annotations

from metadados import processar_mp3
# O adaptador do núcleo reaproveita este processador para saber o que a
# identificação confirmou (``ultimo_resumo``) e quais APIs falharam. O contrato
# continua sendo apenas ``processar_mp3``; isto é um extra opcional.
from metadados import criar_processador_padrao

__all__ = ["criar_processador_padrao", "processar_mp3"]
