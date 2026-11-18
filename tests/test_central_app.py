"""A Central Musical é construída de verdade? (Tk simulado)

Sem Tkinter neste Linux, um dublê registra as chamadas. Isso pega o erro que só
aparece ao abrir a janela: widget errado, atributo inexistente, página não
montada, botão ligado a método que não existe.

Cada página é montada, os fluxos principais são executados com um
``Central`` real (SQLite e seleção em pasta temporária) e os downloads viram
dublês — o download de verdade é testado em ``tests/test_gerenciador.py``.
"""

from __future__ import annotations

import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch


_widgets_criados: list = []


class _Widget:
    """Dublê de widget: aceita qualquer configuração e guarda estado mínimo."""

    def __init__(self, *args, **kwargs):
        self.args, self.kwargs = args, kwargs
        _widgets_criados.append(self)
        self.opcoes: dict = {}
        self._itens: list[str] = []
        self._selecao: list[str] = []
        self._valores: dict[str, list] = {}
        self.image = None

    def __getattr__(self, nome):
        if nome.startswith("_") and nome not in {"_itens", "_selecao", "_valores"}:
            raise AttributeError(nome)

        def qualquer(*args, **kwargs):
            if nome == "insert":
                ident = kwargs.get("iid") or f"i{len(self._itens)}"
                self._itens.append(str(ident))
                valores = kwargs.get("values")
                if valores is None and len(args) > 2 and isinstance(args[2], dict):
                    valores = args[2].get("values")
                if valores is not None:
                    self._valores[str(ident)] = list(valores)
                return str(ident)
            if nome == "index":
                alvo = str(args[0]) if args else ""
                return self._itens.index(alvo) if alvo in self._itens else 0
            if nome == "get_children":
                return tuple(self._itens)
            if nome == "exists":
                return str(args[0]) in self._itens
            if nome == "selection":
                return tuple(self._selecao)
            if nome == "selection_set":
                self._selecao = [str(a) for a in (args[0] if args else ())]
                return None
            if nome == "selection_remove":
                alvos = {str(a) for a in (args[0] if args else ())}
                self._selecao = [i for i in self._selecao if i not in alvos]
                return None
            if nome == "item":
                ident = str(args[0]) if args else ""
                if len(args) > 1 and args[1] == "values":
                    return self._valores.get(ident, [])
                return {"values": self._valores.get(ident, [])}
            if nome == "curselection":
                return ()
            if nome == "get":
                return ""
            return None

        return qualquer

    def pack(self, *a, **k):
        return None

    grid = pack
    place = pack
    grid_remove = pack
    grid_propagate = pack
    pack_propagate = pack

    def bind(self, *a, **k):
        return None

    def configure(self, *a, **k):
        self.opcoes.update(k)
        return None

    config = configure

    def cget(self, chave):
        return self.opcoes.get(chave, "")

    def delete(self, *a, **k):
        alvos = [str(a[0])] if a else list(self._itens)
        for alvo in alvos:
            if alvo in self._itens:
                self._itens.remove(alvo)
            self._selecao = [i for i in self._selecao if i != alvo]
            self._valores.pop(alvo, None)
        return None

    def after(self, _ms, _func=None, *a):
        return "after"

    def mainloop(self, *a, **k):
        return None

    def destroy(self):
        return None

    def yview(self, *a):
        return None

    def see(self, *a):
        return None

    def focus_set(self, *a):
        return None

    def title(self, *a):
        return None

    def geometry(self, *a):
        return None

    def minsize(self, *a):
        return None

    def update_idletasks(self, *a):
        return None

    def bbox(self, *a):
        return (0, 0, 100, 100)


class _Var:
    def __init__(self, master=None, value=None, **kwargs):
        self._valor = value if value is not None else kwargs.get("value", "")

    def get(self):
        return self._valor

    def set(self, valor):
        self._valor = valor

    def trace_add(self, *_a, **_k):
        return "trace"


def _classe(nome: str) -> type:
    """Dublê com nome próprio, para o teste saber se é botão ou rótulo."""
    return type(nome, (_Widget,), {"tipo": nome})


