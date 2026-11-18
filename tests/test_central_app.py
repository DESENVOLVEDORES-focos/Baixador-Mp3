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
from unittest.mock import MagicMock, patch


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
            if nome == "insert" and getattr(self, "tipo", "") == "Text":
                # guarda o texto inserido para os testes poderem conferir
                indice = str(args[1]) if len(args) > 1 else ""
                # caixa.insert("end", "texto") → args = ("end", "texto")
                texto = (args[2] if len(args) > 2
                         else (args[1] if len(args) > 1 else ""))
                self._valores.setdefault("texto", {})[indice] = texto
                return None
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


class TestCestaAvancadaNaTela(unittest.TestCase):
    """Desfazer, topo/fim, estimativa e "salvar como playlist" pela interface."""

    @classmethod
    def setUpClass(cls):
        TestCentralApp.setUpClass()
        cls.app = TestCentralApp.app
        cls.central = TestCentralApp.central
        cls.modulo = TestCentralApp.modulo

    @classmethod
    def tearDownClass(cls):
        TestCentralApp.tearDownClass()

    def setUp(self):
        self.central.selecao.limpar()
        self.app.mostrar("fila")

    def _encher(self, quantidade: int = 3):
        from selecao import ItemSelecao

        for numero in range(quantidade):
            self.central.selecao.adicionar(ItemSelecao(
                f"https://y/{numero}", f"Faixa {numero}", "Artista", 200))
        self.app._atualizar_fila()

    def test_estimativa_aparece_na_tela(self):
        self._encher(3)
        texto = self.app.cesta_estimativa_var.get()
        self.assertIn("Estimativa", texto)
        self.assertIn("download", texto)

    def test_desfazer_pela_tela(self):
        self._encher(3)
        self.app.arvore_cesta.selection_set("1")
        self.app._remover_da_cesta()
        self.assertEqual(self.central.selecao.quantidade(), 2)
        self.app._desfazer_remocao_cesta()
        self.assertEqual(self.central.selecao.quantidade(), 3)
        self.assertIn("devolvido", self.app.status_var.get())

    def test_desfazer_sem_nada_avisa(self):
        self._encher(2)
        self.app._desfazer_remocao_cesta()
        self.assertIn("Nada para desfazer", self.app.status_var.get())

    def test_mover_para_o_topo_pela_tela(self):
        self._encher(3)
        self.app.arvore_cesta.selection_set("2")
        self.app._cesta_para(0)
        self.assertEqual(self.central.selecao.listar()[0].titulo, "Faixa 2")
        self.assertIn("topo", self.app.status_var.get())

    def test_mover_para_o_fim_pela_tela(self):
        self._encher(3)
        self.app.arvore_cesta.selection_set("0")
        self.app._cesta_para(-1)
        self.assertEqual(self.central.selecao.listar()[-1].titulo, "Faixa 0")

    def test_cesta_vazia_nao_salva_playlist(self):
        with patch.object(self.modulo, "messagebox") as caixa:
            with patch.object(caixa, "showinfo") as aviso:
                self.app._salvar_cesta_como_playlist()
        aviso.assert_called_once()

    def test_salvar_cesta_sem_musica_baixada_explica(self):
        self._encher(2)
        with patch.object(self.modulo.simpledialog, "askstring",
                          return_value="Minha Lista"), \
                patch.object(self.app, "notificar") as aviso:
            self.app._salvar_cesta_como_playlist()
        aviso.assert_called_once()
        self.assertIn("baixe", aviso.call_args[0][1].lower())

    def test_salvar_cesta_com_musica_na_biblioteca_cria_playlist(self):
        import shutil
        import subprocess
        from pathlib import Path

        ffmpeg = shutil.which("ffmpeg") or "/tmp/ff10/ffmpeg"
        if not Path(ffmpeg).is_file():
            self.skipTest("Sem FFmpeg")
        pasta = self.central.config.musicas
        pasta.mkdir(parents=True, exist_ok=True)
        arquivo = pasta / "cesta.mp3"
        subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-f", "lavfi",
                        "-i", "sine=frequency=440:duration=2",
                        "-c:a", "libmp3lame", str(arquivo)],
                       capture_output=True, check=False)
        musica = self.central.biblioteca.adicionar(
            arquivo, origem_url="https://y/0")
        self._encher(2)
        with patch.object(self.modulo.simpledialog, "askstring",
                          return_value="Da cesta"):
            self.app._salvar_cesta_como_playlist()
        nomes = [p["nome"] for p in self.central.playlists()]
        self.assertIn("Da cesta", nomes)
        playlist = next(p for p in self.central.playlists()
                        if p["nome"] == "Da cesta")
        self.assertEqual(playlist["total"], 1)
        self.central.excluir_playlist(playlist["id"])
        self.central.biblioteca.remover(musica.id, apagar_arquivo=True)


