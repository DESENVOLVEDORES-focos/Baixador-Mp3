# Baixador-Mp3

Núcleo em Python para pesquisar conteúdo e baixar áudio MP3 ou vídeo MP4 por meio do `yt-dlp` e do FFmpeg. O uso deve respeitar os termos das plataformas e os direitos autorais; use somente conteúdo que você tenha autorização para baixar. O programa não usa cookies nem tenta contornar controles de acesso.

## Requisitos

- Python 3.10 ou superior.
- `yt-dlp` instalado (`python -m pip install -r requirements.txt`) ou executável na pasta `ferramentas`.
- FFmpeg instalado e disponível no `PATH`, ou `ffmpeg.exe`/`ffmpeg` na pasta `ferramentas`.

O programa não baixa binários automaticamente. Verifique a origem e a licença dos executáveis que instalar.

## Comandos

```text
python musica.py check
python musica.py search "nome da música" --limite 10
python musica.py search "nome da música" --selecionar
python musica.py download "https://..." --formato mp3
python musica.py download "https://..." --formato mp4
python musica.py queue-add "https://..." --formato mp3
python musica.py worker
python musica.py history --limite 20
python musica.py retry-failed
```

A pesquisa retorna resultados obtidos pelo yt-dlp, sem inventar títulos/canais. Canais só são priorizados/marcados como verificados quando o extrator fornece um campo explícito de verificação; o texto do nome do canal não é tratado como prova. `search --selecionar` mostra resultados e pede a seleção antes de baixar. Para automação, use `queue-add` e depois `worker`. Execute somente um worker por vez; itens marcados como processando por mais de seis horas são recuperados automaticamente quando o worker inicia.

## Pastas e dados

- `Musicas/`: MP3 extraído com qualidade de conversão máxima (`--audio-quality 0`) e metadados básicos do extrator.
- `Videos/`: MP4 com os melhores fluxos disponíveis; quando necessário, yt-dlp/FFmpeg combina áudio e vídeo sem recomprimir fluxos compatíveis.
- `.baixador/fila.json`: fila persistente.
- `.baixador/historico.jsonl` e `.baixador/erros.jsonl`: registros estruturados. O caminho pode ser alterado com `BAIXADOR_DATA_DIR`.

Os arquivos baixados, os executáveis locais e os dados pessoais não devem ser commitados. O padrão de saída inclui o ID do conteúdo para reduzir colisões. Arquivos existentes não são sobrescritos. O yt-dlp mantém arquivos `.part` enquanto um download está incompleto para poder retomá-lo; o núcleo só registra sucesso depois de confirmar um arquivo final não vazio.

## Integração com IA 2

Veja [`INTEGRATION.md`](INTEGRATION.md) para o contrato `processar_mp3(caminho, metadados)` e a configuração opcional `BAIXADOR_METADATA_MODULE`. Sem o módulo, o núcleo conclui o MP3 e mantém a integração desativada.

## Testes

```text
python -m unittest discover -s tests -v
```

Os testes usam arquivos temporários e mocks; não executam downloads reais nem precisam de FFmpeg.
