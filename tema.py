"""Tema visual do aplicativo (escuro por padrão, claro opcional).

Só define cores, fontes e estilo do ``ttk`` — nada de lógica. Fica separado para
a interface não virar um arquivo gigante e para o usuário trocar de tema na
tela de Configurações sem reiniciar o programa.
"""

from __future__ import annotations

import logging

log = logging.getLogger("baixador.tema")

ESCURO = {
    "fundo": "#12141a",
    "fundo_alt": "#171a22",
    "barra": "#0d0f14",
    "cartao": "#1c2029",
    "cartao_hover": "#232836",
    "texto": "#eef1f7",
    "texto_fraco": "#9aa4b8",
    "borda": "#2a3040",
    "primaria": "#3d7bfd",
    "primaria_escura": "#2f63d4",
    "sucesso": "#2fbf71",
    "alerta": "#e8a33d",
    "erro": "#e2574c",
    "destaque": "#7c5cff",
    "selecao": "#26324d",
}

CLARO = {
    "fundo": "#f5f6fa",
    "fundo_alt": "#ffffff",
    "barra": "#ffffff",
    "cartao": "#ffffff",
    "cartao_hover": "#eef2fb",
    "texto": "#1b1f2a",
    "texto_fraco": "#5c6577",
    "borda": "#d7dbe6",
    "primaria": "#2f63d4",
    "primaria_escura": "#24509c",
    "sucesso": "#1e9e5a",
    "alerta": "#b8771a",
    "erro": "#c0392b",
    "destaque": "#6b4ce0",
    "selecao": "#dbe6ff",
}

TAMANHOS = {
    "pequeno": {"base": 9, "titulo": 15, "subtitulo": 11, "escala": 0.85},
    "normal": {"base": 10, "titulo": 17, "subtitulo": 12, "escala": 1.0},
    "grande": {"base": 12, "titulo": 20, "subtitulo": 14, "escala": 1.15},
}


def paleta(nome: str = "escuro") -> dict[str, str]:
    return dict(CLARO if str(nome).lower().startswith("clar") else ESCURO)


def fonte(tamanho_nome: str = "normal", familia: str = "Segoe UI") -> tuple:
    """Família e tamanho-base; o Windows do usuário tem Segoe UI."""
    dados = TAMANHOS.get(tamanho_nome, TAMANHOS["normal"])
    return familia, dados["base"]