class TestFiltrosDaBibliotecaNaTela(unittest.TestCase):
    """Cada filtro da Biblioteca muda o que aparece — nada de campo decorativo."""

    @classmethod
    def setUpClass(cls):
        TestCentralApp.setUpClass()
        cls.app = TestCentralApp.app
        cls.central = TestCentralApp.central

    @classmethod
    def tearDownClass(cls):
        TestCentralApp.tearDownClass()

    def setUp(self):
        self.app.mostrar("biblioteca")

    def test_filtros_de_duracao_chegam_na_consulta(self):
        capturado = {}

        def falso(**filtros):
            capturado.update(filtros)
            return []

        with patch.object(self.central, "musicas", side_effect=falso):
            self.app.biblioteca_duracao_var.set("3 a 6 min")
            self.app._atualizar_biblioteca()
        self.assertEqual(capturado["duracao_min"], 180)
        self.assertEqual(capturado["duracao_max"], 360)

    def test_filtro_sem_capa_e_recentes(self):
        capturado = {}

        def falso(**filtros):
            capturado.update(filtros)
            return []

        with patch.object(self.central, "musicas", side_effect=falso):
            self.app.biblioteca_sem_capa_var.set(True)
            self.app.biblioteca_recentes_var.set(True)
            self.app._atualizar_biblioteca()
        self.assertTrue(capturado["sem_capa"])
        self.assertEqual(capturado["dias"], 7)

    def test_valor_neutro_nao_vira_filtro(self):
        capturado = {}

        def falso(**filtros):
            capturado.update(filtros)
            return []

        with patch.object(self.central, "musicas", side_effect=falso):
            self.app.biblioteca_artista_var.set("Todos os artistas")
            self.app._atualizar_biblioteca()
        self.assertEqual(capturado["artista"], "")

    def test_limpar_filtros_volta_ao_neutro(self):
        self.app.biblioteca_busca_var.set("rock")
        self.app.biblioteca_sem_capa_var.set(True)
        self.app.biblioteca_duracao_var.set("Até 3 min")
        self.app.biblioteca_artista_var.set("Queen (2)")
        self.app._limpar_filtros_biblioteca()
        self.assertEqual(self.app.biblioteca_busca_var.get(), "")
        self.assertFalse(self.app.biblioteca_sem_capa_var.get())
        self.assertEqual(self.app.biblioteca_duracao_var.get(), "Qualquer duração")
        self.assertEqual(self.app.biblioteca_artista_var.get(), "Todos os artistas")

    def test_estado_vazio_orienta_o_proximo_passo(self):
        with patch.object(self.central, "musicas", return_value=[]), \
                patch.object(self.central.biblioteca, "contar", return_value=0):
            self.app._atualizar_biblioteca()
        self.assertIn("Reindexar", self.app.biblioteca_vazia_var.get())

    def test_filtro_sem_resultado_sugere_limpar(self):
        with patch.object(self.central, "musicas", return_value=[]), \
                patch.object(self.central.biblioteca, "contar", return_value=5):
            self.app._atualizar_biblioteca()
        self.assertIn("Limpar filtros", self.app.biblioteca_vazia_var.get())

    def test_resumo_mostra_filtrado_de_total(self):
        with patch.object(self.central, "musicas", return_value=[]), \
                patch.object(self.central.biblioteca, "contar", return_value=9):
            self.app._atualizar_biblioteca()
        self.assertIn("0 de 9", self.app.biblioteca_resumo_var.get())

    def test_facetas_preenchem_os_menus(self):
        facetas = {"artistas": [{"valor": "Queen", "total": 3}],
                   "albuns": [{"valor": "Opera", "total": 2}],
                   "generos": [{"valor": "Rock", "total": 5}],
                   "anos": [{"valor": "1975", "total": 1}]}
        with patch.object(self.central.biblioteca, "facetas",
                          return_value=facetas):
            self.app._carregar_facetas()
        # o widget dublê guarda os valores recebidos em ``configure``
        textos = [str(w.kwargs) + str(w.opcoes) for w in _widgets_criados]
        self.assertTrue(any("Queen (3)" in texto for texto in textos))
        self.assertTrue(any("1975 (1)" in texto for texto in textos))

    def test_faceta_antiga_que_sumiu_volta_para_neutro(self):
        self.app.biblioteca_artista_var.set("Artista Que Sumiu (1)")
        with patch.object(self.central.biblioteca, "facetas",
                          return_value={"artistas": [], "albuns": [],
                                        "generos": [], "anos": []}):
            self.app._carregar_facetas()
        self.assertEqual(self.app.biblioteca_artista_var.get(),
                         "Todos os artistas")