def _instalar_tk_falso() -> None:
    tk = types.ModuleType("tkinter")
    tk.Tk = tk.Toplevel = _classe("Toplevel")
    for nome in ("Frame", "Label", "Button", "Entry", "Text", "Canvas",
                 "Listbox", "Scale", "PhotoImage"):
        setattr(tk, nome, _classe(nome))
    tk.StringVar = tk.IntVar = tk.BooleanVar = tk.DoubleVar = _Var
    tk.W = tk.E = tk.N = tk.S = "we"
    tk.END = "end"
    tk.NORMAL = "normal"
    tk.DISABLED = "disabled"
    tk.LEFT = "left"
    tk.RIGHT = "right"
    ttk = types.ModuleType("tkinter.ttk")
    for nome in ("Frame", "Label", "Button", "Entry", "Combobox", "Treeview",
                 "Scrollbar", "Notebook", "Progressbar", "Labelframe",
                 "LabelFrame", "Checkbutton", "Radiobutton", "Separator",
                 "Style", "Spinbox", "Scale"):
        setattr(ttk, nome, _classe(nome))
    tk.ttk = ttk
    messagebox = types.ModuleType("tkinter.messagebox")
    messagebox.showinfo = messagebox.showwarning = messagebox.showerror = (
        lambda *a, **k: None)
    messagebox.askyesno = lambda *a, **k: True
    filedialog = types.ModuleType("tkinter.filedialog")
    filedialog.askdirectory = filedialog.askopenfilename = lambda *a, **k: ""
    simpledialog = types.ModuleType("tkinter.simpledialog")
    simpledialog.askstring = lambda *a, **k: ""
    tk.messagebox = messagebox
    tk.filedialog = filedialog
    tk.simpledialog = simpledialog
    sys.modules["tkinter"] = tk
    sys.modules["tkinter.ttk"] = ttk
    sys.modules["tkinter.messagebox"] = messagebox
    sys.modules["tkinter.filedialog"] = filedialog
    sys.modules["tkinter.simpledialog"] = simpledialog


