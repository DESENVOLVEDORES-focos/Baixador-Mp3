"""Baixador-Mp3 — pacote principal.

Organização dos módulos:

- :mod:`baixador.nucleo` — configuração, preferências, biblioteca, fila,
  histórico, limites e organização de arquivos (nada abre janela nem rede).
- :mod:`baixador.midia`  — áudio (MP3, ID3, ReplayGain), capas, prévia e
  reprodutor.
- :mod:`baixador.web`    — pesquisa, playlists, download (yt-dlp), cookies e
  identificação musical por IA.
- :mod:`baixador.app`    — as duas interfaces (Central Musical e a clássica) e
  os serviços que conversam com tudo acima.

A entrada fica em ``main.py``, na raiz do projeto.
"""

__version__ = "6.0"
