"""Contexto da mídia escolhida na pesquisa (contrato entre interface e núcleo).

Quando o usuário seleciona um resultado, já sabemos título, canal, duração e
thumbnail. Passar isso ao download deixa a identificação musical da IA 2 muito
mais precisa do que inferir tudo do nome do arquivo — e permite registrar
metadados honestos mesmo quando as APIs estão fora do ar.

Tudo aqui é opcional e tolerante: qualquer campo ausente continua valendo o
comportamento anterior (derivar do nome do arquivo).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class ContextoMidia:
    titulo: str = ""
    canal: str = ""
    duracao: int | None = None
    thumbnail: str = ""
    url: str = ""

    def como_metadados(self) -> dict[str, Any]:
        """Campos extras entregues a ``processar_mp3(caminho, metadados)``."""
        dados: dict[str, Any] = {}
        if self.titulo:
            dados["titulo"] = self.titulo
        if self.canal:
            dados["canal"] = self.canal
        if self.duracao is not None:
            dados["duracao"] = self.duracao
        if self.thumbnail:
            dados["thumbnail"] = self.thumbnail
        return dados

    @classmethod
    def de_resultado(cls, resultado: Any) -> "ContextoMidia":
        """Aceita ``ResultadoPesquisa`` (duck typing) ou dicionário."""
        if resultado is None:
            return cls()
        if isinstance(resultado, Mapping):
            return cls.de_mapping(resultado)
        return cls(
            titulo=str(getattr(resultado, "titulo", "") or "").strip(),
            canal=str(getattr(resultado, "canal", "") or "").strip(),
            duracao=_inteiro(getattr(resultado, "duracao", None)),
            thumbnail=str(getattr(resultado, "thumbnail", "") or "").strip(),
            url=str(getattr(resultado, "url", "") or "").strip(),
        )

    @classmethod
    def de_mapping(cls, dados: Mapping[str, Any] | None) -> "ContextoMidia":
        if not dados:
            return cls()
        return cls(
            titulo=str(dados.get("titulo") or "").strip(),
            canal=str(dados.get("canal") or dados.get("uploader") or "").strip(),
            duracao=_inteiro(dados.get("duracao")),
            thumbnail=str(dados.get("thumbnail") or "").strip(),
            url=str(dados.get("url") or "").strip(),
        )

    @classmethod
    def normalizar(cls, valor: Any) -> "ContextoMidia":
        """Aceita ``ContextoMidia``, resultado, dicionário, ``None`` ou URL."""
        if isinstance(valor, ContextoMidia):
            return valor
        if isinstance(valor, str):
            return cls(url=valor.strip())
        if isinstance(valor, Mapping):
            return cls.de_mapping(valor)
        if valor is None:
            return cls()
        return cls.de_resultado(valor)


def _inteiro(valor: Any) -> int | None:
    try:
        if valor is None or valor == "":
            return None
        return int(float(valor))
    except (TypeError, ValueError, OverflowError):
        return None


__all__ = ["ContextoMidia"]
