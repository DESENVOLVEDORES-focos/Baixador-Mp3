"""Nomes de arquivo organizados e seguros (multi-plataforma).

Regras:

- ``Artista - Título`` (ou só ``Título`` quando o artista é desconhecido);
- caracteres proibidos no Windows (``<>:"/\\|?*``) e de controle removidos;
- nomes reservados do Windows (``CON``, ``PRN``, ``AUX``, ``NUL``, ``COM1``…)
  recebem sufixo, porque quebram a criação do arquivo;
- ponto/espaço no fim são removidos (o Windows não cria esses nomes);
- comprimento limitado por componente (255 é o máximo do sistema de arquivos;
  usamos 150 para caber ``Artista - Título`` sem truncar o título inteiro);
- opcionalmente a estrutura ``Artista/Álbum/`` para quem organiza por álbum,
  reaproveitando os dados confirmados pela identificação musical — nunca
  inventados.

Nada aqui toca em arquivos: são funções puras, usadas depois que o arquivo
final já existe e precisa ser publicado com nome apresentável.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Any, Mapping

PROIBIDOS_WINDOWS = '<>:"/\\|?*'
RESERVADOS_WINDOWS = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}
LIMITE_COMPONENTE = 150

_RE_ESPACOS = re.compile(r"\s+")
_RE_SEPARADOR_PADRAO = re.compile(r"\s*[-–—]\s*")
_RE_ID_COLCHETES = re.compile(r"\s*\[[A-Za-z0-9_-]{6,}\]$")


def limpar_componente(nome: str, *, limite: int = LIMITE_COMPONENTE) -> str:
    """Transforma um texto em um nome de arquivo/pasta válido em qualquer SO."""
    texto = unicodedata.normalize("NFC", str(nome or ""))
    texto = "".join(
        caractere for caractere in texto
        if caractere not in PROIBIDOS_WINDOWS
        and ord(caractere) >= 32
        and unicodedata.category(caractere) not in {"Cc", "Cf", "Cs", "Co"}
    )
    texto = _RE_ESPACOS.sub(" ", texto).strip(" .")
    if not texto:
        return ""
    if texto.upper() in RESERVADOS_WINDOWS or texto.split(".")[0].upper() in RESERVADOS_WINDOWS:
        texto = f"_{texto}"
    if len(texto) > limite:
        texto = texto[:limite].rstrip(" .")
    return texto


def nome_arquivo(*, titulo: str, artista: str = "", desconhecido: str = "") -> str:
    """``Artista - Título`` sem extensão; nunca devolve vazio."""
    titulo_limpo = limpar_componente(titulo)
    artista_limpo = limpar_componente(artista)
    if artista_limpo and titulo_limpo:
        # Evita "Queen - Queen - Bohemian Rhapsody": o título que já começa pelo
        # artista (com ou sem separador) não é prefixado de novo.
        titulo_baixo = titulo_limpo.lower()
        artista_baixo = artista_limpo.lower()
        if titulo_baixo.startswith(artista_baixo):
            # "Queen - Bohemian Rhapsody" → já está completo (não prefixar).
            # "Queen" → idêntico ao artista: devolve sem repetir.
            return titulo_limpo
        return f"{artista_limpo} - {titulo_limpo}"[:LIMITE_COMPONENTE].rstrip(" .")
    if titulo_limpo:
        return titulo_limpo
    if artista_limpo:
        return artista_limpo
    return limpar_componente(desconhecido) or "Conteúdo baixado"


def titulo_e_artista_do_arquivo(nome: str) -> tuple[str, str]:
    """Extrai ``(título, artista)`` do nome que o yt-dlp gerou.

    Aceita ``"Artista - Título [id]"`` e ``"Título [id]"``; o ID entre colchetes
    que o núcleo acrescenta é descartado.
    """
    base = Path(nome).stem if nome else ""
    base = _RE_ID_COLCHETES.sub("", base).strip()
    partes = _RE_SEPARADOR_PADRAO.split(base, maxsplit=1)
    if len(partes) == 2 and partes[0].strip() and partes[1].strip():
        return partes[1].strip(), partes[0].strip()
    return base, ""


def subpasta(resumo: Mapping[str, Any], *, artista: str = "",
             titulo: str = "") -> Path | None:
    """Pasta ``Artista/Álbum`` quando há dados; ``None`` quando não há."""
    artista_limpo = limpar_componente(str(resumo.get("artista") or artista or ""))
    album_limpo = limpar_componente(str(resumo.get("album") or ""))
    if not artista_limpo and not album_limpo:
        return None
    partes = [parte for parte in (artista_limpo, album_limpo) if parte]
    return Path(*partes) if partes else None


def caminho_disponivel(destino: Path, nome: str, extensao: str = "") -> Path:
    """Primeiro caminho livre em ``destino`` (``nome``, ``nome (2)``, …)."""
    extensao = extensao or Path(nome).suffix
    base = Path(nome).stem if extensao and nome.endswith(extensao) else nome
    alvo = destino / f"{base}{extensao}"
    contador = 1
    while alvo.exists():
        contador += 1
        alvo = destino / f"{base} ({contador}){extensao}"
    return alvo


__all__ = [
    "LIMITE_COMPONENTE", "caminho_disponivel", "limpar_componente",
    "nome_arquivo", "subpasta", "titulo_e_artista_do_arquivo",
]