def aplicar(raiz, *, nome: str = "escuro", tamanho: str = "normal",
            familia: str = "Segoe UI") -> dict[str, str]:
    """Aplica o tema no Tk/ttk; devolve a paleta em uso.

    Quando o Tk não está disponível (ambiente de teste), devolve a paleta sem
    falhar — a lógica continua testável.
    """
    cores = paleta(nome)
    if raiz is None:
        return cores
    try:
        from tkinter import ttk

        estilo = ttk.Style(raiz)
        try:
            estilo.theme_use("clam")  # único tema que aceita cor de fundo plena
        except Exception:
            pass
        dados = TAMANHOS.get(tamanho, TAMANHOS["normal"])
        base = (familia, dados["base"])
        titulo = (familia, dados["titulo"], "bold")
        subtitulo = (familia, dados["subtitulo"])
        raiz.configure(background=cores["fundo"])
        estilo.configure(".", background=cores["fundo"], foreground=cores["texto"],
                         fieldbackground=cores["cartao"], font=base,
                         bordercolor=cores["borda"], focuscolor=cores["primaria"])
        estilo.configure("TFrame", background=cores["fundo"])
        estilo.configure("Cartao.TFrame", background=cores["cartao"])
        estilo.configure("Barra.TFrame", background=cores["barra"])
        estilo.configure("TLabel", background=cores["fundo"],
                         foreground=cores["texto"], font=base)
        estilo.configure("Titulo.TLabel", background=cores["fundo"],
                         foreground=cores["texto"], font=titulo)
        estilo.configure("Fraco.TLabel", background=cores["fundo"],
                         foreground=cores["texto_fraco"], font=subtitulo)
        estilo.configure("Cartao.TLabel", background=cores["cartao"],
                         foreground=cores["texto"], font=base)
        estilo.configure("CartaoTitulo.TLabel", background=cores["cartao"],
                         foreground=cores["texto"],
                         font=(familia, dados["subtitulo"] + 2, "bold"))
        estilo.configure("Forte.TLabel", background=cores["fundo"],
                         foreground=cores["texto"],
                         font=(familia, dados["subtitulo"] + 2, "bold"))
        estilo.configure("TButton", background=cores["cartao"],
                         foreground=cores["texto"], padding=(12, 6),
                         borderwidth=0, focuscolor=cores["primaria"])
        estilo.map("TButton",
                   background=[("active", cores["cartao_hover"]),
                               ("disabled", cores["fundo_alt"])],
                   foreground=[("disabled", cores["texto_fraco"])])
        estilo.configure("Principal.TButton", background=cores["primaria"],
                         foreground="#ffffff", padding=(14, 7))
        estilo.map("Principal.TButton",
                   background=[("active", cores["primaria_escura"]),
                               ("disabled", cores["borda"])])
        estilo.configure("Perigo.TButton", background=cores["erro"],
                         foreground="#ffffff", padding=(12, 6))
        estilo.configure("Nav.TButton", background=cores["barra"],
                         foreground=cores["texto_fraco"], anchor="w",
                         padding=(16, 10), borderwidth=0)
        estilo.map("Nav.TButton",
                   background=[("active", cores["cartao_hover"])],
                   foreground=[("active", cores["texto"])])
        estilo.configure("NavAtivo.TButton", background=cores["cartao"],
                         foreground=cores["texto"], anchor="w",
                         padding=(16, 10),
                         font=(familia, dados["base"], "bold"))
        estilo.configure("TEntry", fieldbackground=cores["cartao"],
                         foreground=cores["texto"], insertcolor=cores["texto"],
                         bordercolor=cores["borda"], padding=6)
        estilo.configure("TCombobox", fieldbackground=cores["cartao"],
                         background=cores["cartao"], foreground=cores["texto"],
                         arrowcolor=cores["texto"], padding=5)
        estilo.configure("Treeview", background=cores["cartao"],
                         fieldbackground=cores["cartao"],
                         foreground=cores["texto"], rowheight=30,
                         borderwidth=0, font=base)
        estilo.configure("Treeview.Heading", background=cores["fundo_alt"],
                         foreground=cores["texto_fraco"],
                         font=(familia, dados["base"], "bold"), borderwidth=0,
                         padding=(8, 6))
        estilo.map("Treeview", background=[("selected", cores["selecao"])],
                   foreground=[("selected", cores["texto"])])
        estilo.map("Treeview.Heading",
                   background=[("active", cores["cartao_hover"])])
        estilo.configure("TNotebook", background=cores["fundo"], borderwidth=0)
        estilo.configure("TNotebook.Tab", background=cores["fundo_alt"],
                         foreground=cores["texto_fraco"], padding=(14, 7))
        estilo.map("TNotebook.Tab",
                   background=[("selected", cores["cartao"])],
                   foreground=[("selected", cores["texto"])])
        estilo.configure("TLabelframe", background=cores["fundo"],
                         foreground=cores["texto"], bordercolor=cores["borda"])
        estilo.configure("TLabelframe.Label", background=cores["fundo"],
                         foreground=cores["destaque"],
                         font=(familia, dados["base"], "bold"))
        estilo.configure("TCheckbutton", background=cores["fundo"],
                         foreground=cores["texto"], font=base)
        estilo.configure("TRadiobutton", background=cores["fundo"],
                         foreground=cores["texto"], font=base)
        estilo.configure("Horizontal.TProgressbar",
                         background=cores["primaria"],
                         troughcolor=cores["cartao"], borderwidth=0,
                         lightcolor=cores["primaria"], darkcolor=cores["primaria"])
        estilo.configure("TSeparator", background=cores["borda"])
        estilo.configure("TScrollbar", background=cores["cartao"],
                         troughcolor=cores["fundo"], arrowcolor=cores["texto_fraco"],
                         borderwidth=0)
        return cores
    except Exception as erro:  # tema nunca impede o programa de abrir
        log.info("Tema não aplicado: %s", erro)
        return cores


__all__ = ["aplicar", "paleta", "fonte", "ESCURO", "CLARO", "TAMANHOS"]
