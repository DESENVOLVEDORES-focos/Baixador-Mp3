"""Reprodutor de áudio integrado (fila, aleatório, repetição, volume).

Decisão técnica: usa o **FFmpeg que o programa já exige** (``ferramentas/ffmpeg``
ou o do PATH), através do ``ffplay``/``ffmpeg`` em subprocesso. Assim não entra
dependência nova (nada de pygame/simpleaudio) e funciona no Windows do usuário.

O estado (fila, posição, modo de repetição, volume) vive aqui, sem Tkinter, para
poder ser testado sem tela. A interface só desenha e chama ``tocar``/``pausar``.
"""

from __future__ import annotations

import json
import logging
import os
import random
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

log = logging.getLogger("baixador.reprodutor")

MODOS_REPETICAO = ("off", "musica", "fila")


@dataclass
class Faixa:
    """Item em reprodução (o que a interface precisa mostrar)."""

    caminho: str
    titulo: str = ""
    artista: str = ""
    album: str = ""
    duracao: float | None = None
    tem_capa: bool = False
    musica_id: int | None = None

    @property
    def nome_exibicao(self) -> str:
        return self.titulo or Path(self.caminho).stem

    @property
    def subtitulo(self) -> str:
        partes = [parte for parte in (self.artista, self.album) if parte]
        return " — ".join(partes)


def localizar_ffplay(config: Any = None) -> list[str]:
    """argv do ``ffplay`` (ferramentas do programa primeiro).

    Devolve lista vazia quando não há ffplay: a interface avisa e oferece abrir
    o arquivo no player padrão do sistema (nunca finge que tocou).
    """
    nomes = ("ffplay.exe", "ffplay") if sys.platform == "win32" else ("ffplay",)
    pastas: list[Path] = []
    if config is not None:
        try:
            pastas.append(Path(config.ferramentas))
        except Exception:
            pass
    for pasta in pastas:
        for nome in nomes:
            candidato = pasta / nome
            if candidato.is_file():
                return [str(candidato)]
    encontrado = shutil.which("ffplay") or shutil.which("ffplay.exe")
    if encontrado:
        return [encontrado]
    # Fallback: usar o mesmo ffmpeg do programa não toca som (é conversor);
    # então procuramos ffplay ao lado dele.
    try:
        from configuracoes import CONFIG

        ffmpeg = Path(CONFIG.caminho_ffmpeg())
        vizinho = ffmpeg.with_name("ffplay.exe" if sys.platform == "win32" else "ffplay")
        if vizinho.is_file():
            return [str(vizinho)]
    except Exception:
        pass
    return []


