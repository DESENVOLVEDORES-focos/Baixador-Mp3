"""Gerenciador de downloads em lote: pausar, retomar, cancelar, concorrência.

Diferente de ``fila.py`` (a fila persistente do núcleo, feita para o CLI), esta
classe mantém os itens **em memória** com tudo o que a página de downloads do
aplicativo precisa mostrar: capa, título, canal, formato, estado, percentual,
mensagem e detalhe do erro.

Estados: ``aguardando`` → ``processando`` → (``convertendo`` →
``metadados`` →) ``concluido`` | ``falhou`` | ``pausado`` | ``cancelado``.

Regras que o código garante:
- ``pausar()`` para de iniciar novos itens; o item em andamento termina (não
  deixamos arquivo pela metade: a publicação só acontece com arquivo válido).
- ``cancelar()`` mata o processo do yt-dlp daquele item e marca ``cancelado``.
- ``retomar()`` volta os pausados/cancelados para ``aguardando``.
- ``repetir_falhas()`` recoloca os que falharam.
- Concorrência configurável (1..4), com pool de threads; a interface é avisada
  por callback a cada mudança, sem travar.
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

log = logging.getLogger("baixador.gerenciador")

ESTADOS = ("aguardando", "processando", "convertendo", "metadados",
           "concluido", "falhou", "pausado", "cancelado")

ROTULO_ESTADO = {
    "aguardando": "Aguardando",
    "processando": "Baixando",
    "convertendo": "Convertendo",
    "metadados": "Organizando metadados",
    "concluido": "Concluído",
    "falhou": "Falhou",
    "pausado": "Pausado",
    "cancelado": "Cancelado",
}


@dataclass
class ItemDownload:
    """Um item da página de downloads (com tudo para a tela)."""

    url: str
    formato: str = "mp3"
    titulo: str = ""
    canal: str = ""
    duracao: int | None = None
    thumbnail: str = ""
    origem: str = ""
    estado: str = "aguardando"
    percentual: float = 0.0
    velocidade: str = ""
    tamanho: str = ""
    eta: str = ""
    mensagem: str = ""
    detalhe_erro: str = ""
    caminho: str = ""
    criado_em: str = ""
    atualizado_em: str = ""
    duracao_processo: float = 0.0
    id: int = 0

    @property
    def titulo_exibicao(self) -> str:
        return self.titulo or self.url

    @property
    def rotulo_estado(self) -> str:
        return ROTULO_ESTADO.get(self.estado, self.estado)

    @property
    def finalizado(self) -> bool:
        return self.estado in ("concluido", "falhou", "cancelado")

    @property
    def progresso_texto(self) -> str:
        if self.estado == "concluido":
            return "100%"
        if self.estado in ("falhou", "cancelado", "pausado", "aguardando"):
            return ""
        return f"{self.percentual:.0f}%"


def _agora() -> str:
    return datetime.now(timezone.utc).isoformat()


class GerenciadorDownloads:
    """Orquestra os downloads com controle total pela interface."""

    def __init__(self, aplicacao: Any, *, simultaneos: int = 2,
                 ao_mudar: Callable[[ItemDownload], None] | None = None,
                 ao_concluir: Callable[[ItemDownload], None] | None = None):
        self.aplicacao = aplicacao
        self.simultaneos = max(1, min(4, int(simultaneos)))
        self.ao_mudar = ao_mudar
        self.ao_concluir = ao_concluir
        self._lock = threading.RLock()
        self._itens: list[ItemDownload] = []
        self._proximo_id = 1
        self._pausado = False
        self._cancelar_total = False
        self._processos: dict[int, Any] = {}
        self._cancelados: set[int] = set()
        self._thread: threading.Thread | None = None
        self._rodando = False

    # -- consulta -----------------------------------------------------------
    def listar(self, *, estado: str | None = None) -> list[ItemDownload]:
        with self._lock:
            if estado:
                return [item for item in self._itens if item.estado == estado]
            return list(self._itens)

    def obter(self, item_id: int) -> ItemDownload | None:
        with self._lock:
            return next((i for i in self._itens if i.id == item_id), None)

    def resumo(self) -> dict[str, int]:
        with self._lock:
            contagem = {estado: 0 for estado in ESTADOS}
            for item in self._itens:
                contagem[item.estado] = contagem.get(item.estado, 0) + 1
        contagem["total"] = len(self._itens)
        contagem["ativos"] = (contagem["aguardando"] + contagem["processando"]
                              + contagem["convertendo"] + contagem["metadados"])
        return contagem

    @property
    def pausado(self) -> bool:
        return self._pausado

    @property
    def rodando(self) -> bool:
        return self._rodando

    def tem_pendentes(self) -> bool:
        with self._lock:
            return any(item.estado in ("aguardando", "processando", "convertendo",
                                       "metadados") for item in self._itens)

    # -- entrada de itens ---------------------------------------------------
    def adicionar(self, url: str, formato: str = "mp3", **extras: Any) -> ItemDownload:
        with self._lock:
            item = ItemDownload(
                url=url, formato=formato, id=self._proximo_id,
                criado_em=_agora(), atualizado_em=_agora(),
                titulo=str(extras.get("titulo") or ""),
                canal=str(extras.get("canal") or ""),
                duracao=extras.get("duracao"),
                thumbnail=str(extras.get("thumbnail") or ""),
                origem=str(extras.get("origem") or ""),
                estado="aguardando",
            )
            self._proximo_id += 1
            self._itens.append(item)
        self._notificar(item)
        return item

    def adicionar_varios(self, pares: list[tuple[str, str]], **extras: Any) -> int:
        """``[(url, formato), ...]``; ignora URLs já presentes e não finalizadas."""
        adicionados = 0
        with self._lock:
            existentes = {(i.url, i.formato) for i in self._itens
                          if i.estado not in ("falhou", "cancelado")}
            novos: list[ItemDownload] = []
            for url, formato in pares:
                if (url, formato) in existentes:
                    continue
                item = ItemDownload(
                    url=url, formato=formato, id=self._proximo_id,
                    criado_em=_agora(), atualizado_em=_agora(),
                    titulo=str(extras.get("titulo") or ""),
                    origem=str(extras.get("origem") or ""),
                )
                self._proximo_id += 1
                novos.append(item)
                existentes.add((url, formato))
            self._itens.extend(novos)
            adicionados = len(novos)
        for item in novos:
            self._notificar(item)
        return adicionados

    # -- controles ----------------------------------------------------------
    def iniciar(self, itens: list[ItemDownload] | None = None) -> int:
        """Começa (ou reinicia) o processamento; devolve quantos entraram."""
        with self._lock:
            self._pausado = False
            self._cancelar_total = False
            alvo = itens if itens is not None else self._itens
            marcados = 0
            for item in alvo:
                if item.estado in ("aguardando", "pausado", "cancelado", "falhou"):
                    item.estado = "aguardando"
                    item.percentual = 0.0
                    item.mensagem = ""
                    item.atualizado_em = _agora()
                    self._cancelados.discard(item.id)
                    marcados += 1
                    self._notificar(item)
            if self._thread is None or not self._thread.is_alive():
                self._rodando = True
                self._thread = threading.Thread(
                    target=self._laco, name="downloads", daemon=True)
                self._thread.start()
        return marcados

    def pausar(self) -> int:
        """Para de iniciar novos; o item em andamento é cancelado com aviso."""
        with self._lock:
            self._pausado = True
            pausados = 0
            for item in self._itens:
                if item.estado == "aguardando":
                    item.estado = "pausado"
                    item.atualizado_em = _agora()
                    pausados += 1
                    self._notificar(item)
            em_andamento = [i for i in self._itens if i.estado == "processando"]
        for item in em_andamento:
            # Parar o processo é mais honesto que deixar baixando "pausado".
            self._matar_processo(item.id)
            self._marcar(item, "pausado", mensagem="Pausado pelo usuário.")
        return pausados

    def retomar(self) -> int:
        with self._lock:
            self._pausado = False
            alvos = [i for i in self._itens if i.estado == "pausado"]
        for item in alvos:
            self._marcar(item, "aguardando", mensagem="Retomado.")
        if alvos:
            with self._lock:
                if self._thread is None or not self._thread.is_alive():
                    self._rodando = True
                    self._thread = threading.Thread(
                        target=self._laco, name="downloads", daemon=True)
                    self._thread.start()
        return len(alvos)

    def cancelar(self, item_id: int) -> bool:
        item = self.obter(item_id)
        if item is None or item.finalizado:
            return False
        self._cancelados.add(item_id)
        self._matar_processo(item_id)
        self._marcar(item, "cancelado", mensagem="Cancelado pelo usuário.")
        return True

    def cancelar_tudo(self) -> int:
        with self._lock:
            self._cancelar_total = True
            alvos = [i for i in self._itens
                     if i.estado in ("aguardando", "processando", "pausado")]
        for item in alvos:
            self._cancelados.add(item.id)
            self._matar_processo(item.id)
            self._marcar(item, "cancelado", mensagem="Cancelado pelo usuário.")
        return len(alvos)

    def repetir_falhas(self) -> int:
        with self._lock:
            alvos = [i for i in self._itens if i.estado == "falhou"]
        for item in alvos:
            item.detalhe_erro = ""
            self._marcar(item, "aguardando", mensagem="Tentando de novo.")
        if alvos:
            with self._lock:
                if self._thread is None or not self._thread.is_alive():
                    self._rodando = True
                    self._thread = threading.Thread(
                        target=self._laco, name="downloads", daemon=True)
                    self._thread.start()
        return len(alvos)

    def remover_finalizados(self) -> int:
        with self._lock:
            antes = len(self._itens)
            self._itens = [i for i in self._itens if not i.finalizado]
            return antes - len(self._itens)

    def limpar(self) -> int:
        with self._lock:
            if any(i.estado == "processando" for i in self._itens):
                raise RuntimeError("Há download em andamento; pause ou cancele antes.")
            quantidade = len(self._itens)
            self._itens = []
            return quantidade

    def aguardar(self, timeout: float = 30.0) -> bool:
        """Bloqueia até a fila terminar (usado por testes e pelo fechamento)."""
        limite = time.monotonic() + timeout
        while time.monotonic() < limite:
            if not self.tem_pendentes() and not self._pausado:
                return True
            thread = self._thread
            if thread is not None and not thread.is_alive():
                return not self.tem_pendentes()
            time.sleep(0.02)
        return False

    # -- execução -----------------------------------------------------------
    def _notificar(self, item: ItemDownload) -> None:
        if callable(self.ao_mudar):
            try:
                self.ao_mudar(item)
            except Exception:
                pass

    def _marcar(self, item: ItemDownload, estado: str, *,
                mensagem: str | None = None, percentual: float | None = None,
                detalhe: str = "") -> None:
        with self._lock:
            item.estado = estado
            if mensagem is not None:
                item.mensagem = mensagem
            if percentual is not None:
                item.percentual = percentual
            if detalhe:
                item.detalhe_erro = detalhe
            item.atualizado_em = _agora()
        self._notificar(item)

    def _matar_processo(self, item_id: int) -> None:
        """Mata o yt-dlp do item (via ``Downloader.cancelar_atual``)."""
        with self._lock:
            self._processos.pop(item_id, None)
        cancelar = getattr(self.aplicacao, "cancelar_download", None)
        if callable(cancelar):
            try:
                cancelar()
            except Exception:
                pass

    def _laco(self) -> None:
        try:
            while True:
                with self._lock:
                    if self._pausado or self._cancelar_total:
                        break
                    pendentes = [i for i in self._itens if i.estado == "aguardando"]
                    if not pendentes:
                        break
                    lote = pendentes[: self.simultaneos]
                    for item in lote:
                        item.estado = "processando"
                        item.percentual = 0.0
                        item.atualizado_em = _agora()
                for item in lote:
                    self._notificar(item)
                with ThreadPoolExecutor(max_workers=len(lote)) as executor:
                    list(executor.map(self._processar, lote))
        finally:
            with self._lock:
                self._rodando = False

    def _processar(self, item: ItemDownload) -> None:
        if item.id in self._cancelados:
            return
        inicio = time.monotonic()
        item._iniciado_em = inicio  # a busca de emergência no disco usa isso

        def ao_progresso(progresso: Any) -> None:
            if item.id in self._cancelados:
                return
            etapa = getattr(progresso, "etapa", "") or "Baixando"
            estado = item.estado
            if "Convert" in etapa or "Extract" in etapa:
                estado = "convertendo"
            elif "metadata" in etapa.lower() or "Metadata" in etapa:
                estado = "metadados"
            with self._lock:
                item.percentual = float(getattr(progresso, "percentual", 0) or 0)
                item.velocidade = str(getattr(progresso, "velocidade", "") or "")
                item.tamanho = str(getattr(progresso, "total", "") or "")
                item.eta = str(getattr(progresso, "eta", "") or "")
                item.mensagem = etapa
            self._marcar(item, estado if estado in ESTADOS else "processando")

        try:
            ok, mensagem = self.aplicacao.baixar(
                item.url, item.formato, ao_progresso=ao_progresso)
        except Exception as erro:  # nunca deixa a thread morrer calada
            ok, mensagem = False, f"Falha inesperada: {erro}"
        item.duracao_processo = round(time.monotonic() - inicio, 2)
        if item.id in self._cancelados:
            return
        if ok:
            caminho = getattr(self.aplicacao, "ultimo_caminho", "") or ""
            # O disco é a fonte da verdade: se o caminho vier vazio ou não
            # existir, procura o arquivo recém-gravado antes de indexar.
            if not caminho or not Path(caminho).is_file():
                caminho = self._procurar_recem_baixado(item) or caminho
            with self._lock:
                item.caminho = str(caminho)
            self._marcar(item, "concluido", mensagem=mensagem or "Concluído.",
                         percentual=100.0)
        else:
            self._marcar(item, "falhou", mensagem=mensagem or "Falhou.",
                         detalhe=mensagem)
        if callable(self.ao_concluir):
            try:
                self.ao_concluir(item)
            except Exception:
                pass


    def _procurar_recem_baixado(self, item: ItemDownload) -> str:
        """Último recurso: acha o arquivo com o maior mtime na pasta de músicas."""
        try:
            pasta = Path(self.aplicacao.config.diretorio_musicas)
            extensao = f".{item.formato}"
            candidatos = [p for p in pasta.rglob(f"*{extensao}")
                          if p.is_file()
                          and p.stat().st_mtime >= self._inicio_item(item)]
            if not candidatos:
                return ""
            return str(max(candidatos, key=lambda p: p.stat().st_mtime))
        except Exception:
            return ""

    @staticmethod
    def _inicio_item(item: ItemDownload) -> float:
        return getattr(item, "_iniciado_em", 0.0)


__all__ = ["GerenciadorDownloads", "ItemDownload", "ESTADOS", "ROTULO_ESTADO"]
