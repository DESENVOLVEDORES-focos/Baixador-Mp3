"""Configuração temporária para testes (pasta própria, nada do usuário).

Fica na raiz do projeto de propósito: os testes rodam a partir da raiz e
assim o arquivo é empacotado junto (o ZIP precisa passar na suíte).
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from configuracoes import Configuracoes


def configuracao_de_teste(raiz: Path | None = None) -> Configuracoes:
    """``Configuracoes`` apontando para uma pasta temporária descartável."""
    base = Path(raiz or tempfile.mkdtemp(prefix="baixador-teste-"))
    return Configuracoes(raiz=base,
                         diretorio_musicas=base / "Musicas",
                         diretorio_videos=base / "Videos")
