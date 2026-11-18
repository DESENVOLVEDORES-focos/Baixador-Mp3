"""Entrada oficial do Baixador-Mp3.

Abre a **Central Musical** (barra lateral, biblioteca, playlists, fila e
reprodutor). A interface antiga por abas continua disponível com
``python main.py --classica`` para quem já estava acostumado — nada foi
removido, só deixou de ser a porta de entrada.

Como o ``iniciar.bat`` chama este arquivo (com ``pythonw``, sem console), todo
erro precisa aparecer de forma legível: janela quando há Tkinter, texto no
console quando não há.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass

VERSAO = "6.0"

AJUDA = """\
Baixador-Mp3 — uso

  python main.py               abre a Central Musical (padrão)
  python main.py --classica    abre a interface antiga por abas
  python main.py --versao      mostra a versão
  python main.py --ajuda       mostra esta ajuda

Nada aqui precisa ser editado à mão: cookies, chave de IA, pasta de músicas e
qualidade do MP3 se ajustam dentro do programa, na página CONFIGURAÇÕES.
"""


@dataclass(frozen=True)
class Escolha:
    modo: str  # "central", "classica", "versao" ou "ajuda"

    @property
    def abre_janela(self) -> bool:
        return self.modo in {"central", "classica"}


def escolher_modo(argumentos: list[str]) -> Escolha:
    """Traduz a linha de comando. Sem argumento = Central Musical."""
    for argumento in argumentos:
        limpo = argumento.strip().lower()
        if limpo in {"--classica", "-c", "--classic", "--antiga"}:
            return Escolha("classica")
        if limpo in {"--versao", "-v", "--version"}:
            return Escolha("versao")
        if limpo in {"--ajuda", "-h", "--help", "-?"}:
            return Escolha("ajuda")
        if limpo in {"--central", ""}:
            continue
        # Argumento desconhecido não pode abrir a tela errada em silêncio.
        raise SystemExit(f"Opção desconhecida: {argumento}\n\n{AJUDA}")
    return Escolha("central")


def _avisar(titulo: str, mensagem: str) -> None:
    """Mostra o erro onde o usuário estiver olhando."""
    try:
        from tkinter import messagebox

        messagebox.showerror(titulo, mensagem)
    except Exception:
        pass
    print(f"[ERRO] {mensagem}", file=sys.stderr)


def main(argumentos: list[str] | None = None) -> int:
    escolha = escolher_modo(list(sys.argv[1:] if argumentos is None else argumentos))
    if escolha.modo == "ajuda":
        print(AJUDA)
        return 0
    if escolha.modo == "versao":
        print(f"Baixador-Mp3 {VERSAO}")
        return 0
    try:
        import tkinter

        del tkinter
    except Exception as erro:
        _avisar("Baixador-Mp3", "Tkinter não está disponível neste Python. "
                                "Rode configurar.bat para instalar as dependências."
                                f"\n\nDetalhe técnico: {erro}")
        return 1
    try:
        if escolha.modo == "classica":
            from baixador.app import interface

            return interface.main()
        from baixador.app import central_app

        central_app.iniciar()
        return 0
    except SystemExit:
        raise
    except Exception as erro:
        _avisar("Baixador-Mp3", f"Falha ao iniciar: {erro}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
