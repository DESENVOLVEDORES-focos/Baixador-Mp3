"""Serviços compartilhados pela Central (config, preferências, IA, cookies).

Separado de ``central.py`` para a fachada não repetir o que o
``ControladorInterface`` já fazia bem: leitura/gravação de preferências,
derivação da ``Configuracoes`` do núcleo, cookies do YouTube e chave de IA
(``api.txt``). Nada aqui depende de Tkinter.
"""

from __future__ import annotations

import logging
import os
from dataclasses import replace
from pathlib import Path
from typing import Any

from configuracoes import CONFIG, Configuracoes
from preferencias import (
    Preferencias, aplicar_ao_ambiente, carregar, derivar_configuracoes, salvar,
)

log = logging.getLogger("baixador.central.servicos")


class ServicosBase:
    """Base com o núcleo (``Aplicacao``), preferências e integrações."""

    def __init__(self, configuracoes: Any = None,
                 preferencias: Preferencias | None = None):
        self._base = configuracoes if configuracoes is not None else CONFIG
        self.preferencias = (preferencias if preferencias is not None
                             else carregar(self._base))
        self._aplicar_ambiente(self.preferencias)
        self.config = self.derivar(self.preferencias)
        from musica import Aplicacao

        self.aplicacao = Aplicacao(self.config)
        self.config.preparar_diretorios()

    # -- derivar/ambiente ---------------------------------------------------
    def derivar(self, prefs: Preferencias) -> Configuracoes:
        return derivar_configuracoes(prefs, self._base)

    def _aplicar_ambiente(self, prefs: Preferencias) -> None:
        try:
            aplicar_ao_ambiente(prefs)
        except Exception as erro:  # preferências estranhas não impedem abrir
            log.info("Ambiente não aplicado: %s", erro)

    def caminho_pasta_musicas(self) -> Path:
        return self.config.musicas

    # -- preferências -------------------------------------------------------
    def dicionario_preferencias(self) -> dict[str, Any]:
        return {campo: getattr(self.preferencias, campo)
                for campo in self.preferencias.__dataclass_fields__}

    def salvar_preferencias_campo(self, **campos: Any) -> Preferencias:
        novas = replace(self.preferencias, **campos)
        novas.validar()
        salvar(novas, self._base)
        self.preferencias = novas
        return novas

    # -- cookies do YouTube -------------------------------------------------
    def importar_cookies(self, origem: str | Path):
        from cookies_youtube import importar

        info = importar(origem, self.config)
        self.salvar_preferencias_campo(cookies_caminho=str(info.caminho))
        self.config = self.derivar(self.preferencias)
        self.aplicacao.config = self.config
        return info

    def status_cookies(self):
        from cookies_youtube import status

        return status(self.config)

    def remover_cookies(self) -> bool:
        from cookies_youtube import remover

        removeu = remover(self.config)
        self.salvar_preferencias_campo(cookies_caminho="")
        return removeu

    # -- chave de IA (api.txt) ---------------------------------------------
    def status_chave(self):
        import api_ia

        return api_ia.status(self.config)

    def importar_chave(self, origem: str | Path):
        import api_ia

        info = api_ia.importar(origem, self.config)
        os.environ["BAIXADOR_IA_API_KEY"] = api_ia.ler_chave(self.config)
        self.salvar_preferencias_campo(ia_api_key="")
        return info

    def remover_chave(self) -> bool:
        import api_ia

        removeu = api_ia.remover(self.config)
        if not self.preferencias.ia_api_key:
            os.environ.pop("BAIXADOR_IA_API_KEY", None)
        return removeu

    def testar_chave(self) -> tuple[bool, str]:
        from identificacao_ia import IdentificadorIA

        return IdentificadorIA(self.config).testar_conexao()

    def testar_provedor(self, nome: str) -> tuple[bool, str]:
        """Teste de conexão com iTunes/MusicBrainz/Deezer (usado na tela)."""
        from metadados import criar_processador_padrao

        processador = criar_processador_padrao()
        resultado = getattr(processador, "testar_provedor", None)
        if callable(resultado):
            return resultado(nome)
        return False, "Teste de provedor não disponível nesta instalação."

    # -- dependências/versão ------------------------------------------------
    def versao_ytdlp(self) -> str:
        from atualizacao import versao_instalada

        return versao_instalada(self.config)

    def atualizar_ytdlp(self):
        from atualizacao import atualizar

        return atualizar(self.config)


__all__ = ["ServicosBase"]