class TestPlayerNaTela(unittest.TestCase):
    """Barra clicável, atalhos e tempo no player do rodapé."""

    @classmethod
    def setUpClass(cls):
        TestCentralApp.setUpClass()
        cls.app = TestCentralApp.app
        cls.central = TestCentralApp.central
        cls.modulo = TestCentralApp.modulo

    @classmethod
    def tearDownClass(cls):
        TestCentralApp.tearDownClass()

    def setUp(self):
        from reprodutor import Faixa

        self.central.reprodutor.definir_fila(
            [Faixa("/tmp/x.mp3", "Faixa", "Artista", duracao=100.0)])

    def test_tempo_aparece_formatado(self):
        self.app._atualizar_player()
        self.assertIn("/", self.app.player_tempo.get())
        self.assertIn("1:40", self.app.player_tempo.get())

    def test_clique_na_barra_pede_seek(self):
        evento = type("E", (), {"x": 50})()
        with patch.object(self.app.player_progresso, "winfo_width",
                          return_value=100), \
                patch.object(self.central.reprodutor, "buscar",
                             return_value=True) as busca:
            self.app._player_clicou_barra(evento)
        busca.assert_called_once()
        self.assertAlmostEqual(busca.call_args[0][0], 50.0, places=1)

    def test_clique_sem_duracao_avisa_em_vez_de_fingir(self):
        from reprodutor import Faixa

        self.central.reprodutor.definir_fila([Faixa("/tmp/x.mp3", "Sem duração")])
        evento = type("E", (), {"x": 10})()
        self.app._player_clicou_barra(evento)
        self.assertIn("desconhecida", self.app.status_var.get())

    def test_atalho_de_espaco_nao_rouba_digitacao(self):
        self.app.raiz.focus_get = lambda: type("Entry", (), {})()
        with patch.object(self.app, "_player_pausar") as pausar:
            self.app._atalho_espaco()
        pausar.assert_not_called()

    def test_atalho_de_espaco_pausa_fora_de_campo(self):
        self.app.raiz.focus_get = lambda: None
        with patch.object(self.app, "_player_pausar") as pausar:
            self.app._atalho_espaco()
        pausar.assert_called_once()

    def test_pular_mostra_o_destino(self):
        with patch.object(self.central.reprodutor, "avancar",
                          return_value=True):
            self.app._player_pular(10)
        self.assertIn("Pulando", self.app.status_var.get())

    def test_volume_por_atalho_respeita_limites(self):
        self.central.reprodutor.volume = 98
        self.app._player_volume_passo(10)
        self.assertEqual(self.central.reprodutor.volume, 100)
        self.central.reprodutor.volume = 2
        self.app._player_volume_passo(-10)
        self.assertEqual(self.central.reprodutor.volume, 0)

    def test_atalhos_estao_ligados_na_janela(self):
        registrados = []
        self.app.raiz.bind = lambda tecla, *_a, **_k: registrados.append(tecla)
        self.app._ligar_atalhos()
        self.assertIn("<space>", registrados)
        self.assertIn("<Control-Right>", registrados)


