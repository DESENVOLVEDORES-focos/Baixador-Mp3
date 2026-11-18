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
3. Dê **dois cliques em `iniciar.bat`** — abre a **Central Musical**.

> A interface antiga (por abas) continua disponível em
> `iniciar_interface.bat` ou `python main.py --classica`. Nada foi removido.

Se o FFmpeg não puder ser baixado automaticamente, o instalador avisa: baixe
em <https://ffmpeg.org/download.html> e coloque `ffmpeg.exe` em `ferramentas\`.

## Central Musical (tela principal)

Uma janela só, com barra lateral fixa à esquerda e o **player sempre no rodapé**:

| Página | O que faz |
| --- | --- |
| **Início** | Totais da biblioteca, downloads em andamento, últimos adicionados, atalhos |
| **Pesquisar** | Busca dentro do programa (vídeos + playlists + canais), abrir playlist, prévia, cesta |
| **Playlists** | Playlists locais: criar, renomear, excluir, reordenar, adicionar da biblioteca, tocar |
| **Fila de downloads** | Estados em tempo ao vivo, pausar/retomar/cancelar, repetir falhas, cesta reordenável |
| **Biblioteca** | Lista e grade com capas, filtros por artista/álbum/gênero, favoritar, editar tags, excluir, duplicatas |
| **Artistas / Álbuns** | Navegação por artista e álbum, com contagem, duração e atalho para tocar |
| **Histórico** | Tudo o que foi baixado, com status, motivo honesto e rebaixar |
| **Favoritos** | Músicas, artistas e álbuns favoritos (salvos no banco) |
| **Configurações** | Tema, fonte, pasta, qualidade, concorrência, identidade visual, cookies, chave de IA, yt-dlp, FFmpeg, normalização e diagnóstico |

O que vale saber:

- **A cesta é acumulativa**: marque músicas numa pesquisa, troque de página,
  pesquise outra coisa e marque mais — os itens ficam. A cesta mostra origem,
  duração total e sobrevive a fechar e abrir o programa. Dá para reordenar,
  remover e limpar antes de baixar.
- **Cada download passa por estados visíveis**: *aguardando → processando →
  convertendo → metadados → concluído* (ou *pausado*, *falhou* com o motivo).
  Você pode baixar de 1 a 4 ao mesmo tempo.
- **Nada é dado como concluído sem conferência**: o MP3 final é aberto pelo
  FFmpeg e, se você ligar a opção, o volume é normalizado (EBU R128, −16 LUFS).
- **A biblioteca é um banco local** (`<dados>\biblioteca.db`) montado a partir
  das tags dos arquivos: fechar e abrir mantém tudo, e a pasta pode ser
  reindexada a qualquer momento sem duplicar.
- **Sem invenção**: quando as fontes públicas e a IA não confirmam um campo, ele
  fica vazio e a tela diz o que não foi confirmado. Capa duvidosa não é
  incorporada — a busca de capa **mostra as opções antes de gravar** e você
  escolhe (ou cancela sem alterar o arquivo).
- **Pesquisa limpa**: repetidos do mesmo canal são escondidos (com a contagem
  do que foi escondido), compilados de 1 h ou mais aparecem marcados e podem ser
  ocultados, e cada resultado mostra ficha e miniatura ao ser selecionado.
- **Player completo no rodapé**: barra clicável para pular, Espaço para pausar,
  Ctrl+←/→ para avançar/voltar 10 s, Ctrl+↑/↓ para o volume. Volume, repetição
  e a última fila voltam quando você abre o programa de novo.
- **Metadados de verdade**: além de título/artista/álbum/ano/gênero/faixa, o MP3
  recebe compositor, disco/total, ISRC, a origem (`fonte`, URL do vídeo) e, se
  você ligar, **ReplayGain medido** com o FFmpeg.
- **Nada se perde de vista**: toda mensagem e todo erro aparecem no botão
  **Mensagens** (e ficam em `.baixador\app.log`) — não é preciso abrir terminal.

## Como usar (fluxo rápido)

1. **Pesquisar**: digite o nome no campo de pesquisa e aperte **Enter** (ou
   *Pesquisar*). A pesquisa é feita **dentro do programa** e traz **vídeos e
   playlists** juntos — a coluna *Tipo* mostra o que é cada linha
   (*Vídeo*, *Playlist (42 vídeos)*, *Canal*). **Não é preciso colar link.**
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

### Playlists e vários vídeos (aba Lote / Playlist)

Serve para baixar uma **playlist inteira** ou **escolher só alguns vídeos** dela:

0. **Ache a playlist pelo nome**: digite na busca da própria aba e clique em
   **Pesquisar playlists** (nada de link). Escolha uma na lista e clique em
   **Listar itens** — ou, na aba *Baixar*, marque uma linha do tipo *Playlist* e
   use **Abrir playlist**.
1. Se você já tem a URL, também pode colá-la no campo *Ou a URL da playlist* e
   clicar em **Listar itens**. Nada é baixado nessa etapa: aparece a lista com
   duração e situação de cada item (itens privados/removidos são marcados e
   ficam fora).
2. Escolha o que baixar: **Ctrl+clique** / **Shift+clique**, ou
   **Selecionar tudo**, ou **"Marcar sem ao vivo/show"** (descarta de uma vez o
   que tem cara de gravação ao vivo, cover, versão estendida e remix).
   Playlists longas avisam quantos itens ficaram fora do limite (200; o botão
   *Listar mais* vai até 500).
