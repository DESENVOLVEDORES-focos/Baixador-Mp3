"""Construção real dos widgets da interface com um Tkinter simulado.

Este Linux não tem Tkinter, então um dublê de ``tkinter``/``ttk`` registra as
chamadas e permite **construir todas as abas de verdade**. Isso pega o tipo de
erro que não aparece ao ler o código: widget com nome errado, atributo
inexistente, aba não montada, callback ligado a método que não existe.

Não valida aparência nem interação real (isso é Etapa D, no Windows).
"""

from __future__ import annotations

import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch



class _Widget:
    """Dublê genérico de widget: aceita qualquer chamada de configuração."""

    _criados: list["_Widget"] = []

    def __init__(self, *args, **kwargs):
        self.args, self.kwargs = args, kwargs
        self.opcoes: dict[str, object] = {}
        self._itens: list[str] = []
        self._selecao: list[str] = []
        self._valores: dict[str, list[str]] = {}
        _Widget._criados.append(self)

    def __getattr__(self, nome):
        if nome.startswith("_"):
            raise AttributeError(nome)

        def qualquer(*args, **kwargs):
            if nome in {"insert", "index"}:
                if nome == "index":
                    ident = args[0] if args else 0
                    return self._itens.index(str(ident)) if str(
                        ident) in self._itens else 0
                ident = kwargs.get("iid") or f"i{len(self._itens)}"
                self._itens.append(ident)
                valores = kwargs.get("values")
                if valores is None and len(args) > 2 and isinstance(args[2], dict):
                    valores = args[2].get("values")
                if valores is not None:
                    self._valores[ident] = list(valores)
                return ident
            if nome == "get_children":
                return tuple(self._itens)
            if nome == "selection":
                return tuple(self._selecao)
            if nome == "selection_set":
                alvos = args[0] if args else ()
                self._selecao = [str(a) for a in alvos]
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
            return None

        return qualquer

    # métodos usados em encadeamento/atribuição direta
    def pack(self, *a, **k):
        return None

    grid = pack
    place = pack

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

    def yview(self, *a):
        return None

    def see(self, *a):
        return None

    def start(self, *a):
        return None

    def stop(self):
        return None

    def after(self, *a, **k):
        return None

    def mainloop(self):
        return None

    def title(self, *a):
        return None

    def geometry(self, *a):
        return None

    def minsize(self, *a):
        return None


class _Var:
    def __init__(self, value=None, *a, **k):
        self._valor = value

    def get(self):
        return self._valor

    def set(self, valor):
        self._valor = valor


def _instalar_tk_falso() -> None:
    tk = types.ModuleType("tkinter")
    for nome in ("Tk Toplevel Canvas Frame Label Entry Text Button Checkbutton "
                 "Radiobutton Listbox PhotoImage").split():
        setattr(tk, nome, _Widget)
    for nome in ("StringVar BooleanVar IntVar DoubleVar").split():
        setattr(tk, nome, _Var)

    ttk = types.ModuleType("tkinter.ttk")
    for nome in ("Frame Label LabelFrame Entry Button Checkbutton Radiobutton "
                 "Combobox Treeview Notebook Progressbar Scrollbar Separator").split():
        setattr(ttk, nome, _Widget)
    tk.ttk = ttk

    messagebox = types.ModuleType("tkinter.messagebox")
    messagebox.showinfo = messagebox.showwarning = messagebox.showerror = (
        lambda *a, **k: None)
    messagebox.askyesno = lambda *a, **k: False
    filedialog = types.ModuleType("tkinter.filedialog")
    filedialog.askdirectory = filedialog.askopenfilename = lambda *a, **k: ""
    tk.messagebox = messagebox
    tk.filedialog = filedialog

    sys.modules["tkinter"] = tk
    sys.modules["tkinter.ttk"] = ttk
    sys.modules["tkinter.messagebox"] = messagebox
    sys.modules["tkinter.filedialog"] = filedialog