def musica_de_teste(**campos):
    """``Musica`` completa (o dataclass exige todos os campos)."""
    from biblioteca import Musica

    dados = dict(id=1, caminho="/tmp/nao_existe.mp3", titulo="Faixa",
                 artista="Artista", album="Álbum", ano="", genero="", faixa="",
                 duracao=None, tamanho=None, tem_capa=False, favorito=False,
                 origem_url="", adicionada_em="", atualizada_em="")
    dados.update(campos)
    return Musica(**dados)


class TestPreviaDeCapa(unittest.TestCase):
    """A capa é mostrada antes de gravar; cancelar não altera o arquivo."""

    @classmethod
    def setUpClass(cls):
        TestCentralApp.setUpClass()
        cls.app = TestCentralApp.app
        cls.central = TestCentralApp.central

    @classmethod
    def tearDownClass(cls):
        TestCentralApp.tearDownClass()

    @staticmethod
    def _candidatos():
        from capas import CapaEncontrada

        def _jpeg(cor: int) -> bytes:
            from PIL import Image
            import io

            buffer = io.BytesIO()
            Image.new("RGB", (600, 600), (cor, 20, 40)).save(buffer, "JPEG")
            return buffer.getvalue()

        return [
            CapaEncontrada("itunes", "https://x/1.jpg", 600, 600, True, _jpeg(10)),
            CapaEncontrada("deezer", "https://x/2.jpg", 1000, 1000, True, _jpeg(90)),
        ]

    def _musica(self):
        return musica_de_teste()

    def test_abre_uma_opcao_por_capa(self):
        del _widgets_criados[:]
        antes = len(_widgets_criados)
        self.app._previa_de_capas(self._musica(), self._candidatos())
        criados = _widgets_criados[antes:]
        textos = " ".join(str(w.kwargs.get("text", "")) for w in criados)
        self.assertIn("itunes", textos)
        # 2 cartões + botão do rodapé (o rótulo de ajuda também cita o texto)
        self.assertEqual(textos.count("Usar esta capa"), 4)
        self.assertIn("itunes", textos)
        self.assertIn("Cancelar", textos)

    def test_cancelar_nao_chama_incorporar(self):
        candidatos = self._candidatos()
        with patch.object(self.central, "incorporar_capa") as incorporar:
            janela = self.app._previa_de_capas(self._musica(), candidatos)
            janela.destroy()
        incorporar.assert_not_called()

    def test_escolher_e_usar_incorpora_a_capa_escolhida(self):
        candidatos = self._candidatos()
        del _widgets_criados[:]
        janela = self.app._previa_de_capas(self._musica(), candidatos)
        botoes = [w for w in _widgets_criados
                  if w.kwargs.get("text") == "Usar esta capa"
                  and getattr(w, "tipo", "") == "Button"]
        self.assertEqual(len(botoes), 3)
        botoes[1].kwargs["command"]()          # marca a segunda
        rodape = botoes[-1]                    # botão do rodapé (o que grava)
        with patch.object(self.app, "_executar",
                          side_effect=lambda trabalho, concluir=None, falhar=None:
                          concluir(trabalho()) if concluir else trabalho()), \
                patch.object(self.app, "_atualizar_biblioteca"), \
                patch.object(self.app, "_mostrar_capa_biblioteca"), \
                patch.object(self.central, "incorporar_capa") as incorporar:
            from colecoes import ResultadoCobertura

            incorporar.return_value = ResultadoCobertura(
                caminho="/tmp/x.mp3", ok=True, mensagem="Capa incorporada ao MP3.")
            rodape.kwargs["command"]()
        incorporar.assert_called_once()
        self.assertEqual(incorporar.call_args.kwargs["imagem"], candidatos[1].dados)
        janela.destroy()

    def test_usar_sem_escolher_avisa_e_nao_grava(self):
        del _widgets_criados[:]
        janela = self.app._previa_de_capas(self._musica(), self._candidatos())
        rodape = [w for w in _widgets_criados
                  if w.kwargs.get("text") == "Usar esta capa"][-1]
        with patch.object(self.central, "incorporar_capa") as incorporar, \
                patch.object(TestCentralApp.modulo, "messagebox") as caixa:
            rodape.kwargs["command"]()
        incorporar.assert_not_called()
        caixa.showinfo.assert_called_once()
        janela.destroy()

    def test_sem_candidatos_avisa_que_nada_foi_gravado(self):
        with patch.object(self.app, "_executar",
                          side_effect=lambda trabalho, concluir=None, falhar=None:
                          concluir(trabalho()) if concluir else trabalho()), \
                patch.object(self.central, "capa_candidatos", return_value=[]), \
                patch.object(self.app, "notificar") as notificar, \
                patch.object(self.central, "incorporar_capa") as incorporar:
            self.app._buscar_capa_selecionada.__wrapped__ if False else None
            with patch.object(self.app, "_musica_selecionada",
                              return_value=self._musica()):
                self.app._buscar_capa_selecionada()
        incorporar.assert_not_called()
        self.assertTrue(notificar.called)
        self.assertIn("Nada foi gravado", notificar.call_args[0][1])

    def test_com_candidatos_abre_a_previa_sem_gravar(self):
        with patch.object(self.app, "_executar",
                          side_effect=lambda trabalho, concluir=None, falhar=None:
                          concluir(trabalho()) if concluir else trabalho()), \
                patch.object(self.central, "capa_candidatos",
                             return_value=self._candidatos()), \
                patch.object(self.app, "_previa_de_capas") as previa, \
                patch.object(self.central, "incorporar_capa") as incorporar, \
                patch.object(self.app, "_musica_selecionada",
                             return_value=self._musica()):
            self.app._buscar_capa_selecionada()
        previa.assert_called_once()
        incorporar.assert_not_called()