3. Clique em **Baixar selecionados** ou **Adicionar selecionados à fila**. Se
   preferir tudo, use **Playlist inteira na fila**.

Também é possível **colar várias URLs de uma vez** (uma por linha, no quadro de
baixo ou no próprio campo de URL da aba Baixar): o programa mostra *item N de M*
e, no fim, um resumo com o motivo de cada falha — **um link quebrado não
interrompe os outros**.

### Baixar de novo e manter o yt-dlp atualizado

- **Histórico → Baixar de novo**: usa a URL original do que já foi baixado, mesmo
  que o arquivo tenha sido apagado ou renomeado.
- **Configurações → MANUTENÇÃO**: mostra a versão do yt-dlp e tem
  **Atualizar o yt-dlp agora**. Se algum dia os downloads pararem de funcionar
  ("Unable to extract..."), é o primeiro botão a clicar.

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
| `.baixador\biblioteca.db` | biblioteca SQLite (a fonte de verdade das músicas) |
| `.baixador\app.log` | log do botão **Mensagens** (o que apareceu na tela) |
| `.baixador\thumbs\` | cache das miniaturas da pesquisa |
| `Capas\` | capas baixadas que ainda não foram gravadas no MP3 |

> A pasta `.baixador\` começa com ponto, então o Explorer e o `dir` a escondem.
> Use `dir /a` no cmd ou marque "Itens ocultos" no Explorer para vê-la. Ela é
> criada na **primeira vez que o programa abre**, não pelo `configurar.bat`.

Downloads acontecem numa pasta de trabalho dentro de `.baixador\` e só o
arquivo final é movido para `Musicas\`/`Videos\`: nenhum `.part`/`.m4a`
intermediário fica nas suas pastas.

## Estrutura do projeto

O código está num pacote (`baixador/`), separado por responsabilidade — nada
mais solto na raiz além da entrada `main.py` e dos `.bat`:

```
main.py                 entrada (Central Musical; --classica abre a antiga)
baixador/
  nucleo/               configuração, preferências, biblioteca, fila,
                        histórico, limites, organização de arquivos
  midia/                MP3/ID3/ReplayGain, capas, prévia, reprodutor
  web/                  pesquisa, playlists, download (yt-dlp), cookies, IA
  app/                  Central Musical (central_app.py), interface clássica
                        (interface.py) e os serviços que ligam tudo
tests/                  suite (pytest) — 578 testes
ferramentas/            ffmpeg.exe / yt-dlp.exe (baixados pelo configurar.bat)
```

Cada pacote tem `__init__.py` com um resumo do que mora nele. Imports são
absolutos (`from baixador.web import pesquisa`), então nada depende de rodar a
partir de uma pasta específica.

## Testes

```bash
python -m pip install -r requirements-dev.txt
python -m pyflakes main.py baixador tests   # deve sair vazio
python -m pytest -q
```

**578 testes automatizados** (94 subtestes) cobrem, entre outros: download de
MP3/MP4 com yt-dlp simulado, **caminho de erro** (HTTP 404 vira mensagem, não
traceback), prévia (ao vivo, corte do trecho, limpeza), política de sobrescrita,
progresso por etapa, miniaturas, cookies, preferências, a integração com
metadados/capa, a **Central Musical** (biblioteca SQLite, cesta, playlists,
fila, reprodutor, filtros, paginação), **ID3 estendido e ReplayGain com MP3
gerado pelo FFmpeg**, validação do JSON da IA, deduplicação da pesquisa e o
**fluxo real de ponta a ponta** (`tests/test_integracao_real.py`).

Há ainda um teste que **clica nos 96 botões** das 10 páginas, com biblioteca e
rede vazias, e falha se algum levantar exceção (`tests/test_botoes_vivos.py`):
é a garantia contra botão decorativo.

Como rodar os testes (opcional, para quem quiser conferir):

```
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

O CI (`.github/workflows/ci.yml`) roda `pyflakes`, `compileall` e `pytest` em
**Windows e Linux** a cada push.

## O que **não** foi testado nesta máquina

Honestidade vale mais que número de testes: o ambiente de desenvolvimento é
Linux, sem Tkinter, e a rede bloqueia YouTube e as APIs de música. Portanto:

- a **janela real** (Tkinter) não foi aberta aqui: a lógica de tela é testada
  com um Tk simulado que registra cada widget e permite *clicar* os botões;
- identificação musical, capa e IA **reais** não foram executadas (os testes
  usam clientes falsos com respostas no formato real das APIs; a validação do
  JSON da IA e o fallback de provedor são testados);
- download real foi validado com yt-dlp/FFmpeg reais **servindo mídia local**;
- **o `ffplay` não existe neste ambiente**, então o áudio não foi ouvido: o
  reprodutor é testado na montagem do comando, no seek e no estado persistido.

Nada disso depende de editar arquivos: abra `iniciar.bat` e use as páginas.
Os passos a confirmar no seu Windows estão em [`AUDITORIA.md`](AUDITORIA.md).

## Documentação do projeto

- [`AUDITORIA.md`](AUDITORIA.md) — auditoria técnica das etapas anteriores, com defeitos reproduzidos.
- [`COMANDOS.md`](COMANDOS.md) — prompts de comando das próximas etapas.
- [`INTEGRATION.md`](INTEGRATION.md) — contrato `processar_mp3(caminho, metadados)`.
- [`CHANGELOG.md`](CHANGELOG.md) / [`DEVELOPMENT_LOG.md`](DEVELOPMENT_LOG.md) — histórico real do desenvolvimento.
