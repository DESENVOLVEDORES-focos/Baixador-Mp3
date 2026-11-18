"""Controlador da Central Musical — toda a lógica, sem Tkinter.

A interface (``central_app.py``) só desenha e chama estes métodos. Assim o
comportamento pode ser testado sem tela, exatamente como já era feito com
``ControladorInterface``.

Serviços reunidos aqui:

- pesquisa (vídeos/playlists/canais) e abertura de playlist;
- seleção acumulativa persistente (``selecao.Selecao``);
- downloads controláveis (``gerenciador.GerenciadorDownloads``);
- biblioteca SQLite (``biblioteca.Biblioteca``): músicas, playlists, favoritos;
- cobertura musical: metadados e capas em lote (``colecoes.py``);
- reprodutor (``reprodutor.Reprodutor``);
- configurações/cookies/chave de IA (reaproveita ``ControladorInterface``).
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any, Callable, Iterable

from biblioteca import Biblioteca, Musica
from capas import CandidatoCapa, GerenciadorCapas
from central_servicos import ServicosBase
from colecoes import (
    ResultadoCobertura, completar_metadados, incorporar_capa, incorporar_capas,
)
from fila import FilaDownloads
from gerenciador import GerenciadorDownloads, ItemDownload
from metadados import InfoMusica, aplicar_metadados
from playlist import Playlist, listar as listar_playlist
from preferencias import Preferencias, salvar
from reprodutor import Faixa, Reprodutor
from selecao import ItemSelecao, Selecao

log = logging.getLogger("baixador.central")


class Central(ServicosBase):
    """Fachada única usada pela interface."""

    def __init__(self, configuracoes: Any = None,
                 preferencias: Preferencias | None = None):
        super().__init__(configuracoes, preferencias)
        self.biblioteca = Biblioteca(self.config)
        self.selecao = Selecao(self.config)
        self.reprodutor = Reprodutor(self.config)
        self.reprodutor.volume = int(getattr(self.preferencias, "volume_reprodutor", 80))
        # Volume, repetição e última faixa sobrevivem ao fechamento.
        try:
            self.reprodutor.usar_arquivo_estado(self.config.dados / "player.json")
        except Exception:
            pass
        self.gerenciador = GerenciadorDownloads(
            self.aplicacao,
            simultaneos=getattr(self.preferencias, "downloads_simultaneos", 2),
            ao_mudar=self._ao_mudar_download,
            ao_concluir=self._ao_concluir_download,
        )
        self.fila_nucleo = FilaDownloads(self.config)
        # A fila sobrevive ao fechamento do programa (retomada no dia seguinte).
        self.gerenciador.usar_arquivo(self.config.dados / "fila.json")
        self.fila_recuperada: dict[str, int] = {}
        try:
            self.fila_recuperada = self.gerenciador.carregar()
        except Exception as erro:  # fila ilegível nunca impede abrir o app
            log.info("Fila anterior não pôde ser lida: %s", erro)
            self.fila_recuperada = {}
        from atualizacao import localizar_ffplay as _localizar

        # Guardado para a tela de configurações dizer a verdade sobre o áudio.
        self.ffplay = _localizar(self.config)
        self._ao_mudar_download_cb: Callable[[ItemDownload], None] | None = None
        self._ao_concluir_download_cb: Callable[[ItemDownload], None] | None = None
        self._lock = threading.RLock()

    # -- callbacks da interface --------------------------------------------
    def definir_callbacks(self, *, download_mudou=None, download_concluiu=None,
                          ) -> None:
        self._ao_mudar_download_cb = download_mudou
        self._ao_concluir_download_cb = download_concluiu

    def _ao_mudar_download(self, item: ItemDownload) -> None:
        if callable(self._ao_mudar_download_cb):
            try:
                self._ao_mudar_download_cb(item)
            except Exception:
                pass

    def _ao_concluir_download(self, item: ItemDownload) -> None:
        """Música pronta é verificada, normalizada (se pedido) e indexada.

        A verificação é o que impede a biblioteca de receber arquivo truncado;
        a normalização é opcional e só acontece se o usuário ligou nas
        configurações. Ambas usam o FFmpeg do programa e nunca derrubam a fila.
        """
        if item.estado == "concluido" and item.caminho:
            self._pos_processar(item)
            try:
                self.biblioteca.adicionar(item.caminho, origem_url=item.url)
            except Exception as erro:
                log.info("Não indexou %s: %s", item.caminho, erro)
        if callable(self._ao_concluir_download_cb):
            try:
                self._ao_concluir_download_cb(item)
            except Exception:
                pass

    def _pos_processar(self, item: ItemDownload) -> None:
        """Verifica o MP3 e aplica a normalização de volume, se configurada."""
        from audio import normalizar, verificar

        caminho = Path(item.caminho)
        try:
            ffmpeg = self.config.caminho_ffmpeg()
        except Exception:
            ffmpeg = None
        if not ffmpeg:
            log.info("Sem FFmpeg: %s fica sem verificação", caminho.name)
            return
        if getattr(self.config, "verificar_audio", True):
            resultado = verificar(caminho, ffmpeg=ffmpeg)
            if not resultado.ok:
                log.info("Verificação de %s: %s", caminho.name, resultado.mensagem)
                item.mensagem = f"{item.mensagem} ({resultado.mensagem})"
            else:
                item.mensagem = f"{item.mensagem} {resultado.mensagem}"
        if getattr(self.config, "normalizar_volume", False):
            resultado = normalizar(caminho, ffmpeg=ffmpeg)
            item.mensagem = f"{item.mensagem} {resultado.mensagem}".strip()
        if getattr(self.config, "replaygain", False):
            # Mede o volume com ebur128 e grava a tag (não altera o áudio).
            from audio import aplicar_replaygain

            try:
                ok, mensagem = aplicar_replaygain(caminho, ffmpeg=ffmpeg)
            except Exception as erro:
                ok, mensagem = False, f"ReplayGain não aplicado: {erro}"
            if not ok:
                log.info("ReplayGain de %s: %s", caminho.name, mensagem)
            item.mensagem = f"{item.mensagem} {mensagem}".strip()

    # -- pesquisa -----------------------------------------------------------
    def pesquisar(self, consulta: str, tipo: str = "tudo") -> list[Any]:
        prefs = self.preferencias
        resultados = self.aplicacao.pesquisador.pesquisar(
            consulta, prefs.limite_pesquisa, tipo,
            remover_equivalentes=bool(
                getattr(prefs, "pesquisa_deduplicar", True)),
            esconder_compilados=bool(
                getattr(prefs, "pesquisa_sem_compilados", False)),
            exigir_duracao=bool(
                getattr(prefs, "pesquisa_so_com_duracao", False)))
        try:
            self.ultima_contagem_pesquisa = dict(getattr(
                self.aplicacao.pesquisador, "ultima_contagem", {}) or {})
        except Exception:
            self.ultima_contagem_pesquisa = {}
        try:
            self.biblioteca.registrar_pesquisa(consulta, tipo)
        except Exception:
            pass
        return resultados

    def pesquisas_recentes(self, limite: int = 12) -> list[dict[str, Any]]:
        return self.biblioteca.pesquisas_recentes(limite)

    def listar_playlist(self, url: str, limite: int = 200) -> Playlist:
        return listar_playlist(url, limite=limite, config=self.config)

    # -- regras de seleção (teto de duração / ao vivo) ----------------------
    def avaliar_itens(self, itens: Iterable[Any]) -> list[tuple[Any, Any]]:
        """Aplica o teto de duração e o filtro de ao vivo a uma lista de itens."""
        from limites import filtrar

        return filtrar(
            itens,
            duracao_maxima_min=int(getattr(self.preferencias,
                                           "duracao_maxima_min", 0) or 0),
            filtrar_ao_vivo=bool(getattr(self.preferencias,
                                        "filtrar_ao_vivo", True)))

    def listar_mais_playlist(self, playlist: Playlist,
                             quantidade: int = 200) -> Playlist:
        """Próxima janela de uma playlist/canal longo (botão "Listar mais")."""
        from playlist import listar_mais

        return listar_mais(playlist, quantidade, config=self.config)

    # -- seleção ------------------------------------------------------------
    def adicionar_a_selecao(self, itens: Iterable[Any], *,
                            formato: str | None = None,
                            origem: str = "") -> tuple[int, int]:
        """Aceita resultados de pesquisa/playlist e monta os itens da cesta."""
        formato = formato or self.preferencias.formato_padrao
        convertidos: list[ItemSelecao] = []
        for bruto in itens:
            if isinstance(bruto, ItemSelecao):
                # Itens já montados (ex.: playlist aberta) herdam o rótulo de
                # origem quando não têm um — é o que agrupa a cesta na tela.
                if origem and not bruto.origem:
                    bruto.origem = origem
                if formato and not bruto.formato:
                    bruto.formato = formato
                convertidos.append(bruto)
                continue
            url = str(getattr(bruto, "url", "") or "")
            if not url:
                continue
            convertidos.append(ItemSelecao(
                url=url,
                titulo=str(getattr(bruto, "titulo", "") or getattr(bruto, "titulo_exibicao", "")),
                canal=str(getattr(bruto, "canal", "") or ""),
                duracao=getattr(bruto, "duracao", None),
                formato=formato,
                thumbnail=str(getattr(bruto, "thumbnail", "") or ""),
                origem=origem or self._origem_padrao(bruto),
            ))
        return self.selecao.adicionar_varios(convertidos)

    def _origem_padrao(self, bruto: Any) -> str:
        """Rótulo do grupo na cesta: playlist, canal ou pesquisa."""
        tipo = str(getattr(bruto, "tipo", "") or "")
        if tipo == "playlist":
            return f"Playlist: {getattr(bruto, 'titulo', '')}"
        canal = str(getattr(bruto, "canal", "") or "").strip()
        return canal or "Pesquisa"

    def remover_da_selecao(self, urls: Iterable[str]) -> int:
        return self.selecao.remover(urls)

    def limpar_selecao(self) -> int:
        return self.selecao.limpar()

    def reordenar_selecao(self, origem: int, destino: int) -> bool:
        return self.selecao.reordenar(origem, destino)

    def selecao_para_downloads(self) -> int:
        """Manda a cesta para a página de downloads (e esvazia a cesta)."""
        itens = self.selecao.listar()
        if not itens:
            return 0
        por_formato: dict[str, list[str]] = {}
        for item in itens:
            por_formato.setdefault(item.formato, []).append(item.url)
        adicionados = 0
        for formato, urls in por_formato.items():
            for url in urls:
                info = next(i for i in itens if i.url == url and i.formato == formato)
                self.gerenciador.adicionar(
                    url, formato, titulo=info.titulo, canal=info.canal,
                    duracao=info.duracao, thumbnail=info.thumbnail,
                    origem=info.origem)
                adicionados += 1
        self.selecao.limpar()
        return adicionados

    # -- downloads ----------------------------------------------------------
    def retomar_fila_salva(self) -> int:
        """Continua a fila que ficou pendente quando o programa fechou.

        ``retomar()`` já trata o caso real: itens ``pausado`` (incluindo os
        interrompidos ao fechar) voltam para ``aguardando`` e a thread recomeça.
        """
        return self.gerenciador.retomar()

    def fila_salva(self) -> dict[str, int]:
        """Resumo do que foi recuperado do ``fila.json`` na abertura."""
        return dict(self.fila_recuperada)

    def fechar(self) -> None:
        """Grava a fila antes de a janela sumir (chamado ao fechar o app)."""
        try:
            self.gerenciador.salvar(forcar=True)
        except Exception as erro:
            log.info("Não salvou a fila ao fechar: %s", erro)
        try:
            self.reprodutor.salvar_estado()
            self.reprodutor.parar(silencioso=True)
        except Exception:
            pass

    def iniciar_downloads(self) -> int:
        """Começa a baixar. Se a cesta ainda tem itens, ela vira a fila antes.

        É isso que os botões "Baixar agora" e "▶ Iniciar todos" fazem: o
        usuário não precisa lembrar de passar pela fila em duas etapas.
        """
        enviados = self.selecao_para_downloads()
        quantidade = self.gerenciador.iniciar()
        log.info("Downloads iniciados: %s da cesta, %s na fila", enviados,
                 quantidade)
        return quantidade + enviados

    def pausar_downloads(self) -> int:
        return self.gerenciador.pausar()

    def retomar_downloads(self) -> int:
        return self.gerenciador.retomar()

    def cancelar_download(self, item_id: int) -> bool:
        return self.gerenciador.cancelar(item_id)

    def cancelar_todos(self) -> int:
        return self.gerenciador.cancelar_tudo()

    def repetir_falhas(self) -> int:
        return self.gerenciador.repetir_falhas()

    def remover_finalizados(self) -> int:
        return self.gerenciador.remover_finalizados()

    def downloads(self, estado: str | None = None) -> list[ItemDownload]:
        return self.gerenciador.listar(estado=estado)

    def resumo_downloads(self) -> dict[str, int]:
        return self.gerenciador.resumo()

    # -- biblioteca ---------------------------------------------------------
    def sincronizar_biblioteca(self, *, remover_ausentes: bool = False) -> dict[str, int]:
        return self.biblioteca.sincronizar(remover_ausentes=remover_ausentes)

    def musicas(self, **filtros: Any) -> list[Musica]:
        return self.biblioteca.listar(**filtros)

    def estatisticas(self) -> dict[str, Any]:
        return self.biblioteca.estatisticas()

    def artistas(self) -> list[dict[str, Any]]:
        return self.biblioteca.artistas()

    def albuns(self) -> list[dict[str, Any]]:
        return self.biblioteca.albuns()

    def generos(self) -> list[dict[str, Any]]:
        return self.biblioteca.generos()

    def duplicatas(self) -> list[list[Musica]]:
        return self.biblioteca.duplicatas()

    def recentes(self, limite: int = 10) -> list[Musica]:
        return self.biblioteca.recentes(limite)

    def sem_capa(self) -> list[Musica]:
        return self.biblioteca.sem_capa()

    def favoritar_musica(self, musica_id: int) -> bool:
        return self.biblioteca.alternar_favorito(musica_id)

    def favoritar(self, tipo: str, chave: str) -> bool:
        if self.biblioteca.eh_favorito(tipo, chave):
            return self.biblioteca.desfavoritar(tipo, chave)
        return self.biblioteca.favoritar(tipo, chave)

    def favoritos(self, tipo: str | None = None) -> list[dict[str, Any]]:
        return self.biblioteca.favoritos(tipo)

    def musicas_favoritas(self) -> list[Musica]:
        return self.biblioteca.musicas_favoritas()

    def excluir_musica(self, musica_id: int, *, apagar_arquivo: bool = True) -> bool:
        return self.biblioteca.remover(musica_id, apagar_arquivo=apagar_arquivo)

    # -- playlists locais ---------------------------------------------------
    def criar_playlist(self, nome: str) -> int:
        return self.biblioteca.criar_playlist(nome)

    def renomear_playlist(self, playlist_id: int, nome: str) -> bool:
        return self.biblioteca.renomear_playlist(playlist_id, nome)

    def excluir_playlist(self, playlist_id: int) -> bool:
        return self.biblioteca.excluir_playlist(playlist_id)

    def playlists(self) -> list[dict[str, Any]]:
        return self.biblioteca.listar_playlists()

    def adicionar_a_playlist(self, playlist_id: int, musica_ids: Iterable[int]) -> int:
        return self.biblioteca.adicionar_a_playlist(playlist_id, musica_ids)

    def remover_da_playlist(self, playlist_id: int, musica_id: int) -> bool:
        return self.biblioteca.remover_da_playlist(playlist_id, musica_id)

    def musicas_da_playlist(self, playlist_id: int) -> list[Musica]:
        return self.biblioteca.musicas_da_playlist(playlist_id)

    def reordenar_playlist(self, playlist_id: int, ordem: Iterable[int]) -> None:
        self.biblioteca.reordenar_playlist(playlist_id, ordem)

    # -- metadados e capas --------------------------------------------------
    def completar_metadados(self, musicas: Iterable[Musica] | None = None,
                            ao_arquivo=None) -> list[ResultadoCobertura]:
        return completar_metadados(self.biblioteca, musicas, ao_arquivo=ao_arquivo)

    def buscar_capas(self, musicas: Iterable[Musica] | None = None,
                     ao_arquivo=None) -> list[ResultadoCobertura]:
        return incorporar_capas(self.biblioteca, musicas, ao_arquivo=ao_arquivo)

    def candidatos_de_capa(self, musica: Musica) -> list[CandidatoCapa]:
        info = InfoMusica(
            titulo=musica.titulo or musica.arquivo.stem,
            artista=musica.artista, album=musica.album, ano=musica.ano)
        return GerenciadorCapas().candidatos(info, musica.origem_url or None)

    def incorporar_capa(self, musica: Musica, imagem: bytes | None = None,
                        ) -> ResultadoCobertura:
        return incorporar_capa(self.biblioteca, musica, imagem=imagem)

    def capa_candidatos(self, musica: Musica,
                        limite: int = 4) -> list[Any]:
        """Capas encontradas para a música, **sem gravar nada** (prévia)."""
        from capas import GerenciadorCapas, baixar_candidatos

        if not musica.artista and not musica.album:
            return []
        info = InfoMusica(titulo=musica.titulo or "", artista=musica.artista or "",
                          album=musica.album or "", ano=musica.ano or "")
        return baixar_candidatos(GerenciadorCapas(), info,
                                 musica.origem_url or None, limite=limite)

    def salvar_metadados(self, musica_id: int, **campos: Any) -> Musica | None:
        """Grava as tags no arquivo **e** no banco (editor manual)."""
        musica = self.biblioteca.obter(musica_id)
        if musica is None:
            return None
        info = InfoMusica(
            titulo=str(campos.get("titulo", musica.titulo) or ""),
            artista=str(campos.get("artista", musica.artista) or ""),
            album=str(campos.get("album", musica.album) or ""),
            ano=str(campos.get("ano", musica.ano) or ""),
            genero=str(campos.get("genero", musica.genero) or ""),
            faixa=str(campos.get("faixa", musica.faixa) or ""),
        )
        if musica.arquivo.is_file():
            aplicar_metadados(musica.arquivo, info)
        dados = {"titulo": info.titulo, "artista": info.artista,
                 "album": info.album, "ano": info.ano, "genero": info.genero,
                 "faixa": info.faixa}
        return self.biblioteca.atualizar(musica_id, **dados)

    # -- reprodutor ---------------------------------------------------------
    def tocar_musica(self, musica: Musica, *, fila: Iterable[Musica] | None = None,
                     ) -> bool:
        lista = list(fila) if fila is not None else [musica]
        faixas = [self._faixa(m) for m in lista]
        indice = next((i for i, m in enumerate(lista) if m.id == musica.id), 0)
        self.reprodutor.definir_fila(faixas, indice=indice)
        return self.reprodutor.tocar()

    def tocar_playlist(self, playlist_id: int) -> bool:
        musicas = self.musicas_da_playlist(playlist_id)
        if not musicas:
            return False
        self.reprodutor.definir_fila([self._faixa(m) for m in musicas])
        return self.reprodutor.tocar(0)

    def tocar_fila(self, musicas: Iterable[Musica], indice: int = 0) -> bool:
        faixas = [self._faixa(m) for m in musicas]
        if not faixas:
            return False
        self.reprodutor.definir_fila(faixas, indice=indice)
        return self.reprodutor.tocar()

    @staticmethod
    def _faixa(musica: Musica) -> Faixa:
        return Faixa(caminho=musica.caminho, titulo=musica.titulo_exibicao,
                     artista=musica.artista, album=musica.album,
                     duracao=musica.duracao, tem_capa=musica.tem_capa,
                     musica_id=musica.id)

    def estado_reprodutor(self) -> dict[str, Any]:
        return self.reprodutor.estado()

    # -- configurações ------------------------------------------------------
    def aplicar_preferencias(self, novas: Preferencias) -> None:
        """Salva e reaplica sem reiniciar o programa."""
        novas.validar()
        salvar(novas, self._base)
        self.preferencias = novas
        self.config = self.derivar(novas)
        self.aplicacao.config = self.config
        self.aplicacao.downloader.config = self.config
        self.aplicacao.fila.config = self.config
        self.aplicacao.historico.config = self.config
        self.gerenciador.simultaneos = max(
            1, min(4, int(getattr(novas, "downloads_simultaneos", 2))))
        self.reprodutor.volume = int(getattr(novas, "volume_reprodutor", 80))
        self._aplicar_ambiente(novas)

    def salvar_preferencias(self) -> None:
        """Grava as preferências atuais sem reaplicar nada (usado pela tela)."""
        try:
            self.preferencias.validar()
            salvar(self.preferencias, self._base)
        except Exception as erro:
            log.info("Não foi possível salvar as preferências: %s", erro)

    def salvar_fila_nucleo(self, pares: Iterable[tuple[str, str]]) -> int:
        """Guarda os downloads no arquivo da fila do núcleo (retomada após fechar)."""
        gravados = 0
        for url, formato in pares:
            try:
                self.fila_nucleo.adicionar(url, formato)  # type: ignore[arg-type]
                gravados += 1
            except Exception as erro:
                log.info("Fila do núcleo recusou %s: %s", url, erro)
        return gravados


__all__ = ["Central", "Musica", "ItemSelecao", "ResultadoCobertura"]