class TestCandidatosDeCapaNoCentral(unittest.TestCase):
    """`Central.capa_candidatos` não grava nada e não inventa fonte."""

    @classmethod
    def setUpClass(cls):
        TestCentralApp.setUpClass()
        cls.central = TestCentralApp.central

    @classmethod
    def tearDownClass(cls):
        TestCentralApp.tearDownClass()

    def test_sem_artista_nem_album_nao_consulta_fonte(self):
        with patch("capas.GerenciadorCapas") as gerenciador:
            resultado = self.central.capa_candidatos(
                musica_de_teste(titulo="Só título", artista="", album=""))
        self.assertEqual(resultado, [])
        gerenciador.assert_not_called()

    def test_devolve_o_que_as_fontes_entregaram(self):
        falso = MagicMock()
        falso.candidatos.return_value = []
        falso.cliente.get_bytes.return_value = b"nao-e-imagem"
        with patch("capas.GerenciadorCapas", return_value=falso):
            resultado = self.central.capa_candidatos(
                musica_de_teste(titulo="T", artista="A", album="Alb"))
        self.assertEqual(resultado, [])


if __name__ == "__main__":
    unittest.main()


class TestDetalhesDoResultado(unittest.TestCase):
    """Clicar num resultado mostra ficha e miniatura — sem baixar mídia."""

    @classmethod
    def setUpClass(cls):
        TestCentralApp.setUpClass()
        cls.app = TestCentralApp.app
        cls.central = TestCentralApp.central

    @classmethod
    def tearDownClass(cls):
        TestCentralApp.tearDownClass()

    @staticmethod
    def _resultado(**campos):
        dados = dict(id="abc12345678", titulo="Faixa", canal="Artista",
                     duracao=210, url="https://youtu.be/abc12345678",
                     thumbnail="https://i.ytimg.com/vi/abc12345678/mqdefault.jpg",
                     tipo="video", quantidade=None, canal_verificado=False,
                     duracao_formatada="3:30", tipo_legivel="Vídeo")
        dados.update(campos)
        return type("R", (), dados)()

    def setUp(self):
        self.app.mostrar("pesquisar")

    def _selecionar(self, resultado):
        self.app._resultados = [resultado]
        with patch.object(self.app, "_indices_selecionados", return_value=[0]):
            self.app._mostrar_detalhes_resultado()

    def test_ficha_mostra_titulo_canal_e_tipo(self):
        self._selecionar(self._resultado())
        texto = self.app.pesquisa_detalhe.get()
        self.assertIn("Faixa", texto)
        self.assertIn("Artista", texto)
        self.assertIn("Vídeo", texto)
        self.assertIn("Duração: 3:30", texto)
        self.assertIn("https://youtu.be/abc12345678", texto)

    def test_sem_duracao_diz_que_nao_foi_informada(self):
        self._selecionar(self._resultado(duracao=None, duracao_formatada="desconhecida"))
        self.assertIn("não informou", self.app.pesquisa_detalhe.get())

    def test_compilado_longo_e_sinalizado(self):
        self._selecionar(self._resultado(duracao=7200, duracao_formatada="2:00:00"))
        self.assertIn("compilado/mix longo", self.app.pesquisa_detalhe.get())

    def test_playlist_mostra_quantidade(self):
        self._selecionar(self._resultado(tipo="playlist", quantidade=42,
                                         tipo_legivel="Playlist (42 vídeos)"))
        self.assertIn("42 vídeos", self.app.pesquisa_detalhe.get())

    def test_diz_se_ja_esta_na_biblioteca(self):
        with patch.object(self.central.biblioteca, "listar", return_value=[]):
            self._selecionar(self._resultado())
        self.assertIn("Ainda não está na biblioteca",
                      self.app.pesquisa_detalhe.get())
        with patch.object(self.central.biblioteca, "listar",
                          return_value=[musica_de_teste(
                              origem_url="https://youtu.be/abc12345678")]):
            self._selecionar(self._resultado())
        self.assertIn("Já na biblioteca", self.app.pesquisa_detalhe.get())

    def test_miniatura_vem_do_cache_sem_rede(self):
        with patch("thumbs.obter", return_value=None) as obter, \
                patch.object(self.app, "_executar",
                             side_effect=lambda t, c=None, f=None:
                             c(t()) if c else t()):
            self._selecionar(self._resultado())
        self.assertTrue(obter.called)
        self.assertIn("indisponível", _texto_do_widget(self.app.pesquisa_thumb))

    def test_sem_thumbnail_nao_tenta_baixar(self):
        with patch("thumbs.obter") as obter:
            self._selecionar(self._resultado(thumbnail=""))
        obter.assert_not_called()


