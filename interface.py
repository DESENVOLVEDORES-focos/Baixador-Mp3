"""Interface gráfica do Baixador-Mp3 (Etapa 3) — Tkinter, sem terminal.

Duas camadas:

- ``ControladorInterface``: toda a lógica (pesquisa, downloads, fila,
  histórico, preferências, cookies, testes de conexão) falando apenas com
  os módulos existentes da IA 1/IA 2. Não importa Tkinter — é testável
  sem tela e é o que os testes automatizados exercitam.
- ``AplicativoGrafico``: as janelas (abas Baixar / Fila / Histórico /
  Configurações), construídas sobre o controlador. Tkinter é a biblioteca
  gráfica padrão do Python no Windows: não exige dependências extras.

Execução: ``python interface.py``, ``python musica.py gui`` ou, no
Windows, dando dois cliques em ``iniciar_interface.bat``.
"""

from __future__ import annotations

import logging
import os
import queue
import sys
import threading
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable

from configuracoes import CONFIG, Configuracoes
from cookies_youtube import ErroCookies
from cookies_youtube import importar as importar_cookies_arquivo
from cookies_youtube import remover as remover_cookies_arquivo
from cookies_youtube import status as status_cookies_arquivo
from musica import Aplicacao
from preferencias import (
    IA_MODELO_PADRAO, IA_URL_PADRAO, Preferencias, aplicar_ao_ambiente,
    carregar, derivar_configuracoes, salvar,
)

log = logging.getLogger("baixador.interface")

try:  # Tkinter acompanha o Python no Windows; pode faltar em Linux mínimo.
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
except ImportError:  # pragma: no cover - ambiente sem suporte gráfico
    tk = None  # type: ignore[assignment]
    filedialog = messagebox = ttk = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Controlador (lógica, sem Tkinter)
# ---------------------------------------------------------------------------


class ControladorInterface:
    """Ponte entre a interface e o núcleo (IA 1) + inteligência (IA 2)."""

    def __init__(self, configuracoes: Configuracoes = CONFIG,
                 preferencias: Preferencias | None = None,
                 aplicacao: Aplicacao | None = None):
        self._base = configuracoes
        self.preferencias = preferencias if preferencias is not None else carregar(configuracoes)
        aplicar_ao_ambiente(self.preferencias)
        if aplicacao is not None:
            self.aplicacao = aplicacao
            self.config = aplicacao.config
        else:
            self.config = derivar_configuracoes(self.preferencias, configuracoes)
            self.aplicacao = Aplicacao(self.config)
        self.aplicacao.config.preparar_diretorios()
        self._ultimo_caminho = ""

    # -- pesquisa e downloads (núcleo da IA 1 + metadados da IA 2) ---------
    def pesquisar(self, consulta: str):
        return self.aplicacao.pesquisador.pesquisar(
            consulta, self.preferencias.limite_pesquisa)

    def baixar(self, url: str, formato: str, ao_progresso=None,
               politica: str | None = None,
               contexto=None) -> tuple[bool, str]:
        resultado = self.aplicacao.baixar(url, formato, ao_progresso=ao_progresso,
                                          politica=politica, contexto=contexto)
        caminho = getattr(self.aplicacao, "ultimo_caminho", "")
        if caminho:
            self._ultimo_caminho = str(caminho)
        return resultado

    def pasta_dados(self) -> Path:
        return self.config.dados

    def ultimo_caminho(self) -> str:
        """Caminho do último arquivo publicado (para exibir/abrir)."""
        return self._ultimo_caminho

    def abrir_pasta_do_arquivo(self, caminho: str) -> None:
        alvo = Path(caminho)
        pasta = alvo.parent if alvo.suffix else alvo
        pasta.mkdir(parents=True, exist_ok=True)
        if os.name == "nt":
            os.startfile(str(pasta))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            os.system(f'open "{pasta}"')
        else:
            os.system(f'xdg-open "{pasta}" >/dev/null 2>&1 &')

    def resumo_musical(self) -> dict[str, Any]:
        """Resumo do último enriquecimento (álbum/ano/capa) para a tela.

        Vem de ``ProcessadorMusical.ultimo_resumo`` quando o módulo expõe isso;
        sem dado confirmado, devolve ``{}`` — a interface diz explicitamente
        "não confirmado" em vez de inventar informação musical.
        """
        processador = getattr(self.aplicacao.metadados, "_processador", None)
        resumo = getattr(processador, "ultimo_resumo", None)
        return dict(resumo) if isinstance(resumo, dict) else {}

    # -- fila e histórico ---------------------------------------------------
    def adicionar_fila(self, url: str, formato: str):
        return self.aplicacao.fila.adicionar(url, formato)  # type: ignore[arg-type]

    def listar_fila(self):
        return self.aplicacao.fila.listar(todos=True)

    def processar_fila(self) -> int:
        return self.aplicacao.processar_fila()

    def reabrir_falhas(self) -> int:
        return self.aplicacao.fila.reabrir_falhas()

    def historico(self, limite: int = 50):
        return self.aplicacao.historico.listar(limite, incluir_erros=True)

    # -- preferências -------------------------------------------------------
    def salvar_preferencias(self, novas: Preferencias) -> None:
        novas.validar()
        salvar(novas, self._base)
        self.preferencias = novas
        aplicar_ao_ambiente(novas)
        # Reconstrói o núcleo para as novas opções valerem na hora.
        self.config = derivar_configuracoes(novas, self._base)
        self.aplicacao = Aplicacao(self.config)
        self.aplicacao.config.preparar_diretorios()

    # -- cookies do YouTube -------------------------------------------------
    def importar_cookies(self, origem: str | Path):
        info = importar_cookies_arquivo(origem, self.config)
        self.salvar_preferencias(replace(
            self.preferencias, cookies_caminho=str(info.caminho)))
        return info

    def remover_cookies(self) -> bool:
        removeu = remover_cookies_arquivo(self.config)
        if self.preferencias.cookies_caminho:
            self.salvar_preferencias(replace(self.preferencias, cookies_caminho=""))
        return removeu

    def status_cookies(self):
        return status_cookies_arquivo(self.config)

    # -- testes de conexão (somente serviços que o código realmente usa) ----
    def testar_ia(self) -> tuple[str, str]:
        """``(estado, mensagem)``: nao_configurada | valida | invalida."""
        chave = self.preferencias.ia_api_key.strip()
        if not chave:
            return ("nao_configurada",
                    "IA externa é opcional e não está configurada; a "
                    "identificação usa as APIs musicais públicas e a "
                    "heurística local de títulos.")
        from inteligencia import AssistenteIAOpenAI, ClienteHTTPUrllib

        assistente = AssistenteIAOpenAI(
            ClienteHTTPUrllib(timeout=10), chave,
            modelo=self.preferencias.ia_modelo or IA_MODELO_PADRAO,
            url=self.preferencias.ia_url or IA_URL_PADRAO)
        consulta = assistente.interpretar_titulo("Queen - Bohemian Rhapsody")
        if consulta is not None:
            return ("valida", "Conexão com a IA respondeu corretamente.")
        return ("invalida",
                "A IA não respondeu como esperado; confira chave, modelo e URL.")

    def testar_provedor_musical(self, nome: str) -> tuple[str, str]:
        """Testa MusicBrainz/iTunes/Deezer (públicos, sem chave)."""
        from inteligencia import (
            ClienteHTTPUrllib, ConsultaMusica, ErroAPI, ProvedorDeezer,
            ProvedorITunes, ProvedorMusicBrainz,
        )

        provedores = {
            "musicbrainz": ProvedorMusicBrainz(), "itunes": ProvedorITunes(),
            "deezer": ProvedorDeezer(),
        }
        provedor = provedores.get(nome)
        if provedor is None:
            return ("invalida", f"Provedor desconhecido: {nome}")
        try:
            achados = provedor.buscar(
                ConsultaMusica(titulo="Bohemian Rhapsody", artista="Queen"),
                ClienteHTTPUrllib(timeout=10))
        except ErroAPI as erro:
            return ("invalida", f"Sem resposta do serviço: {erro}")
        except Exception as erro:  # teste de conexão nunca derruba a interface
            return ("invalida", f"Falha inesperada: {erro}")
        if achados:
            return ("valida", "Serviço público respondendo (não exige chave).")
        return ("invalida", "O serviço respondeu, mas sem resultados de teste.")


