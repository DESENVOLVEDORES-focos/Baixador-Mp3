"""CLI do Baixador-Mp3. Execute ``python musica.py --help`` para ver comandos."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path
from typing import Any

from configuracoes import CONFIG, Configuracoes
from downloader import Downloader, ErroDownload, Progresso
from fila import FilaDownloads
from historico import Historico
from integracao import AdaptadorMetadados
from organizacao import caminho_disponivel, subpasta
from pesquisa import ErroPesquisa, Pesquisador
from previa import Previa, pasta_para_tocar


class Aplicacao:
    def __init__(self, configuracoes: Configuracoes = CONFIG):
        # Sem config explícita (CLI/interface), respeita as preferências
        # salvas pelo usuário (Etapa 3): diretórios, cookies, qualidade e
        # chaves/opções da IA 2 via ambiente. Com config explícita (testes,
        # injeção), nada é alterado — comportamento original preservado.
        if configuracoes is CONFIG:
            try:
                from preferencias import (
                    aplicar_ao_ambiente, carregar, derivar_configuracoes,
                )

                preferencias = carregar(CONFIG)
                aplicar_ao_ambiente(preferencias)
                configuracoes = derivar_configuracoes(preferencias, CONFIG)
            except Exception:
                configuracoes = CONFIG
        self.config = configuracoes
        self.downloader = Downloader(configuracoes)
        self.pesquisador = Pesquisador(configuracoes)
        self.fila = FilaDownloads(configuracoes)
        self.historico = Historico(configuracoes)
        self.metadados = AdaptadorMetadados()
        self.previa = Previa(configuracoes)
        # Última classificação de erro (a interface usa para a dica contextual)
        # e último arquivo publicado (para exibir/abrir a pasta).
        self.ultimo_diagnostico = None
        self.ultimo_caminho: str = ""

    def baixar(self, url: str, formato: str, ao_progresso: Any = None,
               politica: str | None = None,
               contexto: Any = None) -> tuple[bool, str]:
        """Baixa e (em MP3) enriquece; nunca deixa falha virar traceback.

        Retorna ``(sucesso, mensagem)``. Arquivo já existente com a política
        ``pular`` devolve ``(True, motivo)`` sem baixar e sem sobrescrever.
        """
        try:
            try:
                resultado = self.downloader.baixar(  # type: ignore[arg-type]
                    url, formato, ao_progresso=ao_progresso, politica=politica,
                    contexto=contexto)
            except TypeError:
                # Downloader injetado (testes/fakes) sem suporte a progresso.
                resultado = self.downloader.baixar(url, formato)  # type: ignore[arg-type]
            if isinstance(resultado, tuple):  # fake de teste devolve (ok, msg)
                return bool(resultado[0]), str(resultado[1] if len(resultado) > 1 else "")
            if resultado.pulado:
                self.historico.registrar(
                    url=url, formato=formato, status="pulado",
                    mensagem=resultado.motivo, inicio=resultado.iniciado_em,
                )
                print(f"[PULADO] {resultado.motivo}", file=sys.stderr)
                return True, resultado.motivo
            if resultado.caminho is None:  # pragma: no cover - defensivo
                raise ErroDownload("O yt-dlp não informou o arquivo final.")
            caminho = resultado.caminho
            aviso = ""
            if formato == "mp3" and self.metadados.disponivel:
                try:
                    # Contrato v2 (retrocompatível): além dos campos originais,
                    # título/canal/duração/thumbnail do resultado escolhido
                    # tornam a identificação precisa sem depender do nome do
                    # arquivo (que o yt-dlp trunca em 180 bytes).
                    dados = {
                        "url": resultado.url,
                        "formato": resultado.formato,
                        "titulo": resultado.caminho.stem,
                        "caminho": str(resultado.caminho),
                        "inicio": resultado.iniciado_em,
                        "conclusao": resultado.finalizado_em,
                    }
                    from contexto import ContextoMidia

                    dados.update(ContextoMidia.normalizar(contexto).como_metadados())
                    caminho = self.metadados.processar_mp3(caminho, dados)
                except Exception as erro_integracao:
                    aviso = f"Download concluído, mas a integração de metadados falhou: {erro_integracao}"
                    self.historico.registrar(
                        url=url, formato=formato, status="erro",
                        caminho=resultado.caminho, mensagem=aviso,
                        inicio=resultado.iniciado_em,
                    )
            caminho = self._organizar_em_subpasta(caminho, formato)
            self.historico.registrar(
                url=url, formato=formato,
                status="sucesso_com_aviso" if aviso else "sucesso",
                caminho=caminho, mensagem=aviso, inicio=resultado.iniciado_em,
            )
            self.ultimo_caminho = str(caminho)
            print(f"[OK] {formato.upper()} concluído: {caminho}")
            if aviso:
                print(f"[AVISO] {aviso}", file=sys.stderr)
            return True, aviso
        except (ErroDownload, FileNotFoundError, ValueError, OSError) as erro:
            from diagnostico import classificar, sanitizar

            mensagem = str(erro)
            saida = getattr(erro, "saida", "")
            if saida:
                mensagem += "\n" + saida
            # A causa é traduzida em orientação (login, cookies vencidos, rede…)
            # e a mensagem técnica vai sanitizada para o histórico.
            diagnostico = classificar(mensagem)
            self.historico.registrar(
                url=url, formato=formato, status="erro",
                mensagem=f"[{diagnostico.situacao}] {diagnostico.texto} | "
                         f"técnico: {sanitizar(str(erro))}",
            )
            print(f"[ERRO] {diagnostico.texto}", file=sys.stderr)
            self.ultimo_diagnostico = diagnostico
            return False, diagnostico.texto

    # -- pré-visualização ---------------------------------------------------
    def preparar_previa(self, url: str) -> Any:
        """Consulta o vídeo (sem baixar) e devolve ``DadosVideo`` + indícios."""
        return self.previa.preparar(url)

    def ouvir_previa(self, url: str, segundos: int = 20) -> tuple[Path, Path]:
        """Baixa um trecho curto e devolve ``(arquivo, pasta)`` para tocar.

        A pasta é exclusiva desta prévia: quem chamou deve apagá-la depois com
        ``previa.limpar`` (a interface faz isso ao fechar ou ao pedir outra).
        """
        import tempfile

        # A pasta de dados pode ainda não existir (primeira execução).
        self.config.dados.mkdir(parents=True, exist_ok=True)
        pasta = Path(tempfile.mkdtemp(prefix="previa-", dir=str(self.config.dados)))
        arquivo = self.previa.baixar_amostra(url, pasta, segundos)
        return pasta_para_tocar(arquivo, pasta), pasta

    def _organizar_em_subpasta(self, caminho: Any, formato: str) -> Any:
        """Move para ``Artista/Álbum`` usando só dados confirmados pela IA 2.

        Acontece *depois* do enriquecimento (é quando o álbum é conhecido) e
        nunca falha o download: qualquer erro devolve o caminho original.
        """
        if formato != "mp3" or not getattr(self.config, "organizar_por_album", False):
            return caminho
        try:
            processador = getattr(self.metadados, "_processador", None)
            resumo = getattr(processador, "ultimo_resumo", None) or {}
            relativa = subpasta(resumo)
            if relativa is None:
                return caminho
            destino = self.config.musicas / relativa
            if Path(caminho).parent == destino:
                return caminho
            destino.mkdir(parents=True, exist_ok=True)
            final = caminho_disponivel(destino, Path(caminho).name)
            shutil.move(str(caminho), str(final))
            print(f"[ORGANIZADO] {caminho} -> {final}", file=sys.stderr)
            return final
        except Exception as erro:  # organização é cosmética: nunca perde o arquivo
            print(f"[AVISO] Não foi possível organizar em subpasta: {erro}",
                  file=sys.stderr)
            return caminho

    def processar_fila(self, *, max_tentativas: int = 3, intervalo: float = 0) -> int:
        interrompidos = self.fila.reabrir_interrompidos()
        if interrompidos:
            print(f"[FILA] Recuperados {interrompidos} item(ns) deixados por worker interrompido.")
        concluidos = 0
        while True:
            item = self.fila.reivindicar()
            if item is None:
                return concluidos
            print(f"[FILA] {item.formato.upper()} {item.url} (tentativa {item.tentativas})")
            sucesso, mensagem = self.baixar(item.url, item.formato,
                                            ao_progresso=_progresso_terminal)
            if sucesso:
                self.fila.concluir(item.id)
                concluidos += 1
            else:
                self.fila.falhar(item.id, mensagem, max_tentativas=max_tentativas)
                estado = next((x.status for x in self.fila.listar(todos=True) if x.id == item.id), "falhou")
                if estado == "pendente" and intervalo > 0:
                    time.sleep(intervalo)


def _criar_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="baixador-mp3",
        description="Baixa áudio e vídeo com yt-dlp e FFmpeg; use apenas conteúdo autorizado.",
    )
    sub = parser.add_subparsers(dest="comando", required=True)

    baixar = sub.add_parser("download", help="Baixa uma URL como MP3 ou MP4")
    baixar.add_argument("url", help="URL http(s) do conteúdo")
    baixar.add_argument("--formato", choices=("mp3", "mp4"), required=True)

    pesquisar = sub.add_parser("search", help="Pesquisa e exibe resultados reais do yt-dlp")
    pesquisar.add_argument("consulta", help="Texto da pesquisa")
    pesquisar.add_argument("--limite", type=int, default=10)
    pesquisar.add_argument("--selecionar", action="store_true", help="Seleciona um resultado e inicia o download")

    adicionar = sub.add_parser("queue-add", help="Adiciona uma URL à fila persistente")
    adicionar.add_argument("url")
    adicionar.add_argument("--formato", choices=("mp3", "mp4"), required=True)

    worker = sub.add_parser("worker", help="Processa a fila até esvaziá-la")
    worker.add_argument("--max-tentativas", type=int, default=3)
    worker.add_argument("--intervalo", type=float, default=1.0, help="Pausa entre tentativas de falha, em segundos")

    sub.add_parser("gui", help="Abre a interface gráfica (sem terminal)")

    sub.add_parser("retry-failed", help="Reabre itens que esgotaram as tentativas")
    historico = sub.add_parser("history", help="Exibe downloads e falhas recentes")
    historico.add_argument("--limite", type=int, default=20)
    sub.add_parser("check", help="Verifica se yt-dlp e FFmpeg estão disponíveis")
    return parser


def _progresso_terminal(progresso: Progresso) -> None:
    """Progresso compacto no stderr (não interfere em scripts que leem stdout)."""
    partes = [progresso.etapa]
    if progresso.percentual is not None:
        partes.append(f"{progresso.percentual:.1f}%")
    if progresso.total:
        partes.append(f"de {progresso.total}")
    if progresso.velocidade:
        partes.append(f"a {progresso.velocidade}")
    if progresso.eta:
        partes.append(f"ETA {progresso.eta}")
    print("\r" + " | ".join(partes), end="", file=sys.stderr, flush=True)
    if progresso.percentual is not None and progresso.percentual >= 100:
        print(file=sys.stderr)


def _mostrar_resultados(resultados: list[Any]) -> None:
    if not resultados:
        print("Nenhum resultado encontrado.")
        return
    for indice, item in enumerate(resultados, 1):
        marcador = " [canal verificado pelo extrator]" if item.canal_verificado else ""
        print(f"{indice:>2}. {item.titulo}")
        print(f"    Canal: {item.canal}{marcador} | Duração: {item.duracao_formatada}")
        print(f"    URL: {item.url}")


def main(argv: list[str] | None = None) -> int:
    parser = _criar_parser()
    args = parser.parse_args(argv)

    if args.comando == "gui":
        from interface import main as _main_gui

        return _main_gui()

    try:
        app = Aplicacao()
        app.config.preparar_diretorios()
        if args.comando == "download":
            sucesso, _ = app.baixar(args.url, args.formato,
                                    ao_progresso=_progresso_terminal)
            return 0 if sucesso else 1
        if args.comando == "search":
            resultados = app.pesquisador.pesquisar(args.consulta, args.limite)
            _mostrar_resultados(resultados)
            if args.selecionar and resultados:
                try:
                    indice = int(input("Número do resultado para baixar (0 cancela): ").strip())
                except (ValueError, EOFError):
                    print("Seleção inválida.", file=sys.stderr)
                    return 2
                if indice == 0:
                    return 0
                if not 1 <= indice <= len(resultados):
                    print("Seleção fora da lista.", file=sys.stderr)
                    return 2
                formato = input("Formato [mp3/mp4]: ").strip().lower()
                if formato not in {"mp3", "mp4"}:
                    print("Formato inválido; escolha mp3 ou mp4.", file=sys.stderr)
                    return 2
                sucesso, _ = app.baixar(resultados[indice - 1].url, formato)
                return 0 if sucesso else 1
            return 0
        if args.comando == "queue-add":
            item = app.fila.adicionar(args.url, args.formato)
            print(f"Na fila: {item.id} ({item.formato}) {item.url}")
            return 0
        if args.comando == "worker":
            if args.max_tentativas < 1 or args.intervalo < 0:
                parser.error("--max-tentativas deve ser >= 1 e --intervalo >= 0")
            quantidade = app.processar_fila(
                max_tentativas=args.max_tentativas, intervalo=args.intervalo,
            )
            print(f"Processamento encerrado; downloads concluídos nesta execução: {quantidade}.")
            return 0
        if args.comando == "retry-failed":
            quantidade = app.fila.reabrir_falhas()
            print(f"Itens reabertos: {quantidade}")
            return 0
        if args.comando == "history":
            registros = app.historico.listar(args.limite, incluir_erros=True)
            for registro in registros:
                print(json.dumps(registro, ensure_ascii=False))
            return 0
        if args.comando == "check":
            try:
                for nome, caminho in app.config.verificar_dependencias().items():
                    print(f"[OK] {nome}: {caminho}")
                return 0
            except FileNotFoundError as erro:
                print(f"[ERRO] {erro}", file=sys.stderr)
                return 1
    except (ErroPesquisa, ValueError, OSError, RuntimeError, ImportError) as erro:
        print(f"[ERRO] {erro}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