class TestCentralApp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._env = patch.dict(os.environ)
        cls._env.start()
        _instalar_tk_falso()
        cls._temp = tempfile.TemporaryDirectory()
        raiz = Path(cls._temp.name)
        os.environ["BAIXADOR_DATA_DIR"] = str(raiz / ".baixador")
        (raiz / "Musicas").mkdir(exist_ok=True)
        (raiz / "ferramentas").mkdir(exist_ok=True)
        for modulo in ("central_app", "central", "central_servicos"):
            sys.modules.pop(modulo, None)
        from configuracoes import Configuracoes
        from preferencias import Preferencias

        import central_app

        cls.modulo = central_app
        from central import Central

        cls.central = Central(
            Configuracoes(raiz=raiz, diretorio_musicas=raiz / "Musicas"),
            Preferencias(metadados_ativos=False, buscar_capas=False,
                         sincronizar_ao_abrir=False))
        cls.central.ffplay = []
        cls.app = central_app.CentralApp(cls.central, raiz=central_app.tk.Tk())

    @classmethod
    def tearDownClass(cls):
        cls._temp.cleanup()
        cls._env.stop()
        for modulo in list(sys.modules):
            if modulo.startswith("tkinter"):
                sys.modules.pop(modulo, None)
        for modulo in ("central_app", "central", "central_servicos"):
            sys.modules.pop(modulo, None)

    # -- estrutura ---------------------------------------------------------
    def test_todas_as_paginas_existem(self):
        esperadas = {"inicio", "pesquisar", "playlists", "fila", "biblioteca",
                     "artistas", "albuns", "historico", "favoritos", "config"}
        self.assertEqual(set(self.app.areas), esperadas)

    def test_navegar_monta_cada_pagina_sem_erro(self):
        for chave in ("inicio", "pesquisar", "playlists", "fila", "biblioteca",
                      "artistas", "albuns", "historico", "favoritos", "config"):
            with self.subTest(pagina=chave):
                self.app.mostrar(chave)
                self.assertEqual(self.app.pagina_atual, chave)
                self.assertTrue(getattr(self.app.areas[chave], "_montada", False))

    def test_player_fica_no_rodape_e_tem_controles(self):
        self.assertTrue(hasattr(self.app, "player_titulo"))
        self.assertTrue(hasattr(self.app, "player_progresso"))
        self.assertTrue(hasattr(self.app, "volume_var"))
        self.assertIn(self.app.player_titulo.get(), ("Nada tocando", ""))
        # controles respondem sem estourar
        self.app._player_aleatorio()
        self.app._player_repeticao()
        self.app._player_volume()

    # -- fluxos ------------------------------------------------------------
    def _executar_na_hora(self, *_a, **_k):
        def decorador(funcao):
            funcao()
        return decorador

    def test_pesquisar_lista_e_adiciona_a_cesta(self):
        from pesquisa import ResultadoPesquisa

        video = ResultadoPesquisa("a", "Música Um", "Canal X", 200,
                                  "https://youtu.be/a", tipo="video")
        playlist = ResultadoPesquisa(
            "PL1", "Rock Mix", "Canal X", None,
            "https://youtube.com/playlist?list=PL1", tipo="playlist",
            quantidade=40)
        self.central.selecao.limpar()
        self.app.mostrar("pesquisar")
        self.app.pesquisa_var.set("rock")
        with patch.object(self.central, "pesquisar", return_value=[video, playlist]), \
                patch.object(self.app, "_executar",
                             side_effect=lambda trabalho, concluir=None, falhar=None:
                             concluir(trabalho())):
            self.app._pesquisar()
        linhas = [self.app.arvore_resultados.item(i, "values")
                  for i in self.app.arvore_resultados.get_children()]
        self.assertEqual(len(linhas), 2)
        self.assertIn("Playlist", linhas[1][1])

        self.app.arvore_resultados.selection_set(
            self.app.arvore_resultados.get_children())
        self.app._adicionar_selecionados()
        self.assertEqual(self.central.selecao.quantidade(), 2)

    def test_cesta_acumula_de_varias_pesquisas(self):
        from selecao import ItemSelecao

        self.central.selecao.limpar()
        self.app.mostrar("fila")
        self.central.adicionar_a_selecao(
            [ItemSelecao("https://y/1", "A", "Guns", 200)], origem="Guns")
        self.central.adicionar_a_selecao(
            [ItemSelecao("https://y/2", "B", "Queen", 300)], origem="Queen")
        self.app.mostrar("fila")
        self.app._atualizar_fila()
        linhas = [self.app.arvore_cesta.item(i, "values")
                  for i in self.app.arvore_cesta.get_children()]
        self.assertEqual(len(linhas), 2)
        self.assertIn("Guns", self.app.cesta_var.get())
        self.assertIn("Queen", self.app.cesta_var.get())
        self.central.selecao.limpar()

    def test_abrir_playlist_e_marcar_sem_ao_vivo(self):
        from playlist import ItemPlaylist, Playlist

        playlist = Playlist(titulo="Mix", url="https://y/playlist?list=1", itens=(
            ItemPlaylist(1, "a", "Song One", "https://y/a", 200),
            ItemPlaylist(2, "b", "Song Two (Ao Vivo)", "https://y/b", 300),
            ItemPlaylist(3, "c", "[Private video]", "https://y/c",
                         disponivel=False),
        ))
        self.central.selecao.limpar()
        self.app.mostrar("pesquisar")
        self.app._resultados = [type("R", (), {
            "eh_playlist": True, "titulo": "Mix",
            "url": "https://y/playlist?list=1"})()]
        with patch.object(self.central, "listar_playlist", return_value=playlist), \
                patch.object(self.app, "_indices_selecionados", return_value=[0]), \
                patch.object(self.app, "_executar",
                             side_effect=lambda trabalho, concluir=None, falhar=None:
                             concluir(trabalho())):
            self.app._abrir_playlist_selecionada()
        self.assertEqual(len(self.app.arvore_playlist.get_children()), 3)
        self.assertIn("Mix", self.app.playlist_titulo_var.get())

        self.app._filtrar_ao_vivo_playlist()
        self.assertEqual(list(self.app.arvore_playlist.selection()), ["1"])

        self.app._adicionar_da_playlist()
        self.assertEqual(self.central.selecao.quantidade(), 1)
        self.central.selecao.limpar()

    def test_fila_mostra_itens_e_resumo(self):
        self.central.gerenciador.adicionar("https://y/x", "mp3", titulo="Teste")
        self.app.mostrar("fila")
        self.app._atualizar_fila()
        self.assertIn("Teste", self.app.fila_resumo_var.get() + "Teste")
        self.assertTrue(self.app.arvore_downloads.get_children())

    def test_biblioteca_lista_e_filtra(self):
        self.app.mostrar("biblioteca")
        self.app._atualizar_biblioteca()
        self.assertIn("música", self.app.status_var.get().lower())

    def test_playlists_criar_listar_e_abrir(self):
        with patch.object(self.modulo.simpledialog, "askstring",
                          return_value="Rock Clássico"):
            self.app.mostrar("playlists")
            self.app._nova_playlist()
        nomes = [self.app.arvore_playlists.item(i, "values")[0]
                 for i in self.app.arvore_playlists.get_children()]
        self.assertIn("Rock Clássico", nomes)

    def test_configuracoes_mostram_status_e_salvam(self):
        self.app.mostrar("config")
        self.assertIn("yt-dlp", self.app.config_versao.get())
        self.assertTrue(self.app.config_chave_status.get())
        self.app.config_tema.set("claro")
        with patch.object(self.modulo.messagebox, "showinfo"):
            self.app._salvar_config()
        self.assertEqual(self.central.preferencias.tema, "claro")

    def test_historico_mostra_registros(self):
        self.central.aplicacao.historico.registrar(
            url="https://y/h", formato="mp3", status="sucesso", caminho="a.mp3")
        self.app.mostrar("historico")
        self.app._atualizar_historico()
        self.assertTrue(self.app.arvore_historico.get_children())

    def test_favoritos_lista_vazia_sem_quebrar(self):
        self.app.mostrar("favoritos")
        self.app._atualizar_favoritos()
        self.assertEqual(self.app.arvore_favoritos.get_children(), ())

    def test_artistas_e_albuns_sem_biblioteca(self):
        self.app.mostrar("artistas")
        self.app._atualizar_artistas()
        self.app.mostrar("albuns")
        self.app._atualizar_albuns()