class Reprodutor:
    """Toca um arquivo por vez e mantém a fila/modo (estado puro e testável)."""

    def __init__(self, config: Any = None,
                 ao_mudar: Callable[[str], None] | None = None,
                 executar: Callable[..., Any] | None = None):
        self.config = config
        self.ao_mudar = ao_mudar
        self._executar = executar or subprocess.Popen
        self._lock = threading.RLock()
        self.fila: list[Faixa] = []
        self.indice = -1
        self.volume = 80
        self.aleatorio = False
        self.repeticao = "off"
        self.tocando = False
        self.pausado = False
        self._processo: Any = None
        self._iniciado_em = 0.0
        self._posicao_salva = 0.0
        self._historico: list[int] = []
        # Arquivo de estado (volume, repetição, última faixa) — retomada amanhã.
        self._arquivo_estado: Path | None = None

    # -- persistência -------------------------------------------------------
    def usar_arquivo_estado(self, caminho: str | Path) -> None:
        self._arquivo_estado = Path(caminho)

    def salvar_estado(self) -> bool:
        """Grava o que faz diferença na próxima abertura (nada de segredo)."""
        if self._arquivo_estado is None:
            return False
        faixa = self.atual
        dados = {
            "volume": self.volume,
            "repeticao": self.repeticao,
            "aleatorio": self.aleatorio,
            "indice": self.indice,
            "posicao": round(self._posicao_salva, 1),
            "ultima_faixa": faixa.caminho if faixa else "",
            "fila": [f.caminho for f in self.fila][:500],
        }
        try:
            self._arquivo_estado.parent.mkdir(parents=True, exist_ok=True)
            temporario = self._arquivo_estado.with_suffix(".tmp")
            temporario.write_text(json.dumps(dados, ensure_ascii=False),
                                  encoding="utf-8")
            os.replace(temporario, self._arquivo_estado)
            return True
        except Exception as erro:
            log.info("Estado do player não salvo: %s", erro)
            return False

    def carregar_estado(self) -> dict[str, Any]:
        """Lê volume/repetição e devolve a fila anterior (sem tocar nada)."""
        if self._arquivo_estado is None or not self._arquivo_estado.is_file():
            return {}
        try:
            dados = json.loads(self._arquivo_estado.read_text(encoding="utf-8"))
        except Exception as erro:
            log.info("Estado do player ilegível: %s", erro)
            return {}
        if not isinstance(dados, dict):
            return {}
        with self._lock:
            self.volume = max(0, min(100, int(dados.get("volume", self.volume))))
            if dados.get("repeticao") in MODOS_REPETICAO:
                self.repeticao = str(dados["repeticao"])
            self.aleatorio = bool(dados.get("aleatorio", self.aleatorio))
            caminhos = [c for c in dados.get("fila", [])
                        if isinstance(c, str) and Path(c).is_file()]
            if caminhos:
                self.fila = [Faixa(caminho=c) for c in caminhos]
                self.indice = min(max(0, int(dados.get("indice", 0))),
                                  len(self.fila) - 1)
                self.faixa_anterior = caminhos[self.indice]
            self._posicao_salva = 0.0
        return dados

    def tocar_ultima(self) -> bool:
        """Retoma a última faixa ouvida (posição do começo, de propósito)."""
        caminho = getattr(self, "faixa_anterior", "")
        if not caminho:
            return False
        indice = next((i for i, f in enumerate(self.fila)
                       if f.caminho == caminho), None)
        if indice is None:
            return False
        self._posicao_salva = 0.0
        return self.tocar(indice)

    # -- navegação por posição ---------------------------------------------
    def buscar(self, segundos: float) -> bool:
        """Pula para um ponto da faixa atual (a barra de progresso clicável)."""
        with self._lock:
            faixa = self.atual
            if faixa is None:
                return False
            limite = float(faixa.duracao or 0)
            destino = max(0.0, float(segundos))
            if limite:
                destino = min(destino, max(0.0, limite - 0.5))
            self._posicao_salva = destino
        if self.tocando or self.pausado:
            return self._retomar()
        return True

    def avancar(self, segundos: float) -> bool:
        return self.buscar(self.posicao + float(segundos))

    # -- utilitários --------------------------------------------------------
    def _avisar(self, evento: str) -> None:
        if callable(self.ao_mudar):
            try:
                self.ao_mudar(evento)
            except Exception:
                pass

    @property
    def atual(self) -> Faixa | None:
        if 0 <= self.indice < len(self.fila):
            return self.fila[self.indice]
        return None

    @property
    def posicao(self) -> float:
        """Segundos tocados da faixa atual (0 se parado/pausado no início)."""
        if not self.tocando or not self._iniciado_em:
            return 0.0
        return max(0.0, time.monotonic() - self._iniciado_em)

    def definir_fila(self, faixas: Iterable[Faixa], *, indice: int = 0) -> None:
        with self._lock:
            self.fila = list(faixas)
            self.indice = min(max(0, indice), max(0, len(self.fila) - 1))
            self._historico.clear()
        self._avisar("fila")

    def adicionar(self, faixa: Faixa) -> None:
        with self._lock:
            self.fila.append(faixa)
            if self.indice < 0:
                self.indice = 0
        self._avisar("fila")

    # -- controles ----------------------------------------------------------
    def tocar(self, indice: int | None = None) -> bool:
        """Começa/retoma a reprodução; devolve False quando não foi possível."""
        with self._lock:
            if indice is not None:
                if not 0 <= int(indice) <= len(self.fila) - 1:
                    return False
                self.indice = int(indice)
            faixa = self.atual
            if faixa is None:
                return False
            if self.pausado:
                # Pausa no Windows = processo encerrado guardando a posição;
                # retomar continua de onde parou (ffplay -ss), não do começo.
                return self._retomar()
            caminho = Path(faixa.caminho)
            if not caminho.is_file():
                self._avisar("arquivo_ausente")
                return False
            self.parar(silencioso=True)
            base = localizar_ffplay(self.config)
            if not base:
                self._avisar("sem_ffplay")
                return False
            comando = [
                *base, "-nodisp", "-autoexit", "-loglevel", "error",
                "-volume", str(max(0, min(100, self.volume))),
                "-i", str(caminho),
            ]
            try:
                self._processo = self._executar(
                    comando, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL)
            except (OSError, ValueError) as erro:
                log.info("ffplay não iniciou: %s", erro)
                self._processo = None
                self._avisar("erro_audio")
                return False
            self.tocando = True
            self.pausado = False
            self._iniciado_em = time.monotonic()
            if indice is not None:
                self._historico.append(self.indice)
            self._avisar("tocando")
            return True

    def pausar(self) -> bool:
        with self._lock:
            if self._processo is None or not self.tocando or self.pausado:
                return False
            # No Windows não há SIGSTOP: pausar = encerrar e retomar do início do
            # trecho? Não. Preferimos parar o processo e guardar a posição, para
            # retomar com -ss (o ffplay não aceita pausa por sinal no Windows).
            self._posicao_salva = self.posicao
            self._encerrar()
            self.tocando = False
            self.pausado = True
            self._avisar("pausado")
            return True

    def _retomar(self) -> bool:
        faixa = self.atual
        if faixa is None:
            return False
        base = localizar_ffplay(self.config)
        if not base:
            self._avisar("sem_ffplay")
            return False
        inicio = self._posicao_salva
        comando = [
            *base, "-nodisp", "-autoexit", "-loglevel", "error",
            "-volume", str(max(0, min(100, self.volume))),
            "-ss", f"{inicio:.1f}", "-i", faixa.caminho,
        ]
        try:
            self._processo = self._executar(
                comando, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL)
        except (OSError, ValueError):
            self._processo = None
            self._avisar("erro_audio")
            return False
        self.tocando = True
        self.pausado = False
        self._iniciado_em = time.monotonic() - inicio
        self._avisar("tocando")
        return True

    def _encerrar(self) -> None:
        processo, self._processo = self._processo, None
        if processo is None:
            return
        try:
            processo.terminate()
            processo.wait(timeout=3)
        except Exception:
            try:
                processo.kill()
            except Exception:
                pass

    def parar(self, silencioso: bool = False) -> None:
        with self._lock:
            self._encerrar()
            self.tocando = False
            self.pausado = False
            self._iniciado_em = 0.0
            self._posicao_salva = 0.0
        if not silencioso:
            self._avisar("parado")

    def proxima(self, automatico: bool = False) -> bool:
        with self._lock:
            if not self.fila:
                return False
            if automatico and self.repeticao == "musica":
                return self.tocar(self.indice)
            if self.aleatorio and len(self.fila) > 1:
                opcoes = [i for i in range(len(self.fila)) if i != self.indice]
                alvo = random.choice(opcoes)
            else:
                alvo = self.indice + 1
                if alvo >= len(self.fila):
                    if self.repeticao == "fila":
                        alvo = 0
                    else:
                        self.parar(silencioso=True)
                        self._avisar("fim_da_fila")
                        return False
        return self.tocar(alvo)

    def anterior(self) -> bool:
        with self._lock:
            if not self.fila:
                return False
            alvo = self.indice - 1
            if alvo < 0:
                alvo = 0
        return self.tocar(alvo)

    def mudar_volume(self, valor: int) -> int:
        with self._lock:
            self.volume = max(0, min(100, int(valor)))
            # Volume só vale na próxima faixa (ffplay não aceita ajuste ao vivo
            # sem terminal); avisamos para a interface não mentir.
        self._avisar("volume")
        return self.volume

    def alternar_aleatorio(self) -> bool:
        with self._lock:
            self.aleatorio = not self.aleatorio
        self._avisar("aleatorio")
        return self.aleatorio

    def ciclo_repeticao(self) -> str:
        with self._lock:
            ordem = list(MODOS_REPETICAO)
            self.repeticao = ordem[(ordem.index(self.repeticao) + 1) % len(ordem)]
        self._avisar("repeticao")
        return self.repeticao

    def esta_rodando(self) -> bool:
        """True enquanto o processo de áudio está vivo (fim natural da faixa)."""
        with self._lock:
            if self._processo is None:
                return False
            codigo = self._processo.poll()
            return codigo is None

    def descricao_repeticao(self) -> str:
        return {"off": "Repetir: desligado", "musica": "Repetir: esta música",
                "fila": "Repetir: fila"}.get(self.repeticao, "Repetir: desligado")

    def estado(self) -> dict[str, Any]:
        faixa = self.atual
        return {
            "tocando": self.tocando,
            "pausado": self.pausado,
            "indice": self.indice,
            "total": len(self.fila),
            "faixa": faixa.nome_exibicao if faixa else "",
            "subtitulo": faixa.subtitulo if faixa else "",
            "caminho": faixa.caminho if faixa else "",
            "capa": bool(faixa.tem_capa) if faixa else False,
            "volume": self.volume,
            "aleatorio": self.aleatorio,
            "repeticao": self.repeticao,
            "posicao": self.posicao,
        }


__all__ = ["Faixa", "Reprodutor", "localizar_ffplay", "MODOS_REPETICAO"]
