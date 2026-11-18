# Baixador-Mp3

Baixador de músicas (MP3) e vídeos (MP4) para Windows, com interface gráfica,
pesquisa, fila, histórico e enriquecimento automático de metadados e capa.

> **Uso responsável:** baixe somente conteúdo que você tenha autorização para
> baixar. O programa respeita os termos das plataformas e não contorna
> controles de acesso. Cookies são usados apenas para acessar conteúdo da
> **sua própria** conta.

## Instalação no Windows (3 passos)

1. Instale o Python 3.10+ de <https://www.python.org/downloads/windows/>
   marcando **"Add python.exe to PATH"**.
2. Dê **dois cliques em `configurar.bat`** (uma única vez, com internet).
   Ele instala as dependências e baixa `yt-dlp.exe` e `ffmpeg.exe` para
   `ferramentas\`.
3. Dê **dois cliques em `iniciar.bat`**.

Se o FFmpeg não puder ser baixado automaticamente, o instalador avisa: baixe
em <https://ffmpeg.org/download.html> e coloque `ffmpeg.exe` em `ferramentas\`.

## Como usar

1. **Pesquisar**: digite o nome e clique em *Pesquisar*. Selecione o resultado
   (a miniatura aparece ao selecionar).
2. **Formato**: escolha MP3 (música com capa e metadados) ou MP4 (vídeo).
3. **Baixar**: o painel *Downloads* mostra **% , velocidade, tamanho e a etapa
   atual** (Baixando → Convertendo → Gravando metadados).
4. Ao terminar, o MP3 fica em `Musicas\` (ou `Musicas\Artista\Álbum\`, se você
   ligar essa opção) com título, artista, álbum, ano,
   gênero e **capa incorporada** — quando as APIs públicas conseguem
   confirmar a música. Sem confirmação, o arquivo mantém apenas o que o
   próprio vídeo informa e a interface **diz isso explicitamente**.
5. **Já existe?** Por padrão o programa **não sobrescreve**: pergunta e, se você
   aceitar, salva uma cópia com outro nome. A política pode ser mudada em
   Configurações (perguntar / pular / renomear / sobrescrever).

### Ouvir antes de baixar (aba Prévia)

Música de **show** ou versão estendida não precisa mais ser descoberta depois do
download:

- **Conferir dados** mostra título, canal e duração reais do vídeo (sem baixar
  mídia) e avisa quando o título/canal/duração indicam gravação ao vivo,
  festival, versão estendida, remix, cover, slowed ou vídeo sem áudio.
- **Ouvir trecho** baixa 10–40 s e abre no player do Windows. O trecho é
  temporário e apagado ao clicar em "Parar e apagar trecho".
- **Baixar este vídeo** baixa exatamente o que você conferiu.

### Configurações (aba própria)

- **APIs**: chave de IA externa — pode ser **importada de um arquivo**
  (qualquer nome: `api.txt`, `chave.txt`, …), validada, guardada como
  `.baixador\api.txt` e testada na hora. Sem chave, a identificação continua
  funcionando com as APIs públicas. Também há o campo para digitar a chave
  (protegida pelo Windows/DPAPI) e teste de conexão de iTunes, MusicBrainz e
  Deezer (públicas, sem chave).
- **Identificação com IA (opcional)**: com a chave importada, a IA responde
  **Título, Artista, Álbum, Ano, Gênero e Número da faixa** seguindo as regras de
  classificação musical (a lista de gêneros de referência vai no prompt). Ela só
  completa o que as APIs não confirmaram — nunca sobrescreve fato confirmado.
- **Cookies do YouTube**: importe seu `cookies.txt` (formato Netscape). Ele é
  validado, copiado para `.baixador\cookies.txt` e usado automaticamente pelo
  yt-dlp em pesquisas e downloads, sem pedir de novo. Nunca é enviado a
  terceiros, nunca aparece em logs e está no `.gitignore`. Também funciona se
  você simplesmente deixar o `cookies.txt` na pasta do programa.
- **Downloads**: pastas de MP3/MP4, formato e qualidade padrão, número de
  resultados, política de sobrescrita, metadados/capas ligados ou desligados.
- **Nome dos arquivos**: por padrão salva como `Artista - Título.mp3`, sem
  caracteres proibidos no Windows nem marcadores de publicação
  (`Official Video`, `HD`, `Lyrics`). Tags de versão (`Remix`, `Ao Vivo`,
  `Remastered 2011`) são mantidas, porque mudam a faixa. Opcionalmente guarda
  em subpastas `Artista\Álbum`, **somente** quando a identificação confirma o
  álbum — sem confirmação, o arquivo fica na pasta principal.

## Linha de comando (opcional, mesmas funções)

```text
python musica.py check
python musica.py search "nome da música" --limite 10
python musica.py search "nome da música" --selecionar
python musica.py download "https://..." --formato mp3
python musica.py download "https://..." --formato mp4
python musica.py queue-add "https://..." --formato mp3
python musica.py worker
python musica.py gui
```

O arquivo com a chave de IA também é aceito como `api.txt` na pasta do programa
(mesmo esquema do `cookies.txt`). Ele nunca é versionado: está no `.gitignore`.

A CLI mostra o progresso em tempo real no `stderr`; falhas aparecem como
mensagem clara (`[ERRO] ERROR: ...`) e nunca como traceback.

## Pastas e dados

| Pasta/arquivo | Conteúdo |
|---|---|
| `Musicas\` | MP3 finais (qualidade máxima de conversão) |
| `Videos\` | MP4 finais (melhores fluxos; sem recomprimir quando o yt-dlp consegue remuxar) |
| `.baixador\preferencias.json` | configurações (chave de IA protegida) |
| `.baixador\cookies.txt` | cópia gerenciada dos seus cookies |
| `.baixador\fila.json` | fila persistente |
| `.baixador\historico.jsonl` / `erros.jsonl` | histórico e erros (JSON Lines) |
| `.baixador\thumbs\` | cache das miniaturas da pesquisa |

Downloads acontecem numa pasta de trabalho dentro de `.baixador\` e só o
arquivo final é movido para `Musicas\`/`Videos\`: nenhum `.part`/`.m4a`
intermediário fica nas suas pastas.

## Testes

```bash
python -m pip install -r requirements-dev.txt
python -m pyflakes *.py tests/*.py   # deve sair vazio
python -m pytest -q
```

`87 testes` automatizados cobrem, entre outros: download feliz de MP3/MP4 com
yt-dlp simulado, **caminho de erro** (HTTP 404 vira mensagem, não traceback),
prévia (análise de ao vivo, corte do trecho e limpeza),
política de sobrescrita, progresso por etapa, limpeza de intermediários,
miniaturas, cookies, preferências e a integração com metadados/capa.

O CI (`.github/workflows/ci.yml`) roda `pyflakes`, `compileall` e `pytest` em
**Windows e Linux** a cada push.

## O que **não** foi testado nesta máquina

Honestidade vale mais que número de testes: este ambiente de desenvolvimento é
Linux, sem Tkinter, e a rede bloqueia YouTube e as APIs de música. Portanto:

- a **janela real** não foi aberta aqui (a lógica sem tela tem 12 testes);
- identificação musical e capa **reais** não foram executadas (os testes usam
  clientes falsos com respostas reais das APIs);
- download real foi validado com yt-dlp/FFmpeg reais **servindo mídia local**.

Os passos acima devem ser confirmados no seu Windows — veja
[`AUDITORIA.md`](AUDITORIA.md) (checklist da Etapa D).

## Documentação do projeto

- [`AUDITORIA.md`](AUDITORIA.md) — auditoria técnica das etapas anteriores, com defeitos reproduzidos.
- [`COMANDOS.md`](COMANDOS.md) — prompts de comando das próximas etapas.
- [`INTEGRATION.md`](INTEGRATION.md) — contrato `processar_mp3(caminho, metadados)`.
- [`CHANGELOG.md`](CHANGELOG.md) / [`DEVELOPMENT_LOG.md`](DEVELOPMENT_LOG.md) — histórico real do desenvolvimento.
