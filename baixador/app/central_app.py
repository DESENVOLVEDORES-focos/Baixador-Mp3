"""Central Musical — interface moderna em Tkinter (barra lateral + páginas).

Este arquivo contém **só a tela**. Toda a lógica está em ``central.Central``
(pesquisa, seleção, downloads, biblioteca, playlists, metadados, capas,
reprodutor). Assim a interface pode ser construída/testada com Tk simulado.

Páginas: INÍCIO, PESQUISAR, PLAYLISTS, FILA DE DOWNLOADS, BIBLIOTECA,
ARTISTAS, ÁLBUNS, HISTÓRICO, FAVORITOS, CONFIGURAÇÕES — mais a barra do
reprodutor fixa no rodapé, acessível em qualquer página.
"""

from __future__ import annotations

import logging
import queue
import sys
import threading
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from baixador.app import tema
from baixador.app.central import Central

log = logging.getLogger("baixador.central.app")

try:  # Tkinter vem com o Python do Windows; em Linux mínimo pode faltar.
    import tkinter as tk
    from tkinter import filedialog, messagebox, simpledialog, ttk
except ImportError:  # pragma: no cover
    tk = None  # type: ignore[assignment]
    filedialog = messagebox = simpledialog = ttk = None  # type: ignore[assignment]

PAGINAS = (
    ("inicio", "  Início", "🏠"),
    ("pesquisar", "  Pesquisar", "🔍"),
    ("playlists", "  Playlists", "🎵"),
    ("fila", "  Fila de downloads", "⬇"),
    ("biblioteca", "  Biblioteca", "🎧"),
    ("artistas", "  Artistas", "🎤"),
    ("albuns", "  Álbuns", "💿"),
    ("historico", "  Histórico", "🕘"),
    ("favoritos", "  Favoritos", "★"),
    ("config", "  Configurações", "⚙"),
)


def _miniatura(caminho: Path | None, tamanho: tuple[int, int] = (48, 48)) -> Any:
    """PhotoImage quadrada (capa) ou ``None`` sem Pillow/arquivo."""
    if caminho is None:
        return None
    try:
        from PIL import Image, ImageTk  # type: ignore

        with Image.open(caminho) as imagem:
            imagem = imagem.convert("RGB")
            imagem.thumbnail(tamanho)
            return ImageTk.PhotoImage(imagem)
    except Exception:
        return None


def _miniatura_bytes(dados: bytes, tamanho: tuple[int, int] = (48, 48)) -> Any:
    """``PhotoImage`` a partir dos bytes de uma capa baixada (``None`` sem Pillow)."""
    try:
        import io

        from PIL import Image, ImageTk  # type: ignore

        with Image.open(io.BytesIO(dados)) as imagem:
            imagem = imagem.convert("RGB")
            imagem.thumbnail(tamanho)
            return ImageTk.PhotoImage(imagem)
    except Exception:
        return None


def capa_da_musica(caminho: str | Path, *, cache: Path | None = None) -> Path | None:
    """Extrai a capa embutida para um arquivo temporário (para a tela)."""
    caminho = Path(caminho)
    if not caminho.is_file():
        return None
    try:
        from mutagen.id3 import ID3

        audio = ID3(str(caminho))
        capas = audio.getall("APIC")
        if not capas:
            return None
        dados = capas[0].data
        mime = (capas[0].mime or "image/jpeg").lower()
        extensao = ".png" if "png" in mime else ".jpg"
        pasta = cache or (caminho.parent / ".capas")
        pasta.mkdir(parents=True, exist_ok=True)
        alvo = pasta / f"{caminho.stem[:60]}{extensao}"
        if not alvo.is_file() or alvo.stat().st_size != len(dados):
            alvo.write_bytes(dados)
        return alvo
    except Exception:
        return None