class TestConstrucaoDaJanela(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._env = patch.dict(os.environ)
        cls._env.start()
        _instalar_tk_falso()
        cls._temp = tempfile.TemporaryDirectory()
        raiz = Path(cls._temp.name)
        os.environ["BAIXADOR_DATA_DIR"] = str(raiz / ".baixador")
        # Recarrega a interface já com o Tk falso em sys.modules.
        for modulo in ("interface",):
            sys.modules.pop(modulo, None)
        import interface

        cls.interface = interface
        from configuracoes import Configuracoes
        from preferencias import Preferencias

        cls.controlador = interface.ControladorInterface(
            configuracoes=Configuracoes(raiz=raiz),
            preferencias=Preferencias(metadados_ativos=False))
        cls.app = interface.AplicativoGrafico(
            interface.tk.Tk(), controlador=cls.controlador)

    @classmethod
    def tearDownClass(cls):
        cls._temp.cleanup()
        cls._env.stop()
        for modulo in list(sys.modules):
            if modulo.startswith("tkinter"):
                sys.modules.pop(modulo, None)
        sys.modules.pop("interface", None)

    def test_todas_as_abas_foram_montadas(self):
        for atributo in ("aba_baixar", "aba_fila", "aba_historico", "aba_config"):
            self.assertTrue(hasattr(self.app, atributo), atributo)

    def test_painel_de_downloads_tem_as_colunas_prometidas(self):
        colunas = tuple(self.app.downloads_tree.kwargs.get("columns", ()))
        self.assertEqual(
            colunas, ("titulo", "formato", "progresso", "velocidade",
                      "tamanho", "etapa"))

    def test_resultados_mostram_canal_verificado_e_duracao(self):
        colunas = tuple(self.app.resultados_tree.kwargs.get("columns", ()))
        self.assertIn("duracao", colunas)
        self.assertIn("oficial", colunas)

    def test_progresso_atualiza_linha_sem_quebrar(self):
        from downloader import Progresso

        item = self.app.downloads_tree.insert("", "end", values=("",) * 6)
        self.app._aplicar_progresso(item, Progresso(
            percentual=42.5, velocidade="1.2MiB/s", total="3.4MiB",
            eta="00:03", etapa="Baixando"))
        self.assertIn("Baixando", self.app.status_var.get())
        self.assertIn("42", self.app.status_var.get())

    def test_progresso_sem_numero_nao_inventa_percentual(self):
        from downloader import Progresso

        item = self.app.downloads_tree.insert("", "end", values=("",) * 6)
        self.app._aplicar_progresso(item, Progresso(etapa="Convertendo para MP3"))
        texto = self.app.status_var.get()
        self.assertIn("Convertendo", texto)
        self.assertNotIn("%", texto)

    def test_miniatura_indisponivel_mostra_texto_e_nao_quebra(self):
        self.app._mostrar_thumb(None)
        self.assertIn("indisponível", self.app.thumb_label.cget("text"))

    def test_trocar_politica_para_sobrescrever_pede_confirmacao(self):
        self.app.sobrescrita_var.set("sobrescrever")
        with patch.object(self.interface.messagebox, "askyesno", return_value=False):
            self.assertFalse(self.app._salvar_config(silencioso=True))
        # Recusando, nada é salvo com sobrescrita.
        self.assertNotEqual(self.controlador.preferencias.sobrescrita, "sobrescrever")

    def test_salvar_configuracoes_validas_funciona(self):
        self.app.sobrescrita_var.set("renomear")
        self.app.limite_var.set("8")
        self.assertTrue(self.app._salvar_config(silencioso=True))
        from preferencias import carregar

        self.assertEqual(carregar(self.controlador._base).sobrescrita, "renomear")

    def test_historico_exibe_data_legivel(self):
        self.controlador.aplicacao.historico.registrar(
            url="https://e/x", formato="mp3", status="sucesso", caminho="a.mp3")
        self.app._atualizar_historico()  # não deve levantar
        self.assertNotEqual(self.interface._data_legivel(
            self.controlador.historico()[0]["data_hora"]), "")

    def test_importar_cookies_pela_tela(self):
        origem = Path(self._temp.name) / "cookies.txt"
        origem.write_text(
            "# Netscape HTTP Cookie File\n"
            ".youtube.com\tTRUE\t/\tTRUE\t1893456000\tPREF\tf1=500\n",
            encoding="utf-8")
        with patch.object(self.interface.filedialog, "askopenfilename",
                          return_value=str(origem)), patch.object(
                              self.interface.messagebox, "showinfo"):
            self.app._ao_importar_cookies()
        self.assertEqual(self.controlador.status_cookies().do_youtube, 1)
        self.assertIn("Substituir", self.app.cookies_botao_var.get())

    # -- lote / playlist ----------------------------------------------------
    def test_aba_lote_existe_com_tabela_e_campo_de_urls(self):
        self.assertTrue(hasattr(self.app, "aba_lote"))
        self.assertTrue(hasattr(self.app, "lote_tree"))
        self.assertTrue(hasattr(self.app, "lote_urls_text"))

    def test_lista_playlist_na_tela_e_marca_sem_ao_vivo(self):
        from playlist import ItemPlaylist, Playlist

        lista = Playlist(titulo="Mix", url="https://y/playlist?list=X", itens=(
            ItemPlaylist(1, "a", "Song One (Official Video)", "https://y/a", 200),
            ItemPlaylist(2, "b", "Song Two (Ao Vivo)", "https://y/b", 300),
            ItemPlaylist(3, "c", "[Private video]", "https://y/c",
                         disponivel=False),
            ItemPlaylist(4, "d", "Song Four", "https://y/d", 180),
        ), total_informado=4)
        with patch.object(self.controlador, "listar_playlist", return_value=lista), \
                patch.object(self.app, "_executar",
                             side_effect=lambda trabalho, concluir, falhar=None:
                             concluir(trabalho())):
            self.app.lote_url_var.set("https://y/playlist?list=X")
            self.app._ao_listar_playlist()
        self.assertEqual(len(self.app.lote_tree.get_children()), 4)
        self.assertIn("4", self.app.lote_info_var.get())

        self.app._marcar_sem_ao_vivo()
        selecionados = list(self.app.lote_tree.selection())
        self.assertEqual(selecionados, ["1", "4"])  # sem o ao vivo e sem o privado
        self.assertIn("2 ficaram de fora", self.app.lote_progresso_var.get())

    def test_baixar_lote_nao_quebra_com_selecao_vazia(self):
        with patch.object(self.interface.messagebox, "showinfo") as aviso:
            self.app._ao_baixar_lote()
        self.assertTrue(aviso.called)

    def test_playlist_na_fila_ignora_itens_indisponiveis(self):
        from playlist import ItemPlaylist, Playlist

        self.app._playlist_atual = Playlist(titulo="Mix", url="u", itens=(
            ItemPlaylist(1, "a", "Um", "https://127.0.0.1:1/a.mp3"),
            ItemPlaylist(2, "b", "[Private video]", "https://127.0.0.1:1/b.mp3",
                         disponivel=False),
            ItemPlaylist(3, "c", "Três", "https://127.0.0.1:1/c.mp3"),
        ))
        self.app._ao_enfileirar_playlist()
        urls = [self.app.fila_tree.item(i, "values")[3]
                for i in self.app.fila_tree.get_children()]
        self.assertIn("https://127.0.0.1:1/a.mp3", urls)
        self.assertNotIn("https://127.0.0.1:1/b.mp3", urls)

    def test_rebaixar_do_historico_manda_a_url_original(self):
        self.app._historico_atual = [
            {"url": "https://y/x", "caminho": "C:/a.mp3"}]
        self.app.historico_tree.insert("", "end", iid="0", values=("",) * 5)
        self.app.historico_tree.selection_set(["0"])
        pedidos = []
        with patch.object(self.controlador, "baixar_lote",
                          side_effect=lambda urls, formato, **k:
                          pedidos.append(urls) or [(urls[0], True, "ok")]), \
                patch.object(self.app, "_executar",
                             side_effect=lambda trabalho, concluir, falhar=None:
                             concluir(trabalho())):
            self.app._ao_rebaixar()
        self.assertEqual(pedidos, [["https://y/x"]])

    def test_botao_de_atualizar_ytdlp_mostra_o_que_aconteceu(self):
        from atualizacao import ResultadoAtualizacao

        resultado = ResultadoAtualizacao(
            ok=False, versao_antes="2024.1", versao_depois="2024.1",
            mensagem="O yt-dlp em uso é um programa separado (pasta ferramentas).")
        with patch.object(self.controlador, "atualizar_ytdlp",
                          return_value=resultado), \
                patch.object(self.interface.messagebox, "askyesno",
                             return_value=True), \
                patch.object(self.interface.messagebox, "showwarning"), \
                patch.object(self.app, "_executar",
                             side_effect=lambda trabalho, concluir, falhar=None:
                             concluir(trabalho())):
            self.app._ao_atualizar_ytdlp()
        self.assertIn("programa separado", self.app.atualizacao_status_var.get())

    def test_varias_urls_coladas_de_uma_vez_vao_para_o_lote(self):
        pedidos = []
        with patch.object(self.controlador, "baixar_lote",
                          side_effect=lambda urls, formato, **k:
                          pedidos.append(urls) or [(u, True, "ok") for u in urls]), \
                patch.object(self.app, "_executar",
                             side_effect=lambda trabalho, concluir, falhar=None:
                             concluir(trabalho())), \
                patch.object(self.interface.messagebox, "askyesno",
                             return_value=True):
            self.app.url_var.set("https://y/a\nhttps://y/b, https://y/c")
            self.app._ao_baixar_url()
        self.assertEqual(pedidos, [["https://y/a", "https://y/b", "https://y/c"]])


if __name__ == "__main__":
    unittest.main()