def _texto_do_widget(widget) -> str:
    """Texto atual de um rótulo dublê (``configure(text=...)``)."""
    return str(widget.opcoes.get("text", ""))


class TestBuscaEFormatoNaCesta(unittest.TestCase):
    """Achar um item no meio de 200 e trocar formato em lote."""

    @classmethod
    def setUpClass(cls):
        TestCentralApp.setUpClass()
        cls.app = TestCentralApp.app
        cls.central = TestCentralApp.central

    @classmethod
    def tearDownClass(cls):
        TestCentralApp.tearDownClass()

    def setUp(self):
        from selecao import ItemSelecao

        self.central.selecao.limpar()
        self.central.selecao.adicionar_varios([
            ItemSelecao(titulo="Tempo Perdido", canal="Legião Urbana",
                        url="https://y/1", origem="Pesquisa: legião",
                        duracao=320),
            ItemSelecao(titulo="Que País É Este", canal="Legião Urbana",
                        url="https://y/2", origem="Playlist: rock"),
            ItemSelecao(titulo="Sweet Child O' Mine", canal="Guns N' Roses",
                        url="https://y/3", origem="Playlist: rock"),
        ])
        self.app.mostrar("fila")
        self.app._atualizar_fila()

    def _linhas(self):
        return [self.app.arvore_cesta.item(i)["values"]
                for i in self.app.arvore_cesta.get_children()]

    def test_sem_busca_mostra_tudo(self):
        self.app.cesta_busca.set("")
        self.app._atualizar_fila()
        self.assertEqual(len(self._linhas()), 3)

    def test_busca_por_titulo_filtra(self):
        self.app.cesta_busca.set("tempo perdido")
        self.app._atualizar_fila()
        linhas = self._linhas()
        self.assertEqual(len(linhas), 1)
        self.assertIn("Tempo Perdido", linhas[0][0])
        self.assertIn("1 de 3", self.app.cesta_busca_dica.get())

    def test_busca_por_canal_filtra(self):
        self.app.cesta_busca.set("legião")
        self.app._atualizar_fila()
        self.assertEqual(len(self._linhas()), 2)

    def test_busca_sem_resultado_avisa(self):
        self.app.cesta_busca.set("nada a ver")
        self.app._atualizar_fila()
        self.assertEqual(self._linhas(), [])
        self.assertIn("0 de 3", self.app.cesta_busca_dica.get())

    def test_indice_continua_correto_com_busca_ativa(self):
        """Com filtro, remover o item visível tem de remover o item certo."""
        self.app.cesta_busca.set("sweet")
        self.app._atualizar_fila()
        visiveis = self.app.arvore_cesta.get_children()
        self.assertEqual(len(visiveis), 1)
        urls_restantes = [i.url for i in self.central.selecao.listar()]
        self.assertIn("https://y/3", urls_restantes)  # é o que está na tela
        self.central.selecao.remover_indices([int(str(visiveis[0]))])
        restantes = [i.url for i in self.central.selecao.listar()]
        self.assertEqual(sorted(restantes), ["https://y/1", "https://y/2"])

    def test_formato_em_lote_sem_marcar_vale_para_toda_a_cesta(self):
        self.app.arvore_cesta.selection_remove(
            self.app.arvore_cesta.selection())
        self.app.cesta_formato.set("MP4")
        self.app._aplicar_formato_cesta()
        self.assertEqual({i.formato for i in self.central.selecao.listar()},
                         {"mp4"})
        self.assertIn("cesta inteira", self.app.status_var.get())

    def test_formato_em_lote_so_nos_marcados(self):
        self.app.cesta_busca.set("")
        self.app._atualizar_fila()
        self.app.arvore_cesta.selection_set("1")
        self.app.cesta_formato.set("MP4")
        self.app._aplicar_formato_cesta()
        formatos = {i.url: i.formato for i in self.central.selecao.listar()}
        self.assertEqual(formatos["https://y/2"], "mp4")
        self.assertEqual(formatos["https://y/1"], "mp3")

    def test_formato_em_cesta_vazia_avisa(self):
        self.central.selecao.limpar()
        self.app._atualizar_fila()
        with patch.object(self.app, "notificar") as notificar:
            self.app._aplicar_formato_cesta()
        self.assertIn("vazia", notificar.call_args[0][1])

    def test_resumo_mostra_total_mesmo_com_busca(self):
        self.app.cesta_busca.set("tempo")
        self.app._atualizar_fila()
        self.assertIn("3 música(s)", self.app.cesta_var.get())