class CentralApp:
    """Janela principal: barra lateral, páginas e player fixo."""

    def __init__(self, central: Central | None = None, raiz: Any | None = None):
        if tk is None:
            raise RuntimeError("Tkinter não está disponível nesta instalação.")
        self.central = central or Central()
        self.raiz = raiz if raiz is not None else tk.Tk()
        self.raiz.title("Central Musical — Baixador-Mp3")
        self.raiz.geometry("1240x820")
        self.raiz.minsize(1000, 680)
        prefs = self.central.preferencias
        self.cores = tema.aplicar(
            self.raiz, nome=getattr(prefs, "tema", "escuro"),
            tamanho=getattr(prefs, "tamanho_fonte", "normal"))
        self.pagina_atual = "inicio"
        self._botoes_nav: dict[str, Any] = {}
        self._fila_eventos: queue.Queue = queue.Queue()
        # Mensagens/erros mostrados ao usuário nesta sessão (painel + arquivo).
        self.mensagens: list[tuple[str, bool, str]] = []
        self._lock = threading.RLock()
        self._resultados: list[Any] = []
        self._playlists_busca: list[Any] = []
        self._playlist_aberta: Any = None
        self._musicas_biblioteca: list[Any] = []
        self._musicas_fila: list[Any] = []
        self._imagens: dict[str, Any] = {}

        self._montar_estrutura()
        self.central.definir_callbacks(
            download_mudou=lambda item: self._fila_eventos.put(("download", item, None)),
            download_concluiu=lambda item: self._fila_eventos.put(("download_fim", item, None)),
        )
        self.mostrar("inicio")
        if getattr(prefs, "sincronizar_ao_abrir", True):
            threading.Thread(target=self._sincronizar_inicial, daemon=True).start()
        self.raiz.after(150, self._processar_eventos)
        self._ligar_atalhos()
        # Restaura volume/repetição/última faixa da sessão anterior.
        try:
            self.central.reprodutor.carregar_estado()
            self.player_modo.set(self.central.reprodutor.descricao_repeticao())
        except Exception:
            pass

    # -- infraestrutura -----------------------------------------------------
    def _montar_estrutura(self) -> None:
        cores = self.cores
        self.raiz.configure(background=cores["fundo"])
        self.raiz.grid_rowconfigure(0, weight=1)
        self.raiz.grid_columnconfigure(1, weight=1)

        # barra lateral
        self.lateral = ttk.Frame(self.raiz, style="Barra.TFrame", width=220)
        self.lateral.grid(row=0, column=0, rowspan=2, sticky="nsw")
        self.lateral.grid_propagate(False)
        marca = ttk.Label(self.lateral, text="♪ Central Musical",
                          style="Titulo.TLabel", background=cores["barra"])
        marca.pack(anchor="w", padx=16, pady=(18, 2))
        sub = ttk.Label(self.lateral, text="baixar · organizar · ouvir",
                        style="Fraco.TLabel", background=cores["barra"])
        sub.pack(anchor="w", padx=16, pady=(0, 14))
        for chave, rotulo, _icone in PAGINAS:
            botao = ttk.Button(self.lateral, text=rotulo, style="Nav.TButton",
                               command=lambda c=chave: self.mostrar(c))
            botao.pack(fill="x", padx=8, pady=1)
            self._botoes_nav[chave] = botao
        self.contador_cesta = ttk.Label(
            self.lateral, text="Cesta: 0", style="Fraco.TLabel",
            background=cores["barra"])
        self.contador_cesta.pack(anchor="w", padx=16, pady=(16, 4))

        # área principal + rodapé do player
        self.conteudo = ttk.Frame(self.raiz)
        self.conteudo.grid(row=0, column=1, sticky="nsew", padx=(12, 12), pady=(10, 4))
        self.conteudo.grid_rowconfigure(0, weight=1)
        self.conteudo.grid_columnconfigure(0, weight=1)
        self.rodape = ttk.Frame(self.raiz)
        self.rodape.grid(row=1, column=1, sticky="ew", padx=12, pady=(0, 10))

        self.areas: dict[str, Any] = {}
        for chave, _rotulo, _icone in PAGINAS:
            area = ttk.Frame(self.conteudo)
            area.grid(row=0, column=0, sticky="nsew")
            self.areas[chave] = area
        self._montar_player()
        self._montar_status()

    def _montar_status(self) -> None:
        self.status_var = tk.StringVar(value="Pronto.")
        barra = ttk.Frame(self.rodape)
        barra.pack(fill="x", pady=(6, 0))
        ttk.Label(barra, textvariable=self.status_var,
                  style="Fraco.TLabel").pack(side="left")
        ttk.Button(barra, text="Mensagens",
                   command=self._abrir_mensagens).pack(side="right")
        ttk.Button(barra, text="Abrir pasta de dados",
                   command=lambda: self._abrir_no_sistema(
                       str(self.central.config.dados))).pack(side="right", padx=6)

    def mostrar(self, chave: str) -> None:
        """Troca de página sem abrir janela nova e sem perder estado."""
        if chave not in self.areas:
            return
        for nome, botao in self._botoes_nav.items():
            botao.configure(style="NavAtivo.TButton" if nome == chave else "Nav.TButton")
        montar = getattr(self, f"_montar_{chave}", None)
        area = self.areas[chave]
        if not getattr(area, "_montada", False) and callable(montar):
            try:
                montar(area)
                area._montada = True  # type: ignore[attr-defined]
            except Exception as erro:
                log.exception("Falha ao montar %s", chave)
                self.definir_status(f"Erro ao abrir a página: {erro}")
        for nome, outra in self.areas.items():
            if nome != chave:
                outra.grid_remove()
        area.grid()
        self.pagina_atual = chave
        atualizar = getattr(self, f"_atualizar_{chave}", None)
        if callable(atualizar):
            try:
                atualizar()
            except Exception as erro:
                log.info("Atualização de %s falhou: %s", chave, erro)
        self._atualizar_contador_cesta()

    def definir_status(self, texto: str) -> None:
        self.status_var.set(texto)

    def notificar(self, titulo: str, mensagem: str, *, erro: bool = False) -> None:
        """Mensagem clara: barra de status + caixa + registro na tela."""
        self.definir_status(f"{titulo}: {mensagem}")
        self.registrar_mensagem(f"{titulo}: {mensagem}", erro=erro)
        try:
            (messagebox.showerror if erro else messagebox.showinfo)(titulo, mensagem)
        except Exception:
            pass

    # -- registro de mensagens (a tela mostra; o arquivo guarda) -------------
    def registrar_mensagem(self, texto: str, *, erro: bool = False) -> None:
        """Guarda a mensagem para o painel de log e para ``dados/app.log``.

        A interface nunca depende do terminal: o que o programa diz ao usuário
        fica visível na própria janela e sobrevive ao fechamento (arquivo).
        """
        carimbo = datetime.now().strftime("%H:%M:%S")
        linha = f"[{carimbo}] {'ERRO ' if erro else ''}{texto}"
        self.mensagens.append((carimbo, bool(erro), str(texto)))
        del self.mensagens[:-400]          # o painel não cresce sem limite
        try:
            destino = Path(self.central.config.dados) / "app.log"
            destino.parent.mkdir(parents=True, exist_ok=True)
            with destino.open("a", encoding="utf-8") as arquivo:
                arquivo.write(linha + "\n")
        except Exception:
            pass                           # log em arquivo é complemento

    def mensagens_recentes(self, limite: int = 200) -> list[tuple[str, bool, str]]:
        return list(self.mensagens)[-limite:]

    def _abrir_mensagens(self) -> None:
        """Janela com o que o programa informou nesta sessão."""
        janela = tk.Toplevel(self.raiz)
        janela.title("Mensagens desta sessão")
        janela.configure(background=self.cores["fundo"])
        ttk.Label(janela, text="Mensagens e erros desta sessão",
                  style="Titulo.TLabel").pack(anchor="w", padx=10, pady=(10, 2))
        ttk.Label(janela,
                  text="O mesmo conteúdo é gravado em dados/app.log.",
                  style="Fraco.TLabel").pack(anchor="w", padx=10)
        caixa = tk.Text(janela, height=18, width=100, wrap="word")
        caixa.pack(fill="both", expand=True, padx=10, pady=8)
        for carimbo, erro, texto in self.mensagens_recentes():
            prefixo = "ERRO " if erro else ""
            caixa.insert("end", f"[{carimbo}] {prefixo}{texto}\n")
        caixa.see("end")
        rodape = ttk.Frame(janela)
        rodape.pack(fill="x", padx=10, pady=(0, 10))

        def copiar() -> None:
            try:
                self.raiz.clipboard_clear()
                self.raiz.clipboard_append(caixa.get("1.0", "end").strip())
                self.definir_status("Mensagens copiadas para a área de transferência.")
            except Exception:
                pass

        def limpar() -> None:
            self.mensagens.clear()
            caixa.delete("1.0", "end")
            self.definir_status("Painel de mensagens limpo (o arquivo é mantido).")

        ttk.Button(rodape, text="Copiar tudo", command=copiar).pack(side="left")
        ttk.Button(rodape, text="Limpar painel", command=limpar).pack(side="left", padx=6)
        ttk.Button(rodape, text="Fechar", command=janela.destroy).pack(side="right")
        return janela

    def _executar(self, trabalho: Callable[[], Any],
                  concluir: Callable[[Any], None] | None = None,
                  falhar: Callable[[Exception], None] | None = None) -> None:
        """Roda em thread e devolve o resultado na thread da interface."""

        def alvo() -> None:
            try:
                resultado = trabalho()
            except Exception as erro:  # nunca deixa a interface travada
                self._fila_eventos.put(("erro", erro, falhar or self._mostrar_erro))
                return
            self._fila_eventos.put(("ok", resultado, concluir))

        threading.Thread(target=alvo, daemon=True).start()

    def _mostrar_erro(self, erro: Exception) -> None:
        texto = str(erro) or erro.__class__.__name__
        self.definir_status(f"Erro: {texto[:160]}")
        self.registrar_mensagem(texto, erro=True)
        try:
            messagebox.showerror("Central Musical", texto)
        except Exception:
            pass

    def _processar_eventos(self) -> None:
        try:
            while True:
                tipo, valor, callback = self._fila_eventos.get_nowait()
                if tipo == "erro":
                    if callable(callback):
                        callback(valor)
                elif tipo == "ok":
                    if callable(callback):
                        callback(valor)
                elif tipo == "download":
                    self._linha_de_download(valor)
                elif tipo == "download_fim":
                    self._baixou(valor)
                elif tipo == "texto":
                    self.definir_status(str(valor))
        except queue.Empty:
            pass
        except Exception as erro:
            log.info("Evento falhou: %s", erro)
        finally:
            self.raiz.after(150, self._processar_eventos)

    def _sincronizar_inicial(self) -> None:
        try:
            resultado = self.central.sincronizar_biblioteca()
            self._fila_eventos.put(("texto", (
                f"Biblioteca: {resultado['encontrados']} arquivo(s) indexado(s)."), None))
        except Exception as erro:
            self._fila_eventos.put(("texto", f"Biblioteca não indexada: {erro}", None))

    def _atualizar_contador_cesta(self) -> None:
        try:
            quantidade = self.central.selecao.quantidade()
        except Exception:
            quantidade = 0
        texto = f"Cesta: {quantidade} música" + ("s" if quantidade != 1 else "")
        try:
            self.contador_cesta.configure(text=texto)
        except Exception:
            pass

    # -- avisos de download -------------------------------------------------
    def _linha_de_download(self, item: Any) -> None:
        pagina = getattr(self, "arvore_downloads", None)
        if pagina is None:
            return
        try:
            valores = (item.titulo_exibicao[:70], item.formato.upper(),
                       item.rotulo_estado, item.progresso_texto,
                       item.mensagem[:60])
            iid = str(item.id)
            if pagina.exists(iid):  # type: ignore[attr-defined]
                pagina.item(iid, values=valores)
            else:
                pagina.insert("", "end", iid=iid, values=valores)
        except Exception:
            pass

    def _baixou(self, item: Any) -> None:
        self._atualizar_contador_cesta()
        if item.estado == "concluido":
            self.definir_status(f"Concluído: {item.titulo_exibicao[:60]}")

    # =====================================================================
    # PÁGINA: PLAYLISTS
    # =====================================================================
    def _montar_playlists(self, area: Any) -> None:
        ttk.Label(area, text="Playlists", style="Titulo.TLabel").pack(anchor="w")
        ttk.Label(area, text=(
            "Coleções suas (independentes das do YouTube). Crie, renomeie, "
            "reordene e toque direto do aplicativo."),
            style="Fraco.TLabel").pack(anchor="w", pady=(0, 8))

        corpo = ttk.Frame(area)
        corpo.pack(fill="both", expand=True)
        esquerda = ttk.Frame(corpo)
        esquerda.pack(side="left", fill="y", padx=(0, 8))
        self.arvore_playlists = ttk.Treeview(
            esquerda, columns=("nome", "total"), show="headings", height=14,
            selectmode="browse")
        for coluna, titulo, largura in (("nome", "Playlist", 220), ("total", "Músicas", 80)):
            self.arvore_playlists.heading(coluna, text=titulo)
            self.arvore_playlists.column(coluna, width=largura)
        self.arvore_playlists.pack(fill="both", expand=True)
        self.arvore_playlists.bind("<<TreeviewSelect>>", lambda _e: self._abrir_playlist_local())

        botoes = ttk.Frame(esquerda)
        botoes.pack(fill="x", pady=6)
        ttk.Button(botoes, text="Nova", style="Principal.TButton",
                   command=self._nova_playlist).pack(side="left")
        ttk.Button(botoes, text="Renomear",
                   command=self._renomear_playlist).pack(side="left", padx=4)
        ttk.Button(botoes, text="Excluir",
                   command=self._excluir_playlist).pack(side="left")

        direita = ttk.Frame(corpo)
        direita.pack(side="left", fill="both", expand=True)
        self.titulo_playlist_local = tk.StringVar(value="Escolha uma playlist")
        ttk.Label(direita, textvariable=self.titulo_playlist_local,
                  style="Forte.TLabel").pack(anchor="w")
        self.arvore_playlist_local = ttk.Treeview(
            direita, columns=("titulo", "artista", "album", "duracao"),
            show="headings", height=14, selectmode="extended")
        for coluna, titulo, largura in (("titulo", "Título", 260),
                                        ("artista", "Artista", 170),
                                        ("album", "Álbum", 170),
                                        ("duracao", "Duração", 80)):
            self.arvore_playlist_local.heading(coluna, text=titulo)
            self.arvore_playlist_local.column(coluna, width=largura)
        self.arvore_playlist_local.pack(fill="both", expand=True, pady=4)
        self.arvore_playlist_local.bind(
            "<Double-1>", lambda _e: self._tocar_playlist_local())

        acoes = ttk.Frame(direita)
        acoes.pack(fill="x")
        ttk.Button(acoes, text="▶ Tocar", style="Principal.TButton",
                   command=self._tocar_playlist_local).pack(side="left")
        ttk.Button(acoes, text="Remover da playlist",
                   command=self._remover_da_playlist_local).pack(side="left", padx=6)
        ttk.Button(acoes, text="Subir",
                   command=lambda: self._mover_playlist_local(-1)).pack(side="left")
        ttk.Button(acoes, text="Descer",
                   command=lambda: self._mover_playlist_local(1)).pack(side="left", padx=4)
        ttk.Button(acoes, text="Adicionar da biblioteca...",
                   command=self._adicionar_da_biblioteca).pack(side="right")

    def _nova_playlist(self) -> None:
        nome = simpledialog.askstring("Nova playlist", "Nome da playlist:")
        if not nome:
            return
        try:
            self.central.criar_playlist(nome)
        except Exception as erro:
            self.notificar("Playlists", str(erro), erro=True)
            return
        self._atualizar_playlists()
        self.definir_status(f"Playlist \"{nome}\" criada.")

    def _renomear_playlist(self) -> None:
        escolha = self.arvore_playlists.selection()
        if not escolha:
            return
        playlist_id = int(str(escolha[0]))
        atual = self.arvore_playlists.item(escolha[0], "values")[0]
        novo = simpledialog.askstring("Renomear", "Novo nome:", initialvalue=atual)
        if novo:
            self.central.renomear_playlist(playlist_id, novo)
            self._atualizar_playlists()

    def _excluir_playlist(self) -> None:
        escolha = self.arvore_playlists.selection()
        if not escolha:
            return
        playlist_id = int(str(escolha[0]))
        nome = self.arvore_playlists.item(escolha[0], "values")[0]
        if not messagebox.askyesno(
                "Excluir playlist",
                f"Excluir a playlist \"{nome}\"?\n"
                "As músicas continuam na biblioteca."):
            return
        self.central.excluir_playlist(playlist_id)
        self.arvore_playlist_local.delete(*self.arvore_playlist_local.get_children())
        self.titulo_playlist_local.set("Escolha uma playlist")
        self._atualizar_playlists()

    def _abrir_playlist_local(self) -> None:
        escolha = self.arvore_playlists.selection()
        if not escolha:
            return
        playlist_id = int(str(escolha[0]))
        nome = self.arvore_playlists.item(escolha[0], "values")[0]
        musicas = self.central.musicas_da_playlist(playlist_id)
        self._musicas_fila = musicas
        for item in self.arvore_playlist_local.get_children():
            self.arvore_playlist_local.delete(item)
        for musica in musicas:
            self.arvore_playlist_local.insert("", "end", iid=str(musica.id), values=(
                musica.titulo_exibicao, musica.artista or "—",
                musica.album or "—", musica.duracao_formatada))
        total = sum(m.duracao or 0 for m in musicas)
        self.titulo_playlist_local.set(
            f"{nome} — {len(musicas)} música(s), {int(total // 60)} min")

    def _tocar_playlist_local(self) -> None:
        escolha = self.arvore_playlists.selection()
        if not escolha:
            return
        if not self.central.tocar_playlist(int(str(escolha[0]))):
            self._avisar_sem_player()
        else:
            self._atualizar_player()
            self.definir_status("Tocando a playlist.")

    def _remover_da_playlist_local(self) -> None:
        escolha_p = self.arvore_playlists.selection()
        escolhas = self.arvore_playlist_local.selection()
        if not escolha_p or not escolhas:
            return
        playlist_id = int(str(escolha_p[0]))
        for iid in escolhas:
            self.central.remover_da_playlist(playlist_id, int(str(iid)))
        self._abrir_playlist_local()
        self._atualizar_playlists()

    def _mover_playlist_local(self, direcao: int) -> None:
        escolha_p = self.arvore_playlists.selection()
        escolha = self.arvore_playlist_local.selection()
        if not escolha_p or not escolha:
            return
        playlist_id = int(str(escolha_p[0]))
        ordem = [int(str(iid)) for iid in self.arvore_playlist_local.get_children()]
        alvo = int(str(escolha[0]))
        posicao = ordem.index(alvo)
        nova = posicao + direcao
        if not 0 <= nova < len(ordem):
            return
        ordem[posicao], ordem[nova] = ordem[nova], ordem[posicao]
        self.central.reordenar_playlist(playlist_id, ordem)
        self._abrir_playlist_local()
        self.arvore_playlist_local.selection_set(str(alvo))

    def _adicionar_da_biblioteca(self) -> None:
        escolha = self.arvore_playlists.selection()
        if not escolha:
            messagebox.showinfo("Playlists", "Escolha (ou crie) uma playlist primeiro.")
            return
        playlist_id = int(str(escolha[0]))
        janela = tk.Toplevel(self.raiz)
        janela.title("Adicionar músicas da biblioteca")
        janela.geometry("720x480")
        janela.configure(background=self.cores["fundo"])
        procurar = tk.StringVar()
        campo = ttk.Entry(janela, textvariable=procurar)
        campo.pack(fill="x", padx=10, pady=8)
        arvore = ttk.Treeview(janela, columns=("titulo", "artista"),
                              show="headings", selectmode="extended", height=14)
        for coluna, titulo, largura in (("titulo", "Título", 380),
                                        ("artista", "Artista", 240)):
            arvore.heading(coluna, text=titulo)
            arvore.column(coluna, width=largura)
        arvore.pack(fill="both", expand=True, padx=10)
        listadas: list[Any] = []

        def preencher(*_a: Any) -> None:
            listadas.clear()
            for item in arvore.get_children():
                arvore.delete(item)
            for musica in self.central.musicas(texto=procurar.get().strip()):
                listadas.append(musica)
                arvore.insert("", "end", iid=str(musica.id), values=(
                    musica.titulo_exibicao, musica.artista or "—"))

        def confirmar() -> None:
            ids = [int(str(iid)) for iid in arvore.selection()]
            if ids:
                quantidade = self.central.adicionar_a_playlist(playlist_id, ids)
                self.definir_status(f"{quantidade} música(s) adicionada(s).")
                self._abrir_playlist_local()
                self._atualizar_playlists()
            janela.destroy()

        campo.bind("<KeyRelease>", preencher)
        ttk.Button(janela, text="Adicionar selecionadas", style="Principal.TButton",
                   command=confirmar).pack(pady=8)
        preencher()

    def _atualizar_playlists(self) -> None:
        if not hasattr(self, "arvore_playlists"):
            return
        selecionada = self.arvore_playlists.selection()
        for item in self.arvore_playlists.get_children():
            self.arvore_playlists.delete(item)
        for playlist in self.central.playlists():
            self.arvore_playlists.insert("", "end", iid=str(playlist["id"]), values=(
                playlist["nome"], playlist["total"]))
        if selecionada:
            try:
                self.arvore_playlists.selection_set(selecionada[0])
            except Exception:
                pass

    # =====================================================================
    # PÁGINA: FILA DE DOWNLOADS
    # =====================================================================
    def _montar_fila(self, area: Any) -> None:
        ttk.Label(area, text="Fila de downloads", style="Titulo.TLabel").pack(anchor="w")
        self.fila_resumo_var = tk.StringVar(value="Nenhum download.")
        ttk.Label(area, textvariable=self.fila_resumo_var,
                  style="Fraco.TLabel").pack(anchor="w", pady=(0, 6))

        controles = ttk.Frame(area)
        controles.pack(fill="x", pady=4)
        ttk.Button(controles, text="▶ Iniciar todos", style="Principal.TButton",
                   command=self._iniciar_downloads).pack(side="left")
        ttk.Button(controles, text="⏸ Pausar",
                   command=self._pausar_downloads).pack(side="left", padx=4)
        ttk.Button(controles, text="⏵ Retomar",
                   command=self._retomar_downloads).pack(side="left")
        ttk.Button(controles, text="↻ Retomar fila salva",
                   command=self._retomar_fila_salva).pack(side="left", padx=4)
        ttk.Button(controles, text="✖ Cancelar item",
                   command=self._cancelar_item).pack(side="left", padx=4)
        ttk.Button(controles, text="Cancelar todos",
                   command=self._cancelar_todos).pack(side="left")
        ttk.Button(controles, text="Repetir falhas",
                   command=self._repetir_falhas).pack(side="left", padx=4)
        ttk.Button(controles, text="Remover concluídos",
                   command=self._remover_concluidos).pack(side="left")

        corpo = ttk.Frame(area)
        corpo.pack(fill="both", expand=True, pady=6)
        self.arvore_downloads = ttk.Treeview(
            corpo, columns=("titulo", "formato", "estado", "progresso", "mensagem"),
            show="headings", height=12, selectmode="browse")
        for coluna, titulo, largura in (("titulo", "Música", 330),
                                        ("formato", "Formato", 80),
                                        ("estado", "Estado", 150),
                                        ("progresso", "%", 70),
                                        ("mensagem", "Mensagem", 300)):
            self.arvore_downloads.heading(coluna, text=titulo)
            self.arvore_downloads.column(coluna, width=largura)
        barra = ttk.Scrollbar(corpo, orient="vertical",
                              command=self.arvore_downloads.yview)
        self.arvore_downloads.configure(yscrollcommand=barra.set)
        self.arvore_downloads.pack(side="left", fill="both", expand=True)
        barra.pack(side="right", fill="y")
        self.arvore_downloads.bind("<Double-1>", lambda _e: self._detalhes_download())

        rodape = ttk.Frame(area)
        rodape.pack(fill="x")
        ttk.Button(rodape, text="Ver detalhes / erro",
                   command=self._detalhes_download).pack(side="left")
        ttk.Button(rodape, text="Abrir pasta da música",
                   command=self._abrir_pasta_do_item).pack(side="left", padx=6)
        ttk.Button(rodape, text="Voltar à pesquisa",
                   command=lambda: self.mostrar("pesquisar")).pack(side="right")

        cesta = ttk.Labelframe(area, text="Cesta de seleção (o que você marcou)")
        cesta.pack(fill="both", expand=False, pady=(8, 0))
        self.cesta_var = tk.StringVar(value="Cesta vazia.")
        ttk.Label(cesta, textvariable=self.cesta_var,
                  style="Forte.TLabel").pack(anchor="w", padx=8, pady=(4, 0))
        self.cesta_estimativa_var = tk.StringVar(value="")
        ttk.Label(cesta, textvariable=self.cesta_estimativa_var,
                  style="Fraco.TLabel").pack(anchor="w", padx=8, pady=(0, 4))
        self.arvore_cesta = ttk.Treeview(
            cesta, columns=("titulo", "origem", "duracao", "formato"),
            show="headings", height=6, selectmode="extended")
        for coluna, titulo, largura in (("titulo", "Música", 360),
                                        ("origem", "Veio de", 220),
                                        ("duracao", "Duração", 80),
                                        ("formato", "Formato", 80)):
            self.arvore_cesta.heading(coluna, text=titulo)
            self.arvore_cesta.column(coluna, width=largura)
        self.arvore_cesta.pack(fill="both", expand=True, padx=8)
        filtro_cesta = ttk.Frame(cesta)
        filtro_cesta.pack(fill="x", padx=8, pady=(4, 0))
        ttk.Label(filtro_cesta, text="Procurar na cesta:",
                  style="Fraco.TLabel").pack(side="left")
        self.cesta_busca = tk.StringVar()
        campo_cesta = ttk.Entry(filtro_cesta, textvariable=self.cesta_busca,
                                width=28)
        campo_cesta.pack(side="left", padx=6)
        campo_cesta.bind("<KeyRelease>", lambda _e: self._atualizar_fila())
        ttk.Button(filtro_cesta, text="Limpar busca",
                   command=lambda: (self.cesta_busca.set(""),
                                    self._atualizar_fila())).pack(side="left")
        self.cesta_busca_dica = tk.StringVar(value="")
        ttk.Label(filtro_cesta, textvariable=self.cesta_busca_dica,
                  style="Fraco.TLabel").pack(side="left", padx=8)
        ttk.Label(filtro_cesta, text="Formato dos marcados:",
                  style="Fraco.TLabel").pack(side="left", padx=(12, 4))
        self.cesta_formato = tk.StringVar(value="MP3")
        ttk.Combobox(filtro_cesta, textvariable=self.cesta_formato, width=6,
                     state="readonly", values=("MP3", "MP4")).pack(side="left")
        ttk.Button(filtro_cesta, text="Aplicar",
                   command=self._aplicar_formato_cesta).pack(side="left", padx=4)

        acoes_cesta = ttk.Frame(cesta)
        acoes_cesta.pack(fill="x", padx=8, pady=6)
        ttk.Button(acoes_cesta, text="Baixar tudo da cesta", style="Principal.TButton",
                   command=self._baixar_cesta).pack(side="left")
        ttk.Button(acoes_cesta, text="Limpar cesta",
                   command=self._limpar_cesta).pack(side="left", padx=6)
        ttk.Button(acoes_cesta, text="Remover marcados",
                   command=self._remover_da_cesta).pack(side="left")
        ttk.Button(acoes_cesta, text="Subir",
                   command=lambda: self._mover_cesta(-1)).pack(side="left", padx=(6, 0))
        ttk.Button(acoes_cesta, text="Descer",
                   command=lambda: self._mover_cesta(1)).pack(side="left", padx=4)
        ttk.Button(acoes_cesta, text="↥ Topo",
                   command=lambda: self._cesta_para(0)).pack(side="left", padx=4)
        ttk.Button(acoes_cesta, text="↧ Fim",
                   command=lambda: self._cesta_para(-1)).pack(side="left")
        ttk.Button(acoes_cesta, text="↶ Desfazer remoção",
                   command=self._desfazer_remocao_cesta).pack(side="left", padx=4)
        ttk.Button(acoes_cesta, text="Salvar cesta como playlist",
                   command=self._salvar_cesta_como_playlist).pack(side="left")

    def _aplicar_formato_cesta(self) -> None:
        """Troca MP3↔MP4 dos itens marcados (ou de toda a cesta)."""
        formato = str(self.cesta_formato.get()).strip().lower() or "mp3"
        escolhas = self.arvore_cesta.selection()
        itens = self.central.selecao.listar()
        if escolhas:
            urls = [itens[int(str(iid))].url for iid in escolhas
                    if 0 <= int(str(iid)) < len(itens)]
        else:
            urls = [item.url for item in itens]
        if not urls:
            self.notificar("Cesta", "A cesta está vazia.", erro=True)
            return
        mudados = self.central.selecao.definir_formato(urls, formato)
        self._atualizar_fila()
        self.definir_status(
            f"{mudados} item(ns) marcados como {formato.upper()}"
            + ("" if escolhas else " (cesta inteira: nenhum item estava marcado)")
            + ".")

    def _iniciar_downloads(self) -> None:
        quantidade = self.central.iniciar_downloads()
        self.definir_status(f"{quantidade} item(ns) na fila — baixando "
                            f"{self.central.gerenciador.simultaneos} por vez.")

    def _retomar_fila_salva(self) -> None:
        """Continua o que ficou pendente da última vez que o programa fechou."""
        quantidade = self.central.retomar_fila_salva()
        if quantidade:
            self.definir_status(
                f"{quantidade} download(s) da sessão anterior retomado(s).")
        else:
            self.definir_status("Nada pendente da sessão anterior.")
        self._atualizar_fila()

    def _pausar_downloads(self) -> None:
        self.central.pausar_downloads()
        self.definir_status("Downloads pausados.")

    def _retomar_downloads(self) -> None:
        quantidade = self.central.retomar_downloads()
        self.definir_status(f"{quantidade} item(ns) retomado(s).")

    def _cancelar_item(self) -> None:
        escolha = self.arvore_downloads.selection()
        if not escolha:
            messagebox.showinfo("Downloads", "Selecione um item da fila.")
            return
        if self.central.cancelar_download(int(str(escolha[0]))):
            self.definir_status("Download cancelado.")

    def _cancelar_todos(self) -> None:
        if not messagebox.askyesno("Cancelar tudo", "Cancelar todos os downloads?"):
            return
        quantidade = self.central.cancelar_todos()
        self.definir_status(f"{quantidade} download(s) cancelado(s).")

    def _repetir_falhas(self) -> None:
        quantidade = self.central.repetir_falhas()
        self.definir_status(f"{quantidade} item(ns) tentando de novo.")

    def _remover_concluidos(self) -> None:
        quantidade = self.central.remover_finalizados()
        self._atualizar_fila()
        self.definir_status(f"{quantidade} item(ns) removido(s) da lista.")

    def _detalhes_download(self) -> None:
        escolha = self.arvore_downloads.selection()
        if not escolha:
            return
        item = self.central.gerenciador.obter(int(str(escolha[0])))
        if item is None:
            return
        detalhe = (
            f"Música: {item.titulo_exibicao}\n"
            f"Formato: {item.formato.upper()}\n"
            f"Estado: {item.rotulo_estado}\n"
            f"Progresso: {item.progresso_texto or '—'}\n"
            f"Mensagem: {item.mensagem or '—'}\n"
            f"Caminho: {item.caminho or '—'}\n"
            f"URL: {item.url}\n"
            f"Tempo: {item.duracao_processo or '—'} s"
        )
        if item.detalhe_erro:
            detalhe += f"\n\nDetalhe do erro:\n{item.detalhe_erro}"
        messagebox.showinfo("Detalhes do download", detalhe)

    def _abrir_pasta_do_item(self) -> None:
        escolha = self.arvore_downloads.selection()
        if not escolha:
            return
        item = self.central.gerenciador.obter(int(str(escolha[0])))
        if item and item.caminho and Path(item.caminho).exists():
            self._abrir_no_sistema(str(Path(item.caminho).parent))
        else:
            self._abrir_no_sistema(str(self.central.config.musicas))

    def _baixar_cesta(self) -> None:
        quantidade = self.central.selecao_para_downloads()
        if not quantidade:
            messagebox.showinfo("Cesta", "A cesta está vazia.")
            return
        self._atualizar_fila()
        self.central.iniciar_downloads()
        self._atualizar_contador_cesta()
        self.definir_status(f"{quantidade} música(s) da cesta começaram a baixar.")

    def _limpar_cesta(self) -> None:
        quantidade = self.central.limpar_selecao()
        self._atualizar_fila()
        self.definir_status(f"Cesta limpa ({quantidade} item(ns)).")

    def _remover_da_cesta(self) -> None:
        escolhas = self.arvore_cesta.selection()
        if not escolhas:
            return
        itens = self.central.selecao.listar()
        urls = [itens[int(str(iid))].url for iid in escolhas
                if str(iid).isdigit() and int(str(iid)) < len(itens)]
        removidos = self.central.remover_da_selecao(urls)
        self._atualizar_fila()
        self.definir_status(f"{removidos} item(ns) removido(s) da cesta.")

    def _cesta_para(self, destino: int) -> None:
        """Manda o item marcado para o topo (0) ou para o fim (-1)."""
        escolhas = self.arvore_cesta.selection()
        if not escolhas:
            messagebox.showinfo("Cesta", "Marque um item da cesta.")
            return
        indice = int(str(escolhas[0]))
        if self.central.selecao.mover_para(indice, destino):
            self._atualizar_fila()
            novo = 0 if destino == 0 else self.central.selecao.quantidade() - 1
            self.arvore_cesta.selection_set(str(novo))
            self.definir_status("Item movido " + ("para o topo." if destino == 0
                                                  else "para o fim."))

    def _desfazer_remocao_cesta(self) -> None:
        devolvidos = self.central.selecao.desfazer_remocao()
        self._atualizar_fila()
        self.definir_status(
            f"{devolvidos} item(ns) devolvido(s) à cesta." if devolvidos
            else "Nada para desfazer.")

    def _salvar_cesta_como_playlist(self) -> None:
        itens = self.central.selecao.listar()
        if not itens:
            messagebox.showinfo("Cesta", "A cesta está vazia.")
            return
        nome = simpledialog.askstring(
            "Salvar cesta", "Nome da playlist local:",
            initialvalue="Minha seleção", parent=self.raiz)
        if not nome or not str(nome).strip():
            return
        na_biblioteca = {m.origem_url: m.id
                         for m in self.central.biblioteca.listar()
                         if m.origem_url}
        ids = [na_biblioteca[item.url] for item in itens
               if item.url in na_biblioteca]
        if not ids:
            self.notificar(
                "Playlist", "Nenhum item da cesta já está na biblioteca: baixe "
                            "antes de salvar (playlist só guarda músicas baixadas).",
                erro=True)
            return
        playlist = self.central.criar_playlist(str(nome).strip())
        adicionadas = self.central.adicionar_a_playlist(playlist, ids)
        self.definir_status(
            f"Playlist \"{nome}\" criada com {adicionadas} música(s)"
            + (f"; {len(itens) - len(ids)} item(ns) ainda não baixado(s) ficaram fora."
               if len(ids) < len(itens) else "."))
        self._atualizar_fila()

    def _mover_cesta(self, direcao: int) -> None:
        escolhas = self.arvore_cesta.selection()
        if not escolhas:
            return
        indice = int(str(escolhas[0]))
        self.central.reordenar_selecao(indice, indice + direcao)
        self._atualizar_fila()
        self.arvore_cesta.selection_set(str(max(0, indice + direcao)))

    def _atualizar_fila(self) -> None:
        if not hasattr(self, "arvore_downloads"):
            return
        for item in self.central.downloads():
            iid = str(item.id)
            valores = (item.titulo_exibicao[:70], item.formato.upper(),
                       item.rotulo_estado, item.progresso_texto,
                       (item.mensagem or "")[:70])
            if self.arvore_downloads.exists(iid):
                self.arvore_downloads.item(iid, values=valores)
            else:
                self.arvore_downloads.insert("", "end", iid=iid, values=valores)
        resumo = self.central.resumo_downloads()
        self.fila_resumo_var.set(
            f"{resumo.get('total', 0)} item(ns) · {resumo.get('aguardando', 0)} "
            f"aguardando · {resumo.get('processando', 0)} baixando · "
            f"{resumo.get('concluido', 0)} concluído(s) · "
            f"{resumo.get('falhou', 0)} falha(s) · "
            f"{resumo.get('pausado', 0)} pausado(s)")
        recuperados = self.central.fila_salva()
        if recuperados and resumo.get("total"):
            partes = [f"{qtd} {estado}" for estado, qtd in recuperados.items()
                      if qtd]
            if partes:
                self.fila_resumo_var.set(
                    self.fila_resumo_var.get()
                    + "  ·  da sessão anterior: " + ", ".join(partes))
        for item in self.arvore_cesta.get_children():
            self.arvore_cesta.delete(item)
        todos = self.central.selecao.listar()
        texto_busca = ""
        try:
            texto_busca = str(self.cesta_busca.get()).strip()
        except Exception:
            texto_busca = ""
        if texto_busca:
            # O índice é o da cesta completa: remover/subir continua correto.
            indices = {id(item): posicao for posicao, item in enumerate(todos)}
            itens = self.central.selecao.pesquisar(texto_busca)
            self.cesta_busca_dica.set(
                f"{len(itens)} de {len(todos)} item(ns) casam com "
                f"\"{texto_busca}\" (os botões valem só para os visíveis).")
        else:
            indices = {}
            itens = todos
            self.cesta_busca_dica.set("")
        for entrada in itens:
            posicao = indices.get(id(entrada), todos.index(entrada))
            self.arvore_cesta.insert("", "end", iid=str(posicao), values=(
                entrada.titulo_exibicao, entrada.origem or "Pesquisa",
                entrada.duracao_formatada, entrada.formato.upper()))
        grupos = self.central.selecao.agrupado_por_origem()
        resumo_cesta = ", ".join(f"{nome}: {qtd}" for nome, qtd in grupos.items())
        segundos, bytes_ = self.central.selecao.estimativa()
        from baixador.nucleo.limites import tamanho_legivel, tempo_legivel

        repetidas = len(self.central.selecao.ja_na_biblioteca(
            self.central.biblioteca))
        self.cesta_estimativa_var.set(
            f"Estimativa: {tempo_legivel(segundos)} de áudio, "
            f"~{tamanho_legivel(bytes_)} de download"
            + (f" · {repetidas} já na biblioteca" if repetidas else ""))
        self.cesta_var.set(
            (f"Cesta: {len(todos)} música(s) · "
             f"{self.central.selecao.duracao_formatada()}"
             + (f" · {resumo_cesta}" if resumo_cesta else ""))
            if itens else "Cesta vazia — pesquise e clique em \"Adicionar à cesta\".")
        self._atualizar_contador_cesta()

    # =====================================================================
    # PÁGINA: BIBLIOTECA
    # =====================================================================
    def _montar_biblioteca(self, area: Any) -> None:
        ttk.Label(area, text="Biblioteca", style="Titulo.TLabel").pack(anchor="w")
        filtros = ttk.Frame(area)
        filtros.pack(fill="x", pady=(4, 6))
        self.biblioteca_busca_var = tk.StringVar()
        campo = ttk.Entry(filtros, textvariable=self.biblioteca_busca_var)
        campo.pack(side="left", fill="x", expand=True, padx=(0, 6), ipady=3)
        campo.bind("<KeyRelease>", lambda _e: self._atualizar_biblioteca())
        self.biblioteca_ordem_var = tk.StringVar(value="Título")
        ttk.Combobox(filtros, textvariable=self.biblioteca_ordem_var, width=12,
                     state="readonly",
                     values=("Título", "Artista", "Álbum", "Ano", "Gênero",
                             "Adicionada", "Duração")).pack(side="left", padx=(0, 6))
        self.biblioteca_ordem_var.trace_add(
            "write", lambda *_a: self._atualizar_biblioteca())
        self.biblioteca_favoritos_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(filtros, text="Só favoritas",
                        variable=self.biblioteca_favoritos_var,
                        command=self._atualizar_biblioteca).pack(side="left", padx=(0, 6))
        ttk.Button(filtros, text="Reindexar pasta",
                   command=self._reindexar).pack(side="left")

        detalhados = ttk.Frame(area)
        detalhados.pack(fill="x", pady=(0, 6))
        self.biblioteca_artista_var = tk.StringVar(value="Todos os artistas")
        self.biblioteca_album_var = tk.StringVar(value="Todos os álbuns")
        self.biblioteca_genero_var = tk.StringVar(value="Todos os gêneros")
        self.biblioteca_ano_var = tk.StringVar(value="Todos os anos")
        self.biblioteca_duracao_var = tk.StringVar(value="Qualquer duração")
        self.biblioteca_sem_capa_var = tk.BooleanVar(value=False)
        self.biblioteca_recentes_var = tk.BooleanVar(value=False)
        # menu -> (variável, faceta, rótulo neutro). Guardado para receber os
        # valores reais do banco em ``_carregar_facetas``.
        self._combos_facetas: list[tuple[Any, str, str, str]] = []
        combos = (
            (self.biblioteca_artista_var, 22, "artistas", "Todos os artistas"),
            (self.biblioteca_album_var, 20, "albuns", "Todos os álbuns"),
            (self.biblioteca_genero_var, 14, "generos", "Todos os gêneros"),
            (self.biblioteca_ano_var, 8, "anos", "Todos os anos"),
        )
        for variavel, largura, faceta, neutro in combos:
            caixa = ttk.Combobox(detalhados, textvariable=variavel,
                                 width=largura, state="readonly",
                                 values=(neutro,))
            caixa.pack(side="left", padx=(0, 6))
            caixa.bind("<<ComboboxSelected>>",
                       lambda _e: self._atualizar_biblioteca())
            self._combos_facetas.append((caixa, faceta, neutro, variavel))
        ttk.Combobox(detalhados, textvariable=self.biblioteca_duracao_var,
                     width=16, state="readonly",
                     values=("Qualquer duração", "Até 3 min", "3 a 6 min",
                             "6 a 10 min", "Mais de 10 min")).pack(
            side="left", padx=(0, 6))
        ttk.Checkbutton(detalhados, text="Sem capa",
                        variable=self.biblioteca_sem_capa_var,
                        command=self._atualizar_biblioteca).pack(side="left")
        ttk.Checkbutton(detalhados, text="Últimos 7 dias",
                        variable=self.biblioteca_recentes_var,
                        command=self._atualizar_biblioteca).pack(side="left", padx=6)
        ttk.Button(detalhados, text="Limpar filtros",
                   command=self._limpar_filtros_biblioteca).pack(side="left")

        self.biblioteca_resumo_var = tk.StringVar(value="")
        ttk.Label(area, textvariable=self.biblioteca_resumo_var,
                  style="Fraco.TLabel").pack(anchor="w", pady=(0, 4))
        self.biblioteca_vazia_var = tk.StringVar(value="")
        ttk.Label(area, textvariable=self.biblioteca_vazia_var,
                  style="Dica.TLabel").pack(anchor="w", pady=(0, 4))

        corpo = ttk.Frame(area)
        corpo.pack(fill="both", expand=True)
        self.arvore_biblioteca = ttk.Treeview(
            corpo, columns=("titulo", "artista", "album", "ano", "genero",
                            "duracao", "capa"),
            show="headings", selectmode="extended", height=14)
        for coluna, titulo, largura in (("titulo", "Título", 280),
                                        ("artista", "Artista", 170),
                                        ("album", "Álbum", 170),
                                        ("ano", "Ano", 60),
                                        ("genero", "Gênero", 140),
                                        ("duracao", "Duração", 70),
                                        ("capa", "Capa", 60)):
            self.arvore_biblioteca.heading(coluna, text=titulo)
            self.arvore_biblioteca.column(coluna, width=largura)
        barra = ttk.Scrollbar(corpo, orient="vertical",
                              command=self.arvore_biblioteca.yview)
        self.arvore_biblioteca.configure(yscrollcommand=barra.set)
        self.arvore_biblioteca.pack(side="left", fill="both", expand=True)
        barra.pack(side="right", fill="y")
        self.arvore_biblioteca.bind("<Double-1>", lambda _e: self._tocar_selecionada())
        self.arvore_biblioteca.bind("<<TreeviewSelect>>",
                                    lambda _e: self._mostrar_capa_biblioteca())

        acoes = ttk.Frame(area)
        acoes.pack(fill="x", pady=6)
        ttk.Button(acoes, text="▶ Tocar", style="Principal.TButton",
                   command=self._tocar_selecionada).pack(side="left")
        ttk.Button(acoes, text="★ Favoritar",
                   command=self._favoritar_selecionada).pack(side="left", padx=4)
        ttk.Button(acoes, text="Editar metadados",
                   command=self._editar_metadados_selecionada).pack(side="left")
        ttk.Button(acoes, text="Buscar capa",
                   command=self._buscar_capa_selecionada).pack(side="left", padx=4)
        ttk.Button(acoes, text="Adicionar à playlist",
                   command=self._adicionar_selecionada_a_playlist).pack(side="left")
        ttk.Button(acoes, text="Abrir pasta",
                   command=self._abrir_pasta_selecionada).pack(side="left", padx=4)
        ttk.Button(acoes, text="Excluir arquivo",
                   command=self._excluir_selecionada).pack(side="left")
        ttk.Button(acoes, text="Completar metadados (lote)",
                   command=self._completar_metadados_lote).pack(side="right")

        self.capa_biblioteca = tk.Label(
            area, text="", background=self.cores["fundo"], height=8)
        self.capa_biblioteca.pack(anchor="w", pady=(4, 0))

    def _atualizar_biblioteca(self) -> None:
        if not hasattr(self, "arvore_biblioteca"):
            return
        ordens = {"Título": "titulo", "Artista": "artista", "Álbum": "album",
                  "Ano": "ano", "Gênero": "genero", "Adicionada": "adicionada",
                  "Duração": "duracao"}
        ordem = ordens.get(self.biblioteca_ordem_var.get(), "titulo")
        faixas = {"Até 3 min": (0, 180), "3 a 6 min": (180, 360),
                  "6 a 10 min": (360, 600), "Mais de 10 min": (600, 0)}
        duracao_min, duracao_max = faixas.get(
            self.biblioteca_duracao_var.get(), (0, 0))
        musicas = self.central.musicas(
            texto=self.biblioteca_busca_var.get().strip(), ordenar=ordem,
            somente_favoritos=bool(self.biblioteca_favoritos_var.get()),
            artista=self._valor_filtro(self.biblioteca_artista_var),
            album=self._valor_filtro(self.biblioteca_album_var),
            genero=self._valor_filtro(self.biblioteca_genero_var),
            ano=self._valor_filtro(self.biblioteca_ano_var),
            sem_capa=bool(self.biblioteca_sem_capa_var.get()),
            dias=7 if self.biblioteca_recentes_var.get() else 0,
            duracao_min=duracao_min, duracao_max=duracao_max)
        self._musicas_biblioteca = musicas
        self._carregar_facetas()
        for item in self.arvore_biblioteca.get_children():
            self.arvore_biblioteca.delete(item)
        for musica in musicas:
            self.arvore_biblioteca.insert("", "end", iid=str(musica.id), values=(
                ("★ " if musica.favorito else "") + musica.titulo_exibicao,
                musica.artista or "—", musica.album or "—", musica.ano or "—",
                musica.genero or "—", musica.duracao_formatada,
                "sim" if musica.tem_capa else "não"))
        total = self.central.biblioteca.contar()
        segundos = sum(m.duracao or 0 for m in musicas)
        from baixador.nucleo.limites import tempo_legivel

        self.biblioteca_resumo_var.set(
            f"{len(musicas)} de {total} música(s) · {tempo_legivel(int(segundos))}"
            + (" (filtro ativo)" if len(musicas) != total else ""))
        if not musicas and not total:
            self.biblioteca_vazia_var.set(
                "Biblioteca vazia: clique em \"Reindexar pasta\" para ler os MP3 "
                "da pasta de músicas, ou baixe algo na página Pesquisar.")
        elif not musicas:
            self.biblioteca_vazia_var.set(
                "Nenhuma música com esses filtros. Use \"Limpar filtros\".")
        else:
            self.biblioteca_vazia_var.set("")
        self.definir_status(f"{len(musicas)} música(s) na biblioteca.")

    @staticmethod
    def _valor_filtro(variavel: Any) -> str:
        """Traduz "Todos os artistas"/"Todos" em "sem filtro"."""
        valor = str(variavel.get() or "").strip()
        return "" if valor.lower().startswith(("todos", "qualquer")) else valor

    def _carregar_facetas(self) -> None:
        """Preenche os menus de filtro com o que existe no banco (com contagem)."""
        try:
            facetas = self.central.biblioteca.facetas()
        except Exception as erro:
            log.info("Facetas indisponíveis: %s", erro)
            return

        for caixa, faceta, neutro, _variavel in getattr(self, "_combos_facetas", []):
            opcoes = (neutro,) + tuple(
                f"{item['valor']} ({item['total']})"
                for item in facetas.get(faceta, []))
            caixa.configure(values=opcoes)
            # Se o filtro atual deixou de existir, volta para o neutro.
            atual = str(_variavel.get())
            if atual != neutro and atual not in opcoes:
                _variavel.set(neutro)

    def _limpar_filtros_biblioteca(self) -> None:
        """Volta a biblioteca ao estado neutro (um clique)."""
        self.biblioteca_busca_var.set("")
        self.biblioteca_artista_var.set("Todos os artistas")
        self.biblioteca_album_var.set("Todos os álbuns")
        self.biblioteca_genero_var.set("Todos os gêneros")
        self.biblioteca_ano_var.set("Todos os anos")
        self.biblioteca_duracao_var.set("Qualquer duração")
        self.biblioteca_sem_capa_var.set(False)
        self.biblioteca_recentes_var.set(False)
        self.biblioteca_favoritos_var.set(False)
        self._atualizar_biblioteca()

    def _reindexar(self) -> None:
        self.definir_status("Lendo as pastas e as tags dos arquivos...")

        def concluir(resultado: dict[str, int]) -> None:
            self._atualizar_biblioteca()
            self.notificar("Biblioteca", (
                f"{resultado['encontrados']} arquivo(s) encontrado(s): "
                f"{resultado['novos']} novo(s), {resultado['atualizados']} "
                f"atualizado(s), {resultado['removidos']} removido(s)."))

        self._executar(lambda: self.central.sincronizar_biblioteca(
            remover_ausentes=True), concluir)

    def _musica_selecionada(self) -> Any:
        escolha = self.arvore_biblioteca.selection()
        if not escolha:
            messagebox.showinfo("Biblioteca", "Selecione uma música.")
            return None
        return self.central.biblioteca.obter(int(str(escolha[0])))

    def _tocar_selecionada(self) -> None:
        musica = self._musica_selecionada()
        if musica is None:
            return
        if self.central.tocar_fila(self._musicas_biblioteca or [musica]):
            self._atualizar_player()
            self.definir_status(f"Tocando: {musica.titulo_exibicao}")
        else:
            self._avisar_sem_player()

    def _mostrar_capa_biblioteca(self) -> None:
        escolha = self.arvore_biblioteca.selection()
        if not escolha:
            return
        musica = self.central.biblioteca.obter(int(str(escolha[0])))
        if musica is None:
            return
        imagem = _miniatura(capa_da_musica(musica.caminho), (150, 150))
        if imagem is not None:
            self.capa_biblioteca.image = imagem  # type: ignore[attr-defined]
            self.capa_biblioteca.configure(image=imagem, text="")
        else:
            self.capa_biblioteca.image = None  # type: ignore[attr-defined]
            self.capa_biblioteca.configure(
                image="", text="Sem capa — use \"Buscar capa\"")

    def _favoritar_selecionada(self) -> None:
        musica = self._musica_selecionada()
        if musica is None:
            return
        novo = self.central.favoritar_musica(musica.id)
        self._atualizar_biblioteca()
        self.definir_status("Adicionada aos favoritos." if novo else "Removida dos favoritos.")

    def _abrir_pasta_selecionada(self) -> None:
        musica = self._musica_selecionada()
        if musica is not None:
            self._abrir_no_sistema(str(Path(musica.caminho).parent))

    def _excluir_selecionada(self) -> None:
        musica = self._musica_selecionada()
        if musica is None:
            return
        if not messagebox.askyesno(
                "Excluir", f"Excluir \"{musica.titulo_exibicao}\" do disco?\n"
                           "Essa ação não pode ser desfeita."):
            return
        if self.central.excluir_musica(musica.id, apagar_arquivo=True):
            self._atualizar_biblioteca()
            self.definir_status("Arquivo excluído.")

    def _editar_metadados_selecionada(self) -> None:
        musica = self._musica_selecionada()
        if musica is None:
            return
        janela = tk.Toplevel(self.raiz)
        janela.title(f"Metadados — {musica.titulo_exibicao}")
        janela.configure(background=self.cores["fundo"])
        janela.geometry("560x380")
        campos = (
            ("Título", "titulo"), ("Artista", "artista"), ("Álbum", "album"),
            ("Ano", "ano"), ("Gênero", "genero"), ("Nº da faixa", "faixa"),
        )
        variaveis: dict[str, Any] = {}
        for linha, (rotulo, chave) in enumerate(campos):
            ttk.Label(janela, text=rotulo).grid(row=linha, column=0,
                                                sticky="e", padx=8, pady=4)
            variavel = tk.StringVar(value=str(getattr(musica, chave) or ""))
            variaveis[chave] = variavel
            ttk.Entry(janela, textvariable=variavel, width=44).grid(
                row=linha, column=1, sticky="we", padx=8, pady=4)

        def salvar() -> None:
            dados = {chave: variavel.get().strip()
                     for chave, variavel in variaveis.items()}
            self.central.salvar_metadados(musica.id, **dados)
            self._atualizar_biblioteca()
            self.definir_status("Metadados gravados no arquivo MP3.")
            janela.destroy()

        ttk.Button(janela, text="Salvar no arquivo", style="Principal.TButton",
                   command=salvar).grid(row=len(campos), column=1, sticky="e",
                                        padx=8, pady=10)

    def _buscar_capa_selecionada(self) -> None:
        """Busca as capas e **mostra antes de gravar** (o usuário confirma)."""
        musica = self._musica_selecionada()
        if musica is None:
            return
        self.definir_status("Procurando capas nas fontes públicas...")

        def concluir(candidatos: list[Any]) -> None:
            if not candidatos:
                self.notificar(
                    "Capa",
                    "Nenhuma capa válida encontrada para este artista/álbum.\n"
                    "Nada foi gravado no arquivo.", erro=True)
                self.definir_status("Sem capa confirmada.")
                return
            self.definir_status(f"{len(candidatos)} capa(s) encontrada(s).")
            self._previa_de_capas(musica, candidatos)

        self._executar(lambda: self.central.capa_candidatos(musica), concluir)

    def _previa_de_capas(self, musica: Any, candidatos: list[Any]) -> None:
        """Janela com as capas encontradas; grava só a que for escolhida."""
        janela = tk.Toplevel(self.raiz)
        janela.title("Escolher capa — nada é gravado antes de você confirmar")
        janela.configure(background=self.cores["fundo"])
        cabecalho = f"{musica.titulo_exibicao}\n{musica.album or 'álbum não identificado'}"
        ttk.Label(janela, text=cabecalho, style="Titulo.TLabel").pack(
            anchor="w", padx=10, pady=(10, 2))
        ttk.Label(janela,
                  text="A capa só é incorporada ao MP3 depois do clique em Usar esta capa.",
                  style="Fraco.TLabel").pack(anchor="w", padx=10, pady=(0, 8))

        grade = ttk.Frame(janela)
        grade.pack(fill="both", expand=True, padx=10, pady=6)
        escolhida: dict[str, Any] = {"indice": None}
        imagens: list[Any] = []
        marcas: list[tk.StringVar] = []

        def escolher(indice: int) -> None:
            escolhida["indice"] = indice
            for posicao, marca in enumerate(marcas):
                marca.set("● escolhida" if posicao == indice else "")

        for indice, capa in enumerate(candidatos):
            cartao = ttk.Frame(grade, style="Cartao.TFrame")
            cartao.grid(row=0, column=indice, padx=6, pady=4, sticky="n")
            imagem = _miniatura_bytes(capa.dados, (170, 170))
            if imagem is not None:
                imagens.append(imagem)  # referência viva: senão o Tk apaga
                rotulo = tk.Label(cartao, image=imagem, background=self.cores["cartao"])
            else:
                rotulo = tk.Label(cartao, text="(prévia indisponível)\ninstale o Pillow",
                                  background=self.cores["cartao"],
                                  foreground=self.cores["texto_fraco"], width=20, height=8)
            rotulo.pack(padx=6, pady=6)
            rotulo.bind("<Button-1>", lambda _e, i=indice: escolher(i))
            ttk.Label(cartao, text=capa.rotulo, style="Cartao.TLabel",
                      wraplength=180).pack(padx=6)
            marca = tk.StringVar(value="")
            marcas.append(marca)
            ttk.Label(cartao, textvariable=marca,
                      style="CartaoTitulo.TLabel").pack(pady=(2, 4))
            ttk.Button(cartao, text="Usar esta capa",
                       command=lambda i=indice: escolher(i)).pack(pady=(0, 6))

        rodape = ttk.Frame(janela)
        rodape.pack(fill="x", padx=10, pady=(4, 10))

        def usar() -> None:
            indice = escolhida["indice"]
            if indice is None:
                messagebox.showinfo("Capa",
                                    "Clique em \"Usar esta capa\" na imagem escolhida.",
                                    parent=janela)
                return
            capa = candidatos[indice]
            janela.destroy()
            self.definir_status("Incorporando a capa escolhida...")

            def concluir(resultado: Any) -> None:
                if getattr(resultado, "ok", False):
                    self._atualizar_biblioteca()
                    self._mostrar_capa_biblioteca()
                self.notificar("Capa", resultado.mensagem,
                               erro=not getattr(resultado, "ok", False))

            self._executar(
                lambda: self.central.incorporar_capa(musica, imagem=capa.dados),
                concluir)

        def buscar_sozinho() -> None:
            janela.destroy()
            self.definir_status("Procurando capa nas fontes públicas...")

            def concluir(resultado: Any) -> None:
                if getattr(resultado, "ok", False):
                    self._atualizar_biblioteca()
                    self._mostrar_capa_biblioteca()
                    self.notificar("Capa", resultado.mensagem)
                else:
                    self.notificar("Capa", resultado.mensagem, erro=True)

            self._executar(lambda: self.central.incorporar_capa(musica), concluir)

        ttk.Button(rodape, text="Usar esta capa", command=usar).pack(side="left")
        ttk.Button(rodape, text="Deixar o programa escolher",
                   command=buscar_sozinho).pack(side="left", padx=6)
        ttk.Button(rodape, text="Cancelar (não gravar nada)",
                   command=janela.destroy).pack(side="right")
        janela.imagens = imagens  # type: ignore[attr-defined]
        return janela

    def _completar_metadados_lote(self) -> None:
        escolhas = self.arvore_biblioteca.selection()
        musicas = ([self.central.biblioteca.obter(int(str(i))) for i in escolhas]
                   if escolhas else None)
        musicas = [m for m in musicas if m] if musicas else None
        self.definir_status("Identificando e gravando metadados...")

        def concluir(resultados: list[Any]) -> None:
            ok = sum(1 for r in resultados if getattr(r, "ok", False))
            self._atualizar_biblioteca()
            self.notificar(
                "Metadados",
                f"{ok} de {len(resultados)} arquivo(s) atualizados.\n"
                "Campos que as fontes não confirmaram foram deixados como estavam.")

        self._executar(lambda: self.central.completar_metadados(musicas), concluir)

    def _adicionar_selecionada_a_playlist(self) -> None:
        escolhas = self.arvore_biblioteca.selection()
        if not escolhas:
            messagebox.showinfo("Playlists", "Selecione as músicas.")
            return
        playlists = self.central.playlists()
        if not playlists:
            if messagebox.askyesno("Playlists",
                                   "Você ainda não tem playlists. Criar uma agora?"):
                self.mostrar("playlists")
                self._nova_playlist()
            return
        janela = tk.Toplevel(self.raiz)
        janela.title("Adicionar à playlist")
        janela.configure(background=self.cores["fundo"])
        janela.geometry("420x300")
        lista = tk.Listbox(janela, height=10)
        for playlist in playlists:
            lista.insert("end", playlist["nome"])
        lista.pack(fill="both", expand=True, padx=10, pady=10)

        def confirmar() -> None:
            selecao = lista.curselection()
            if not selecao:
                return
            playlist_id = playlists[selecao[0]]["id"]
            quantidade = self.central.adicionar_a_playlist(
                playlist_id, [int(str(i)) for i in escolhas])
            self.definir_status(f"{quantidade} música(s) adicionada(s) à playlist.")
            janela.destroy()

        ttk.Button(janela, text="Adicionar", style="Principal.TButton",
                   command=confirmar).pack(pady=(0, 10))

    # =====================================================================
    # PÁGINA: INÍCIO (painel de controle)
    # =====================================================================
    def _montar_inicio(self, area: Any) -> None:
        ttk.Label(area, text="Início", style="Titulo.TLabel").pack(anchor="w")
        self.inicio_saudacao = tk.StringVar(value="")
        ttk.Label(area, textvariable=self.inicio_saudacao,
                  style="Fraco.TLabel").pack(anchor="w", pady=(0, 8))

        busca = ttk.Frame(area)
        busca.pack(fill="x", pady=(0, 10))
        self.inicio_busca_var = tk.StringVar()
        campo = ttk.Entry(busca, textvariable=self.inicio_busca_var)
        campo.pack(side="left", fill="x", expand=True, padx=(0, 6), ipady=4)
        campo.bind("<Return>", lambda _e: self._inicio_pesquisar())
        ttk.Button(busca, text="Pesquisar", style="Principal.TButton",
                   command=self._inicio_pesquisar).pack(side="left")

        cartoes = ttk.Frame(area)
        cartoes.pack(fill="x", pady=6)
        self.cartoes: dict[str, Any] = {}
        for chave, titulo in (("biblioteca", "Músicas na biblioteca"),
                             ("concluidos", "Downloads concluídos"),
                             ("andamento", "Em andamento"),
                             ("cesta", "Na cesta de seleção"),
                             ("playlists", "Playlists"),
                             ("favoritos", "Favoritos")):
            cartao = ttk.Frame(cartoes, style="Cartao.TFrame")
            cartao.pack(side="left", fill="both", expand=True, padx=4)
            ttk.Label(cartao, text=titulo, style="Cartao.TLabel").pack(
                anchor="w", padx=12, pady=(10, 0))
            valor = tk.StringVar(value="—")
            ttk.Label(cartao, textvariable=valor,
                      style="CartaoTitulo.TLabel").pack(anchor="w", padx=12,
                                                        pady=(0, 10))
            self.cartoes[chave] = valor

        colunas = ttk.Frame(area)
        colunas.pack(fill="both", expand=True, pady=(10, 0))
        recentes = ttk.Labelframe(colunas, text="Últimas músicas adicionadas")
        recentes.pack(side="left", fill="both", expand=True, padx=(0, 6))
        self.arvore_recentes = ttk.Treeview(
            recentes, columns=("titulo", "artista", "album"),
            show="headings", height=8)
        for coluna, titulo, largura in (("titulo", "Título", 220),
                                        ("artista", "Artista", 150),
                                        ("album", "Álbum", 150)):
            self.arvore_recentes.heading(coluna, text=titulo)
            self.arvore_recentes.column(coluna, width=largura)
        self.arvore_recentes.pack(fill="both", expand=True, padx=6, pady=6)
        self.arvore_recentes.bind("<Double-1>", lambda _e: self._inicio_tocar())

        atalhos = ttk.Labelframe(colunas, text="Atalhos")
        atalhos.pack(side="left", fill="both", padx=(6, 0))
        for texto, destino in (("Pesquisar música ou playlist", "pesquisar"),
                               ("Ver fila de downloads", "fila"),
                               ("Abrir biblioteca", "biblioteca"),
                               ("Criar/editar playlists", "playlists"),
                               ("Ver histórico", "historico")):
            ttk.Button(atalhos, text=texto,
                       command=lambda d=destino: self.mostrar(d)).pack(
                fill="x", padx=8, pady=3)

        self.inicio_atividade = tk.StringVar(value="")
        ttk.Label(area, textvariable=self.inicio_atividade,
                  style="Fraco.TLabel", wraplength=900).pack(anchor="w", pady=(8, 0))

    def _inicio_pesquisar(self) -> None:
        texto = self.inicio_busca_var.get().strip()
        if not texto:
            return
        try:
            self.pesquisa_var.set(texto)
        except Exception:
            pass
        self.mostrar("pesquisar")
        self._pesquisar()

    def _inicio_tocar(self) -> None:
        escolha = self.arvore_recentes.selection()
        if not escolha:
            return
        indice = self.arvore_recentes.index(escolha[0])
        musicas = self.central.recentes(20)
        if indice < len(musicas):
            if self.central.tocar_fila(musicas, indice):
                self._atualizar_player()
            else:
                self._avisar_sem_player()

    def _avisar_sem_player(self) -> None:
        if self.central.ffplay:
            self.notificar("Reprodutor", "Não foi possível tocar este arquivo.", erro=True)
        else:
            self.notificar(
                "Reprodutor",
                "O áudio precisa do ffplay, que vem com o FFmpeg. Rode "
                "configurar.bat (ou instale o FFmpeg) e reabra o programa.\n\n"
                "Enquanto isso, use \"Abrir no player do Windows\".", erro=True)

    def _atualizar_inicio(self) -> None:
        try:
            estatisticas = self.central.estatisticas()
            resumo = self.central.resumo_downloads()
        except Exception as erro:
            self.definir_status(f"Não foi possível ler os dados: {erro}")
            return
        self.cartoes["biblioteca"].set(str(estatisticas["total"]))
        self.cartoes["concluidos"].set(str(resumo.get("concluido", 0)))
        self.cartoes["andamento"].set(str(resumo.get("ativos", 0)))
        self.cartoes["cesta"].set(str(self.central.selecao.quantidade()))
        self.cartoes["playlists"].set(str(estatisticas["playlists"]))
        self.cartoes["favoritos"].set(str(estatisticas["favoritos"]))
        horas = int(estatisticas["segundos"] // 3600)
        minutos = int((estatisticas["segundos"] % 3600) // 60)
        self.inicio_saudacao.set(
            f"Sua biblioteca tem {estatisticas['total']} música(s) — "
            f"{horas}h{minutos:02} de áudio · {estatisticas['com_capa']} com capa, "
            f"{estatisticas['sem_capa']} sem capa.")
        for item in self.arvore_recentes.get_children():
            self.arvore_recentes.delete(item)
        for musica in self.central.recentes(20):
            self.arvore_recentes.insert("", "end", iid=str(musica.id), values=(
                musica.titulo_exibicao, musica.artista or "—",
                musica.album or "—"))
        recentes = self.central.pesquisas_recentes(3)
        if recentes:
            self.inicio_atividade.set(
                "Pesquisas recentes: " + " · ".join(p["consulta"] for p in recentes))
        else:
            self.inicio_atividade.set(
                "Comece pesquisando um artista, uma música ou uma playlist.")
        self._atualizar_contador_cesta()

    # =====================================================================
    # PÁGINA: PESQUISAR
    # =====================================================================
    def _montar_pesquisar(self, area: Any) -> None:
        ttk.Label(area, text="Pesquisar", style="Titulo.TLabel").pack(anchor="w")
        ttk.Label(area, text=(
            "Digite o nome e aperte Enter. A pesquisa traz vídeos, playlists e "
            "canais — tudo dentro do programa. Marque o que quiser (Ctrl+clique "
            "ou Shift+clique) e adicione à cesta; pode pesquisar outros artistas "
            "sem perder o que já marcou."),
            style="Fraco.TLabel", wraplength=980).pack(anchor="w", pady=(0, 8))

        linha = ttk.Frame(area)
        linha.pack(fill="x")
        self.pesquisa_var = tk.StringVar()
        campo = ttk.Entry(linha, textvariable=self.pesquisa_var)
        campo.pack(side="left", fill="x", expand=True, padx=(0, 6), ipady=4)
        campo.bind("<Return>", lambda _e: self._pesquisar())
        self.tipo_var = tk.StringVar(value="Tudo")
        ttk.Combobox(linha, textvariable=self.tipo_var, width=13, state="readonly",
                     values=("Tudo", "Só vídeos", "Só playlists")).pack(
            side="left", padx=(0, 6))
        ttk.Button(linha, text="Pesquisar", style="Principal.TButton",
                   command=self._pesquisar).pack(side="left")

        self.pesquisa_dica = tk.StringVar(value="")
        self.pesquisa_filtro_dica = tk.StringVar(value="")

        filtros = ttk.Frame(area)
        filtros.pack(fill="x", pady=(4, 0))
        prefs_pesquisa = self.central.preferencias
        self.pesq_deduplicar = tk.BooleanVar(
            value=bool(getattr(prefs_pesquisa, "pesquisa_deduplicar", True)))
        self.pesq_sem_compilados = tk.BooleanVar(
            value=bool(getattr(prefs_pesquisa, "pesquisa_sem_compilados", False)))
        self.pesq_so_com_duracao = tk.BooleanVar(
            value=bool(getattr(prefs_pesquisa, "pesquisa_so_com_duracao", False)))
        ttk.Checkbutton(filtros, text="Esconder repetidos",
                        variable=self.pesq_deduplicar,
                        command=self._aplicar_filtros_pesquisa).pack(side="left")
        ttk.Checkbutton(filtros, text="Sem compilados (>1 h)",
                        variable=self.pesq_sem_compilados,
                        command=self._aplicar_filtros_pesquisa).pack(
            side="left", padx=8)
        ttk.Checkbutton(filtros, text="Só com duração conhecida",
                        variable=self.pesq_so_com_duracao,
                        command=self._aplicar_filtros_pesquisa).pack(side="left")
        ttk.Label(area, textvariable=self.pesquisa_dica,
                  style="Fraco.TLabel").pack(anchor="w", pady=(6, 2))
        ttk.Label(area, textvariable=self.pesquisa_filtro_dica,
                  style="Fraco.TLabel").pack(anchor="w")

        corpo = ttk.Frame(area)
        corpo.pack(fill="both", expand=True, pady=4)
        self.arvore_resultados = ttk.Treeview(
            corpo, columns=("titulo", "tipo", "canal", "duracao", "oficial"),
            show="headings", selectmode="extended", height=12)
        for coluna, titulo, largura in (("titulo", "Título", 400),
                                        ("tipo", "Tipo", 140),
                                        ("canal", "Canal", 180),
                                        ("duracao", "Duração", 80),
                                        ("oficial", "Verificado", 90)):
            self.arvore_resultados.heading(coluna, text=titulo)
            self.arvore_resultados.column(coluna, width=largura)
        barra = ttk.Scrollbar(corpo, orient="vertical",
                              command=self.arvore_resultados.yview)
        self.arvore_resultados.configure(yscrollcommand=barra.set)
        self.arvore_resultados.pack(side="left", fill="both", expand=True)
        barra.pack(side="right", fill="y")
        self.arvore_resultados.bind("<Double-1>", lambda _e: self._adicionar_selecionados())

        acoes = ttk.Frame(area)
        acoes.pack(fill="x", pady=6)
        ttk.Button(acoes, text="Adicionar à cesta", style="Principal.TButton",
                   command=self._adicionar_selecionados).pack(side="left")
        ttk.Button(acoes, text="Adicionar todos",
                   command=self._adicionar_todos).pack(side="left", padx=6)
        ttk.Button(acoes, text="Abrir playlist",
                   command=self._abrir_playlist_selecionada).pack(side="left")
        ttk.Button(acoes, text="Prévia (ouvir trecho)",
                   command=self._previa_selecionada).pack(side="left", padx=6)
        ttk.Button(acoes, text="Baixar agora",
                   command=self._baixar_selecionados_agora).pack(side="left")
        ttk.Button(acoes, text="Ver cesta",
                   command=lambda: self.mostrar("fila")).pack(side="right")

        self._montar_area_playlist(area)

        detalhe = ttk.Frame(area)
        detalhe.pack(fill="x", pady=(4, 0))
        self.pesquisa_thumb = tk.Label(detalhe, text="", anchor="nw",
                                       background=self.cores["fundo"],
                                       foreground=self.cores["texto_fraco"])
        self.pesquisa_thumb.pack(side="left", padx=(0, 8))
        self.pesquisa_detalhe = tk.StringVar(
            value="Clique num resultado para ver os detalhes e a miniatura.")
        ttk.Label(detalhe, textvariable=self.pesquisa_detalhe,
                  style="Fraco.TLabel", justify="left",
                  wraplength=560).pack(side="left", anchor="w")
        self.arvore_resultados.bind(
            "<<TreeviewSelect>>", lambda _e: self._mostrar_detalhes_resultado())

    def _montar_area_playlist(self, area: Any) -> None:
        quadro = ttk.Labelframe(area, text="Itens da playlist aberta")
        self.playlist_area = quadro
        linha = ttk.Frame(quadro)
        linha.pack(fill="x", padx=6, pady=4)
        self.playlist_titulo_var = tk.StringVar(value="Nenhuma playlist aberta.")
        ttk.Label(linha, textvariable=self.playlist_titulo_var,
                  style="Forte.TLabel").pack(side="left")
        ttk.Button(linha, text="Marcar tudo",
                   command=lambda: self._marcar_playlist(True)).pack(side="right")
        ttk.Button(linha, text="Desmarcar",
                   command=lambda: self._marcar_playlist(False)).pack(side="right", padx=4)
        ttk.Button(linha, text="Adicionar marcados",
                   command=self._adicionar_da_playlist).pack(side="right", padx=4)
        ttk.Button(linha, text="Sem ao vivo/show",
                   command=self._filtrar_ao_vivo_playlist).pack(side="right", padx=4)
        ttk.Button(linha, text="Listar mais",
                   command=self._listar_mais_itens).pack(side="right", padx=4)
        self.playlist_resumo_var = tk.StringVar(
            value="Abra uma playlist nos resultados para ver o resumo.")
        ttk.Label(quadro, textvariable=self.playlist_resumo_var,
                  style="Fraco.TLabel").pack(anchor="w", padx=8)
        linha2 = ttk.Frame(quadro)
        linha2.pack(fill="x", padx=6, pady=(2, 4))
        ttk.Button(linha2, text="Marcar só os disponíveis",
                   command=self._marcar_disponiveis).pack(side="left")
        ttk.Button(linha2, text="Salvar na biblioteca",
                   command=self._salvar_playlist_aberta).pack(side="left", padx=6)
        ttk.Button(linha2, text="Ver o que já tenho",
                   command=self._ver_o_que_ja_tenho).pack(side="left")
        self.arvore_playlist = ttk.Treeview(
            quadro, columns=("n", "titulo", "duracao", "situacao", "observacao"),
            show="headings", height=7, selectmode="extended")
        for coluna, titulo, largura in (("n", "#", 40), ("titulo", "Título", 380),
                                        ("duracao", "Duração", 90),
                                        ("situacao", "Situação", 130),
                                        ("observacao", "Fora do filtro", 220)):
            self.arvore_playlist.heading(coluna, text=titulo)
            self.arvore_playlist.column(coluna, width=largura)
        self.arvore_playlist.pack(fill="both", expand=True, padx=6, pady=(0, 6))
        quadro.pack(fill="both", expand=False, pady=(6, 0))

    def _pesquisar(self) -> None:
        consulta = self.pesquisa_var.get().strip()
        if not consulta:
            messagebox.showwarning("Pesquisar", "Digite o que pesquisar.")
            return
        tipo = {"Tudo": "tudo", "Só vídeos": "videos",
                "Só playlists": "playlists"}.get(self.tipo_var.get(), "tudo")
        self.pesquisa_dica.set("Pesquisando no YouTube...")
        self.definir_status(f"Pesquisando \"{consulta}\"...")

        def concluir(resultados: list[Any]) -> None:
            # Guarda TUDO o que veio: os filtros só escondem, não descartam.
            self._resultados_brutos = list(resultados)
            self._preencher_resultados(resultados)

        self._executar(lambda: self.central.pesquisar(consulta, tipo), concluir)

    def _preencher_resultados(self, resultados: list[Any]) -> None:
        """Insere os resultados na tabela e escreve o resumo honesto."""
        self._resultados = list(resultados)
        for item in self.arvore_resultados.get_children():
            self.arvore_resultados.delete(item)
        for posicao, resultado in enumerate(self._resultados):
            duracao = getattr(resultado, "duracao_formatada", "")
            segundos = getattr(resultado, "duracao", None)
            if segundos and segundos > 3600:
                duracao += " ⚠ compilado/mix de 1 h ou mais"
            self.arvore_resultados.insert("", "end", iid=str(posicao), values=(
                getattr(resultado, "titulo", ""),
                getattr(resultado, "tipo_legivel", "Vídeo"),
                getattr(resultado, "canal", ""),
                duracao,
                "sim" if getattr(resultado, "canal_verificado", False) else "não"))
        playlists = sum(1 for r in self._resultados
                        if getattr(r, "eh_playlist", False))
        if not resultados:
            self.pesquisa_dica.set(
                "Nada encontrado. Tente outras palavras ou o tipo \"Tudo\".")
            self.pesquisa_filtro_dica.set("")
            self.definir_status("Nenhum resultado.")
            return
        self.pesquisa_dica.set(
            f"{len(resultados)} resultado(s)"
            + (f" · {playlists} playlist(s) — use \"Abrir playlist\""
               if playlists else "")
            + " · Ctrl+clique marca vários e Adicionar à cesta leva todos.")
        self.definir_status(f"{len(resultados)} resultado(s) na lista.")
        self._mostrar_filtros_pesquisa()

    def _mostrar_filtros_pesquisa(self) -> None:
        """Diz quantos resultados os filtros esconderam (e por quê)."""
        contagem = dict(getattr(self.central, "ultima_contagem_pesquisa", {}) or {})
        from baixador.web.pesquisa import descrever_filtro

        resumo = descrever_filtro(contagem)
        brutos = len(getattr(self, "_resultados_brutos", []) or [])
        if resumo:
            total = len(getattr(self, "_resultados", []) or [])
            self.pesquisa_filtro_dica.set(
                f"Filtros esconderam {brutos - total} de {brutos}: {resumo}. "
                "Desmarque a caixa para vê-los.")
        else:
            self.pesquisa_filtro_dica.set("")

    def _aplicar_filtros_pesquisa(self) -> None:
        """Reaplica os filtros sobre o que já foi pesquisado (sem nova busca)."""
        brutos = list(getattr(self, "_resultados_brutos", []) or [])
        if not brutos:
            return
        from baixador.web.pesquisa import organizar_resultados

        filtrados, contagem = organizar_resultados(
            brutos,
            remover_equivalentes=bool(self.pesq_deduplicar.get()),
            esconder_compilados=bool(self.pesq_sem_compilados.get()),
            exigir_duracao=bool(self.pesq_so_com_duracao.get()))
        self.central.ultima_contagem_pesquisa = contagem
        self._preencher_resultados(filtrados)
        try:
            self.central.preferencias = replace(
                self.central.preferencias,
                pesquisa_deduplicar=bool(self.pesq_deduplicar.get()),
                pesquisa_sem_compilados=bool(self.pesq_sem_compilados.get()),
                pesquisa_so_com_duracao=bool(self.pesq_so_com_duracao.get()))
            gravar = getattr(self.central, "salvar_preferencias", None)
            if callable(gravar):
                gravar()
        except Exception:
            pass

    def _mostrar_detalhes_resultado(self) -> None:
        """Miniatura + ficha do resultado selecionado (nada é baixado)."""
        indices = self._indices_selecionados(self.arvore_resultados)
        if not indices:
            return
        resultado = self._resultados[indices[0]]
        linhas = [f"{getattr(resultado, 'titulo', '')}"]
        linhas.append(f"{getattr(resultado, 'tipo_legivel', 'Vídeo')} · "
                      f"{getattr(resultado, 'canal', 'canal não informado') or 'canal não informado'}")
        duracao = getattr(resultado, "duracao", None)
        if duracao:
            linhas.append(f"Duração: {getattr(resultado, 'duracao_formatada', '')}"
                          + (" (compilado/mix longo)" if duracao > 3600 else ""))
        else:
            linhas.append("Duração: o YouTube não informou")
        if getattr(resultado, "quantidade", None):
            linhas.append(f"Playlist com {resultado.quantidade} vídeos")
        linhas.append("Canal verificado pelo YouTube"
                      if getattr(resultado, "canal_verificado", False)
                      else "Canal não verificável pelo YouTube")
        linhas.append("Já na biblioteca" if self._ja_na_biblioteca(resultado)
                      else "Ainda não está na biblioteca")
        url = str(getattr(resultado, "url", "") or "")
        if url:
            linhas.append(url)
        self.pesquisa_detalhe.set("\n".join(linhas))
        self._mostrar_miniatura_resultado(resultado)

    def _ja_na_biblioteca(self, resultado: Any) -> bool:
        url = str(getattr(resultado, "url", "") or "")
        if not url:
            return False
        try:
            return any(m.origem_url == url
                       for m in self.central.biblioteca.listar())
        except Exception:
            return False

    def _mostrar_miniatura_resultado(self, resultado: Any) -> None:
        """Baixa a miniatura do vídeo para o cache e mostra (falha em silêncio)."""
        url = str(getattr(resultado, "thumbnail", "") or "")
        if not url:
            self.pesquisa_thumb.image = None  # type: ignore[attr-defined]
            self.pesquisa_thumb.configure(image="", text="sem miniatura")
            return
        self.pesquisa_thumb.configure(text="carregando miniatura...", image="")

        def trabalho() -> Any:
            from baixador.web.thumbs import obter

            return obter(url, self.central.config.dados)

        def concluir(caminho: Any) -> None:
            imagem = _miniatura(caminho, (200, 112)) if caminho else None
            if imagem is None:
                self.pesquisa_thumb.configure(image="", text="miniatura indisponível")
                return
            self.pesquisa_thumb.image = imagem  # type: ignore[attr-defined]
            self.pesquisa_thumb.configure(image=imagem, text="")

        try:
            self._executar(trabalho, concluir)
        except Exception:
            self.pesquisa_thumb.configure(image="", text="miniatura indisponível")

    def _indices_selecionados(self, arvore: Any) -> list[int]:
        indices = []
        for iid in arvore.selection():
            try:
                indices.append(int(str(iid)))
            except ValueError:
                try:
                    indices.append(arvore.index(iid))
                except Exception:
                    continue
        return indices

    def _adicionar_selecionados(self) -> None:
        indices = self._indices_selecionados(self.arvore_resultados)
        if not indices:
            messagebox.showinfo("Cesta", "Marque um ou mais resultados na lista.")
            return
        escolhidos = [self._resultados[i] for i in indices if i < len(self._resultados)]
        adicionados, ignorados = self.central.adicionar_a_selecao(escolhidos)
        origem = getattr(escolhidos[0], "canal", "") or "Pesquisa"
        self.notificar(
            "Adicionado à cesta",
            f"{adicionados} música(s) adicionada(s) ({origem})."
            + (f" {ignorados} já estavam na cesta." if ignorados else "")
            + f"\nTotal na cesta: {self.central.selecao.quantidade()}.")
        self._atualizar_contador_cesta()

    def _adicionar_todos(self) -> None:
        if not self._resultados:
            return
        adicionados, ignorados = self.central.adicionar_a_selecao(self._resultados)
        self.notificar("Cesta", f"{adicionados} adicionada(s)"
                                + (f", {ignorados} repetida(s)" if ignorados else "")
                                + f". Total: {self.central.selecao.quantidade()}.")
        self._atualizar_contador_cesta()

    def _abrir_playlist_selecionada(self) -> None:
        indices = self._indices_selecionados(self.arvore_resultados)
        if not indices:
            messagebox.showinfo("Playlist", "Marque uma playlist na lista.")
            return
        resultado = self._resultados[indices[0]]
        if not getattr(resultado, "eh_playlist", False):
            messagebox.showinfo(
                "Playlist",
                "Esse resultado é um vídeo/canal. Marque uma linha do tipo Playlist.")
            return
        self.playlist_titulo_var.set(f"Carregando {resultado.titulo}...")
        self.definir_status("Listando os itens da playlist (nada foi baixado)...")

        def concluir(playlist: Any) -> None:
            self._playlist_aberta = playlist
            for item in self.arvore_playlist.get_children():
                self.arvore_playlist.delete(item)
            self._preencher_playlist(playlist)
            self._mostrar_titulo_playlist(playlist)
            self.definir_status(f"Playlist listada: {playlist.quantidade} item(ns).")

        self._executar(lambda: self.central.listar_playlist(resultado.url), concluir)

    def _preencher_playlist(self, playlist: Any) -> None:
        """Insere os itens e já marca os que passam no teto/ao vivo."""
        for item in self.arvore_playlist.get_children():
            self.arvore_playlist.delete(item)
        avaliados = self.central.avaliar_itens(playlist.itens)
        aprovados = []
        for item, avaliacao in avaliados:
            self.arvore_playlist.insert("", "end", iid=str(item.indice), values=(
                item.indice, item.titulo, item.duracao_formatada,
                "disponível" if item.disponivel else "privado/removido",
                avaliacao.motivo or ("" if item.disponivel else "indisponível")))
            if item.disponivel and avaliacao.marcar:
                aprovados.append(str(item.indice))
        if aprovados:
            self.arvore_playlist.selection_set(aprovados)
        from baixador.web.playlist import analisar

        resumo = analisar(playlist.itens)
        self.playlist_resumo_var.set(resumo.como_texto())
        fora = len(playlist.itens) - len(aprovados)
        if fora:
            self.definir_status(
                f"{len(aprovados)} de {len(playlist.itens)} marcada(s); "
                f"{fora} fora do filtro (veja a coluna 'Fora do filtro').")

    def _mostrar_titulo_playlist(self, playlist: Any) -> None:
        """Título honesto: quantos itens estão na tela e quantos existem."""
        minutos = int(playlist.duracao_total // 60)
        texto = (f"{playlist.titulo} — {playlist.quantidade} item(ns) na lista, "
                 f"~{minutos} min")
        if playlist.total_informado and playlist.restantes:
            texto += f" · faltam {playlist.restantes} (de {playlist.total_informado})"
        elif playlist.total_informado and not playlist.restantes:
            texto += " · lista completa"
        self.playlist_titulo_var.set(texto)

    def _listar_mais_itens(self) -> None:
        """Traz a próxima janela sem perder o que já está marcado."""
        playlist = self._playlist_aberta
        if playlist is None:
            messagebox.showinfo("Playlist", "Abra uma playlist primeiro.")
            return
        if not playlist.truncada:
            self.definir_status("A lista já está completa: nada mais a trazer.")
            return
        marcados = set(self.arvore_playlist.selection())
        self.definir_status(f"Listando mais itens de \"{playlist.titulo}\"...")

        def concluir(nova: Any) -> None:
            self._playlist_aberta = nova
            for item in self.arvore_playlist.get_children():
                self.arvore_playlist.delete(item)
            self._preencher_playlist(nova)
            # a marcação anterior continua válida (o número do item não muda)
            if marcados:
                self.arvore_playlist.selection_set(
                    [iid for iid in marcados
                     if self.arvore_playlist.exists(iid)])
            self._mostrar_titulo_playlist(nova)
            self.definir_status(
                f"{nova.quantidade} item(ns) na lista"
                + (f"; faltam {nova.restantes}." if nova.restantes else "; fim da lista."))

        self._executar(lambda: self.central.listar_mais_playlist(playlist), concluir)

    def _marcar_playlist(self, marcar: bool) -> None:
        itens = self.arvore_playlist.get_children()
        if marcar:
            self.arvore_playlist.selection_set(itens)
        else:
            self.arvore_playlist.selection_remove(itens)

    def _filtrar_ao_vivo_playlist(self) -> None:
        from baixador.midia.previa import analisar

        escolhidos = []
        fora = 0
        for iid in self.arvore_playlist.get_children():
            valores = self.arvore_playlist.item(iid, "values")
            titulo = str(valores[1]) if len(valores) > 1 else ""
            situacao = str(valores[3]) if len(valores) > 3 else ""
            if "privado" in situacao or "removido" in situacao:
                fora += 1
                continue
            if analisar(titulo).possivel_ao_vivo:
                fora += 1
                continue
            escolhidos.append(iid)
        self.arvore_playlist.selection_set(escolhidos)
        self.definir_status(
            f"{len(escolhidos)} marcada(s); {fora} fora (ao vivo/show ou indisponível).")

    def _adicionar_da_playlist(self) -> None:
        playlist = self._playlist_aberta
        if playlist is None:
            return
        indices = {int(str(iid)) for iid in self.arvore_playlist.selection()}
        escolhidos = [item for item in playlist.itens
                      if item.indice in indices and item.disponivel]
        if not escolhidos:
            messagebox.showinfo("Cesta", "Marque os itens da playlist que deseja.")
            return
        adicionados, ignorados = self.central.adicionar_a_selecao(
            escolhidos, origem=f"Playlist: {playlist.titulo}")
        self.notificar("Cesta",
                       f"{adicionados} adicionada(s) de \"{playlist.titulo}\""
                       + (f", {ignorados} repetida(s)" if ignorados else "")
                       + f". Total: {self.central.selecao.quantidade()}.")
        self._atualizar_contador_cesta()

    def _marcar_disponiveis(self) -> None:
        """Marca só o que existe: privado/removido não entra na cesta."""
        playlist = self._playlist_aberta
        if playlist is None:
            messagebox.showinfo("Playlist", "Abra uma playlist primeiro.")
            return
        disponiveis = [str(item.indice) for item in playlist.itens
                       if item.disponivel]
        self.arvore_playlist.selection_set(
            [iid for iid in disponiveis if self.arvore_playlist.exists(iid)])
        fora = len(playlist.itens) - len(disponiveis)
        self.definir_status(
            f"{len(disponiveis)} item(ns) disponível(is) marcado(s)"
            + (f"; {fora} privado/removido ficou de fora." if fora else "."))

    def _ver_o_que_ja_tenho(self) -> None:
        """Diz quantos itens da playlist aberta já estão na biblioteca."""
        playlist = self._playlist_aberta
        if playlist is None:
            messagebox.showinfo("Playlist", "Abra uma playlist primeiro.")
            return
        urls = {m.origem_url for m in self.central.biblioteca.listar()
                if m.origem_url}
        meus = [item for item in playlist.itens if item.url in urls]
        if not meus:
            self.notificar(
                "Playlist",
                f"Nenhum dos {playlist.quantidade} item(ns) desta playlist já "
                "está na sua biblioteca.")
            return
        linhas = "\n".join(f"• {item.titulo}" for item in meus[:12])
        extra = (f"\n... e mais {len(meus) - 12}." if len(meus) > 12 else "")
        self.notificar(
            "Playlist",
            f"{len(meus)} de {playlist.quantidade} já estão na biblioteca:\n"
            f"{linhas}{extra}")

    def _salvar_playlist_aberta(self) -> None:
        """Guarda a playlist do YouTube como playlist local (só o que existe)."""
        playlist = self._playlist_aberta
        if playlist is None:
            messagebox.showinfo("Playlist", "Abra uma playlist primeiro.")
            return
        nome = simpledialog.askstring(
            "Salvar na biblioteca", "Nome da playlist local:",
            initialvalue=playlist.titulo[:60] or "Playlist do YouTube",
            parent=self.raiz)
        if not nome or not str(nome).strip():
            return
        urls = {m.origem_url: m.id for m in self.central.biblioteca.listar()
                if m.origem_url}
        ids = [urls[item.url] for item in playlist.itens if item.url in urls]
        if not ids:
            self.notificar(
                "Playlist",
                "Nenhum item desta playlist já foi baixado, então não há "
                "música para guardar. A playlist local só guarda músicas que "
                "estão na biblioteca.", erro=True)
            return
        nova = self.central.criar_playlist(str(nome).strip())
        adicionadas = self.central.adicionar_a_playlist(nova, ids)
        self.definir_status(
            f"Playlist \"{nome}\" criada com {adicionadas} música(s) da "
            f"playlist aberta"
            + (f"; {playlist.quantidade - len(ids)} item(ns) ainda não baixado(s) "
               "ficaram fora." if playlist.quantidade > len(ids) else "."))
        self._atualizar_fila()

    def _previa_selecionada(self) -> None:
        indices = self._indices_selecionados(self.arvore_resultados)
        if not indices:
            messagebox.showinfo("Prévia", "Marque um vídeo para ouvir um trecho.")
            return
        resultado = self._resultados[indices[0]]
        self.definir_status("Preparando um trecho para ouvir (10–40 s)...")

        def trabalho() -> Any:
            previa = self.central.aplicacao.previa
            pasta = previa.pasta_temporaria()
            arquivo = previa.baixar_amostra(resultado.url, pasta)
            from baixador.midia.previa import pasta_para_tocar

            return pasta_para_tocar(arquivo, pasta)

        def concluir(caminho: Any) -> None:
            if caminho:
                self._abrir_no_sistema(str(caminho))
                self.definir_status("Trecho aberto no player do Windows.")
            else:
                self.definir_status("Não foi possível preparar o trecho.")

        self._executar(trabalho, concluir)

    def _baixar_selecionados_agora(self) -> None:
        indices = self._indices_selecionados(self.arvore_resultados)
        if not indices:
            messagebox.showinfo("Baixar", "Marque o que deseja baixar.")
            return
        escolhidos = [self._resultados[i] for i in indices if i < len(self._resultados)]
        formato = self.central.preferencias.formato_padrao
        for resultado in escolhidos:
            if getattr(resultado, "eh_playlist", False):
                continue
            self.central.gerenciador.adicionar(
                resultado.url, formato, titulo=getattr(resultado, "titulo", ""),
                canal=getattr(resultado, "canal", ""),
                duracao=getattr(resultado, "duracao", None),
                thumbnail=getattr(resultado, "thumbnail", ""),
                origem=getattr(resultado, "canal", "") or "Pesquisa")
        self.mostrar("fila")
        self.central.iniciar_downloads()
        self.definir_status("Download iniciado — acompanhe na página da fila.")

    def _abrir_no_sistema(self, caminho: str) -> None:
        """Abre arquivo/pasta no programa padrão do sistema (Windows/Linux)."""
        import os
        import subprocess

        try:
            if sys.platform == "win32":
                os.startfile(caminho)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", caminho])
            else:
                subprocess.Popen(["xdg-open", caminho])
        except Exception as erro:
            self.definir_status(f"Não foi possível abrir: {erro}")

    # =====================================================================
    # PÁGINAS: ARTISTAS e ÁLBUNS
    # =====================================================================
    def _montar_artistas(self, area: Any) -> None:
        ttk.Label(area, text="Artistas", style="Titulo.TLabel").pack(anchor="w")
        ttk.Label(area, text="Clique duas vezes para ver as músicas do artista.",
                  style="Fraco.TLabel").pack(anchor="w", pady=(0, 6))
        corpo = ttk.Frame(area)
        corpo.pack(fill="both", expand=True)
        self.arvore_artistas = ttk.Treeview(
            corpo, columns=("nome", "total", "duracao"), show="headings",
            height=16, selectmode="browse")
        for coluna, titulo, largura in (("nome", "Artista", 380),
                                        ("total", "Músicas", 100),
                                        ("duracao", "Tempo", 120)):
            self.arvore_artistas.heading(coluna, text=titulo)
            self.arvore_artistas.column(coluna, width=largura)
        self.arvore_artistas.pack(fill="both", expand=True)
        self.arvore_artistas.bind("<Double-1>", lambda _e: self._abrir_artista())
        acoes = ttk.Frame(area)
        acoes.pack(fill="x", pady=6)
        ttk.Button(acoes, text="Ver músicas", style="Principal.TButton",
                   command=self._abrir_artista).pack(side="left")
        ttk.Button(acoes, text="★ Favoritar artista",
                   command=self._favoritar_artista).pack(side="left", padx=6)
        ttk.Button(acoes, text="Tocar tudo",
                   command=self._tocar_artista).pack(side="left")
        self.artista_detalhe = tk.StringVar(value="")
        ttk.Label(area, textvariable=self.artista_detalhe,
                  style="Fraco.TLabel", wraplength=980).pack(anchor="w", pady=4)

    def _atualizar_artistas(self) -> None:
        if not hasattr(self, "arvore_artistas"):
            return
        for item in self.arvore_artistas.get_children():
            self.arvore_artistas.delete(item)
        for artista in self.central.artistas():
            segundos = int(artista["duracao"] or 0)
            nome = artista["nome"]
            favorito = self.central.biblioteca.eh_favorito("artista", nome)
            self.arvore_artistas.insert("", "end", iid=nome, values=(
                ("★ " if favorito else "") + nome, artista["total"],
                f"{segundos // 60} min"))

    def _artista_escolhido(self) -> str:
        escolha = self.arvore_artistas.selection()
        if not escolha:
            return ""
        return str(escolha[0])

    def _abrir_artista(self) -> None:
        nome = self._artista_escolhido()
        if not nome:
            return
        musicas = self.central.musicas(artista=nome, ordenar="album")
        self.artista_detalhe.set(
            f"{nome}: " + ", ".join(
                f"{m.album or 'sem álbum'} — {m.titulo_exibicao}" for m in musicas[:20]))
        self._musicas_fila = musicas
        self.definir_status(f"{len(musicas)} música(s) de {nome}.")

    def _tocar_artista(self) -> None:
        nome = self._artista_escolhido()
        if not nome:
            return
        musicas = self.central.musicas(artista=nome, ordenar="album")
        if self.central.tocar_fila(musicas):
            self._atualizar_player()
        else:
            self._avisar_sem_player()

    def _favoritar_artista(self) -> None:
        nome = self._artista_escolhido()
        if not nome:
            return
        ativo = self.central.favoritar("artista", nome)
        self._atualizar_artistas()
        self.definir_status(
            f"{nome} {'adicionado aos' if ativo else 'removido dos'} favoritos.")

    def _montar_albuns(self, area: Any) -> None:
        ttk.Label(area, text="Álbuns", style="Titulo.TLabel").pack(anchor="w")
        corpo = ttk.Frame(area)
        corpo.pack(fill="both", expand=True, pady=6)
        self.arvore_albuns = ttk.Treeview(
            corpo, columns=("album", "artista", "ano", "total"),
            show="headings", height=16, selectmode="browse")
        for coluna, titulo, largura in (("album", "Álbum", 340),
                                        ("artista", "Artista", 240),
                                        ("ano", "Ano", 70), ("total", "Músicas", 90)):
            self.arvore_albuns.heading(coluna, text=titulo)
            self.arvore_albuns.column(coluna, width=largura)
        self.arvore_albuns.pack(fill="both", expand=True)
        self.arvore_albuns.bind("<Double-1>", lambda _e: self._tocar_album())
        acoes = ttk.Frame(area)
        acoes.pack(fill="x")
        ttk.Button(acoes, text="Tocar álbum", style="Principal.TButton",
                   command=self._tocar_album).pack(side="left")
        ttk.Button(acoes, text="★ Favoritar álbum",
                   command=self._favoritar_album).pack(side="left", padx=6)
        self.album_detalhe = tk.StringVar(value="")
        ttk.Label(area, textvariable=self.album_detalhe,
                  style="Fraco.TLabel").pack(anchor="w", pady=4)

    def _atualizar_albuns(self) -> None:
        if not hasattr(self, "arvore_albuns"):
            return
        for item in self.arvore_albuns.get_children():
            self.arvore_albuns.delete(item)
        for posicao, album in enumerate(self.central.albuns()):
            self.arvore_albuns.insert("", "end", iid=str(posicao), values=(
                album["album"], album["artista"] or "—", album["ano"] or "—",
                album["total"]))

    def _album_escolhido(self) -> Any:
        escolha = self.arvore_albuns.selection()
        if not escolha:
            return None
        albuns = self.central.albuns()
        indice = int(str(escolha[0]))
        return albuns[indice] if indice < len(albuns) else None

    def _tocar_album(self) -> None:
        album = self._album_escolhido()
        if album is None:
            return
        musicas = self.central.biblioteca.listar(album=album["album"],
                                                 ordenar="album")
        if self.central.tocar_fila(musicas):
            self._atualizar_player()
            self.album_detalhe.set(
                f"{album['album']}: " + ", ".join(m.titulo_exibicao for m in musicas))
        else:
            self._avisar_sem_player()

    def _favoritar_album(self) -> None:
        album = self._album_escolhido()
        if album is None:
            return
        ativo = self.central.favoritar("album", album["album"])
        self.definir_status(
            f"Álbum {album['album']} {'favoritado' if ativo else 'removido dos favoritos'}.")

    # =====================================================================
    # PÁGINA: HISTÓRICO
    # =====================================================================
    def _montar_historico(self, area: Any) -> None:
        ttk.Label(area, text="Histórico", style="Titulo.TLabel").pack(anchor="w")
        ttk.Label(area, text="Downloads, falhas, músicas adicionadas e pesquisas.",
                  style="Fraco.TLabel").pack(anchor="w", pady=(0, 6))
        corpo = ttk.Frame(area)
        corpo.pack(fill="both", expand=True)
        self.arvore_historico = ttk.Treeview(
            corpo, columns=("quando", "status", "formato", "url", "mensagem"),
            show="headings", height=14, selectmode="extended")
        for coluna, titulo, largura in (("quando", "Quando", 150),
                                        ("status", "Status", 120),
                                        ("formato", "Formato", 80),
                                        ("url", "Música/URL", 320),
                                        ("mensagem", "Mensagem", 300)):
            self.arvore_historico.heading(coluna, text=titulo)
            self.arvore_historico.column(coluna, width=largura)
        self.arvore_historico.pack(fill="both", expand=True)
        acoes = ttk.Frame(area)
        acoes.pack(fill="x", pady=6)
        ttk.Button(acoes, text="Atualizar",
                   command=self._atualizar_historico).pack(side="left")
        ttk.Button(acoes, text="Baixar de novo",
                   command=self._rebaixar_do_historico).pack(side="left", padx=6)
        ttk.Button(acoes, text="Abrir arquivo",
                   command=self._abrir_do_historico).pack(side="left")
        ttk.Button(acoes, text="Limpar pesquisas",
                   command=self._limpar_pesquisas).pack(side="right")
        self.pesquisas_var = tk.StringVar(value="")
        ttk.Label(area, textvariable=self.pesquisas_var,
                  style="Fraco.TLabel", wraplength=980).pack(anchor="w")

    def _atualizar_historico(self) -> None:
        if not hasattr(self, "arvore_historico"):
            return
        for item in self.arvore_historico.get_children():
            self.arvore_historico.delete(item)
        registros = self.central.aplicacao.historico.listar(200, incluir_erros=True)
        registros.sort(key=lambda r: str(r.get("data_hora") or ""), reverse=True)
        self._historico_atual = registros
        for posicao, registro in enumerate(registros):
            quando = str(registro.get("data_hora") or "")[:16].replace("T", " ")
            self.arvore_historico.insert("", "end", iid=str(posicao), values=(
                quando, str(registro.get("status") or ""),
                str(registro.get("formato") or "").upper(),
                str(registro.get("caminho") or registro.get("url") or "")[:80],
                str(registro.get("mensagem") or "")[:80]))
        pesquisas = self.central.pesquisas_recentes(10)
        self.pesquisas_var.set(
            "Pesquisas recentes: " + " · ".join(p["consulta"] for p in pesquisas)
            if pesquisas else "Nenhuma pesquisa registrada ainda.")

    def _rebaixar_do_historico(self) -> None:
        registros = getattr(self, "_historico_atual", [])
        escolhas = self.arvore_historico.selection()
        urls = []
        for iid in escolhas:
            indice = int(str(iid))
            if 0 <= indice < len(registros):
                url = str(registros[indice].get("url") or "")
                if url.startswith("http") and url not in urls:
                    urls.append(url)
        if not urls:
            messagebox.showinfo("Histórico", "As linhas marcadas não têm URL.")
            return
        formato = self.central.preferencias.formato_padrao
        self.central.gerenciador.adicionar_varios([(u, formato) for u in urls])
        self.mostrar("fila")
        self.central.iniciar_downloads()

    def _abrir_do_historico(self) -> None:
        registros = getattr(self, "_historico_atual", [])
        escolhas = self.arvore_historico.selection()
        if not escolhas:
            return
        indice = int(str(escolhas[0]))
        if 0 <= indice < len(registros):
            caminho = str(registros[indice].get("caminho") or "")
            if caminho and Path(caminho).exists():
                self._abrir_no_sistema(caminho)
            else:
                messagebox.showinfo("Histórico", "O arquivo não está mais no disco.")

    def _limpar_pesquisas(self) -> None:
        self.central.biblioteca.limpar_pesquisas()
        self._atualizar_historico()

    # =====================================================================
    # PÁGINA: FAVORITOS
    # =====================================================================
    def _montar_favoritos(self, area: Any) -> None:
        ttk.Label(area, text="Favoritos", style="Titulo.TLabel").pack(anchor="w")
        ttk.Label(area, text="Músicas, artistas, álbuns e playlists que você marcou.",
                  style="Fraco.TLabel").pack(anchor="w", pady=(0, 6))
        corpo = ttk.Frame(area)
        corpo.pack(fill="both", expand=True)
        self.arvore_favoritos = ttk.Treeview(
            corpo, columns=("titulo", "artista", "album", "duracao"),
            show="headings", height=16, selectmode="extended")
        for coluna, titulo, largura in (("titulo", "Música", 320),
                                        ("artista", "Artista", 200),
                                        ("album", "Álbum", 200),
                                        ("duracao", "Duração", 80)):
            self.arvore_favoritos.heading(coluna, text=titulo)
            self.arvore_favoritos.column(coluna, width=largura)
        self.arvore_favoritos.pack(fill="both", expand=True)
        self.arvore_favoritos.bind("<Double-1>", lambda _e: self._tocar_favoritas())
        acoes = ttk.Frame(area)
        acoes.pack(fill="x", pady=6)
        ttk.Button(acoes, text="▶ Tocar favoritas", style="Principal.TButton",
                   command=self._tocar_favoritas).pack(side="left")
        ttk.Button(acoes, text="Remover dos favoritos",
                   command=self._remover_favorita).pack(side="left", padx=6)
        self.favoritos_outros = tk.StringVar(value="")
        ttk.Label(area, textvariable=self.favoritos_outros,
                  style="Fraco.TLabel", wraplength=980).pack(anchor="w")

    def _atualizar_favoritos(self) -> None:
        if not hasattr(self, "arvore_favoritos"):
            return
        for item in self.arvore_favoritos.get_children():
            self.arvore_favoritos.delete(item)
        musicas = self.central.musicas_favoritas()
        self._musicas_favoritas = musicas
        for musica in musicas:
            self.arvore_favoritos.insert("", "end", iid=str(musica.id), values=(
                musica.titulo_exibicao, musica.artista or "—",
                musica.album or "—", musica.duracao_formatada))
        artistas = [f["chave"] for f in self.central.favoritos("artista")]
        albuns = [f["chave"] for f in self.central.favoritos("album")]
        self.favoritos_outros.set(
            ("Artistas favoritos: " + ", ".join(artistas) if artistas else "")
            + ("\n" if artistas and albuns else "")
            + ("Álbuns favoritos: " + ", ".join(albuns) if albuns else ""))

    def _tocar_favoritas(self) -> None:
        musicas = getattr(self, "_musicas_favoritas", [])
        if not musicas:
            return
        if self.central.tocar_fila(musicas):
            self._atualizar_player()
        else:
            self._avisar_sem_player()

    def _remover_favorita(self) -> None:
        for iid in self.arvore_favoritos.selection():
            self.central.favoritar_musica(int(str(iid)))
        self._atualizar_favoritos()

    # =====================================================================
    # PÁGINA: CONFIGURAÇÕES
    # =====================================================================
    def _montar_config(self, area: Any) -> None:
        ttk.Label(area, text="Configurações", style="Titulo.TLabel").pack(anchor="w")
        rolagem = ttk.Frame(area)
        rolagem.pack(fill="both", expand=True)
        canvas = tk.Canvas(rolagem, highlightthickness=0,
                           background=self.cores["fundo"])
        barra = ttk.Scrollbar(rolagem, orient="vertical", command=canvas.yview)
        quadro = ttk.Frame(canvas)
        quadro.bind("<Configure>",
                    lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=quadro, anchor="nw")
        canvas.configure(yscrollcommand=barra.set)
        canvas.pack(side="left", fill="both", expand=True)
        barra.pack(side="right", fill="y")
        prefs = self.central.preferencias

        aparencia = ttk.Labelframe(quadro, text="APARÊNCIA")
        aparencia.pack(fill="x", padx=8, pady=6)
        ttk.Label(aparencia, text="Tema:").grid(row=0, column=0, sticky="e", padx=6)
        self.config_tema = tk.StringVar(value=getattr(prefs, "tema", "escuro"))
        ttk.Combobox(aparencia, textvariable=self.config_tema, width=12,
                     state="readonly", values=("escuro", "claro")).grid(
            row=0, column=1, sticky="w", pady=3)
        ttk.Label(aparencia, text="Tamanho do texto:").grid(row=1, column=0,
                                                            sticky="e", padx=6)
        self.config_fonte = tk.StringVar(value=getattr(prefs, "tamanho_fonte", "normal"))
        ttk.Combobox(aparencia, textvariable=self.config_fonte, width=12,
                     state="readonly",
                     values=("pequeno", "normal", "grande")).grid(
            row=1, column=1, sticky="w", pady=3)

        downloads = ttk.Labelframe(quadro, text="DOWNLOADS")
        downloads.pack(fill="x", padx=8, pady=6)
        ttk.Label(downloads, text="Pasta das músicas:").grid(
            row=0, column=0, sticky="e", padx=6)
        self.config_mp3 = tk.StringVar(value=getattr(prefs, "diretorio_mp3", ""))
        ttk.Entry(downloads, textvariable=self.config_mp3, width=52).grid(
            row=0, column=1, sticky="we", pady=3)
        ttk.Button(downloads, text="Escolher...",
                   command=lambda: self._escolher_pasta(self.config_mp3)).grid(
            row=0, column=2, padx=4)
        ttk.Label(downloads, text="Bitrate do MP3:").grid(
            row=1, column=0, sticky="e", padx=6)
        from baixador.nucleo.preferencias import OPCOES_BITRATE, descrever_bitrate

        self._bitrates = dict(OPCOES_BITRATE)
        self.config_qualidade = tk.StringVar(
            value=descrever_bitrate(str(prefs.qualidade_mp3)))
        ttk.Combobox(downloads, textvariable=self.config_qualidade, width=42,
                     state="readonly",
                     values=[texto for texto in self._bitrates.values()]).grid(
            row=1, column=1, sticky="w", pady=3)
        self.bitrate_dica = tk.StringVar(
            value="O arquivo final é sempre MP3; a qualidade da fonte é o "
                  "melhor áudio disponível no YouTube.")
        ttk.Label(downloads, textvariable=self.bitrate_dica,
                  style="Fraco.TLabel").grid(row=1, column=2, sticky="w", padx=6)
        ttk.Label(downloads, text="Downloads ao mesmo tempo (1–4):").grid(
            row=2, column=0, sticky="e", padx=6)
        self.config_simultaneos = tk.IntVar(value=int(prefs.downloads_simultaneos))
        ttk.Spinbox(downloads, from_=1, to=4, textvariable=self.config_simultaneos,
                    width=6).grid(row=2, column=1, sticky="w", pady=3)
        ttk.Label(downloads, text="Se o arquivo já existir:").grid(
            row=3, column=0, sticky="e", padx=6)
        self.config_sobrescrita = tk.StringVar(value=str(prefs.sobrescrita))
        ttk.Combobox(downloads, textvariable=self.config_sobrescrita, width=14,
                     state="readonly",
                     values=("perguntar", "pular", "renomear", "sobrescrever")).grid(
            row=3, column=1, sticky="w", pady=3)
        self.config_organizar = tk.BooleanVar(value=bool(prefs.organizar_nomes))
        ttk.Checkbutton(downloads, text="Salvar como \"Artista - Título.mp3\"",
                        variable=self.config_organizar).grid(
            row=4, column=0, columnspan=3, sticky="w", padx=6, pady=2)
        self.config_album = tk.BooleanVar(value=bool(prefs.organizar_por_album))
        ttk.Checkbutton(downloads, text="Guardar em subpastas Artista/Álbum",
                        variable=self.config_album).grid(
            row=5, column=0, columnspan=3, sticky="w", padx=6, pady=2)

        metadados = ttk.Labelframe(quadro, text="METADADOS E CAPAS")
        metadados.pack(fill="x", padx=8, pady=6)
        self.config_metadados = tk.BooleanVar(value=bool(prefs.metadados_ativos))
        ttk.Checkbutton(metadados,
                        text="Identificar metadados automaticamente (APIs + IA)",
                        variable=self.config_metadados).pack(anchor="w", padx=6, pady=2)
        self.config_capas = tk.BooleanVar(value=bool(prefs.buscar_capas))
        ttk.Checkbutton(metadados, text="Buscar e incorporar capas oficiais",
                        variable=self.config_capas).pack(anchor="w", padx=6, pady=2)

        audio = ttk.Labelframe(quadro, text="CONVERSÃO E QUALIDADE DO ÁUDIO")
        audio.pack(fill="x", padx=8, pady=6)
        self.config_normalizar = tk.BooleanVar(
            value=bool(getattr(prefs, "normalizar_volume", False)))
        ttk.Checkbutton(audio,
                        text="Normalizar volume ao terminar (EBU R128, -16 LUFS)",
                        variable=self.config_normalizar).pack(anchor="w", padx=6, pady=2)
        self.config_replaygain = tk.BooleanVar(
            value=bool(getattr(prefs, "replaygain", False)))
        ttk.Checkbutton(audio,
                        text="Gravar ReplayGain (mede o volume e nivela no player)",
                        variable=self.config_replaygain).pack(anchor="w", padx=6, pady=2)
        self.config_verificar = tk.BooleanVar(
            value=bool(getattr(prefs, "verificar_audio", True)))
        ttk.Checkbutton(audio,
                        text="Verificar o MP3 antes de marcar como concluído",
                        variable=self.config_verificar).pack(anchor="w", padx=6, pady=2)
        linha_teto = ttk.Frame(audio)
        linha_teto.pack(anchor="w", fill="x", padx=6, pady=2)
        ttk.Label(linha_teto,
                  text="Teto de duração por música (minutos, 0 = sem limite):"
                  ).pack(side="left")
        self.config_teto = tk.StringVar(
            value=str(int(getattr(prefs, "duracao_maxima_min", 0) or 0)))
        ttk.Entry(linha_teto, textvariable=self.config_teto, width=6).pack(
            side="left", padx=6)
        self.config_ao_vivo = tk.BooleanVar(
            value=bool(getattr(prefs, "filtrar_ao_vivo", True)))
        ttk.Checkbutton(audio,
                        text="Desmarcar automaticamente gravações ao vivo/show",
                        variable=self.config_ao_vivo).pack(anchor="w", padx=6, pady=2)

        ia = ttk.Labelframe(quadro, text="INTELIGÊNCIA ARTIFICIAL (opcional)")
        ia.pack(fill="x", padx=8, pady=6)
        self.config_chave_status = tk.StringVar(value="")
        ttk.Label(ia, textvariable=self.config_chave_status,
                  wraplength=760).grid(row=0, column=0, columnspan=3,
                                       sticky="w", padx=6, pady=3)
        ttk.Button(ia, text="Importar chave (api.txt)",
                   command=self._importar_chave).grid(row=1, column=0, padx=6, pady=3)
        ttk.Button(ia, text="Testar chave",
                   command=self._testar_chave).grid(row=1, column=1, padx=6)
        ttk.Button(ia, text="Remover",
                   command=self._remover_chave).grid(row=1, column=2, padx=6)

        servicos = ttk.Labelframe(quadro, text="YOUTUBE E COOKIES")
        servicos.pack(fill="x", padx=8, pady=6)
        self.config_cookies_status = tk.StringVar(value="")
        ttk.Label(servicos, textvariable=self.config_cookies_status,
                  wraplength=760).grid(row=0, column=0, columnspan=3,
                                       sticky="w", padx=6, pady=3)
        ttk.Button(servicos, text="Importar cookies.txt",
                   command=self._importar_cookies).grid(row=1, column=0, padx=6, pady=3)
        ttk.Button(servicos, text="Remover cookies",
                   command=self._remover_cookies).grid(row=1, column=1, padx=6)

        sistema = ttk.Labelframe(quadro, text="SISTEMA E MANUTENÇÃO")
        sistema.pack(fill="x", padx=8, pady=6)
        self.config_versao = tk.StringVar(value="")
        ttk.Label(sistema, textvariable=self.config_versao,
                  wraplength=760).grid(row=0, column=0, columnspan=3,
                                       sticky="w", padx=6, pady=3)
        ttk.Button(sistema, text="Atualizar o yt-dlp",
                   command=self._atualizar_ytdlp).grid(row=1, column=0, padx=6, pady=3)
        ttk.Button(sistema, text="Limpar arquivos temporários",
                   command=self._limpar_temporarios).grid(row=1, column=1, padx=6)
        ttk.Button(sistema, text="Testar dependências",
                   command=self._testar_dependencias).grid(row=1, column=2, padx=6)
        self.config_sincronizar = tk.BooleanVar(
            value=bool(getattr(prefs, "sincronizar_ao_abrir", True)))
        ttk.Checkbutton(sistema, text="Indexar a pasta de músicas ao abrir",
                        variable=self.config_sincronizar).grid(
            row=2, column=0, columnspan=3, sticky="w", padx=6, pady=2)

        ttk.Button(quadro, text="Salvar configurações", style="Principal.TButton",
                   command=self._salvar_config).pack(anchor="w", padx=8, pady=10)
        self._atualizar_config()

    def _escolher_pasta(self, variavel: Any) -> None:
        escolhida = filedialog.askdirectory()
        if escolhida:
            variavel.set(escolhida)

    def _atualizar_config(self) -> None:
        try:
            status = self.central.status_chave()
            texto = ("Chave de IA configurada (" + str(getattr(status, "mascara", ""))
                     + ")") if getattr(status, "configurada", False) else (
                "Nenhuma chave de IA (opcional — o programa funciona sem ela).")
            self.config_chave_status.set(texto)
        except Exception as erro:
            self.config_chave_status.set(f"Chave de IA: {erro}")
        try:
            cookies = self.central.status_cookies()
            self.config_cookies_status.set(
                "cookies.txt carregado ("
                f"{getattr(cookies, 'do_youtube', 0)} cookie(s) do YouTube)."
                if getattr(cookies, "configurado", False) else
                "Nenhum cookies.txt (downloads públicos funcionam sem ele).")
        except Exception as erro:
            self.config_cookies_status.set(f"Cookies: {erro}")
        try:
            versao = self.central.versao_ytdlp() or "não identificada"
        except Exception:
            versao = "não identificada"
        audio = ("ffplay disponível" if self.central.ffplay else
                 "ffplay ausente — o áudio tocará no player do Windows")
        self.config_versao.set(
            f"yt-dlp: {versao} · áudio: {audio} · "
            f"biblioteca: {self.central.biblioteca.caminho}")

    def _salvar_config(self) -> None:
        try:
            self.central.aplicar_preferencias(replace(self.central.preferencias,
                tema=self.config_tema.get(), tamanho_fonte=self.config_fonte.get(),
                diretorio_mp3=self.config_mp3.get().strip(),
                qualidade_mp3=self._codigo_do_bitrate(),
                downloads_simultaneos=int(self.config_simultaneos.get()),
                sobrescrita=self.config_sobrescrita.get(),
                organizar_nomes=bool(self.config_organizar.get()),
                organizar_por_album=bool(self.config_album.get()),
                metadados_ativos=bool(self.config_metadados.get()),
                buscar_capas=bool(self.config_capas.get()),
                normalizar_volume=bool(self.config_normalizar.get()),
                verificar_audio=bool(self.config_verificar.get()),
                replaygain=bool(self.config_replaygain.get()),
                duracao_maxima_min=int(self.config_teto.get() or 0),
                filtrar_ao_vivo=bool(self.config_ao_vivo.get()),
                sincronizar_ao_abrir=bool(self.config_sincronizar.get())))
        except Exception as erro:
            self.notificar("Configurações", str(erro), erro=True)
            return
        self.cores = tema.aplicar(
            self.raiz, nome=self.config_tema.get(), tamanho=self.config_fonte.get())
        self.notificar("Configurações", "Salvo. As mudanças já valem nesta sessão.")

    def _codigo_do_bitrate(self) -> str:
        """Texto escolhido na lista → valor que o yt-dlp entende."""
        escolhido = str(self.config_qualidade.get()).strip()
        for codigo, descricao in self._bitrates.items():
            if escolhido == descricao:
                return codigo
        return escolhido or "0"   # valor personalizado digitado à mão

    def _importar_chave(self) -> None:
        caminho = filedialog.askopenfilename(
            title="Arquivo com a chave da IA",
            filetypes=(("Texto", "*.txt"), ("Todos", "*.*")))
        if not caminho:
            return
        try:
            info = self.central.importar_chave(caminho)
        except Exception as erro:
            self.notificar("Chave de IA", str(erro), erro=True)
            return
        self._atualizar_config()
        self.notificar("Chave de IA", getattr(info, "mensagem", "Chave importada."))

    def _testar_chave(self) -> None:
        self.definir_status("Testando a chave...")

        def concluir(resultado: tuple[bool, str]) -> None:
            self.notificar("Chave de IA", resultado[1], erro=not resultado[0])

        self._executar(self.central.testar_chave, concluir)

    def _remover_chave(self) -> None:
        self.central.remover_chave()
        self._atualizar_config()
        self.definir_status("Chave de IA removida.")

    def _importar_cookies(self) -> None:
        caminho = filedialog.askopenfilename(
            title="cookies.txt", filetypes=(("Texto", "*.txt"), ("Todos", "*.*")))
        if not caminho:
            return
        try:
            info = self.central.importar_cookies(caminho)
        except Exception as erro:
            self.notificar("Cookies", str(erro), erro=True)
            return
        self._atualizar_config()
        self.notificar("Cookies", getattr(info, "mensagem", "cookies.txt importado."))

    def _remover_cookies(self) -> None:
        self.central.remover_cookies()
        self._atualizar_config()
        self.definir_status("Cookies removidos.")

    def _atualizar_ytdlp(self) -> None:
        self.definir_status("Atualizando o yt-dlp (pode levar um minuto)...")

        def concluir(resultado: Any) -> None:
            self._atualizar_config()
            self.notificar("yt-dlp", getattr(resultado, "mensagem", "Pronto."),
                           erro=not getattr(resultado, "ok", False))

        self._executar(self.central.atualizar_ytdlp, concluir)

    def _limpar_temporarios(self) -> None:
        import shutil

        removidos = 0
        for pasta in (self.central.config.dados / "previa",
                      self.central.config.dados / ".cache-capas"):
            if pasta.is_dir():
                shutil.rmtree(pasta, ignore_errors=True)
                removidos += 1
        for pasta in self.central.config.dados.glob("baixador-*"):
            if pasta.is_dir():
                shutil.rmtree(pasta, ignore_errors=True)
                removidos += 1
        self.notificar("Temporários", f"{removidos} pasta(s) temporária(s) limpa(s).")

    def _testar_dependencias(self) -> None:
        try:
            resultado = self.central.config.verificar_dependencias()
            texto = "\n".join(f"{nome}: {caminho}" for nome, caminho in resultado.items())
        except Exception as erro:
            texto = f"Faltando: {erro}"
        self.notificar("Dependências", texto, erro="Faltando" in texto)

    # -- player (rodapé, sempre visível) -----------------------------------
    def _montar_player(self) -> None:
        cores = self.cores
        quadro = ttk.Frame(self.rodape, style="Cartao.TFrame")
        quadro.pack(fill="x", pady=(4, 0))
        self.capa_player = tk.Label(quadro, text="♪", width=6, height=3,
                                    background=cores["cartao"], foreground=cores["texto_fraco"])
        self.capa_player.pack(side="left", padx=8, pady=6)
        info = ttk.Frame(quadro, style="Cartao.TFrame")
        info.pack(side="left", fill="x", expand=True)
        self.player_titulo = tk.StringVar(value="Nada tocando")
        self.player_sub = tk.StringVar(value="Escolha uma música na Biblioteca")
        ttk.Label(info, textvariable=self.player_titulo,
                  style="CartaoTitulo.TLabel").pack(anchor="w", pady=(6, 0))
        ttk.Label(info, textvariable=self.player_sub,
                  style="Cartao.TLabel").pack(anchor="w")
        self.player_progresso = ttk.Progressbar(info, mode="determinate", maximum=100)
        self.player_progresso.pack(fill="x", pady=(4, 2), padx=(0, 8))
        # Clicar na barra pula para o ponto (seek) — o ffplay recomeça com -ss.
        self.player_progresso.bind("<Button-1>", self._player_clicou_barra)
        self.player_tempo = tk.StringVar(value="0:00 / 0:00")
        ttk.Label(info, textvariable=self.player_tempo,
                  style="Cartao.TLabel").pack(anchor="w", pady=(0, 4))

        controles = ttk.Frame(quadro, style="Cartao.TFrame")
        controles.pack(side="left", padx=6)
        for texto, acao in (("⏮", self._player_anterior), ("▶", self._player_tocar),
                            ("⏸", self._player_pausar), ("⏭", self._player_proxima)):
            ttk.Button(controles, text=texto, width=3,
                       command=acao).pack(side="left", padx=1)
        self.player_modo = tk.StringVar(value="Repetir: desligado")
        ttk.Button(controles, text="🔀", width=3,
                   command=self._player_aleatorio).pack(side="left", padx=1)
        botao_rep = ttk.Button(controles, text="🔁", width=3,
                               command=self._player_repeticao)
        botao_rep.pack(side="left", padx=1)
        ttk.Label(quadro, textvariable=self.player_modo,
                  style="Cartao.TLabel").pack(side="left", padx=6)
        ttk.Label(quadro, text="Volume", style="Cartao.TLabel").pack(side="left")
        self.volume_var = tk.IntVar(value=self.central.reprodutor.volume)
        escala = ttk.Scale(quadro, from_=0, to=100, orient="horizontal",
                          variable=self.volume_var, length=110,
                          command=lambda _v: self._player_volume())
        escala.pack(side="left", padx=(4, 10))

    def _player_tocar(self) -> None:
        if not self.central.reprodutor.tocar():
            motivo = ("O arquivo não existe mais."
                      if self.central.reprodutor.fila else
                      "Escolha uma música na Biblioteca (duplo clique).")
            if not self.central.ffplay:
                motivo = ("O player precisa do ffplay (vem com o FFmpeg). Rode "
                          "configurar.bat ou toque a música no player do Windows.")
            self.notificar("Reprodutor", motivo, erro=True)
            return
        self.definir_status("Tocando...")
        self._atualizar_player()

    def _player_pausar(self) -> None:
        if self.central.reprodutor.pausado:
            self.central.reprodutor.tocar()
            self.definir_status("Continuando...")
        else:
            self.central.reprodutor.pausar()
            self.definir_status("Pausado.")
        self._atualizar_player()

    def _player_proxima(self) -> None:
        if not self.central.reprodutor.proxima():
            self.definir_status("Fim da fila.")
        self._atualizar_player()

    def _player_anterior(self) -> None:
        self.central.reprodutor.anterior()
        self._atualizar_player()

    def _player_aleatorio(self) -> None:
        ativo = self.central.reprodutor.alternar_aleatorio()
        self.definir_status(f"Aleatório {'ligado' if ativo else 'desligado'}.")

    def _player_repeticao(self) -> None:
        modo = self.central.reprodutor.ciclo_repeticao()
        self.player_modo.set(self.central.reprodutor.descricao_repeticao())
        self.definir_status(f"Modo de repetição: {modo}.")

    def _em_campo_de_texto(self) -> bool:
        """Não sequestrar a barra de espaço enquanto o usuário digita."""
        try:
            foco = self.raiz.focus_get()
        except Exception:
            return False
        classe = foco.__class__.__name__.lower() if foco is not None else ""
        return any(nome in classe for nome in ("entry", "text", "spinbox",
                                               "combobox"))

    def _atalho_espaco(self) -> None:
        if self._em_campo_de_texto():
            return
        self._player_pausar()

    def _player_pular(self, segundos: float) -> None:
        if self.central.reprodutor.avancar(segundos):
            self._atualizar_player()
            self.definir_status(
                f"Pulando {int(segundos):+d}s: {self.player_tempo.get()}")
        else:
            self.definir_status("Nada tocando para avançar.")

    def _player_volume_passo(self, passo: int) -> None:
        atual = int(self.central.reprodutor.volume) + passo
        self.volume_var.set(max(0, min(100, atual)))
        self._player_volume()

    def _player_clicou_barra(self, evento: Any) -> None:
        """Converte o clique em segundos e pede o seek ao reprodutor."""
        faixa = self.central.reprodutor.atual
        if faixa is None:
            self.definir_status("Escolha uma música para poder avançar.")
            return
        total = float(faixa.duracao or 0)
        if not total:
            self.definir_status(
                "Duração desconhecida nesta faixa: não dá para pular com precisão.")
            return
        try:
            largura = max(1, int(self.player_progresso.winfo_width()))
            fracao = max(0.0, min(1.0, float(evento.x) / largura))
        except Exception:
            return
        if self.central.reprodutor.buscar(fracao * total):
            self._atualizar_player()
            self.definir_status(f"Indo para {self.player_tempo.get()}.")

    def _player_volume(self) -> None:
        try:
            self.central.reprodutor.mudar_volume(int(self.volume_var.get()))
            self.central.reprodutor.salvar_estado()
        except Exception:
            pass

    def _atualizar_player(self) -> None:
        estado = self.central.estado_reprodutor()
        self.player_titulo.set(estado.get("faixa") or "Nada tocando")
        subtitulo = estado.get("subtitulo") or ""
        if estado.get("pausado"):
            subtitulo = (subtitulo + " · pausado").strip(" ·")
        self.player_sub.set(subtitulo or "Escolha uma música na Biblioteca")
        faixa = self.central.reprodutor.atual
        total = float(faixa.duracao or 0) if faixa else 0.0
        posicao = float(estado.get("posicao") or 0)
        if total:
            minutos, segundos = divmod(int(min(posicao, total)), 60)
            total_min, total_seg = divmod(int(total), 60)
            self.player_tempo.set(f"{minutos}:{segundos:02d} / "
                                  f"{total_min}:{total_seg:02d}")
        else:
            self.player_tempo.set("duração desconhecida")
        caminho = estado.get("caminho")
        if caminho and estado.get("capa"):
            imagem = _miniatura(capa_da_musica(caminho), (56, 56))
            if imagem is not None:
                self.capa_player.image = imagem  # type: ignore[attr-defined]
                self.capa_player.configure(image=imagem, text="")
                return
        self.capa_player.image = None  # type: ignore[attr-defined]
        self.capa_player.configure(image="", text="♪")

    def _verificar_fim_da_musica(self) -> None:
        """Avança sozinho quando a faixa termina (sem travar a interface)."""
        try:
            rodando = self.central.reprodutor
            if rodando.tocando and not rodando.esta_rodando():
                rodando.proxima(automatico=True)
                self._atualizar_player()
            elif rodando.tocando:
                faixa = rodando.atual
                total = (faixa.duracao if faixa and faixa.duracao else 0) or 0
                if total:
                    self.player_progresso.configure(
                        value=min(100, rodando.posicao / total * 100))
        except Exception:
            pass
        finally:
            self.raiz.after(1000, self._verificar_fim_da_musica)

    def _ligar_atalhos(self) -> None:
        """Atalhos globais do player (não roubam digitação em campos de texto)."""
        for tecla, acao in (("<space>", self._atalho_espaco),
                            ("<Control-Right>", lambda: self._player_pular(10)),
                            ("<Control-Left>", lambda: self._player_pular(-10)),
                            ("<Control-Up>", lambda: self._player_volume_passo(5)),
                            ("<Control-Down>", lambda: self._player_volume_passo(-5)),
                            ("<Control-n>", self._player_proxima),
                            ("<Control-p>", self._player_anterior),
                            ("<Control-l>", self._player_aleatorio),
                            ("<Control-r>", self._player_repeticao)):
            self.raiz.bind(tecla, lambda _e, acao=acao: acao())


__all__ = ["CentralApp", "PAGINAS", "capa_da_musica"]


def iniciar(configuracoes: Any = None) -> None:
    """Abre a Central Musical (ponto de entrada: ``python central_app.py``)."""
    if tk is None:
        raise SystemExit("Tkinter não está disponível neste Python.")
    from logging.handlers import RotatingFileHandler

    from baixador.app.central import Central as _Central

    central = _Central(configuracoes)
    try:
        pasta = central.config.dados
        pasta.mkdir(parents=True, exist_ok=True)
        manipulador = RotatingFileHandler(
            pasta / "central.log", maxBytes=1_000_000, backupCount=2,
            encoding="utf-8")
        manipulador.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s: %(message)s"))
        logging.getLogger("baixador").addHandler(manipulador)
        logging.getLogger("baixador").setLevel(logging.INFO)
        log.info("Central Musical aberta em %s", datetime.now().isoformat())
    except Exception:
        pass
    app = CentralApp(central)
    try:
        app.raiz.mainloop()
    finally:
        # Uma única saída: grava a fila pendente e para o áudio.
        app.central.fechar()


if __name__ == "__main__":
    iniciar()