def _data_legivel(valor: Any) -> str:
    """ISO-8601 → "17/11/2026 21:35" (fuso local). Entrada inválida = ""."""
    texto = str(valor or "").strip()
    if not texto:
        return ""
    try:
        from datetime import datetime

        data = datetime.fromisoformat(texto.replace("Z", "+00:00"))
        if data.tzinfo is not None:
            data = data.astimezone()
        return data.strftime("%d/%m/%Y %H:%M")
    except (ValueError, TypeError, OverflowError):
        return texto[:19]


def _parece_falta_de_login(mensagem: str) -> bool:
    """Compatibilidade: delega ao classificador único de erros (diagnostico.py)."""
    from diagnostico import classificar

    return classificar(mensagem).exige_cookies


def _resumo_texto(resumo: dict[str, Any]) -> str:
    """Resumo legível do enriquecimento, sem inventar campo ausente."""
    partes: list[str] = []
    artista = str(resumo.get("artista") or "").strip()
    titulo = str(resumo.get("titulo") or "").strip()
    if artista or titulo:
        partes.append(" — ".join(p for p in (artista, titulo) if p))
    album = str(resumo.get("album") or "").strip()
    ano = resumo.get("ano")
    if album or ano:
        partes.append(f"{album or 'álbum não identificado'}"
                      + (f" ({ano})" if ano else ""))
    capa = "capa incorporada" if resumo.get("capa_incorporada") else "sem capa"
    fonte = str(resumo.get("fonte") or "").strip()
    if fonte and fonte != "nome_do_arquivo":
        partes.append(f"{capa} · fonte: {fonte}")
    else:
        partes.append(f"{capa} · identificação não confirmada "
                      "(apenas o nome do arquivo)")
    return " | ".join(partes)


def _miniatura_tk(caminho: Path, tamanho: tuple[int, int] = (224, 126)) -> Any:
    """PhotoImage da miniatura; ``None`` quando Pillow/Tk não permitem.

    Tk puro só lê PNG/GIF; os thumbnails do YouTube são JPEG, então Pillow
    (opcional, declarado no requirements) é usado para decodificar e reduzir.
    """
    try:
        from PIL import Image, ImageTk  # type: ignore
    except ImportError:
        return None
    try:
        with Image.open(caminho) as imagem:
            imagem = imagem.convert("RGB")
            imagem.thumbnail(tamanho)
            return ImageTk.PhotoImage(imagem)
    except Exception:  # imagem corrompida nunca derruba a interface
        return None


# ---------------------------------------------------------------------------
# Interface Tkinter
# ---------------------------------------------------------------------------


def _exigir_tkinter() -> None:
    if tk is None:
        raise RuntimeError(
            "Tkinter não está disponível nesta instalação do Python. "
            "No Windows ele acompanha o Python oficial; no Linux instale "
            "o pacote python3-tk.")


