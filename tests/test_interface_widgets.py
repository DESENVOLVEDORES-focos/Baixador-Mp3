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
        _Widget._criados.append(self)

    def __getattr__(self, nome):
        if nome.startswith("_"):
            raise AttributeError(nome)

        def qualquer(*args, **kwargs):
            if nome in {"insert", "index"}:
                if nome == "index":
                    return 0
                ident = f"i{len(self._itens)}"
                self._itens.append(ident)
                return ident
            if nome == "get_children":
                return tuple(self._itens)
            if nome == "selection":
                return tuple(self._itens[:1])
            if nome == "item":
                return {"values": ["", "", "", "", "", ""]}
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


if __name__ == "__main__":
    unittest.main()
