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

    # -- chave de IA por arquivo (api.txt) ----------------------------------
    def importar_chave(self, origem: Any):
        """Valida o arquivo escolhido, guarda a cópia e ativa a chave."""
        import api_ia

        info = api_ia.importar(origem, self.config)
        # Passa a valer já nesta sessão, sem reabrir o programa.
        os.environ["BAIXADOR_IA_API_KEY"] = api_ia.ler_chave(self.config)
        self.preferencias = replace(self.preferencias, ia_api_key="")
        return info

    def status_chave(self):
        import api_ia

        return api_ia.status(self.config)

    def remover_chave(self) -> bool:
        import api_ia

        removeu = api_ia.remover(self.config)
        if not self.preferencias.ia_api_key:
            os.environ.pop("BAIXADOR_IA_API_KEY", None)
        return removeu

    def testar_chave(self) -> tuple[bool, str]:
        """Chamada mínima à API para confirmar que a chave funciona."""
        import api_ia
        from identificacao_ia import IdentificadorIA

        chave = api_ia.ler_chave(self.config)
        if not chave:
            return False, ("Nenhuma chave configurada: importe o api.txt "
                           "em Configurações.")
        return IdentificadorIA(api_key=chave, config=self.config).testar_conexao()

    def identificar_com_ia(self, consulta: str, canal: str = ""):
        """Usa o prompt de identificação/catalogação (6 campos)."""
        from identificacao_ia import IdentificadorIA

        return IdentificadorIA(config=self.config).identificar(consulta, canal)

    # -- manutenção ---------------------------------------------------------
    def versao_ytdlp(self) -> str:
        from atualizacao import versao_instalada

        return versao_instalada(self.aplicacao.config)

    def atualizar_ytdlp(self):
        from atualizacao import atualizar

        return atualizar(self.aplicacao.config)

    # -- lote e playlist ----------------------------------------------------
    def listar_playlist(self, url: str, limite: int = 200):
        """Itens de uma playlist/canal (só metadados, nada baixado)."""
        return self.aplicacao.listar_playlist(url, limite)

    def baixar_lote(self, urls: list[str], formato: str, ao_item=None,
                    ao_progresso=None) -> list[tuple[str, bool, str]]:
        """Baixa várias URLs em sequência; nunca para no primeiro erro."""
        return self.aplicacao.baixar_varios(
            urls, formato, ao_progresso=ao_progresso, ao_item=ao_item)

    # -- pré-visualização (ouvir antes de baixar) ---------------------------
    def inspecionar(self, url: str):
        """Dados do vídeo + indícios de ao vivo/show, sem baixar mídia."""
        return self.aplicacao.preparar_previa(url)

    def ouvir_trecho(self, url: str, segundos: int = 20) -> tuple[Any, Any]:
        """Baixa um trecho curto: ``(arquivo_para_tocar, pasta_temporaria)``."""
        return self.aplicacao.ouvir_previa(url, segundos)

    def descartar_previa(self, pasta: Any) -> None:
        """Apaga o trecho baixado (nunca deixa lixo em `.baixador`)."""
        if pasta:
            from previa import limpar

            limpar(Path(pasta))

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
        metadados = self.aplicacao.metadados
        processador = (getattr(metadados, "processador_real", None)
                       or getattr(metadados, "_processador", None))
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
                      "(apenas o título/canal do vídeo)")
    # Quantos provedores falharam, sem despejar stack trace na tela: o detalhe
    # fica no histórico (sanitizado) para diagnóstico.
    erros = resumo.get("provedores_com_erro") or []
    if erros:
        nomes = sorted({str(erro).split(":", 1)[0] for erro in erros})
        partes.append("APIs indisponíveis: " + ", ".join(nomes))
    if resumo.get("identificado") is False:
        partes.append("Álbum/ano/gênero não confirmados")
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
        self.aba_lote = ttk.Frame(abas)
        self.aba_previa = ttk.Frame(abas)
        self.aba_config = ttk.Frame(abas)
        abas.add(self.aba_baixar, text="Baixar")
        abas.add(self.aba_fila, text="Fila")
        abas.add(self.aba_historico, text="Histórico")
        abas.add(self.aba_lote, text="Lote / Playlist")
        abas.add(self.aba_previa, text="Prévia (ouvir antes)")
        abas.add(self.aba_config, text="Configurações")

        self._montar_baixar()
        self._montar_fila()
        self._montar_historico()
        self._montar_lote()
        self._montar_previa()
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
                elif tipo == "lote":
                    posicao, total, referencia = valor
                    self.lote_progresso_var.set(
                        f"Item {posicao} de {total}: {referencia}")
                    self._definir_status(f"Baixando {posicao}/{total}...")
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
        """Erro em português: classificação + ação, com o técnico sanitizado.

        O usuário não deve receber um rastreamento do yt-dlp na cara; a
        mensagem crua fica no histórico (sanitizada) para diagnóstico.
        """
        from diagnostico import classificar, dica_para_interface, sanitizar

        diagnostico = classificar(str(erro))
        texto = dica_para_interface(
            diagnostico, bool(self.controlador.status_cookies().configurado))
        self._registrar(f"[ERRO] {texto} | técnico: {sanitizar(str(erro))}")
        self._definir_status(f"Erro: {diagnostico.explicacao}")
        messagebox.showerror("Baixador-Mp3", f"{diagnostico.explicacao}\n\n"
                                             f"{diagnostico.acao}")

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
            show="headings", height=10,
            # "extended": Ctrl+clique e Shift+clique para escolher vários.
            selectmode="extended")
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
        ttk.Button(botoes, text="Ouvir antes de baixar (prévia)",
                   command=self._ao_previas_selecionado).pack(side="left", padx=6)
        ttk.Button(botoes, text="Baixar selecionados",
                   command=self._baixar_varios_selecionados).pack(
            side="left", padx=6)

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

    def _selecionados(self) -> list[Any]:
        """Todos os resultados marcados (Ctrl+clique / Shift+clique)."""
        escolhas = list(self.resultados_tree.selection())  # type: ignore[attr-defined]
        escolhidos: list[Any] = []
        for iid in escolhas:
            try:
                indice = self.resultados_tree.index(iid)
            except Exception:
                continue
            if indice < len(self._resultados):
                escolhidos.append(self._resultados[indice])
        return escolhidos

    def _baixar_varios_selecionados(self) -> None:
        """Baixa todos os resultados marcados, mostrando 1 de N."""
        escolhidos = self._selecionados()
        if not escolhidos:
            messagebox.showinfo("Baixar", "Selecione um ou mais resultados "
                                          "(Ctrl+clique para vários).")
            return
        formato = self.formato_var.get()
        urls = [resultado.url for resultado in escolhidos]
        if len(urls) > 5 and not messagebox.askyesno(
                "Baixar vários",
                f"Baixar {len(urls)} itens em {formato.upper()}?"):
            return

        def ao_item(posicao: int, total: int, referencia: str) -> None:
            self._fila_eventos.put(("lote", (posicao, total, referencia[:60]), None))

        def concluir(resultados: list[tuple[str, bool, str]]) -> None:
            self._finalizar_lote(resultados)

        self._executar(
            lambda: self.controlador.baixar_lote(urls, formato, ao_item=ao_item),
            concluir, lambda erro: self._mostrar_erro(erro))

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
        texto = self.url_var.get().strip()
        if not texto:
            messagebox.showwarning("Baixador-Mp3", "Cole uma URL primeiro.")
            return
        # Aceita uma URL por linha (ou separadas por espaço/vírgula).
        urls: list[str] = []
        for pedaco in texto.replace(",", "\n").replace(";", "\n").split():
            if pedaco.startswith(("http://", "https://")) and pedaco not in urls:
                urls.append(pedaco)
        if not urls:
            messagebox.showwarning(
                "Baixador-Mp3",
                "Não encontrei uma URL começando com http:// ou https://.")
            return
        if len(urls) > 1:
            # Várias URLs: passa pelo mesmo lote (1 de N, sem parar no erro).
            self._baixar_urls(urls)
            return
        self._baixar(urls[0], self.formato_var.get())

    def _baixar_urls(self, urls: list[str]) -> None:
        """Baixa uma lista de URLs mostrando o progresso item a item."""
        formato = self.formato_var.get()
        if len(urls) > 5 and not messagebox.askyesno(
                "Baixar vários",
                f"Baixar {len(urls)} link(s) em {formato.upper()}?"):
            return

        def ao_item(posicao: int, total: int, referencia: str) -> None:
            self._fila_eventos.put(
                ("lote", (posicao, total, str(referencia)[:60]), None))

        self._executar(
            lambda: self.controlador.baixar_lote(urls, formato, ao_item=ao_item),
            lambda resultados: self._finalizar_lote(resultados),
            lambda erro: self._mostrar_erro(erro))

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

    def _ao_enfileirar_playlist(self) -> None:
        """Manda a playlist listada inteira para a fila (nada baixa agora)."""
        playlist = self._playlist_atual
        if playlist is None:
            messagebox.showinfo(
                "Fila", "Liste uma playlist primeiro (aba Lote / Playlist).")
            return
        formato = self.formato_var.get()
        disponiveis = [item for item in playlist.itens if item.disponivel]
        if not disponiveis:
            messagebox.showinfo(
                "Fila", "A playlist listada não tem itens disponíveis.")
            return
        novos = 0
        for item in disponiveis:
            antes = len(self.controlador.listar_fila())
            self.controlador.adicionar_fila(item.url, formato)
            if len(self.controlador.listar_fila()) > antes:
                novos += 1
        self._atualizar_fila()
        self._registrar(f"Playlist na fila: {novos} novo(s) de "
                        f"{len(disponiveis)} item(ns).")
        self._definir_status(f"{novos} item(ns) adicionados à fila.")

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
        self.historico_tree.configure(selectmode="extended")
        self.historico_tree.pack(fill="both", expand=True, padx=8, pady=8)
        acoes = ttk.Frame(aba)
        acoes.pack(padx=8, pady=(0, 8), anchor="w")
        ttk.Button(acoes, text="Atualizar",
                   command=self._atualizar_historico).pack(side="left")
        ttk.Button(acoes, text="Baixar de novo",
                   command=self._ao_rebaixar).pack(side="left", padx=6)
        self._atualizar_historico()

    def _ao_rebaixar(self) -> None:
        """Rebaixa o que está marcado no histórico (usando a URL original)."""
        registros = getattr(self, "_historico_atual", [])
        escolhas = list(self.historico_tree.selection())  # type: ignore[attr-defined]
        if not escolhas:
            messagebox.showinfo(
                "Histórico", "Selecione uma ou mais linhas do histórico.")
            return
        urls: list[str] = []
        for iid in escolhas:
            try:
                indice = int(str(iid))
            except ValueError:
                indice = self.historico_tree.index(iid)
            if 0 <= indice < len(registros):
                url = str(registros[indice].get("url") or "")
                if url.startswith(("http://", "https://")) and url not in urls:
                    urls.append(url)
        if not urls:
            messagebox.showinfo(
                "Histórico", "As linhas marcadas não têm URL para rebaixar.")
            return
        formato = self.formato_var.get()
        self._registrar(f"Rebaixando {len(urls)} item(ns) do histórico.")

        self._executar(
            lambda: self.controlador.baixar_lote(urls, formato),
            lambda resultados: self._finalizar_lote(resultados),
            lambda erro: self._mostrar_erro(erro))

    def _finalizar_lote(self, resultados: list[tuple[str, bool, str]]) -> None:
        ok = sum(1 for _u, sucesso, _m in resultados if sucesso)
        falhas = len(resultados) - ok
        self.lote_progresso_var.set(
            f"Lote concluído: {ok} com sucesso, {falhas} com falha.")
        self._registrar(f"Lote: {ok} sucesso(s), {falhas} falha(s).")
        self._definir_status(f"Lote concluído: {ok}/{len(resultados)}.")
        self._atualizar_historico()
        if falhas:
            detalhes = "\n".join(
                f"- {url[:60]}: {mensagem[:90]}"
                for url, sucesso, mensagem in resultados if not sucesso)
            messagebox.showwarning(
                "Lote concluído com falhas",
                f"{ok} baixado(s), {falhas} com falha:\n\n{detalhes}")

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
        self._historico_atual = registros
        for posicao, registro in enumerate(registros):
            # iid = posição: rebaixar não depende da ordem visual da tabela.
            self.historico_tree.insert("", "end", iid=str(posicao), values=(
                _data_legivel(registro.get("data_hora")),
                str(registro.get("formato") or "").upper(),
                registro.get("status") or "",
                registro.get("caminho") or registro.get("url") or "",
                registro.get("mensagem") or ""))

    # -- aba Configurações --------------------------------------------------
    # -- aba Lote / Playlist ------------------------------------------------
    def _montar_lote(self) -> None:
        """Playlist inteira, vários vídeos e uma lista de URLs de uma vez."""
        aba = self.aba_lote
        ttk.Label(aba, text=(
            "Cole a URL de uma playlist/canal e clique em \"Listar\": nada é "
            "baixado na listagem. Depois escolha os itens (Ctrl+clique, "
            "Shift+clique, ou os botões de seleção rápida) e mande baixar. "
            "Itens privados/removidos são ignorados automaticamente."),
            wraplength=900, justify="left").pack(anchor="w", padx=8, pady=(8, 4))

        linha = ttk.Frame(aba)
        linha.pack(fill="x", padx=8, pady=4)
        self.lote_url_var = tk.StringVar()
        ttk.Label(linha, text="URL da playlist:").pack(side="left")
        ttk.Entry(linha, textvariable=self.lote_url_var).pack(
            side="left", fill="x", expand=True, padx=6)
        ttk.Button(linha, text="Listar", command=self._ao_listar_playlist).pack(
            side="left")
        ttk.Button(linha, text="Listar mais (500)",
                   command=lambda: self._ao_listar_playlist(500)).pack(
            side="left", padx=6)
        ttk.Button(linha, text="Colar da área de transferência",
                   command=self._ao_colar_url).pack(side="left", padx=6)

        self.lote_info_var = tk.StringVar(value="Nenhuma playlist listada.")
        ttk.Label(aba, textvariable=self.lote_info_var, wraplength=900,
                  justify="left").pack(anchor="w", padx=8)

        corpo = ttk.Frame(aba)
        corpo.pack(fill="both", expand=True, padx=8, pady=4)
        self.lote_tree = ttk.Treeview(
            corpo, columns=("n", "titulo", "duracao", "situacao"),
            show="headings", height=14, selectmode="extended")
        for coluna, titulo, largura in (
                ("n", "#", 50), ("titulo", "Título", 520),
                ("duracao", "Duração", 90), ("situacao", "Situação", 160)):
            self.lote_tree.heading(coluna, text=titulo)
            self.lote_tree.column(coluna, width=largura)
        self.lote_tree.pack(side="left", fill="both", expand=True)
        rolagem = ttk.Scrollbar(corpo, orient="vertical",
                                command=self.lote_tree.yview)
        self.lote_tree.configure(yscrollcommand=rolagem.set)
        rolagem.pack(side="right", fill="y")

        acoes = ttk.Frame(aba)
        acoes.pack(fill="x", padx=8, pady=(0, 4))
        ttk.Button(acoes, text="Selecionar tudo",
                   command=lambda: self._selecionar_tudo_lote(True)
                   ).pack(side="left")
        ttk.Button(acoes, text="Limpar seleção",
                   command=lambda: self._selecionar_tudo_lote(False)
                   ).pack(side="left", padx=6)
        ttk.Button(acoes, text="Marcar sem ao vivo/show",
                   command=self._marcar_sem_ao_vivo).pack(side="left", padx=6)
        ttk.Button(acoes, text="Baixar selecionados",
                   command=self._ao_baixar_lote).pack(side="left", padx=6)
        ttk.Button(acoes, text="Adicionar selecionados à fila",
                   command=self._ao_enfileirar_lote).pack(side="left")
        ttk.Button(acoes, text="Playlist inteira na fila",
                   command=self._ao_enfileirar_playlist).pack(
            side="left", padx=6)

        ttk.Label(aba, text="Ou cole várias URLs (uma por linha):").pack(
            anchor="w", padx=8, pady=(8, 0))
        self.lote_urls_text = tk.Text(aba, height=5, wrap="none")
        self.lote_urls_text.pack(fill="x", padx=8, pady=4)
        self.lote_progresso_var = tk.StringVar(value="")
        ttk.Label(aba, textvariable=self.lote_progresso_var).pack(
            anchor="w", padx=8, pady=(0, 8))
        self._playlist_atual: Any = None

    def _ao_colar_url(self) -> None:
        """Colar da área de transferência (Ctrl+V já funciona nos campos)."""
        try:
            texto = self.raiz.clipboard_get()  # type: ignore[attr-defined]
        except Exception:
            messagebox.showinfo("Colar", "A área de transferência está vazia.")
            return
        texto = (texto or "").strip()
        if texto:
            self.lote_url_var.set(texto.split()[0])

    def _ao_listar_playlist(self, limite: int = 200) -> None:
        url = self.lote_url_var.get().strip()
        if not url:
            messagebox.showwarning("Playlist", "Cole a URL da playlist ou canal.")
            return
        self.lote_info_var.set("Listando os itens (sem baixar nada)...")
        self._definir_status("Listando playlist...")

        def concluir(playlist: Any) -> None:
            self._playlist_atual = playlist
            for item in self.lote_tree.get_children():
                self.lote_tree.delete(item)
            for item in playlist.itens:
                self.lote_tree.insert("", "end", iid=str(item.indice), values=(
                    item.indice, item.titulo, item.duracao_formatada,
                    "disponível" if item.disponivel else "privado/removido"))
            minutos = playlist.duracao_total // 60
            aviso = ""
            restantes = getattr(playlist, "restantes", 0)
            if restantes > 0:
                aviso = (f" ATENÇÃO: {restantes} item(ns) não foram listados "
                         "(playlist longa). Use \"Listar mais\" para incluir.")
            elif playlist.truncada:
                aviso = (f" Mostrando os primeiros {playlist.quantidade} "
                         "item(ns).")
            self.lote_info_var.set(
                f"{playlist.titulo or 'Playlist'} — {playlist.quantidade} "
                f"item(ns), ~{minutos} min no total.{aviso}")
            self._registrar(f"Playlist listada: {playlist.quantidade} item(ns).")
            self._definir_status(f"{playlist.quantidade} item(ns) na playlist.")

        self._executar(
            lambda: self.controlador.listar_playlist(url, limite), concluir,
            lambda erro: self._mostrar_erro(erro))

    def _selecionar_tudo_lote(self, marcar: bool) -> None:
        itens = self.lote_tree.get_children()
        if marcar:
            self.lote_tree.selection_set(itens)  # type: ignore[attr-defined]
        else:
            self.lote_tree.selection_remove(itens)  # type: ignore[attr-defined]

    def _marcar_sem_ao_vivo(self) -> None:
        """Seleciona só os itens sem indício de ao vivo/show (a razão nº 1)."""
        from previa import analisar

        escolhidos = []
        eliminados = 0
        for iid in self.lote_tree.get_children():
            valores = self.lote_tree.item(iid, "values")
            titulo = str(valores[1]) if len(valores) > 1 else ""
            situacao = str(valores[3]) if len(valores) > 3 else ""
            if "privado" in situacao or "removido" in situacao:
                eliminados += 1
                continue
            if analisar(titulo).possivel_ao_vivo:
                eliminados += 1
                continue
            escolhidos.append(iid)
        self.lote_tree.selection_set(escolhidos)  # type: ignore[attr-defined]
        self.lote_progresso_var.set(
            f"{len(escolhidos)} selecionado(s); {eliminados} ficaram de fora "
            "(ao vivo/show ou indisponível).")

    def _urls_do_lote(self) -> list[str]:
        """URLs escolhidas na lista + as coladas no campo de várias URLs."""
        playlist = self._playlist_atual
        escolhidos = list(self.lote_tree.selection())  # type: ignore[attr-defined]
        urls: list[str] = []
        if playlist is not None:
            mapa = {str(item.indice): item for item in playlist.itens}
            for iid in escolhidos:
                item = mapa.get(str(iid))
                if item is not None and item.disponivel:
                    urls.append(item.url)
        texto = self.lote_urls_text.get("1.0", "end") if hasattr(
            self.lote_urls_text, "get") else ""
        for linha in str(texto or "").splitlines():
            linha = linha.strip()
            if linha.startswith(("http://", "https://")) and linha not in urls:
                urls.append(linha)
        return urls

    def _ao_baixar_lote(self) -> None:
        urls = self._urls_do_lote()
        if not urls:
            messagebox.showinfo(
                "Lote", "Selecione itens na lista ou cole URLs no campo abaixo.")
            return
        formato = self.formato_var.get()
        if len(urls) > 5 and not messagebox.askyesno(
                "Baixar em lote",
                f"Baixar {len(urls)} item(ns) em {formato.upper()} agora?"):
            return

        def ao_item(posicao: int, total: int, referencia: str) -> None:
            self._fila_eventos.put((
                "lote", (posicao, total, str(referencia)[:60]), None))

        def executar() -> list[tuple[str, bool, str]]:
            return self.controlador.baixar_lote(urls, formato, ao_item=ao_item)

        def concluir(resultados: list[tuple[str, bool, str]]) -> None:
            self._finalizar_lote(resultados)

        self.lote_progresso_var.set(f"Baixando {len(urls)} item(ns)...")
        self._executar(executar, concluir, lambda erro: self._mostrar_erro(erro))

    def _ao_enfileirar_lote(self) -> None:
        urls = self._urls_do_lote()
        if not urls:
            messagebox.showinfo("Lote", "Selecione itens ou cole URLs primeiro.")
            return
        formato = self.formato_var.get()
        for url in urls:
            self.controlador.adicionar_fila(url, formato)
        self._atualizar_fila()
        self.lote_progresso_var.set(f"{len(urls)} item(ns) na fila.")
        self._registrar(f"{len(urls)} item(ns) adicionados à fila.")

    # -- aba Prévia ---------------------------------------------------------
    def _montar_previa(self) -> None:
        """Ouvir/checar antes de baixar: evita show e versão errada."""
        aba = self.aba_previa
        ttk.Label(aba, text=(
            "Antes de baixar, confira o que é: a prévia mostra título, canal e "
            "duração reais e avisa quando o título indica gravação ao vivo "
            "(show), versão estendida, remix ou cover. O botão “Ouvir” baixa um "
            "trecho curto (20 s) e abre no player do Windows — nada é salvo em "
            "Musicas\\."), wraplength=900, justify="left").pack(
            anchor="w", padx=8, pady=(8, 4))

        linha = ttk.Frame(aba)
        linha.pack(fill="x", padx=8, pady=4)
        self.previa_url_var = tk.StringVar()
        ttk.Label(linha, text="URL do vídeo:").pack(side="left")
        ttk.Entry(linha, textvariable=self.previa_url_var).pack(
            side="left", fill="x", expand=True, padx=6)
        ttk.Button(linha, text="Usar resultado selecionado",
                   command=self._previa_do_selecionado).pack(side="left")
        ttk.Button(linha, text="Conferir dados",
                   command=self._ao_conferir).pack(side="left", padx=6)

        dados = ttk.LabelFrame(aba, text="Dados do vídeo (sem baixar)")
        dados.pack(fill="x", padx=8, pady=6)
        self.previa_info_var = tk.StringVar(value="Nada conferido ainda.")
        ttk.Label(dados, textvariable=self.previa_info_var, wraplength=900,
                  justify="left").pack(anchor="w", padx=6, pady=6)
        self.previa_alerta_var = tk.StringVar(value="")
        self.previa_alerta_label = tk.Label(
            dados, textvariable=self.previa_alerta_var, wraplength=880,
            justify="left", anchor="w", fg="#8a4b00")
        self.previa_alerta_label.pack(fill="x", padx=6, pady=(0, 6))

        acoes = ttk.Frame(dados)
        acoes.pack(fill="x", padx=6, pady=(0, 6))
        self.previa_segundos_var = tk.StringVar(value="20")
        ttk.Label(acoes, text="Segundos do trecho:").pack(side="left")
        ttk.Combobox(acoes, textvariable=self.previa_segundos_var, width=4,
                     values=("10", "20", "30", "40")).pack(side="left", padx=4)
        ttk.Button(acoes, text="Ouvir trecho",
                   command=self._ao_ouvir_trecho).pack(side="left", padx=6)
        ttk.Button(acoes, text="Parar e apagar trecho",
                   command=self._ao_parar_previa).pack(side="left")
        ttk.Button(acoes, text="Baixar este vídeo",
                   command=self._ao_baixar_previa).pack(side="left", padx=6)
        ttk.Button(acoes, text="Dados musicais (IA)",
                   command=self._ao_identificar_ia).pack(side="left", padx=6)
        self.ia_resultado_var = tk.StringVar(value="")
        ttk.Label(aba, textvariable=self.ia_resultado_var, wraplength=900,
                  justify="left").pack(anchor="w", padx=8, pady=(0, 8))
        self.previa_trecho_var = tk.StringVar(value="")
        ttk.Label(aba, textvariable=self.previa_trecho_var).pack(
            anchor="w", padx=8, pady=(0, 8))
        self._previa_pasta: Any = None

    def _previa_do_selecionado(self) -> None:
        resultado = self._selecionado(silencioso=True)
        if resultado is None:
            messagebox.showinfo("Prévia", "Selecione um resultado na aba Baixar.")
            return
        self.previa_url_var.set(resultado.url)
        self._ao_conferir()

    def _url_da_previa(self) -> str:
        url = self.previa_url_var.get().strip()
        if not url:
            selecionado = self._selecionado(silencioso=True)
            url = getattr(selecionado, "url", "") if selecionado else ""
        if not url:
            messagebox.showwarning("Prévia", "Informe a URL ou selecione um resultado.")
        return url

    def _ao_conferir(self) -> None:
        url = self._url_da_previa()
        if not url:
            return
        self.previa_info_var.set("Conferindo com o yt-dlp (sem baixar mídia)...")
        self.previa_alerta_var.set("")
        self._definir_status("Conferindo o vídeo...")

        def concluir(dados: Any) -> None:
            duracao = getattr(dados, "duracao", None)
            minutos = f"{duracao // 60}:{duracao % 60:02}" if duracao else "desconhecida"
            canal = getattr(dados, "canal", "") or "(canal não informado)"
            titulo = getattr(dados, "titulo", "") or "(sem título)"
            extras = []
            if getattr(dados, "ao_vivo", False):
                extras.append("AO VIVO agora")
            if getattr(dados, "idade_restrita", False):
                extras.append("restrição de idade (precisa de cookies)")
            if not getattr(dados, "tem_audio", True):
                extras.append("sem faixa de áudio: não dá para extrair MP3")
            self.previa_info_var.set(
                f"{titulo}\nCanal: {canal} | Duração: {minutos}"
                + ("\n" + " | ".join(extras) if extras else ""))
            analise = getattr(dados, "analise", None)
            if analise is not None and getattr(analise, "alerta", False):
                self.previa_alerta_var.set(
                    "ATENÇÃO — pode não ser a versão de estúdio: "
                    + analise.resumo())
            else:
                self.previa_alerta_var.set(
                    "Sem indício de show/ao vivo pelo título, canal ou duração.")
            self._definir_status("Vídeo conferido.")

        self._executar(lambda: self.controlador.inspecionar(url), concluir)

    def _ao_ouvir_trecho(self) -> None:
        url = self._url_da_previa()
        if not url:
            return
        try:
            segundos = int(float(self.previa_segundos_var.get() or 20))
        except (TypeError, ValueError):
            segundos = 20
        self._ao_parar_previa()  # nunca acumula trechos antigos
        self.previa_trecho_var.set(f"Baixando {segundos}s de amostra...")
        self._definir_status("Preparando prévia...")

        def concluir(resultado: Any) -> None:
            arquivo, pasta = resultado
            self._previa_pasta = pasta
            self.previa_trecho_var.set(f"Trecho em {arquivo} (temporário)")
            self._definir_status("Tocando prévia no player do sistema.")
            self._registrar(f"Prévia de {segundos}s: {Path(arquivo).name}")
            self._abrir_arquivo(arquivo)

        self._executar(lambda: self.controlador.ouvir_trecho(url, segundos), concluir)

    def _ao_parar_previa(self) -> None:
        if self._previa_pasta:
            self.controlador.descartar_previa(self._previa_pasta)
            self._previa_pasta = None
            self.previa_trecho_var.set("Trecho apagado.")

    def _ao_identificar_ia(self) -> None:
        """Identifica título/artista/álbum/ano/gênero/faixa (6 campos)."""
        url = self._url_da_previa()
        if not url:
            return
        texto = self.previa_info_var.get().strip()
        consulta = texto.splitlines()[0] if texto else url
        canal = ""
        for linha in texto.splitlines():
            if linha.startswith("Canal:"):
                canal = linha.split("|")[0].replace("Canal:", "").strip()
                break
        self.ia_resultado_var.set("Consultando a IA de identificação...")

        def concluir(identificacao: Any) -> None:
            from identificacao_ia import IdentificadorIA

            if identificacao is None:
                erro = ""
                try:
                    erro = IdentificadorIA(config=self.controlador.config).ultimo_erro
                except Exception:
                    pass
                self.ia_resultado_var.set(
                    "Sem dados musicais. " + (erro or
                    "Configure a chave em Configurações (api.txt) para a IA "
                    "preencher álbum, ano, gênero e faixa."))
                return
            linhas = [f"{rotulo}: {valor}"
                      for rotulo, valor in identificacao.como_linhas()]
            self.ia_resultado_var.set("\n".join(linhas))
            self._registrar("IA: dados musicais de \"" + consulta + "\".")

        self._executar(
            lambda: self.controlador.identificar_com_ia(consulta, canal),
            concluir)

    def _ao_baixar_previa(self) -> None:
        url = self._url_da_previa()
        if not url:
            return
        selecionado = self._selecionado(silencioso=True)
        contexto = selecionado if getattr(selecionado, "url", "") == url else None
        self._baixar(url, self.formato_var.get(), contexto=contexto)

    def _abrir_arquivo(self, caminho: Path) -> None:
        """Abre o arquivo no aplicativo padrão do sistema (player de áudio)."""
        caminho = Path(caminho)
        try:
            if os.name == "nt":
                os.startfile(str(caminho))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                os.system(f'open "{caminho}"')
            else:
                os.system(f'xdg-open "{caminho}" >/dev/null 2>&1 &')
        except Exception as erro:
            messagebox.showerror("Prévia", f"Não foi possível abrir o trecho: {erro}")

    # -- chave de IA por arquivo --------------------------------------------
    def _atualizar_status_chave(self) -> None:
        try:
            info = self.controlador.status_chave()
        except Exception as erro:
            self.chave_status_var.set(f"Erro ao verificar a chave: {erro}")
            return
        if not info.configurada:
            self.chave_status_var.set(
                "Nenhuma chave configurada — a identificação usa só as APIs "
                "públicas (iTunes/Deezer/MusicBrainz), sem gênero por IA.")
            self.chave_botao_var.set("Selecionar arquivo da chave...")
            return
        self.chave_botao_var.set("Substituir arquivo da chave...")
        onde = f" — {info.caminho}" if info.caminho else ""
        self.chave_status_var.set(
            f"Configurada: {info.mascarada} (provedor: {info.provedor})"
            f"{onde}. Clique em \"Testar chave\" para confirmar que funciona.")

    def _ao_importar_chave(self) -> None:
        from api_ia import ErroChave

        caminho = filedialog.askopenfilename(
            title="Selecione o arquivo com a chave de API",
            filetypes=(("Texto", "*.txt *.env"), ("Todos", "*.*")))
        if not caminho:
            return
        try:
            info = self.controlador.importar_chave(caminho)
        except ErroChave as erro:
            messagebox.showerror("Chave de IA", str(erro))
            self._atualizar_status_chave()
            return
        self._atualizar_status_chave()
        renomeado = ""
        if getattr(info, "renomeado", False):
            renomeado = (f"\n\nO arquivo {info.nome_original} foi renomeado "
                         "para api.txt na cópia gerenciada.")
        self._registrar(
            f"Chave de IA importada ({info.provedor}, {info.mascarada}).")
        # Valida de verdade na hora: formato bom não garante chave ativa.
        ok, mensagem = self.controlador.testar_chave()
        if ok:
            messagebox.showinfo(
                "Chave de IA",
                f"Chave importada de {Path(caminho).name} e validada.\n\n"
                f"{mensagem}{renomeado}")
        else:
            messagebox.showwarning(
                "Chave de IA",
                f"Chave importada de {Path(caminho).name}, mas a API recusou:"
                f"\n\n{mensagem}{renomeado}")
        self._registrar(f"Teste da chave: {'OK' if ok else 'falhou'}.")

    def _ao_testar_chave(self) -> None:
        self.chave_status_var.set("Testando a chave com a API...")
        self._executar(
            self.controlador.testar_chave,
            lambda resultado: self._mostrar_resultado_chave(resultado))

    def _mostrar_resultado_chave(self, resultado: Any) -> None:
        ok, mensagem = resultado
        self._atualizar_status_chave()
        if ok:
            self._registrar(f"Chave de IA: {mensagem}")
            messagebox.showinfo("Chave de IA", mensagem)
        else:
            self._registrar(f"[ERRO] Chave de IA: {mensagem}")
            messagebox.showerror("Chave de IA", mensagem)

    def _ao_remover_chave(self) -> None:
        if not messagebox.askyesno(
                "Chave de IA",
                "Remover a chave guardada? A identificação volta a usar apenas "
                "as APIs públicas."):
            return
        try:
            self.controlador.remover_chave()
        except Exception as erro:
            messagebox.showerror("Chave de IA", str(erro))
            return
        self._atualizar_status_chave()
        self._registrar("Chave de IA removida.")

    def _ao_previas_selecionado(self) -> None:
        """Leva o resultado selecionado para a aba Prévia e confere os dados."""
        resultado = self._selecionado(silencioso=True)
        if resultado is None:
            messagebox.showinfo("Prévia", "Selecione um resultado na lista.")
            return
        self.previa_url_var.set(resultado.url)
        try:
            self._abas.select(self.aba_previa)  # type: ignore[attr-defined]
        except Exception:
            pass
        self._ao_conferir()

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

        # Chave por arquivo (api.txt) — mesmo padrão do cookies.txt -----------
        chave_arquivo = ttk.LabelFrame(
            quadro, text="CONFIGURAÇÕES — CHAVE DE IA POR ARQUIVO (api.txt)")
        chave_arquivo.pack(fill="x", padx=8, pady=4)
        ttk.Label(chave_arquivo, text=(
            "Escolha o arquivo com a sua chave de API (pode ter qualquer nome: "
            "api.txt, chave.txt, anotacao.txt). O conteúdo pode ser a chave "
            "sozinha (sk-...) ou uma linha como api_key=sk-.... O programa "
            "valida, guarda uma cópia em .baixador\\api.txt (fora do Git, "
            "permissão restrita) e renomeia a cópia para api.txt. A chave nunca "
            "aparece em log nem na tela."), wraplength=900,
            justify="left").pack(anchor="w", padx=6, pady=6)
        self.chave_status_var = tk.StringVar()
        ttk.Label(chave_arquivo, textvariable=self.chave_status_var).pack(
            anchor="w", padx=6)
        botoes_chave = ttk.Frame(chave_arquivo)
        botoes_chave.pack(fill="x", padx=6, pady=6)
        self.chave_botao_var = tk.StringVar(value="Selecionar arquivo da chave...")
        ttk.Button(botoes_chave, textvariable=self.chave_botao_var,
                   command=self._ao_importar_chave).pack(side="left")
        ttk.Button(botoes_chave, text="Testar chave",
                   command=self._ao_testar_chave).pack(side="left", padx=6)
        ttk.Button(botoes_chave, text="Remover",
                   command=self._ao_remover_chave).pack(side="left")
        self._atualizar_status_chave()

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

        manutencao = ttk.LabelFrame(
            quadro, text="MANUTENÇÃO — atualizar o yt-dlp (quando parar de baixar)")
        manutencao.pack(fill="x", padx=8, pady=4)
        self.versao_ytdlp_var = tk.StringVar(
            value=f"Versão em uso: {self._texto_versao_ytdlp()}")
        ttk.Label(manutencao, textvariable=self.versao_ytdlp_var,
                  wraplength=820, justify="left").grid(
            row=0, column=0, columnspan=3, sticky="w", padx=6, pady=(6, 2))
        ttk.Button(manutencao, text="Atualizar o yt-dlp agora",
                   command=self._ao_atualizar_ytdlp).grid(
            row=1, column=0, sticky="w", padx=6, pady=(0, 6))
        self.atualizacao_status_var = tk.StringVar(
            value="Se o YouTube mudar e os downloads falharem, clique no botão "
                  "acima (precisa de internet).")
        ttk.Label(manutencao, textvariable=self.atualizacao_status_var,
                  wraplength=820, justify="left").grid(
            row=2, column=0, columnspan=3, sticky="w", padx=6, pady=(0, 8))

        ttk.Button(quadro, text="Salvar configurações",
                   command=self._ao_salvar_config).pack(padx=8, pady=10, anchor="w")

    def _texto_versao_ytdlp(self) -> str:
        try:
            versao = self.controlador.versao_ytdlp()
        except Exception:
            versao = ""
        return versao or "não identificada"

    def _ao_atualizar_ytdlp(self) -> None:
        if not messagebox.askyesno(
                "Atualizar o yt-dlp",
                "Atualizar o yt-dlp agora? É preciso internet e o programa "
                "continua funcionando se a atualização falhar."):
            return
        self.atualizacao_status_var.set("Atualizando (pode levar um minuto)...")
        self._definir_status("Atualizando o yt-dlp...")

        def concluir(resultado: Any) -> None:
            self.atualizacao_status_var.set(resultado.mensagem)
            self.versao_ytdlp_var.set(
                f"Versão em uso: {resultado.versao_depois or 'não identificada'}")
            self._definir_status(resultado.mensagem)
            self._registrar(resultado.mensagem)
            if not resultado.ok:
                messagebox.showwarning("Atualizar o yt-dlp", resultado.mensagem)

        self._executar(self.controlador.atualizar_ytdlp, concluir,
                       lambda erro: self._mostrar_erro(erro))

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
            if getattr(info, "expirados_do_youtube", 0):
                texto = (f"ATENÇÃO: {info.expirados_do_youtube} de "
                         f"{info.do_youtube} cookie(s) do YouTube já venceram. "
                         "Exporte o cookies.txt de novo se o YouTube pedir login. ")
            else:
                texto += " — pronto para usar."
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
        vencidos = getattr(info, "expirados_do_youtube", 0)
        if vencidos and vencidos >= info.do_youtube:
            messagebox.showwarning(
                "Cookies",
                "cookies.txt importado, mas TODOS os cookies do YouTube já "
                "venceram — o yt-dlp vai ignorá-los.\n\nExporte o arquivo de "
                "novo pelo navegador (logado no YouTube) e importe outra vez.")
        elif vencidos:
            messagebox.showwarning(
                "Cookies",
                f"cookies.txt importado. Atenção: {vencidos} cookie(s) do "
                "YouTube já venceram; se o YouTube pedir login, exporte de novo.")
        else:
            messagebox.showinfo(
                "Cookies",
                "cookies.txt importado e válido. Ele já está sendo usado "
                "automaticamente pelo yt-dlp.")

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