class AplicativoGrafico:
    def __init__(self, raiz: Any, controlador: ControladorInterface | None = None):
        _exigir_tkinter()
        self.raiz = raiz
        self.controlador = controlador or ControladorInterface()
        self.prefs = self.controlador.preferencias
        self._fila_eventos: queue.Queue = queue.Queue()
        self._resultados: list[Any] = []

        raiz.title("Baixador-Mp3")
        raiz.geometry("1020x700")
        raiz.minsize(880, 600)

        self.status_var = tk.StringVar(value="Pronto.")
        # Barra determinada: sem progresso real ela fica em 0 (não "gira").
        self.progresso = ttk.Progressbar(raiz, mode="determinate", maximum=100)
        abas = ttk.Notebook(raiz)
        abas.pack(fill="both", expand=True, padx=8, pady=(8, 4))
        self.progresso.pack(fill="x", padx=8)
        ttk.Label(raiz, textvariable=self.status_var).pack(
            fill="x", padx=8, pady=(2, 8))

        self.aba_baixar = ttk.Frame(abas)
        self.aba_fila = ttk.Frame(abas)
        self.aba_historico = ttk.Frame(abas)
        self.aba_config = ttk.Frame(abas)
        abas.add(self.aba_baixar, text="Baixar")
        abas.add(self.aba_fila, text="Fila")
        abas.add(self.aba_historico, text="Histórico")
        abas.add(self.aba_config, text="Configurações")

        self._montar_baixar()
        self._montar_fila()
        self._montar_historico()
        self._montar_configuracoes()
        self.raiz.after(120, self._processar_eventos)

    # -- infraestrutura -----------------------------------------------------
    def _definir_status(self, texto: str) -> None:
        self.status_var.set(texto)

    def _executar(self, trabalho: Callable[[], Any],
                  concluir: Callable[[Any], None],
                  falhar: Callable[[Exception], None] | None = None) -> None:
        self.progresso.start(12)

        def _rodar() -> None:
            try:
                self._fila_eventos.put(("ok", trabalho(), concluir))
            except Exception as erro:  # volta para a thread da interface
                self._fila_eventos.put(("erro", erro, falhar))

        threading.Thread(target=_rodar, daemon=True).start()

    def _processar_eventos(self) -> None:
        try:
            while True:
                tipo, valor, callback = self._fila_eventos.get_nowait()
                self.progresso.stop()
                if tipo == "progresso":
                    item, progresso = valor
                    self._aplicar_progresso(item, progresso)
                elif tipo == "thumb":
                    self._mostrar_thumb(valor)
                elif tipo == "ok" and callback:
                    callback(valor)
                elif tipo == "erro":
                    if callback:
                        callback(valor)
                    else:
                        self._mostrar_erro(valor)
        except queue.Empty:
            pass
        self.raiz.after(120, self._processar_eventos)

    def _mostrar_erro(self, erro: Exception) -> None:
        self._registrar(f"[ERRO] {erro}")
        self._definir_status(f"Erro: {erro}")
        messagebox.showerror("Baixador-Mp3", str(erro))

    def _registrar(self, texto: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", texto + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    # -- aba Baixar ---------------------------------------------------------
    def _montar_baixar(self) -> None:
        aba = self.aba_baixar
        busca = ttk.LabelFrame(aba, text="Pesquisar músicas e vídeos")
        busca.pack(fill="x", padx=8, pady=8)
        self.busca_var = tk.StringVar()
        ttk.Entry(busca, textvariable=self.busca_var).pack(
            side="left", fill="x", expand=True, padx=6, pady=6)
        ttk.Button(busca, text="Pesquisar", command=self._ao_pesquisar).pack(
            side="left", padx=6, pady=6)

        direto = ttk.LabelFrame(aba, text="Ou cole uma URL")
        direto.pack(fill="x", padx=8, pady=4)
        self.url_var = tk.StringVar()
        ttk.Entry(direto, textvariable=self.url_var).pack(
            side="left", fill="x", expand=True, padx=6, pady=6)
        self.formato_var = tk.StringVar(value=self.prefs.formato_padrao)
        ttk.Radiobutton(direto, text="MP3", value="mp3",
                        variable=self.formato_var).pack(side="left")
        ttk.Radiobutton(direto, text="MP4", value="mp4",
                        variable=self.formato_var).pack(side="left")
        ttk.Button(direto, text="Baixar URL", command=self._ao_baixar_url).pack(
            side="left", padx=6, pady=6)

        meio = ttk.Frame(aba)
        meio.pack(fill="both", expand=True, padx=8, pady=4)
        ttk.Label(meio, text="Resultados encontrados:").pack(anchor="w")
        corpo = ttk.Frame(meio)
        corpo.pack(fill="both", expand=True)
        self.resultados_tree = ttk.Treeview(
            corpo, columns=("titulo", "canal", "duracao", "oficial"),
            show="headings", height=10, selectmode="browse")
        for coluna, titulo, largura in (
                ("titulo", "Título", 420), ("canal", "Canal", 200),
                ("duracao", "Duração", 80), ("oficial", "Canal verificado", 120)):
            self.resultados_tree.heading(coluna, text=titulo)
            self.resultados_tree.column(coluna, width=largura)
        self.resultados_tree.pack(side="left", fill="both", expand=True)
        rolagem = ttk.Scrollbar(corpo, orient="vertical",
                                command=self.resultados_tree.yview)
        self.resultados_tree.configure(yscrollcommand=rolagem.set)
        rolagem.pack(side="right", fill="y")
        # Miniatura do resultado selecionado (carregada em thread).
        self.thumb_label = tk.Label(meio, text="Selecione um resultado",
                                    width=24, height=7, relief="groove",
                                    background="#f0f0f0")
        self.thumb_label.pack(fill="x", pady=4)
        self.resultados_tree.bind("<<TreeviewSelect>>", self._ao_selecionar_resultado)
        self.resultados_tree.bind("<Double-1>", lambda _e: self._ao_baixar_selecionado())
        botoes = ttk.Frame(aba)
        botoes.pack(fill="x", padx=8, pady=4)
        ttk.Button(botoes, text="Baixar selecionado",
                   command=self._ao_baixar_selecionado).pack(side="left")
        ttk.Button(botoes, text="Adicionar selecionado à fila",
                   command=self._ao_enfileirar_selecionado).pack(side="left", padx=6)

        self._montar_downloads(aba)

        ttk.Label(aba, text="Mensagens:").pack(anchor="w", padx=8)
        self.log_text = tk.Text(aba, height=7, state="disabled", wrap="word")
        self.log_text.pack(fill="both", expand=False, padx=8, pady=(0, 8))

    def _montar_downloads(self, aba: Any) -> None:
        """Acompanhamento por item: %, velocidade, tamanho e etapa atual."""
        quadro = ttk.LabelFrame(aba, text="Downloads")
        quadro.pack(fill="both", expand=True, padx=8, pady=(6, 0))
        self.downloads_tree = ttk.Treeview(
            quadro, columns=("titulo", "formato", "progresso", "velocidade",
                             "tamanho", "etapa"),
            show="headings", height=5, selectmode="browse")
        for coluna, titulo, largura in (
                ("titulo", "Título", 300), ("formato", "Formato", 70),
                ("progresso", "%", 70), ("velocidade", "Velocidade", 110),
                ("tamanho", "Tamanho", 130), ("etapa", "Etapa atual", 190)):
            self.downloads_tree.heading(coluna, text=titulo)
            self.downloads_tree.column(coluna, width=largura)
        self.downloads_tree.pack(fill="both", expand=True, padx=6, pady=6)
        botoes = ttk.Frame(quadro)
        botoes.pack(fill="x", padx=6, pady=(0, 6))
        ttk.Button(botoes, text="Abrir pasta da música",
                   command=lambda: self._abrir_pasta(self.controlador.config.musicas)
                   ).pack(side="left")
        ttk.Button(botoes, text="Abrir pasta dos vídeos",
                   command=lambda: self._abrir_pasta(self.controlador.config.videos)
                   ).pack(side="left", padx=6)

    def _abrir_pasta(self, pasta: Path) -> None:
        try:
            pasta.mkdir(parents=True, exist_ok=True)
            if os.name == "nt":
                os.startfile(str(pasta))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                os.system(f'open "{pasta}"')
            else:
                os.system(f'xdg-open "{pasta}" >/dev/null 2>&1 &')
        except Exception as erro:
            messagebox.showerror("Baixador-Mp3", f"Não foi possível abrir a pasta: {erro}")

    def _ao_selecionar_resultado(self, _evento: Any = None) -> None:
        resultado = self._selecionado(silencioso=True)
        if resultado is None:
            return
        url = getattr(resultado, "thumbnail", "") or ""
        self.thumb_label.configure(image="", text="Carregando miniatura...")

        def carregar() -> None:
            dados_dir = self.controlador.pasta_dados()
            try:
                from thumbs import obter

                caminho = obter(url, dados_dir)
            except Exception:
                caminho = None
            self._fila_eventos.put(("thumb", caminho, None))

        if not url:
            self.thumb_label.configure(text="Sem miniatura disponível")
            return
        threading.Thread(target=carregar, daemon=True).start()

    def _mostrar_thumb(self, caminho: Any) -> None:
        if caminho is None:
            self.thumb_label.configure(image="", text="Miniatura indisponível")
            self.thumb_label.image = None  # type: ignore[attr-defined]
            return
        imagem = _miniatura_tk(Path(caminho))
        if imagem is None:
            self.thumb_label.configure(
                image="",
                text="Miniatura baixada.\nInstale Pillow para exibi-la:\n"
                     "python -m pip install Pillow")
            return
        self.thumb_label.image = imagem  # type: ignore[attr-defined]
        self.thumb_label.configure(image=imagem, text="")

    def _ao_pesquisar(self) -> None:
        consulta = self.busca_var.get().strip()
        if not consulta:
            messagebox.showwarning("Baixador-Mp3", "Digite o que pesquisar.")
            return
        self._definir_status("Pesquisando...")

        def concluir(resultados: list[Any]) -> None:
            self._resultados = resultados
            for item in self.resultados_tree.get_children():
                self.resultados_tree.delete(item)
            for resultado in resultados:
                self.resultados_tree.insert("", "end", values=(
                    resultado.titulo, resultado.canal,
                    resultado.duracao_formatada,
                    "sim (evidência do extrator)"
                    if getattr(resultado, "canal_verificado", False) else "não"))
            self._registrar(f"Pesquisa: {len(resultados)} resultado(s).")
            self._definir_status(f"{len(resultados)} resultado(s) encontrado(s).")

        self._executar(lambda: self.controlador.pesquisar(consulta), concluir)

    def _selecionado(self, silencioso: bool = False):
        escolha = self.resultados_tree.selection()
        if not escolha:
            if not silencioso:
                messagebox.showwarning("Baixador-Mp3", "Selecione um resultado.")
            return None
        indice = self.resultados_tree.index(escolha[0])
        return self._resultados[indice] if indice < len(self._resultados) else None

    def _baixar(self, url: str, formato: str, contexto: Any = None) -> None:
        self._definir_status(f"Preparando {formato.upper()}...")
        item = self.downloads_tree.insert("", "end", values=(
            url, formato.upper(), "0%", "", "", "Preparando"))
        self.progresso.configure(value=0)

        def ao_progresso(progresso: Any) -> None:
            # Chamado da thread do download: só publica o evento.
            self._fila_eventos.put(("progresso", (item, progresso), None))

        def concluir(resultado: tuple[bool, str]) -> None:
            sucesso, mensagem = resultado
            if sucesso:
                self.downloads_tree.item(item, values=(
                    url, formato.upper(), "100%", "", "", "Concluído"))
                caminho_final = self.controlador.ultimo_caminho()
                texto = f"[OK] Download {formato.upper()} concluído."
                if caminho_final:
                    texto += f" Arquivo: {caminho_final}"
                resumo = self.controlador.resumo_musical()
                if resumo:
                    texto += " " + _resumo_texto(resumo)
                if mensagem:
                    texto += f" Aviso: {mensagem}"
                self._registrar(texto)
                self._definir_status("Download concluído.")
                self.progresso.configure(value=100)
            else:
                self.downloads_tree.item(item, values=(
                    url, formato.upper(), "", "", "", f"Falhou: {mensagem[:60]}"))
                self._registrar(f"[ERRO] {mensagem}")
                diagnostico = getattr(self.controlador.aplicacao,
                                      "ultimo_diagnostico", None)
                if diagnostico is not None:
                    from diagnostico import dica_para_interface

                    tem_cookies = bool(self.controlador.status_cookies().configurado)
                    dica = dica_para_interface(diagnostico, tem_cookies)
                    if dica and dica != mensagem:
                        self._registrar(f"[DICA] {dica}")
                    if diagnostico.exige_cookies:
                        self._definir_status(
                            "Falhou por autenticação — veja a dica de cookies abaixo.")
                self._definir_status("O download falhou; veja as mensagens.")
                self.progresso.configure(value=0)
            self._atualizar_historico()
            self._atualizar_fila()

        def rodar():
            return self.controlador.baixar(url, formato, ao_progresso=ao_progresso,
                                           contexto=contexto)

        def concluir_com_pergunta(resultado: tuple[bool, str]) -> None:
            sucesso, mensagem = resultado
            concluir(resultado)
            # Política "perguntar": o núcleo não sobrescreveu; oferecemos baixar
            # como cópia, com o nome renomeado — sempre com autorização.
            if (sucesso and "já existe" in mensagem
                    and self.prefs.sobrescrita == "perguntar"):
                if messagebox.askyesno(
                        "Arquivo já existe",
                        "Este arquivo já está na pasta e nada foi sobrescrito.\n\n"
                        "Baixar mesmo assim, criando uma cópia com outro nome?"):
                    item2 = self.downloads_tree.insert("", "end", values=(
                        url, formato.upper(), "0%", "", "", "Baixando cópia"))
                    self._executar(
                        lambda: self.controlador.baixar(
                            url, formato, ao_progresso=lambda p: self._fila_eventos.put(
                                ("progresso", (item2, p), None)),
                            politica="renomear"),
                        concluir)

        self._executar(rodar, concluir_com_pergunta)

    def _aplicar_progresso(self, item: str, progresso: Any) -> None:
        """Atualiza a linha do item com o que o yt-dlp realmente informou."""
        valores = list(self.downloads_tree.item(item, "values"))
        if not valores:  # item removido
            return
        while len(valores) < 6:
            valores.append("")
        if progresso.percentual is not None:
            valores[2] = f"{progresso.percentual:.0f}%"
            self.progresso.configure(value=progresso.percentual)
        if progresso.velocidade:
            valores[3] = progresso.velocidade
        if progresso.total:
            valores[4] = (f"{progresso.baixado} / {progresso.total}"
                          if progresso.baixado else progresso.total)
        valores[5] = progresso.etapa
        self.downloads_tree.item(item, values=valores)
        self._definir_status(
            f"{progresso.etapa}"
            + (f" — {progresso.percentual:.0f}%" if progresso.percentual is not None else "")
            + (f" — {progresso.velocidade}" if progresso.velocidade else "")
            + (f" — faltam {progresso.eta}" if progresso.eta else ""))

    def _ao_baixar_url(self) -> None:
        url = self.url_var.get().strip()
        if not url:
            messagebox.showwarning("Baixador-Mp3", "Cole uma URL primeiro.")
            return
        self._baixar(url, self.formato_var.get())

    def _ao_baixar_selecionado(self) -> None:
        resultado = self._selecionado()
        if resultado:
            self._baixar(resultado.url, self.formato_var.get(),
                         contexto=resultado)

    def _ao_enfileirar_selecionado(self) -> None:
        resultado = self._selecionado()
        if not resultado:
            return
        item = self.controlador.adicionar_fila(resultado.url, self.formato_var.get())
        self._registrar(f"Na fila: {item.id} ({item.formato}) {item.url}")
        self._atualizar_fila()

    # -- aba Fila -----------------------------------------------------------
    def _montar_fila(self) -> None:
        aba = self.aba_fila
        self.fila_tree = ttk.Treeview(
            aba, columns=("formato", "status", "tentativas", "url"),
            show="headings", height=16)
        for coluna, titulo, largura in (
                ("formato", "Formato", 80), ("status", "Status", 110),
                ("tentativas", "Tentativas", 90), ("url", "URL", 600)):
            self.fila_tree.heading(coluna, text=titulo)
            self.fila_tree.column(coluna, width=largura)
        self.fila_tree.pack(fill="both", expand=True, padx=8, pady=8)
        botoes = ttk.Frame(aba)
        botoes.pack(fill="x", padx=8, pady=(0, 8))
        ttk.Button(botoes, text="Atualizar", command=self._atualizar_fila).pack(side="left")
        ttk.Button(botoes, text="Processar fila",
                   command=self._ao_processar_fila).pack(side="left", padx=6)
        ttk.Button(botoes, text="Reabrir falhas",
                   command=self._ao_reabrir_falhas).pack(side="left")
        self._atualizar_fila()

    def _atualizar_fila(self) -> None:
        if not hasattr(self, "fila_tree"):
            return
        for item in self.fila_tree.get_children():
            self.fila_tree.delete(item)
        try:
            itens = self.controlador.listar_fila()
        except Exception as erro:
            self._definir_status(f"Erro ao ler a fila: {erro}")
            return
        for item in itens:
            self.fila_tree.insert("", "end", values=(
                item.formato.upper(), item.status, item.tentativas, item.url))

    def _ao_processar_fila(self) -> None:
        self._definir_status("Processando a fila...")
        self._executar(
            self.controlador.processar_fila,
            lambda qtd: (self._registrar(f"Fila processada: {qtd} download(s)."),
                         self._atualizar_fila(), self._atualizar_historico(),
                         self._definir_status("Fila processada.")))

    def _ao_reabrir_falhas(self) -> None:
        qtd = self.controlador.reabrir_falhas()
        self._registrar(f"Itens reabertos: {qtd}")
        self._atualizar_fila()

    # -- aba Histórico ------------------------------------------------------
    def _montar_historico(self) -> None:
        aba = self.aba_historico
        self.historico_tree = ttk.Treeview(
            aba, columns=("quando", "formato", "status", "url", "mensagem"),
            show="headings", height=18)
        for coluna, titulo, largura in (
                ("quando", "Quando", 150), ("formato", "Formato", 70),
                ("status", "Status", 130), ("url", "URL / arquivo", 340),
                ("mensagem", "Mensagem", 260)):
            self.historico_tree.heading(coluna, text=titulo)
            self.historico_tree.column(coluna, width=largura)
        self.historico_tree.pack(fill="both", expand=True, padx=8, pady=8)
        ttk.Button(aba, text="Atualizar", command=self._atualizar_historico).pack(
            padx=8, pady=(0, 8), anchor="w")
        self._atualizar_historico()

    def _atualizar_historico(self) -> None:
        if not hasattr(self, "historico_tree"):
            return
        for item in self.historico_tree.get_children():
            self.historico_tree.delete(item)
        try:
            registros = self.controlador.historico()
        except Exception as erro:
            self._definir_status(f"Erro ao ler o histórico: {erro}")
            return
        for registro in registros:
            self.historico_tree.insert("", "end", values=(
                _data_legivel(registro.get("data_hora")),
                str(registro.get("formato") or "").upper(),
                registro.get("status") or "",
                registro.get("caminho") or registro.get("url") or "",
                registro.get("mensagem") or ""))

    # -- aba Configurações --------------------------------------------------
    def _montar_configuracoes(self) -> None:
        # Área rolável: são muitas opções em janelas menores.
        canvas = tk.Canvas(self.aba_config, highlightthickness=0)
        rolagem = ttk.Scrollbar(self.aba_config, orient="vertical",
                                command=canvas.yview)
        quadro = ttk.Frame(canvas)
        quadro.bind("<Configure>",
                    lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=quadro, anchor="nw")
        canvas.configure(yscrollcommand=rolagem.set)
        canvas.pack(side="left", fill="both", expand=True)
        rolagem.pack(side="right", fill="y")
        prefs = self.prefs

        # APIs e inteligência artificial -------------------------------------
        apis = ttk.LabelFrame(quadro, text="CONFIGURAÇÕES — APIs e inteligência artificial")
        apis.pack(fill="x", padx=8, pady=8)
        ttk.Label(apis, text="Inteligência artificial (opcional — interpreta títulos de vídeo)").grid(
            row=0, column=0, columnspan=4, sticky="w", padx=6, pady=(6, 2))
        ttk.Label(apis, text="API Key:").grid(row=1, column=0, sticky="e", padx=6)
        self.ia_chave_var = tk.StringVar(value=prefs.ia_api_key)
        self.ia_chave_entry = ttk.Entry(apis, textvariable=self.ia_chave_var, width=52, show="•")
        self.ia_chave_entry.grid(row=1, column=1, sticky="we", pady=2)
        self.ia_mostrar_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(apis, text="Mostrar", variable=self.ia_mostrar_var,
                        command=self._alternar_chave).grid(row=1, column=2, padx=4)
        ttk.Label(apis, text="Modelo:").grid(row=2, column=0, sticky="e", padx=6)
        self.ia_modelo_var = tk.StringVar(value=prefs.ia_modelo)
        ttk.Entry(apis, textvariable=self.ia_modelo_var, width=52).grid(
            row=2, column=1, sticky="we", pady=2)
        ttk.Label(apis, text="URL da API:").grid(row=3, column=0, sticky="e", padx=6)
        self.ia_url_var = tk.StringVar(value=prefs.ia_url)
        ttk.Entry(apis, textvariable=self.ia_url_var, width=52).grid(
            row=3, column=1, sticky="we", pady=2)
        self.ia_status_var = tk.StringVar(value=self._texto_status_ia())
        ttk.Label(apis, textvariable=self.ia_status_var).grid(
            row=4, column=1, sticky="w", pady=2)
        ttk.Button(apis, text="Testar conexão", command=self._ao_testar_ia).grid(
            row=4, column=2, padx=4, pady=2)

        ttk.Label(apis, text="Identificação musical (APIs públicas — funcionam SEM chave):").grid(
            row=5, column=0, columnspan=4, sticky="w", padx=6, pady=(10, 2))
        self.provedor_status: dict[str, tk.StringVar] = {}
        linha = 6
        for nome, rotulo in (("itunes", "iTunes Search"),
                             ("musicbrainz", "MusicBrainz"),
                             ("deezer", "Deezer")):
            ttk.Label(apis, text=f"{rotulo}: sem chave necessária").grid(
                row=linha, column=0, columnspan=2, sticky="w", padx=6)
            var = tk.StringVar(value="Não testado")
            self.provedor_status[nome] = var
            ttk.Label(apis, textvariable=var).grid(row=linha, column=2, sticky="w")
            ttk.Button(apis, text="Testar conexão",
                       command=lambda n=nome: self._ao_testar_provedor(n)).grid(
                row=linha, column=3, padx=4, pady=1)
            linha += 1

        # Cookies do YouTube --------------------------------------------------
        cookies = ttk.LabelFrame(quadro, text="CONFIGURAÇÕES — COOKIES DO YOUTUBE")
        cookies.pack(fill="x", padx=8, pady=4)
        ttk.Label(cookies, text=(
            "O cookies.txt contém informações de autenticação da sua conta. "
            "Ele fica guardado só neste computador, nunca é enviado a outros "
            "serviços, nunca aparece em logs e não deve ser compartilhado. "
            "Para obter o seu: entre no YouTube no navegador, use uma extensão "
            "de exportação de cookies no formato Netscape (cookies.txt) e "
            "salve o arquivo — nenhuma senha é pedida por este programa."),
            wraplength=900, justify="left").pack(anchor="w", padx=6, pady=6)
        self.cookies_status_var = tk.StringVar()
        ttk.Label(cookies, textvariable=self.cookies_status_var).pack(
            anchor="w", padx=6)
        botoes_cookies = ttk.Frame(cookies)
        botoes_cookies.pack(fill="x", padx=6, pady=6)
        self.cookies_botao_var = tk.StringVar(value="Selecionar cookies.txt...")
        ttk.Button(botoes_cookies, textvariable=self.cookies_botao_var,
                   command=self._ao_importar_cookies).pack(side="left")
        ttk.Button(botoes_cookies, text="Verificar",
                   command=self._atualizar_status_cookies).pack(side="left")
        ttk.Button(botoes_cookies, text="Remover",
                   command=self._ao_remover_cookies).pack(side="left", padx=6)
        self._atualizar_status_cookies()

        # Downloads ------------------------------------------------------------
        downloads = ttk.LabelFrame(quadro, text="CONFIGURAÇÕES — Downloads")
        downloads.pack(fill="x", padx=8, pady=4)
        self.dir_mp3_var = tk.StringVar(value=prefs.diretorio_mp3)
        self.dir_mp4_var = tk.StringVar(value=prefs.diretorio_mp4)
        self._campo_diretorio(downloads, 0, "Pasta dos MP3 (vazio = Musicas):",
                              self.dir_mp3_var)
        self._campo_diretorio(downloads, 1, "Pasta dos MP4 (vazio = Videos):",
                              self.dir_mp4_var)
        ttk.Label(downloads, text="Formato padrão:").grid(row=2, column=0, sticky="e", padx=6)
        self.formato_padrao_var = tk.StringVar(value=prefs.formato_padrao)
        ttk.Combobox(downloads, textvariable=self.formato_padrao_var,
                     values=("mp3", "mp4"), width=12, state="readonly").grid(
            row=2, column=1, sticky="w", pady=2)
        ttk.Label(downloads, text="Qualidade MP3 (0 = melhor, ou ex.: 192K):").grid(
            row=3, column=0, sticky="e", padx=6)
        self.qualidade_var = tk.StringVar(value=prefs.qualidade_mp3)
        ttk.Entry(downloads, textvariable=self.qualidade_var, width=14).grid(
            row=3, column=1, sticky="w", pady=2)
        ttk.Label(downloads, text="Resultados por pesquisa (1–50):").grid(
            row=4, column=0, sticky="e", padx=6)
        self.limite_var = tk.StringVar(value=str(prefs.limite_pesquisa))
        ttk.Entry(downloads, textvariable=self.limite_var, width=14).grid(
            row=4, column=1, sticky="w", pady=2)
        ttk.Label(downloads, text="Se o arquivo já existir:\n(nada é sobrescrito sem escolha)").grid(
            row=7, column=0, sticky="e", padx=6)
        self.sobrescrita_var = tk.StringVar(
            value=getattr(prefs, "sobrescrita", "perguntar"))
        ttk.Combobox(downloads, textvariable=self.sobrescrita_var,
                     values=("perguntar", "pular", "renomear", "sobrescrever"),
                     width=16, state="readonly").grid(
            row=7, column=1, sticky="w", pady=2)
        self.metadados_var = tk.BooleanVar(value=prefs.metadados_ativos)
        ttk.Checkbutton(downloads, text="Preencher metadados e capas automaticamente (IA 2)",
                        variable=self.metadados_var).grid(
            row=5, column=0, columnspan=3, sticky="w", padx=6, pady=2)
        self.capas_var = tk.BooleanVar(value=prefs.buscar_capas)
        ttk.Checkbutton(downloads, text="Buscar e incorporar capas oficiais",
                        variable=self.capas_var).grid(
            row=6, column=0, columnspan=3, sticky="w", padx=6, pady=2)
        self.organizar_var = tk.BooleanVar(
            value=getattr(prefs, "organizar_nomes", True))
        ttk.Checkbutton(downloads,
                        text="Salvar como \"Artista - Título.mp3\" (nome organizado)",
                        variable=self.organizar_var).grid(
            row=8, column=0, columnspan=3, sticky="w", padx=6, pady=2)
        self.por_album_var = tk.BooleanVar(
            value=getattr(prefs, "organizar_por_album", False))
        ttk.Checkbutton(
            downloads,
            text="Guardar em subpastas Artista/Álbum (só com dados confirmados)",
            variable=self.por_album_var).grid(
            row=9, column=0, columnspan=3, sticky="w", padx=6, pady=2)

        ttk.Button(quadro, text="Salvar configurações",
                   command=self._ao_salvar_config).pack(padx=8, pady=10, anchor="w")

    def _campo_diretorio(self, pai: Any, linha: int, rotulo: str,
                         variavel: Any) -> None:
        ttk.Label(pai, text=rotulo).grid(row=linha, column=0, sticky="e", padx=6)
        ttk.Entry(pai, textvariable=variavel, width=52).grid(
            row=linha, column=1, sticky="we", pady=2)
        ttk.Button(pai, text="Escolher...",
                   command=lambda: self._escolher_diretorio(variavel)).grid(
            row=linha, column=2, padx=4)

    def _escolher_diretorio(self, variavel: Any) -> None:
        escolhido = filedialog.askdirectory()
        if escolhido:
            variavel.set(escolhido)

    def _alternar_chave(self) -> None:
        # Mostrar/ocultar a chave: só muda o caractere de máscara do campo.
        self.ia_chave_entry.configure(show="" if self.ia_mostrar_var.get() else "•")

    def _texto_status_ia(self) -> str:
        return ("Configurada (chave protegida neste computador)"
                if self.prefs.ia_api_key else
                "Não configurada — opcional; o programa funciona sem ela")

    def _ao_testar_ia(self) -> None:
        self._salvar_config(silencioso=True)
        self.ia_status_var.set("Testando...")

        def concluir(resultado: tuple[str, str]) -> None:
            self.ia_status_var.set(f"{resultado[0]}: {resultado[1]}")

        self._executar(self.controlador.testar_ia, concluir)

    def _ao_testar_provedor(self, nome: str) -> None:
        self.provedor_status[nome].set("Testando...")

        def concluir(resultado: tuple[str, str]) -> None:
            self.provedor_status[nome].set(f"{resultado[0]}: {resultado[1]}")

        self._executar(lambda: self.controlador.testar_provedor_musical(nome), concluir)

    def _atualizar_status_cookies(self) -> None:
        try:
            info = self.controlador.status_cookies()
        except Exception as erro:
            self.cookies_status_var.set(f"Erro ao verificar cookies: {erro}")
            return
        if not info.configurado:
            texto = "Nenhum cookies.txt configurado (downloads públicos funcionam sem ele)."
            self.cookies_botao_var.set("Selecionar cookies.txt...")
        elif info.valido:
            idade = ""
            try:
                from datetime import datetime

                quando = datetime.fromtimestamp(info.caminho.stat().st_mtime)  # type: ignore[union-attr]
                dias = (datetime.now() - quando).days
                idade = f" importado em {quando.strftime('%d/%m/%Y')} ({dias} dia(s))"
            except OSError:
                idade = ""
            texto = (f"Configurado e válido: {info.total} cookie(s), "
                     f"{info.do_youtube} do YouTube/Google{idade} — {info.caminho}")
            self.cookies_botao_var.set("Substituir cookies.txt...")
        else:
            texto = f"Configurado, mas inválido: {info.mensagem}"
        self.cookies_status_var.set(texto)

    def _ao_importar_cookies(self) -> None:
        caminho = filedialog.askopenfilename(
            title="Selecione o cookies.txt (formato Netscape)",
            filetypes=(("Cookies Netscape", "cookies.txt *.txt"), ("Todos", "*.*")))
        if not caminho:
            return
        try:
            info = self.controlador.importar_cookies(caminho)
        except ErroCookies as erro:
            messagebox.showerror("Cookies", str(erro))
            return
        self._registrar(f"Cookies importados: {info.total} cookie(s) válido(s).")
        self._atualizar_status_cookies()
        messagebox.showinfo("Cookies", "cookies.txt importado e válido. "
                                       "Ele será usado automaticamente pelo yt-dlp.")

    def _ao_remover_cookies(self) -> None:
        if not messagebox.askyesno(
                "Cookies", "Remover o cookies.txt guardado? Os downloads "
                           "voltam a ser feitos sem autenticação."):
            return
        try:
            self.controlador.remover_cookies()
        except ErroCookies as erro:
            messagebox.showerror("Cookies", str(erro))
            return
        self._atualizar_status_cookies()
        self._registrar("Cookies removidos pelo usuário.")

    def _salvar_config(self, silencioso: bool = False) -> bool:
        try:
            limite = int(self.limite_var.get())
        except ValueError:
            messagebox.showerror("Configurações", "Resultados por pesquisa deve ser um número.")
            return False
        sobrescrita = str(self.sobrescrita_var.get() or "perguntar").lower()
        if sobrescrita == "sobrescrever":
            if not messagebox.askyesno(
                    "Sobrescrita", "Com 'sobrescrever' o programa pode substituir "
                                   "um arquivo já existente na pasta. Confirmar?"):
                return False
        novas = Preferencias(
            ia_api_key=self.ia_chave_var.get().strip(),
            ia_modelo=self.ia_modelo_var.get().strip() or IA_MODELO_PADRAO,
            ia_url=self.ia_url_var.get().strip() or IA_URL_PADRAO,
            cookies_caminho=self.controlador.preferencias.cookies_caminho,
            diretorio_mp3=self.dir_mp3_var.get().strip(),
            diretorio_mp4=self.dir_mp4_var.get().strip(),
            formato_padrao=self.formato_padrao_var.get(),
            qualidade_mp3=self.qualidade_var.get().strip() or "0",
            limite_pesquisa=limite,
            metadados_ativos=bool(self.metadados_var.get()),
            buscar_capas=bool(self.capas_var.get()),
            sobrescrita=sobrescrita,
            organizar_nomes=bool(self.organizar_var.get()),
            organizar_por_album=bool(self.por_album_var.get()),
        )
        try:
            self.controlador.salvar_preferencias(novas)
        except ValueError as erro:
            messagebox.showerror("Configurações", str(erro))
            return False
        self.prefs = novas
        self.ia_status_var.set(self._texto_status_ia())
        if not silencioso:
            self._definir_status("Configurações salvas.")
            messagebox.showinfo("Configurações", "Configurações salvas neste computador.")
        return True

    def _ao_salvar_config(self) -> None:
        self._salvar_config()


def main() -> int:
    try:
        _exigir_tkinter()
    except RuntimeError as erro:
        print(f"[ERRO] {erro}", file=sys.stderr)
        return 1
    raiz = tk.Tk()
    try:
        AplicativoGrafico(raiz)
    except Exception as erro:
        messagebox.showerror("Baixador-Mp3", f"Falha ao iniciar: {erro}")
        return 1
    raiz.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