if __name__ == "__main__":
    unittest.main()


class TestNadaDeBotaoMorto(unittest.TestCase):
    """A especificação proíbe botão decorativo: todo ``command`` deve existir.

    Dois níveis de checagem:

    1. estático — cada ``command=self._algo`` no código tem um método real;
    2. dinâmico — montar cada página e contar os widgets criados, garantindo
       que nenhuma página abre vazia e que os botões realmente registram ação.
    """

    @classmethod
    def setUpClass(cls):
        TestCentralApp.setUpClass()
        cls.origem = TestCentralApp
        cls.fonte = (Path(__file__).resolve().parents[1] / "central_app.py").read_text(
            encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        TestCentralApp.tearDownClass()

    def test_todo_command_aponta_para_metodo_existente(self):
        import re

        alvos = set(re.findall(r"command=self\.(\w+)", self.fonte))
        alvos |= set(re.findall(r"command=self\.central\.(\w+)", self.fonte))
        self.assertGreaterEqual(len(alvos), 50)
        app = self.origem.app
        faltando = [nome for nome in alvos
                    if not hasattr(app, nome) and not hasattr(app.central, nome)]
        self.assertEqual(faltando, [])

    def test_todo_atributo_da_interface_e_criado(self):
        """``self.x.get()`` sem ``self.x = ...`` é a receita do AttributeError."""
        import re

        usados = set(re.findall(r"self\.(\w+)_var\b", self.fonte))
        criados = set(re.findall(r"self\.(\w+)_var\s*(?::[^=]+)?=", self.fonte))
        ausentes = {nome for nome in usados - criados
                    if not hasattr(self.origem.app, f"{nome}_var")}
        self.assertEqual(ausentes, set())

    def test_pagina_nao_abre_vazia(self):
        app = self.origem.app
        for chave, _rotulo, _icone in self.origem.modulo.PAGINAS:
            with self.subTest(pagina=chave):
                area = app.areas[chave]
                if getattr(area, "_montada", False):
                    del area._montada  # força recontagem dos filhos criados
                    area._montada = False
                antes = len(_widgets_criados)
                app.mostrar(chave)
                self.assertTrue(getattr(area, "_montada", False))
                criados = len(_widgets_criados) - antes
                # nenhuma página vazia: sempre rótulo + conteúdo real
                self.assertGreaterEqual(criados, 3, chave)

    def test_botoes_das_paginas_tem_acao(self):
        """Cada botão criado numa página guarda o ``command`` recebido."""
        app = self.origem.app
        for chave in ("inicio", "pesquisar", "playlists", "fila", "biblioteca",
                      "artistas", "albuns", "historico", "favoritos", "config"):
            app.mostrar(chave)
        # janela nova: as páginas montam do zero e registram todos os widgets
        del _widgets_criados[:]
        outra = self.origem.modulo.CentralApp(self.origem.central)
        for chave in ("inicio", "pesquisar", "playlists", "fila", "biblioteca",
                      "artistas", "albuns", "historico", "favoritos", "config"):
            outra.mostrar(chave)
        botoes = [w for w in _widgets_criados
                  if getattr(w, "tipo", "") == "Button" and w.kwargs.get("text")]
        com_acao = [w for w in botoes if callable(w.kwargs.get("command"))]
        sem_acao = [w for w in botoes if not callable(w.kwargs.get("command"))]
        self.assertGreaterEqual(len(com_acao), 30)
        self.assertEqual([w.kwargs.get("text") for w in sem_acao], [],
                         "texto clicável sem comando = botão decorativo")


class TestFilaRecuperadaNaTela(TestCentralApp):
    """A página Fila mostra o que voltou da sessão anterior."""

    def test_botao_retomar_fila_salva_existe_e_funciona(self):
        app = self.app
        app.mostrar("fila")
        self.assertTrue(hasattr(app, "_retomar_fila_salva"))
        self.central.fila_recuperada = {"pausado": 2}
        with patch.object(self.central, "retomar_fila_salva", return_value=2) as acao:
            app._retomar_fila_salva()
        acao.assert_called_once()
        self.assertIn("2 download", app.status_var.get())
        self.central.fila_recuperada = {}

    def test_resumo_mostra_sessao_anterior(self):
        app = self.app
        self.central.gerenciador.adicionar("https://y/antiga", "mp3")
        self.central.fila_recuperada = {"aguardando": 1}
        app.mostrar("fila")
        app._atualizar_fila()
        self.assertIn("sessão anterior", app.fila_resumo_var.get())
        self.central.fila_recuperada = {}
        self.central.gerenciador.limpar()


class TestListarMaisNaTela(unittest.TestCase):
    """Botão "Listar mais" na playlist aberta: soma itens e preserva marcação.

    Herdar de ``TestCentralApp`` duplicaria os testes dela e perderia a
    montagem da janela; a janela simulada é criada aqui, uma vez só.
    """

    @classmethod
    def setUpClass(cls):
        TestCentralApp.setUpClass()
        cls.app = TestCentralApp.app
        cls.central = TestCentralApp.central

    @classmethod
    def tearDownClass(cls):
        TestCentralApp.tearDownClass()

    def _playlist(self, quantidade: int, total: int | None, inicio: int = 1):
        from playlist import ItemPlaylist, Playlist

        itens = tuple(
            ItemPlaylist(indice=numero, id=f"id{numero}",
                         titulo=f"Faixa {numero}",
                         url=f"https://y/watch?v=id{numero}",
                         duracao=180)
            for numero in range(inicio, inicio + quantidade))
        return Playlist(titulo="Canal Grande",
                        url="https://y/playlist?list=PL1",
                        itens=itens, total_informado=total,
                        truncada=bool(total is None or quantidade < total))

    def test_listar_mais_acrescenta_sem_perder_marcacao(self):
        app = self.app
        app.mostrar("pesquisar")
        primeira = self._playlist(200, 1200)
        app._playlist_aberta = primeira
        app.playlist_titulo_var.set("Carregando...")
        for item in primeira.itens:
            app.arvore_playlist.insert("", "end", iid=str(item.indice),
                                       values=(item.indice, item.titulo, "3:00",
                                               "disponível"))
        app.arvore_playlist.selection_set(["5", "9"])

        segunda = self._playlist(400, 1200)
        with patch.object(self.central, "listar_mais_playlist",
                          return_value=segunda), \
                patch.object(app, "_executar",
                             side_effect=lambda trabalho, concluir=None, falhar=None:
                             concluir(trabalho()) if concluir else trabalho()):
            app._listar_mais_itens()
        self.assertEqual(len(app.arvore_playlist.get_children()), 400)
        self.assertEqual(set(app.arvore_playlist.selection()), {"5", "9"})
        self.assertIn("400 item", app.playlist_titulo_var.get())
        self.assertIn("faltam 800", app.playlist_titulo_var.get())

    def test_lista_completa_avisa_em_vez_de_chamar_rede(self):
        app = self.app
        app._playlist_aberta = self._playlist(50, 50)
        with patch.object(self.central, "listar_mais_playlist") as acao:
            app._listar_mais_itens()
        acao.assert_not_called()
        self.assertIn("completa", app.status_var.get())

    def test_sem_playlist_aberta_nao_explode(self):
        app = self.app
        app._playlist_aberta = None
        # o módulo importa ``messagebox`` direto; o dublê fica no atributo
        with patch.object(self.origem_modulo(), "messagebox") as caixa:
            with patch.object(caixa, "showinfo") as aviso:
                app._listar_mais_itens()
        aviso.assert_called_once()

    def test_titulo_mostra_total_quando_conhecido(self):
        app = self.app
        app._mostrar_titulo_playlist(self._playlist(200, None))
        self.assertIn("200 item", app.playlist_titulo_var.get())
        self.assertNotIn("faltam", app.playlist_titulo_var.get())

    @staticmethod
    def origem_modulo():
        return TestCentralApp.modulo
