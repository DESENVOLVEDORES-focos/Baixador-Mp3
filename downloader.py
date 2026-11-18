"""Motor de downloads MP3/MP4 baseado no yt-dlp e FFmpeg.

Decisões de comportamento (ver AUDITORIA.md, defeitos A1–A6):

- **Falha do yt-dlp nunca vira traceback**: ``_resumir_erro`` extrai a linha
  real do erro e ``ErroDownload`` carrega a saída completa para diagnóstico.
- **Arquivo existente não é sobrescrito** por padrão. A política vem de
  ``Configuracoes.sobrescrita`` (``pular``/``renomear``/``sobrescrever``) e o
  resultado devolve ``pulado=True`` quando nada novo foi gerado.
- **O arquivo devolvido é o desta execução**: além do ``--print
  after_move:filepath`` do yt-dlp, o ``--print`` é desativado quando há
  renomeação e o caminho é confirmado por existência + ``mtime``.
- **Progresso real** (opcional): ``ao_progresso`` recebe percentual, tamanho,
  velocidade, ETA e etapa (baixando/convertendo/mesclando/metadados). Nenhum
  número é inventado: se o yt-dlp não imprimir o dado, o campo fica vazio.
- **Intermediários limpos**: sobras do yt-dlp na pasta de destino
  (``.part``, ``.ytdl``, e o áudio original já convertido) são removidas sem
  nunca tocar no arquivo final.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Literal
from urllib.parse import urlsplit

from configuracoes import CONFIG, Configuracoes, argumentos_cookies
from organizacao import (
    caminho_disponivel, limpar_componente, nome_arquivo,
    titulo_e_artista_do_arquivo,
)

Formato = Literal["mp3", "mp4"]

# Extensões que o yt-dlp pode deixar na pasta de destino como intermediárias.
EXTENSOES_INTERMEDIARIAS = {
    ".part", ".ytdl", ".temp", ".m4a", ".webm", ".opus", ".ogg", ".aac",
    ".mp4", ".mkv", ".flv", ".3gp", ".mpga", ".wav", ".srt", ".vtt",
}

# Cauda entre colchetes acrescentada pelo yt-dlp: "[dQw4w9WgXcQ]" ou, quando a
# URL não tem ID, "[<título inteiro>]". Só "[Remix]"-style fica.
_RE_CAUDA = re.compile(r"\s*\[([^\]]*)\]\s*$")

ETAPA_BAIXANDO = "Baixando"
ETAPA_CONVERTENDO = "Convertendo para MP3"
ETAPA_MESCLANDO = "Mesclando vídeo e áudio"
ETAPA_METADADOS = "Gravando metadados"


@dataclass(frozen=True)
class Progresso:
    """Estado de um download em andamento (campos vazios = desconhecido)."""

    etapa: str = ETAPA_BAIXANDO
    percentual: float | None = None
    baixado: str = ""
    total: str = ""
    velocidade: str = ""
    eta: str = ""
    linha: str = ""


@dataclass(frozen=True)
class ResultadoDownload:
    url: str
    formato: Formato
    caminho: Path | None
    iniciado_em: str
    finalizado_em: str
    stdout: str = ""
    pulado: bool = False
    motivo: str = ""


class ErroDownload(RuntimeError):
    """Falha do yt-dlp ou saída final inválida/incompleta."""

    def __init__(self, mensagem: str, *, codigo: int | None = None, saida: str = ""):
        super().__init__(mensagem)
        self.codigo = codigo
        self.saida = saida


def validar_url(url: str) -> str:
    url = url.strip()
    partes = urlsplit(url)
    if partes.scheme not in {"http", "https"} or not partes.netloc:
        raise ValueError("Informe uma URL http(s) válida para iniciar o download.")
    return url


# ---------------------------------------------------------------------------
# Interpretação da saída do yt-dlp (isolada para poder ser testada)
# ---------------------------------------------------------------------------

_RE_PROGRESSO = re.compile(
    r"^\[download\]\s+(?P<pct>\d{1,3}(?:\.\d+)?)%"
    r"(?:\s+of\s+~?\s*(?P<total>[\d.]+[KMGTP]?i?B))?"
    r"(?:\s+at\s+(?P<vel>[\d.]+[KMGTP]?i?B/s|[Uu]nknown\s+speed))?"
    r"(?:\s+ETA\s+(?P<eta>[\d:]+|Unknown))?",
)
_RE_ETAPA = (
    (re.compile(r"^\[(?:ExtractAudio|ffmpeg)\]"), ETAPA_CONVERTENDO),
    (re.compile(r"^\[(?:Merger|VideoConvertor|VideoRemuxer)\]"), ETAPA_MESCLANDO),
    (re.compile(r"^\[(?:Metadata|EmbedThumbnail)\]"), ETAPA_METADADOS),
)
_RE_JA_EXISTE = re.compile(r"already been downloaded|has already been downloaded", re.I)


def interpretar_linha(linha: str, etapa_atual: str = ETAPA_BAIXANDO) -> Progresso | None:
    """Traduz uma linha do yt-dlp em ``Progresso``; ``None`` se irrelevante."""
    texto = (linha or "").strip()
    if not texto:
        return None
    achado = _RE_PROGRESSO.match(texto)
    if achado:
        try:
            percentual = float(achado.group("pct"))
        except (TypeError, ValueError):  # pragma: no cover - regex já garante
            percentual = None
        return Progresso(
            etapa=etapa_atual,
            percentual=percentual,
            total=(achado.group("total") or "").replace("~", ""),
            velocidade=achado.group("vel") or "",
            eta=achado.group("eta") or "",
            linha=texto,
        )
    for padrao, etapa in _RE_ETAPA:
        if padrao.match(texto):
            return Progresso(etapa=etapa, linha=texto)
    return None


def _resumir_erro(saida: str) -> str:
    """Extrai a linha de erro mais informativa da saída do yt-dlp."""
    linhas = [linha.strip() for linha in (saida or "").splitlines() if linha.strip()]
    for linha in reversed(linhas):
        baixa = linha.lower()
        if "error:" in baixa or "erro:" in baixa or "fatal:" in baixa:
            return linha
    return linhas[-1] if linhas else "Falha no yt-dlp sem detalhes de saída."


def _encontrar_saida(stdout: str, destino: Path, formato: Formato) -> Path | None:
    extensoes = {"mp3"} if formato == "mp3" else {"mp4"}
    candidatos: list[Path] = []
    for linha in (stdout or "").splitlines():
        texto = linha.strip().strip('"')
        if not texto:
            continue
        caminho = Path(texto)
        if not caminho.is_absolute():
            caminho = destino / caminho
        if caminho.suffix.lower().lstrip(".") in extensoes:
            candidatos.append(caminho)
    for caminho in reversed(candidatos):
        try:
            if caminho.is_file() and caminho.stat().st_size > 0:
                return caminho.resolve()
        except OSError:
            continue
    return None


def _texto(valor: str | bytes | None) -> str:
    if isinstance(valor, bytes):
        return valor.decode("utf-8", errors="replace")
    return valor or ""


def _sem_cauda_tecnica(nome: str) -> str:
    """Remove caudas ``[...]`` que são técnica (ID, nome repetido), não versão.

    ``"[dQw4w9WgXcQ]"`` (ID), ``"[Queen - Bohemian Rhapsody (Official Video)]"``
    (título duplicado) saem; ``"[Remix]"``, ``"[Ao Vivo]"``, ``"[HD]"`` ficam.
    """
    atual = nome.strip()
    while True:
        achado = _RE_CAUDA.search(atual)
        if achado is None:
            return atual
        conteudo = achado.group(1).strip()
        tecnica = (
            len(conteudo) > 24                      # texto longo não é tag
            or " - " in conteudo                    # repetição de "Artista - Título"
            or (len(conteudo) >= 6 and " " not in conteudo)  # ID do vídeo
        )
        if not tecnica:
            return atual
        atual = atual[:achado.start()].strip()


class Downloader:
    def __init__(self, configuracoes: Configuracoes = CONFIG, timeout: int | None = None):
        self.config = configuracoes
        self.timeout = timeout

    # -- montagem dos argumentos -------------------------------------------
    def construir_argumentos(self, url: str, formato: Formato,
                             saida: str | None = None,
                             politica: str | None = None,
                             destino: Path | None = None) -> list[str]:
        """Monta argv sem shell; separar esta etapa facilita testes e auditoria."""
        url = validar_url(url)
        if formato not in ("mp3", "mp4"):
            raise ValueError("Formato deve ser 'mp3' ou 'mp4'.")
        if destino is None:
            destino = self.config.musicas if formato == "mp3" else self.config.videos
        destino.mkdir(parents=True, exist_ok=True)
        cmd = self.config.comando_yt_dlp()
        ffmpeg = self.config.caminho_ffmpeg()
        padrao = saida or "%(title).180B [%(id)s].%(ext)s"
        argumentos = [
            *cmd,
            "--ignore-config",
            "--no-playlist",
            # Progresso máquina-legível (uma atualização por linha) para a
            # interface mostrar %/velocidade/ETA sem inventar nada.
            "--newline", "--progress",
            "--windows-filenames",
            "--retries", "10",
            "--fragment-retries", "10",
            "--extractor-retries", "5",
            "--socket-timeout", "30",
            "--retry-sleep", "http:exp=1:20",
            "--ffmpeg-location", ffmpeg,
            # Cookies do usuário (Etapa 3), quando importados na interface:
            # só o caminho vai ao yt-dlp local; o conteúdo nunca é lido aqui.
            *argumentos_cookies(self.config),
            "--paths", str(destino),
            "--output", padrao,
            # A linha impressa após o processamento permite verificar o arquivo real.
            "--print", "after_move:filepath",
        ]
        # Com --no-overwrites o yt-dlp baixa de novo o arquivo intermediário e
        # regrava o final; a política de sobrescrita é decidida antes (ver
        # baixar()), não pelo yt-dlp. Só sobrescrevemos com autorização.
        if self._politica(politica) == "sobrescrever":
            argumentos.append("--force-overwrites")
        else:
            argumentos.append("--no-overwrites")
        if formato == "mp3":
            # Qualidade das preferências (Etapa 3); padrão "0" = melhor,
            # exatamente o comportamento original do núcleo.
            qualidade = str(getattr(self.config, "qualidade_mp3", "0") or "0")
            if not (qualidade.isdigit() or qualidade.upper().endswith("K")):
                qualidade = "0"
            argumentos.extend([
                "--format", "bestaudio/best",
                "--extract-audio",
                "--audio-format", "mp3",
                "--audio-quality", qualidade,
                "--embed-metadata",
                "--no-keep-video",
            ])
        else:
            argumentos.extend([
                "--format", "bestvideo+bestaudio/best[ext=mp4]/best",
                "--merge-output-format", "mp4",
                "--remux-video", "mp4",
            ])
        argumentos.append(url)
        return argumentos

    def _politica(self, politica: str | None = None) -> str:
        valor = str(politica or getattr(self.config, "sobrescrita", "pular")
                    or "pular").lower()
        return valor if valor in {"pular", "renomear", "sobrescrever"} else "pular"

    # -- execução -----------------------------------------------------------
    def baixar(self, url: str, formato: Formato,
               ao_progresso: Callable[[Progresso], None] | None = None,
               politica: str | None = None,
               contexto: object = None,
               ) -> ResultadoDownload:
        """Baixa para uma pasta de trabalho e só então publica no destino.

        Motivo (reproduzido): o nome do arquivo é a entrada da identificação
        musical da IA 2. Renomear com sufixo antes de baixar (ou limpar
        intermediários na própria pasta de destino) fazia o título virar
        ``"titulo (20261118-005140)"`` e o ano/id contaminarem as tags.
        Com a pasta de trabalho, o nome publicado é sempre limpo e nenhum
        ``.m4a``/``.part`` aparece em ``Musicas/``/``Videos/``.

        ``contexto`` (opcional) é o resultado escolhido na pesquisa
        (``ContextoMidia``/dicionário/objeto). Quando o nome organizado está
        ligado nas preferências, ele dá o nome apresentável do arquivo; caso
        contrário o nome do yt-dlp é mantido (comportamento anterior).
        """
        url = validar_url(url)
        self.config.preparar_diretorios()
        destino = self.config.musicas if formato == "mp3" else self.config.videos
        inicio_dt = datetime.now(timezone.utc)
        iniciado = inicio_dt.isoformat()
        antes = self._fotografar(destino, formato)

        saida_nome, politica_final = self._planejar_colisao(
            url, formato, destino, politica)
        if politica_final == "pular":
            return ResultadoDownload(
                url=url, formato=formato, caminho=None,
                iniciado_em=iniciado, finalizado_em=iniciado,
                pulado=True,
                motivo="O arquivo correspondente já existe nesta pasta; nada foi "
                       "sobrescrito (política de sobrescrita: pular).",
            )

        # Pasta de trabalho: o download (e os intermediários) acontecem aqui.
        trabalho = Path(tempfile.mkdtemp(prefix="baixador-", dir=str(self.config.dados)))
        try:
            argumentos = self.construir_argumentos(
                url, formato, saida=saida_nome, politica=politica_final,
                destino=destino if politica_final == "sobrescrever" else trabalho)
            stdout, codigo = self._executar(argumentos, ao_progresso)

            if codigo != 0:
                resumo = _resumir_erro(stdout) or f"yt-dlp terminou com código {codigo}."
                if _RE_JA_EXISTE.search(stdout):
                    resumo = ("O arquivo já existia e o yt-dlp não gerou nada novo "
                              "(nada foi sobrescrito).")
                raise ErroDownload(resumo, codigo=codigo, saida=stdout)

            produzido = _encontrar_saida(stdout, trabalho, formato)
            if produzido is None or not produzido.is_file():
                produzido = self._arquivo_novo(trabalho, formato, {}, inicio_dt)
            if produzido is None:
                raise ErroDownload(
                    "yt-dlp terminou sem erro, mas não foi possível confirmar um arquivo "
                    f"final {formato.upper()} válido; o item não será marcado como "
                    "concluído.",
                    codigo=codigo,
                    saida=stdout,
                )
            if politica_final == "sobrescrever" and produzido.parent != trabalho:
                # Já publicado direto no destino, por autorização explícita.
                return ResultadoDownload(
                    url=url, formato=formato, caminho=produzido.resolve(),
                    iniciado_em=iniciado,
                    finalizado_em=datetime.now(timezone.utc).isoformat(),
                    stdout=stdout,
                )
            publicado = self._publicar(produzido, destino, politica_final,
                                       contexto=contexto)
            return ResultadoDownload(
                url=url,
                formato=formato,
                caminho=publicado,
                iniciado_em=iniciado,
                finalizado_em=datetime.now(timezone.utc).isoformat(),
                stdout=stdout,
            )
        finally:
            shutil.rmtree(trabalho, ignore_errors=True)
            self._limpar_residuos(destino, antes, None)

    def _publicar(self, produzido: Path, destino: Path, politica: str,
                  contexto: object = None) -> Path:
        """Move o arquivo da pasta de trabalho para o destino, com nome livre.

        ``pular``: já não chegamos aqui (a checagem aconteceu antes).
        ``renomear``/``baixar``: nome limpo; se colidir, acrescenta ``(2)``.
        O nome organizado (``Artista - Título``) só é aplicado quando a
        preferência ``organizar_nomes`` está ligada — antes disso o arquivo
        mantém o nome do yt-dlp, que é a entrada da identificação musical.
        """
        destino.mkdir(parents=True, exist_ok=True)
        nome = produzido.name
        if self._organizar():
            nome = self._nome_organizado(produzido, contexto)
        alvo = destino / nome
        if politica != "sobrescrever":
            alvo = caminho_disponivel(destino, nome)
        shutil.move(str(produzido), str(alvo))
        return alvo.resolve()

    def _organizar(self) -> bool:
        return bool(getattr(self.config, "organizar_nomes", False))

    def _nome_organizado(self, produzido: Path, contexto: object = None) -> str:
        """``Artista - Título.ext`` a partir do contexto ou do nome do arquivo."""
        extensao = produzido.suffix
        titulo_contexto = ""
        artista_contexto = ""
        if contexto is not None:
            try:
                from contexto import ContextoMidia

                dados = ContextoMidia.normalizar(contexto)
                titulo_contexto = dados.titulo
                artista_contexto = dados.canal
            except Exception:  # contexto estranho nunca impede a publicação
                titulo_contexto = artista_contexto = ""
        from inteligencia import limpar_nome_canal, limpar_titulo_video

        # Regra de precedência do nome apresentável:
        # 1. O nome do arquivo do yt-dlp (``Título [id]``), que já é o título
        #    real do vídeo — só o ID entre colchetes é removido. Usar isso como
        #    TÍTULO evita duplicar quando o próprio título contém "Artista - ".
        # 2. O título do resultado escolhido na pesquisa.
        # 3. O nome cru do arquivo.
        base = _sem_cauda_tecnica(produzido.stem) or produzido.stem
        titulo = limpar_titulo_video(base) or base or titulo_contexto
        # Artista: o canal do resultado, ou a parte antes de " - " no nome.
        artista = limpar_nome_canal(artista_contexto)
        if not artista:
            _, artista_arquivo = titulo_e_artista_do_arquivo(produzido.name)
            artista = artista_arquivo
        # "(Official Video)", "[HD]", "(Lyrics)" saem do nome; "[Remix]" fica.
        nome = nome_arquivo(titulo=titulo, artista=artista,
                            desconhecido=produzido.stem)
        return f"{nome}{extensao}"

    def _executar(self, argumentos: list[str],
                  ao_progresso: Callable[[Progresso], None] | None
                  ) -> tuple[str, int]:
        """Roda o yt-dlp lendo a saída linha a linha (progresso em tempo real)."""
        return self._comunicar(argumentos, ao_progresso, "iniciar o yt-dlp")

    def _comunicar(self, argumentos: list[str],
                   ao_progresso: Callable[[Progresso], None] | None,
                   contexto: str = "iniciar o processo") -> tuple[str, int]:
        """Executa o argv e consome a saída linha a linha (progresso real).

        Argumentos (e não uma função ``abrir``) para que os testes possam
        substituir ``subprocess.Popen``: o processo é sempre criado aqui.
        """
        try:
            # argv como primeiro argumento posicional (``args``); os testes
            # substituem ``subprocess.Popen`` e recebem a lista como antes.
            processo = subprocess.Popen(
                argumentos,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
        except OSError as erro:
            raise ErroDownload(f"Não foi possível {contexto}: {erro}") from erro
        except FileNotFoundError as erro:
            raise ErroDownload(f"Não foi possível {contexto}: {erro}") from erro

        linhas: list[str] = []
        etapa = ETAPA_BAIXANDO
        excedeu = threading.Event()

        def _matar() -> None:
            excedeu.set()
            try:
                processo.kill()
            except OSError:  # pragma: no cover - processo já morto
                pass

        temporizador = None
        if self.timeout:
            temporizador = threading.Timer(self.timeout, _matar)
            temporizador.daemon = True
            temporizador.start()
        try:
            assert processo.stdout is not None
            for linha in processo.stdout:
                linhas.append(linha.rstrip("\n"))
                if ao_progresso is not None:
                    progresso = interpretar_linha(linha, etapa)
                    if progresso is not None:
                        etapa = progresso.etapa
                        try:
                            ao_progresso(progresso)
                        except Exception:  # callback da UI nunca derruba o download
                            pass
            # Popen.wait(); mocks de teste podem expor só ``returncode``.
            await_ = getattr(processo, "wait", None)
            codigo = await_() if callable(await_) else int(
                getattr(processo, "returncode", 0) or 0)
        finally:
            if temporizador is not None:
                temporizador.cancel()
            try:
                fechar = getattr(processo.stdout, "close", None)
                if callable(fechar):
                    fechar()
            except Exception:  # pragma: no cover - mocks e pipes já fechados
                pass
        if excedeu.is_set():
            raise ErroDownload("O download excedeu o tempo limite.",
                               saida="\n".join(linhas))
        return "\n".join(linhas), codigo

    # -- colisão de nomes --------------------------------------------------
    def _planejar_colisao(self, url: str, formato: Formato, destino: Path,
                          politica: str | None = None) -> tuple[str | None, str]:
        """Decide antes de baixar se pula, renomeia ou sobrescreve.

        ``--no-overwrites`` do yt-dlp protege o arquivo *intermediário*, não o
        final pós-processado (foi reproduzido: o MP3 era regravado). Por isso a
        política ``pular`` consulta o título esperado antes e, se o arquivo
        final já existir, não inicia o download. Se a consulta falhar (rede,
        extrato), segue o download e a verificação por ``mtime`` decide.
        """
        politica = self._politica(politica)
        if politica in {"renomear", "sobrescrever"}:
            # O nome sai limpo; a desambiguação ("(2)") acontece ao publicar,
            # para não contaminar a identificação musical da IA 2.
            return None, politica
        titulo = self.titulo_esperado(url)
        if titulo:
            nome = titulo
            if self._organizar():
                titulo_limpo, artista_limpo = titulo_e_artista_do_arquivo(titulo)
                nome = nome_arquivo(titulo=titulo_limpo, artista=artista_limpo,
                                    desconhecido=limpar_componente(titulo))
            final = destino / f"{nome}{'.mp3' if formato == 'mp3' else '.mp4'}"
            try:
                if final.is_file() and final.stat().st_size > 0:
                    return None, "pular"
            except OSError:
                pass
        return None, "baixar"

    def titulo_esperado(self, url: str) -> str | None:
        """Consulta leve (``--skip-download``) só para saber o nome do arquivo."""
        comando = [
            *self.config.comando_yt_dlp(),
            "--ignore-config", "--no-playlist", "--no-warnings", "--skip-download",
            *argumentos_cookies(self.config),
            "--print", "%(title).180B [%(id)s]",
            url,
        ]
        try:
            saida, codigo = self._comunicar(comando, None, "consultar o título")
        except ErroDownload:
            return None
        if codigo != 0:
            return None
        linhas = [linha.strip() for linha in saida.splitlines() if linha.strip()]
        return linhas[-1] if linhas else None

    @staticmethod
    def _fotografar(destino: Path, formato: Formato) -> dict[Path, tuple[int, float]]:
        extensoes = {".mp3"} if formato == "mp3" else {".mp4"}
        foto: dict[Path, tuple[int, float]] = {}
        try:
            for arquivo in destino.iterdir():
                if arquivo.suffix.lower() in extensoes and arquivo.is_file():
                    info = arquivo.stat()
                    foto[arquivo.resolve()] = (info.st_size, info.st_mtime)
        except OSError:
            pass
        return foto

    @staticmethod
    def _novo_ou_atualizado(arquivo: Path, antes: dict[Path, tuple[int, float]],
                            inicio: datetime) -> bool:
        info = arquivo.stat()
        anterior = antes.get(arquivo.resolve())
        if anterior is None:
            return info.st_size > 0
        return info.st_mtime >= inicio.timestamp() - 1

    @staticmethod
    def _arquivo_novo(destino: Path, formato: Formato,
                      antes: dict[Path, tuple[int, float]],
                      inicio: datetime) -> Path | None:
        extensao = ".mp3" if formato == "mp3" else ".mp4"
        candidatos: list[Path] = []
        try:
            for arquivo in destino.iterdir():
                if arquivo.suffix.lower() != extensao or not arquivo.is_file():
                    continue
                resolvido = arquivo.resolve()
                anterior = antes.get(resolvido)
                if anterior is not None and arquivo.stat().st_mtime < inicio.timestamp() - 1:
                    continue
                if arquivo.stat().st_size > 0:
                    candidatos.append(resolvido)
        except OSError:
            return None
        if not candidatos:
            return None
        return max(candidatos, key=lambda c: c.stat().st_mtime)

    # -- limpeza ------------------------------------------------------------
    def _limpar_residuos(self, destino: Path, antes: dict[Path, tuple[int, float]],
                         final: Path | None) -> list[Path]:
        """Remove intermediários desta execução; nunca toca no arquivo final.

        Um resíduo é um arquivo cujo nome começa por um final conhecido (mesmo
        ``stem``) e cuja extensão é intermediária, ou qualquer ``.part``/``.ytdl``.
        Arquivos que já existiam antes e continuam com o mesmo tamanho são
        preservados.
        """
        removidos: list[Path] = []
        tries_base = {final.stem} if final is not None else set()
        try:
            entradas = list(destino.iterdir())
        except OSError:
            return removidos
        for arquivo in entradas:
            if not arquivo.is_file() or (final is not None and arquivo == final):
                continue
            extensao = arquivo.suffix.lower()
            if extensao not in EXTENSOES_INTERMEDIARIAS:
                continue
            relacionado = extensao in {".part", ".ytdl", ".temp"}
            if not relacionado:
                relacionado = any(arquivo.stem == base for base in tries_base) or any(
                    arquivo.name.startswith(base) for base in tries_base)
            if not relacionado:
                continue
            try:
                info = arquivo.stat()
                anterior = antes.get(arquivo.resolve())
                if anterior == (info.st_size, info.st_mtime):
                    continue  # preexistente: não é nosso
                arquivo.unlink()
                removidos.append(arquivo)
            except OSError:
                continue
        return removidos


def limpar_parts(destino: Path) -> list[Path]:
    """Remove ``.part``/``.ytdl`` órfãos de uma pasta (usada no início do app)."""
    removidos: list[Path] = []
    try:
        for arquivo in destino.iterdir():
            if arquivo.is_file() and arquivo.suffix.lower() in {".part", ".ytdl"}:
                try:
                    arquivo.unlink()
                    removidos.append(arquivo)
                except OSError:
                    continue
    except OSError:
        pass
    return removidos


__all__ = [
    "Downloader", "ErroDownload", "ETAPA_BAIXANDO", "ETAPA_CONVERTENDO",
    "ETAPA_MESCLANDO", "ETAPA_METADADOS", "Formato", "Progresso",
    "ResultadoDownload", "interpretar_linha", "limpar_parts", "validar_url",
]