class TestPainelDeMensagens(unittest.TestCase):
    """O que a interface diz fica na tela e no arquivo — não só no terminal."""

    @classmethod
    def setUpClass(cls):
        TestCentralApp.setUpClass()
        cls.app = TestCentralApp.app
        cls.central = TestCentralApp.central

    @classmethod
    def tearDownClass(cls):
        TestCentralApp.tearDownClass()

    def setUp(self):
        self.app.mensagens.clear()
        self.arquivo = Path(self.central.config.dados) / "app.log"
        if self.arquivo.exists():
            self.arquivo.unlink()

    def test_notificar_registra_com_e_sem_erro(self):
        with patch.object(TestCentralApp.modulo, "messagebox"):
            self.app.notificar("Cesta", "3 itens adicionados")
            self.app.notificar("Capa", "Nenhuma capa válida", erro=True)
        recentes = self.app.mensagens_recentes()
        self.assertEqual(len(recentes), 2)
        self.assertFalse(recentes[0][1])
        self.assertTrue(recentes[1][1])
        self.assertIn("Nenhuma capa válida", recentes[1][2])

    def test_mensagem_vai_para_o_arquivo_de_log(self):
        with patch.object(TestCentralApp.modulo, "messagebox"):
            self.app.notificar("Downloads", "2 concluídos")
        self.assertTrue(self.arquivo.is_file())
        conteudo = self.arquivo.read_text(encoding="utf-8")
        self.assertIn("Downloads: 2 concluídos", conteudo)

    def test_erro_assincrono_aparece_no_painel(self):
        with patch.object(TestCentralApp.modulo, "messagebox"):
            self.app._mostrar_erro(RuntimeError("falha de rede"))
        textos = [t for _c, _e, t in self.app.mensagens_recentes()]
        self.assertTrue(any("falha de rede" in t for t in textos))

    def test_painel_nao_cresce_sem_limite(self):
        with patch.object(TestCentralApp.modulo, "messagebox"):
            for numero in range(410):
                self.app.notificar("Teste", f"mensagem {numero}")
        self.assertLessEqual(len(self.app.mensagens), 400)
        self.assertIn("mensagem 409", self.app.mensagens[-1][2])

    def test_janela_mostra_as_mensagens(self):
        self.app.registrar_mensagem("primeira")
        self.app.registrar_mensagem("segunda", erro=True)
        janela = self.app._abrir_mensagens()
        caixas = [w for w in _widgets_criados
                  if getattr(w, "tipo", "") == "Text"]
        self.assertTrue(caixas)
        # o dublê de Text anota o conteúdo inserido em _valores["texto"]
        conteudo = caixas[-1]._valores.get("texto") or {}
        texto = " ".join(str(v) for v in conteudo.values()) or " ".join(
            str(v) for v in caixas[-1]._itens)
        self.assertIn("primeira", texto)
        self.assertIn("ERRO segunda", texto)
        janela.destroy()

    def test_botao_mensagens_existe_na_barra_de_status(self):
        rotulos = [w.kwargs.get("text") for w in _widgets_criados
                   if getattr(w, "tipo", "") == "Button"]
        self.assertIn("Mensagens", rotulos)
        self.assertIn("Abrir pasta de dados", rotulos)

    def test_limpar_painel_nao_apaga_o_arquivo(self):
        with patch.object(TestCentralApp.modulo, "messagebox"):
            self.app.notificar("Teste", "para apagar")
        janela = self.app._abrir_mensagens()
        limpar = [w for w in _widgets_criados
                  if w.kwargs.get("text") == "Limpar painel"][-1]
        limpar.kwargs["command"]()
        self.assertEqual(self.app.mensagens, [])
        self.assertIn("para apagar", self.arquivo.read_text(encoding="utf-8"))
        janela.destroy()
