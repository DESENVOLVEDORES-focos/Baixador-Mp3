"""Regras de seleção do que entra no download — sem esconder nada do usuário.

Duas decisões moram aqui, para a pesquisa, a playlist aberta e a cesta usarem
**a mesma** regra (antes cada tela teria a sua):

- **teto de duração**: item mais longo que o limite aparece, marcado e
  desmarcado, com o motivo. Nunca some sem explicação.
- **gravação ao vivo/show**: reaproveita `previa.analisar`, que é conservador e
  sempre diz qual foi o indício.

O usuário escolhe na tela se quer filtrar ao vivo (padrão) e qual o teto.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from baixador.midia.previa import analisar

# Tempo de download aproximado usado na estimativa da cesta (MP3 ~128 kbps).
BYTES_POR_SEGUNDO = 16_000


@dataclass(frozen=True)
class Avaliacao:
    """Por que um item entra (ou não) e qual motivo mostrar."""

    marcar: bool
    motivo: str = ""
    ao_vivo: bool = False
    acima_do_teto: bool = False

    @property
    def bloqueado(self) -> bool:
        return bool(self.motivo)


def avaliar(titulo: str = "", canal: str = "", duracao: int | None = None,
            *, duracao_maxima_min: int = 0,
            filtrar_ao_vivo: bool = False) -> Avaliacao:
    """Decide a marcação inicial de um item, sempre com motivo legível."""
    teto = max(0, int(duracao_maxima_min or 0)) * 60
    acima = bool(teto and duracao and duracao > teto)
    analise = analisar(titulo or "", canal or "", duracao)
    ao_vivo = bool(filtrar_ao_vivo and analise.possivel_ao_vivo)
    motivos: list[str] = []
    if acima:
        minutos = int(duracao // 60) if duracao else 0
        motivos.append(f"acima do limite ({minutos} min > {duracao_maxima_min} min)")
    if ao_vivo:
        indícios = ", ".join(analise.indicios[:2]) or "título"
        motivos.append(f"parece ao vivo/show ({indícios})")
    return Avaliacao(marcar=not motivos, motivo="; ".join(motivos),
                     ao_vivo=ao_vivo, acima_do_teto=acima)


def filtrar(itens: Iterable[Any], *, duracao_maxima_min: int = 0,
            filtrar_ao_vivo: bool = False) -> list[tuple[Any, Avaliacao]]:
    """``[(item, avaliação)]`` na mesma ordem — nada é descartado."""
    return [
        (item, avaliar(getattr(item, "titulo", ""), getattr(item, "canal", ""),
                       getattr(item, "duracao", None),
                       duracao_maxima_min=duracao_maxima_min,
                       filtrar_ao_vivo=filtrar_ao_vivo))
        for item in itens
    ]


def estimar(segundos: Iterable[int | None]) -> tuple[int, int]:
    """``(segundos_totais, bytes_aproximados)`` para a cesta antes de baixar."""
    total = sum(int(s) for s in segundos if s)
    return total, total * BYTES_POR_SEGUNDO


def tempo_legivel(segundos: int) -> str:
    """``3725`` -> ``"1h 02min"``; ``95`` -> ``"1min 35s"``."""
    segundos = max(0, int(segundos or 0))
    horas, resto = divmod(segundos, 3600)
    minutos, seg = divmod(resto, 60)
    if horas:
        return f"{horas}h {minutos:02d}min"
    if minutos:
        return f"{minutos}min {seg:02d}s"
    return f"{seg}s"


def tamanho_legivel(bytes_: int) -> str:
    """Tamanho aproximado, no padrão que o usuário lê (MB)."""
    valor = float(max(0, int(bytes_ or 0)))
    for unidade in ("B", "KB", "MB", "GB"):
        if valor < 1024 or unidade == "GB":
            return f"{valor:.0f} {unidade}" if unidade == "B" else f"{valor:.1f} {unidade}"
        valor /= 1024
    return f"{valor:.1f} GB"


__all__ = [
    "Avaliacao", "avaliar", "estimar", "filtrar", "tamanho_legivel",
    "tempo_legivel",
]
