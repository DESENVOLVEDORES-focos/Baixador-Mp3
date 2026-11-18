# Changelog

## 2026-11-17 — A pesquisa é dentro do programa: vídeos **e** playlists

Pedido do usuário: *"o yt-dlp tem que pesquisar vídeos e playlist e mostrar lá,
a pesquisa é feita no próprio baixador, por acaso eu tenho que ficar colando
links?"* — razão: playlists só apareciam se ele colasse a URL.

### Mudado

- A busca da aba **Baixar** agora traz **vídeos, playlists e canais juntos**,
  com coluna **Tipo** (*Vídeo*, *Playlist (42 vídeos)*, *Canal*), **Enter para
  pesquisar** e filtro *Tudo / Só vídeos / Só playlists*.
- A busca nativa do yt-dlp (`ytsearch`) só devolve vídeos; para playlists usamos
  a página de resultados do YouTube com o filtro de playlist (`sp=EgIQAw`), que
  o próprio extrator do yt-dlp interpreta. Em *Tudo* as duas buscas rodam em
  paralelo e são mescladas **sem duplicar**; se uma falhar, a outra ainda
  entrega resultados.
- Na aba **Lote / Playlist** existe um campo **Pesquisar playlists**: digite o
  nome, escolha na lista (com contagem de vídeos) e clique em **Listar itens**.
  A URL passou a ser opcional (*Ou a URL da playlist*).
- Novo botão **Abrir playlist** na aba Baixar: pega a playlist do resultado da
  pesquisa, leva para a aba de itens e já lista as faixas. Também há **Usar a URL
  deste resultado**, para quem preferir o campo de download.
- O parâmetro ``tipo`` é retrocompatível: ``pesquisar(consulta)`` continua
  funcionando (padrão ``tudo``).

### Testes

- 258 testes (+15): `tests/test_pesquisa_playlists.py` cobre comando por tipo,
  filtro de playlist, acentos, mesclagem sem duplicar, fallback quando uma das
  buscas falha e classificação de vídeo/playlist/canal; a interface é exercitada
  com Tk simulado (pesquisar, abrir playlist sem link, pesquisar playlists na aba
  Lote e usar a URL do resultado).

## 2026-11-17 — Playlist com seleção, lote e manutenção pela interface

Pedido do usuário: *"poder baixar playlist, selecionar vários vídeos e outras
coisas"* — sem quebrar o fluxo de prévia/identificação que já funcionava.

### Novo: aba **Lote / Playlist**

- **Listar sem baixar nada**: cole a URL de uma playlist, álbum ou canal e clique
  em *Listar* (`--flat-playlist --skip-download --dump-single-json`). A lista
  mostra número, título, duração e situação de cada item.
- **Seleção múltipla de verdade**: Ctrl+clique e Shift+clique na tabela,
  *Selecionar tudo* / *Limpar seleção*, e **"Marcar sem ao vivo/show"**, que
  desmarca de uma vez tudo que tem indício de show, cover ou versão estendida
  (usa o mesmo classificador da Prévia) e também os itens privados/removidos.
- **Playlist inteira** ou **só os marcados**, tanto para *Baixar selecionados*
  quanto para *Adicionar selecionados à fila* / *Playlist inteira na fila*.
- **Colar várias URLs** (uma por linha) no mesmo quadro e baixar tudo de uma vez.
  O campo de URL da aba Baixar também aceita várias linhas/linhas com vírgula.
- **Limite honesto**: até 200 itens por listagem (botão *Listar mais* vai a 500).
  Se a playlist for maior, a tela diz **quantos itens ficaram de fora** — nada de
  fingir que listou tudo.
- Item privado/removido aparece como *privado/removido* e é **pulado**, com motivo
  registrado, em vez de derrubar o lote.
- Progresso **item N de M** durante o lote, e resumo final
  (*"Lote concluído: 28 com sucesso, 2 com falha"*) com o motivo de cada falha.

### Corrigido: playlist era descartada

- `--no-playlist` era fixo em todo download, então colar uma URL de playlist
  baixava **só o primeiro vídeo**. Agora o padrão continua sendo baixar apenas o
  vídeo escolhido (comportamento correto para a busca), mas com
  `--yes-playlist` quando o usuário pede a playlist — explícito nos dois sentidos.
- Cada item listado tem a URL **sem `&list=`**, para que baixar um item da
  playlist não baixe a playlist inteira outra vez.

### Novo: baixar de novo pelo Histórico

- Selecione uma ou mais linhas do **Histórico** e clique em *Baixar de novo*: o
  programa usa a URL original (mesmo que o arquivo tenha sido apagado ou o nome
  mudado), com o mesmo resumo de lote.

### Novo: atualizar o yt-dlp pela própria tela

- Aba **Configurações → MANUTENÇÃO**: mostra a versão em uso e tem o botão
  *Atualizar o yt-dlp agora*. É o conserto mais comum quando o YouTube muda e os
  downloads começam a falhar ("Unable to extract...").
- Atualiza só quando o yt-dlp é o pacote Python (instalação do `configurar.bat`);
  se for um `yt-dlp.exe` na pasta `ferramentas`, **avisa** e diz onde baixar a
  versão nova em vez de mexer no arquivo por baixo dos panos.
- Confere a versão **depois** de atualizar: "já estava na mais nova", "atualizado
  de X para Y" ou "não consegui confirmar" — sem declarar sucesso sem prova.

### Testes

- 243 testes (+52): `tests/test_playlist.py` (heurística de URL, comando sem
  download, itens quebrados, truncamento, seleção por índice),
  `tests/test_lote.py` (playlist inteira, falha isolada não para o lote,
  `--no-playlist` x `--yes-playlist`) e `tests/test_atualizacao.py`
  (versão, falha do pip, exe separado, comando sem shell), além dos novos botões
  exercitados em `tests/test_interface_widgets.py`.

## 2026-11-17 — Chave de IA por arquivo (api.txt) e identificação com 6 campos

Pedido do usuário: poder colocar a chave de API por **arquivo**, como já acontece
com o `cookies.txt`, e usar o prompt de identificação/catalogação musical para
preencher título, artista, álbum, ano, gênero e número da faixa.

### Novo: chave por arquivo (`api_ia.py`)

- Aba **Configurações → "CHAVE DE IA POR ARQUIVO (api.txt)"**, com
  **Selecionar arquivo da chave...**, **Testar chave** e **Remover**.
- **Aceita qualquer nome de arquivo.** O conteúdo pode ser a chave sozinha
  (`sk-...`), `api_key=sk-...`, `OPENAI_API_KEY: ...`, `export ...`,
  `.env`, JSON (`{"api_key": "..."}`) ou linha com comentário `#`.
- Valida **antes de copiar**: texto sem chave reconhecível é recusado com
  mensagem clara (não vira lixo no disco). `api.txt` grande demais também.
- Guarda **cópia gerenciada** em `.baixador\api.txt` com permissão 0600,
  contendo **somente a chave** — comentários e restos do arquivo ficam fora.
- A cópia é sempre `api.txt`: se você escolheu `minha chave.txt`, a interface
  informa que foi **renomeada** para `api.txt`.
- Também funciona se você simplesmente deixar o `api.txt` na pasta do programa.
- **Ao importar, a chave é testada de verdade** na API (chamada mínima) e o
  resultado aparece na hora: válida, 401 (chave recusada), 429 (sem créditos),
  403, modelo inexistente ou falha de rede — sempre em português.
- Nada de segredo em log: registra apenas provedor e máscara
  (`••••••••abcd`). `api.txt` e variações estão no `.gitignore`.

### Novo: identificação musical com os 6 campos (`identificacao_ia.py`)

- Prompt completo de **identificação e classificação musical**, com as regras de
  pesquisa/precisão e a **lista de referência de gêneros** (todas as famílias e
  subgêneros pedidos: rock, metal, pop, eletrônica, hip-hop, R&B/soul, blues,
  jazz, folk/country, reggae, latina/brasileira, clássica, outros).
- Resposta em JSON é lida campo a campo: `"Não identificado"` vira campo vazio
  (nunca tag inventada); ano e faixa são validados; gênero é normalizado para o
  nome canônico quando reconhecível, com no máximo 3 itens ("sem exagerar").
- **Prioridade preservada**: o que iTunes/MusicBrainz/Deezer confirmaram nunca é
  sobrescrito — a IA só preenche lacunas.
- **O que a IA preencheu é dito na tela**: *"Preenchido pela IA de identificação
  (chave em api.txt): album, ano, artista, faixa, genero, titulo."*, e o relato
  separa "confirmado por API" de "vindo da IA" — nada de a IA se passar por API.
- Botão **"Dados musicais (IA)"** na aba Prévia mostra os seis campos na ordem
  pedida (Título, Artista, Álbum, Ano, Gênero, Número da faixa).

### Testes

- `tests/test_api_ia.py`: 28 testes (formatos de chave, renomeação, arquivo
  inválido, status, remoção, mascaramento, prompt com os 6 campos e a lista de
  gêneros, parsing do JSON, erros 401/rede, prioridade API > IA e gravação real
  das tags em MP3).
- Suíte completa: **191 passed, 1 skipped**; `pyflakes` limpo.
- Validação real com servidor local imitando a API: importar arquivo de nome
  diferente → cópia vira `api.txt` → chave testada → MP3 recebe
  `Dois / 1986 / Rock, Pós-Punk, MPB / faixa 2`.

## 2026-11-17 — Prévia antes de baixar (evitar show), nomes longos e erros em português

Pedido do usuário: muitas músicas estão em **shows/ao vivo** e só se percebe
depois de baixar. Agora dá para conferir e ouvir **antes**, sem sujar `Musicas\`.

### Novo: aba "Prévia (ouvir antes)"

- **Conferir dados** consulta o yt-dlp (`-J`, sem baixar mídia) e mostra título,
  canal e duração reais, além de sinalizar *ao vivo agora*, restrição de idade e
  vídeo sem áudio.
- **Análise conservadora de risco** (`previa.analisar`): aponta indícios de
  gravação ao vivo (ao vivo/live/show/tour/festival/concert/unplugged/estádio,
  canal de show, transmissão, duração ≥ 12 min) e de versões que não são a de
  estúdio (extended, remix, cover, instrumental/karaokê, slowed/speed up).
  Sempre diz **qual** foi o indício — nunca afirma "é show" por conta própria.
- **Ouvir trecho**: baixa 10–40 s de áudio (`--download-sections`) e abre no
  player do sistema; o arquivo fica numa pasta temporária em `.baixador` e é
  apagado em "Parar e apagar trecho" ou ao fechar a prévia.
- **Baixar este vídeo** e **Usar resultado selecionado** ligam a prévia à
  pesquisa, para conferir exatamente o item escolhido.

### Corrigido (encontrados em teste real)

- **Nome de arquivo perdia o título**: `"Artista - Título"` estourando 150
  caracteres era cortado pelo fim, apagando o título. Agora o artista é
  abreviado e o título sempre sobrevive.
- **Prévia falhava mesmo com FFmpeg instalado**: o `--download-sections` exige
  `--ffmpeg-location`; sem isso o yt-dlp abortava com *"ffmpeg is not
  installed"* apesar do `ffmpeg.exe` em `ferramentas\`.
- **Primeira execução quebrava a prévia**: a pasta de dados ainda não existia
  quando o `mkdtemp` era chamado (`FileNotFoundError`).
- **Trecho vazio abria um player mudo**: corte em fonte sem duração declarada
  gera arquivo de ~300 bytes; agora é detectado (< 2 KB), descartado e
  explicado. Trecho acima de 4 MB também é descartado.
- **Erro cru do yt-dlp na cara do usuário**: `_mostrar_erro` agora classifica
  (rede, 404, vídeo indisponível, cookies…) e mostra explicação + ação; o texto
  técnico vai sanitizado para o histórico.
- **"Unable to download webpage: TLS…" era tratado como 404**: falha de rede
  agora é classificada como rede, e `Video unavailable` como indisponível.

### Identificação musical: relato honesto do que foi confirmado

- Depois do download, a interface/histórico passam a informar **o que as APIs
  confirmaram** (álbum, ano, gênero), se a **capa** foi incorporada e **quais
  provedores falharam** — em vez de só dizer "concluído".
- Sem confirmação externa, a mensagem é explícita: *"Não confirmado pelas APIs
  de música: as tags usam apenas o título e o canal do vídeo."*
- Para isso, `AdaptadorMetadados.processador_real` expõe o processador com
  estado (antes o adaptador embrulhava a função e o `ultimo_resumo` se perdia) e
  `modulo_metadados` reexporta `criar_processador_padrao`.
- Detectado no caminho: `preferencias.aplicar_ao_ambiente` sempre aponta
  `BAIXADOR_METADATA_MODULE=modulo_metadados` (a fachada), que era justamente
  o caso em que o resumo se perdia.

### Testes

- `tests/test_previa.py`: 24 testes (análise, comandos, execução simulada,
  trecho vazio/grande, limpeza, conversão para MP3).
- Suíte completa: **163 passed, 1 skipped**; `pyflakes` limpo.
- Validação real (FFmpeg + yt-dlp, mídia local): conferir dados, trecho de 15 s
  gerado a partir de um MP3 de 45 s e pasta temporária apagada ao final.

## 2026-11-17 — Identificação pelo resultado escolhido, nome apresentável e diagnóstico de erros

Continuação da etapa anterior, motivada por uso real (yt-dlp 2026.10.26 +
FFmpeg 9.0.2 + Mutagen, mídia servida por HTTP local).

### Novos módulos

- **`contexto.py`** — `ContextoMidia`: leva título, canal, duração, thumbnail e
  URL do **resultado escolhido na pesquisa** até o download e a identificação.
  `normalizar` aceita objeto, dicionário ou nada (nunca estoura) e
  `como_metadados` omite campos vazios — nada de dado inventado.
- **`organizacao.py`** — nome de arquivo portátil: `Artista - Título.ext`,
  removendo caracteres proibidos no Windows, nomes reservados (`CON`, `NUL`,
  `COM1`…), pontos/espaços finais e limitando cada componente a 150 caracteres
  (o limite de caminho do Windows é 260). Também calcula a subpasta
  `Artista/Álbum` e evita colisão (`(2)`).
- **`diagnostico.py`** — traduz a saída técnica do yt-dlp em **situação +
  ação recomendada** (idade, privado, membros, região, cookies vencidos, rede,
  disco cheio, FFmpeg/yt-dlp ausente, URL inválida, já baixado) e **sanitiza**
  URLs com `token=`, `sig=`, `Bearer …` antes de gravar em histórico/log.

### Melhorado

- **Identificação musical usa o resultado escolhido**, não o nome do arquivo:
  título e canal vêm do `ContextoMidia`, a thumbnail do vídeo entra como último
  recurso de capa (depois de iTunes/Deezer, nunca antes) e o resumo informa
  `fonte` (`resultado_da_pesquisa` / `nome_do_arquivo`) e `identificado`.
- **Nome final apresentável**: `(Official Video)`, `[HD]`, `(Lyrics)`,
  `(Legendado)` saem; `[Remix]`, `[Ao Vivo]`, `[Remastered 2011]` **ficam** —
  versão é informação. Cauda técnica do yt-dlp (`[dQw4w9WgXcQ]` ou
  `[título inteiro repetido]`) é removida. `QueenVEVO`/`Queen Official` viram
  `Queen`. O arquivo só é renomeado na **publicação** — a identificação continua
  usando o nome original.
- **Subpastas `Artista/Álbum`** (opcional, desligado por padrão): só com dados
  confirmados pela identificação, só para MP3, e qualquer erro devolve o
  arquivo onde estava. Colisão nunca sobrescreve.
- **Nova aba Configurações**: "Salvar como `Artista - Título.mp3`" e "Guardar em
  subpastas `Artista/Álbum`", sem editar Python.
- **Erros deixam de ser "desconhecido"**: mensagens do próprio núcleo
  (yt-dlp/FFmpeg ausente, URL inválida) também são classificadas.
- **Histórico e `erros.jsonl`** gravam URL e mensagem sanitizadas (credenciais
  fora dos logs).

### Cookies do YouTube

- O `cookies.txt` pode ser importado pela aba **Configurações** (botão
  "Selecionar cookies.txt..."), que valida o formato Netscape, copia para
  `.baixador\cookies.txt` (fora do Git) e mostra quantidade e data de importação.
- **Detecta cookies vencidos**: lê a data de expiração de cada cookie e avisa
  na própria tela e em popup quando **todos** os cookies do YouTube já
  expiraram ("o yt-dlp vai ignorá-los, exporte de novo") ou quando parte deles
  venceu. Era a causa mais comum de "importei e continuou pedindo login" —
  cookies de sessão (`expira = 0`) não são contados como vencidos.
- Depois de importar, o status diz explicitamente **"pronto para usar"** em vez
  de apenas listar a quantidade.
- **Agora também é aceito** o arquivo deixado diretamente na pasta do programa
  (`cookies.txt` ao lado de `iniciar.bat`), sem passar pela interface — era o
  caso mais comum de "coloquei o arquivo e nada aconteceu". Um arquivo em
  formato inválido continua sendo recusado com mensagem clara.
- O `--cookies` é passado ao yt-dlp em downloads **e** pesquisas; o conteúdo
  nunca é exibido, registrado em log nem versionado.

### Testes

- `tests/test_organizacao_contexto.py`: 31 testes cobrindo saneamento de nome,
  limpeza de ruído, cauda técnica, precedência de nome na publicação, subpastas
  com/sem dados, colisão, `ContextoMidia` e classificador de erros.
- Suíte completa: **135 passed, 1 skipped**; `pyflakes` limpo.
- Validação manual real: MP3 (`.m4a` → MP3, tags aplicadas), MP4 320x240,
  repetição do mesmo item (pulado, sem sobrescrever), 404 com mensagem em
  português e organização em `Musicas/Queen/A Night at the Opera/`.

## 2026-11-17 — Etapa A/B (IA 3): correções reproduzidas + interface utilizável

Todas as correções abaixo foram motivadas por defeitos **reproduzidos** com
yt-dlp 2026.10.26 + FFmpeg 9.0.2 + Mutagen reais, servindo mídia por HTTP local
(ver AUDITORIA.md). Nenhuma foi feita "por precaução".

### Corrigido (núcleo)

- **Falha de download virava `NameError`**: `downloader._resumir_erro` usava a
  variável inexistente `line`; qualquer erro (404, vídeo privado, sem internet)
  estourava traceback em vez da mensagem. Corrigido e coberto por teste com
  saída real do yt-dlp.
- **Arquivo existente era sobrescrito**, apesar de `--no-overwrites` e do README
  prometerem o contrário (reproduzido: MP3 de 30569 → 30674 bytes). Agora há
  política explícita (`perguntar`/`pular`/`renomear`/`sobrescrever`), padrão
  **perguntar** na interface e **pular** no núcleo; `--force-overwrites` só
  aparece com autorização. Status próprio `pulado` no histórico.
- **Intermediários poluíam as pastas**: o download agora acontece numa pasta de
  trabalho em `.baixador/` e só o arquivo final é movido para `Musicas/`/
  `Videos/`. Fim dos `.m4a`/`.webm`/`.part` órfãos.
- **"Renomear" contaminava o título** usado na identificação musical (o arquivo
  saía como `titulo (20261118-005140)` e o ano virava tag). A desambiguação
  (`(2)`) passou a ser feita ao publicar, com nome limpo.
- **Sucesso sem arquivo desta execução**: o caminho final é confirmado por
  existência + `mtime` da execução; arquivo antigo no stdout não vira sucesso.
- **`musica.py` quebrava em `typing.get_type_hints`** (`Any` não importado) e
  tinha variável morta.

### Adicionado

- **Progresso real**: `Downloader.baixar(..., ao_progresso=callback, politica=)`
  com leitura linha a linha (`--newline`) e parser de %/tamanho/velocidade/ETA e
  das etapas (baixando, convertendo, mesclando, metadados). A CLI mostra no
  `stderr`; a interface mostra por item. Callback quebrado nunca derruba o
  download.
- **`thumbnail` em `ResultadoPesquisa`** + `thumbs.py` (cache validado por
  assinatura real, limite de tamanho, poda) para a lista de resultados.
- **Interface**: painel de *Downloads* com %, velocidade, tamanho e etapa;
  miniatura do resultado selecionado; coluna "Canal verificado" com evidência;
  duplo clique para baixar; botões para abrir as pastas; **histórico agora
  mostra a data** (antes a coluna ficava sempre vazia por ler uma chave
  inexistente); resumo musical ao concluir ("Artista — Título | Álbum (ano) |
  capa incorporada") e aviso explícito quando a identificação não foi
  confirmada; dica automática de cookies quando o erro indica falta de login.
- **Configuração de sobrescrita** persistente e aviso de data de importação dos
  cookies com rótulo dinâmico (um botão só, em vez de dois iguais).
- `thumbs.py`, `tests/test_erros_e_progresso.py` (20 casos) e
  `tests/test_interface_logica.py` (12 casos).

### Instalação e qualidade

- `configurar.bat` (novo): verifica Python, instala dependências e baixa
  `yt-dlp.exe` e `ffmpeg.exe` para `ferramentas/`, cria as pastas e roda o
  `check`. `iniciar.bat` (novo): entrada única, abre sem console (`pythonw`).
- `requirements.txt` agora inclui **Pillow** (necessário para exibir as
  miniaturas e redimensionar capas); `requirements-dev.txt` para testes.
- **CI** em GitHub Actions rodando `pyflakes`, `compileall` e `pytest` em
  Windows e Linux.
- **87 testes** (eram 54): 53 antigos preservados, 34 novos no caminho de erro,
  progresso, sobrescrita, miniaturas e lógica da interface. `pyflakes` limpo.

### Não testado aqui (registrado, não fingido)

- Janela Tkinter real (este Linux não tem Tkinter), identificação/capa reais e
  download no YouTube (rede bloqueada). Download real de MP3/MP4, progresso,
  falha e política de sobrescrita **foram** executados com yt-dlp/FFmpeg reais
  contra um servidor HTTP local.


## 2026-11-17 — Etapa 1: núcleo modular inicial

- Criados configuração portátil por caminhos relativos e descoberta de yt-dlp/FFmpeg para Windows, PATH ou módulo Python.
- Implementados downloads MP3 (melhor áudio disponível, conversão de qualidade 0) e MP4 (melhores fluxos, mesclagem/remux para MP4), retries, não sobrescrita e verificação do arquivo final.
- Implementada pesquisa via yt-dlp com deduplicação, seleção pelo usuário e marcação/priorização de canal somente com evidência explícita do extrator.
- Implementados fila persistente com retries, recuperação de itens em processamento há mais de seis horas, histórico JSONL, registro separado de erros e comandos CLI de diagnóstico/recuperação.
- Definido adaptador para a IA 2 processar MP3 sem duplicar pesquisa de capas ou edição de tags no núcleo.
- Adicionados README, contrato de integração, dependência yt-dlp, regras de ignorados e 15 testes automatizados com mocks/arquivos temporários.
- Testes: `python -m unittest discover -s tests -v` (15 testes); `compileall` e `python musica.py --help` concluídos sem erro.
- O diagnóstico `check` foi executado e reporta dependências ausentes; yt-dlp/FFmpeg não detectados para download real, portanto nenhum download real foi falsamente declarado como testado.

## 2026-11-17 — Etapa 2 (IA 2): inteligência musical, capas e metadados

- `inteligencia.py`: interpretação de títulos brutos do yt-dlp/vídeo (artista, título, `feat.`, canal `- Topic`) e identificação via APIs públicas sem chave do iTunes, MusicBrainz e Deezer, com pontuação de confiança, limiar de aceitação e mescla apenas de campos da mesma faixa. Álbum/ano/gênero/faixa/gravadora só vêm das APIs — nada é inventado. Assistente de IA opcional (API compatível com OpenAI, via `BAIXADOR_IA_*`) apenas interpreta o título; campos factuais da IA são descartados pelo código.
- `capas.py`: capas oficiais do álbum/single (iTunes 1200x1200, Cover Art Archive/MusicBrainz, Deezer `cover_xl`; thumbnail do YouTube apenas como último recurso), download com limite de tamanho, validação por assinatura e dimensões reais de JPEG/PNG (rejeita HTML e placeholders) e processamento com Pillow quando disponível.
- `metadados.py` + `modulo_metadados.py`: implementam o contrato da IA 1 — `processar_mp3(caminho, metadados)` carregável por `BAIXADOR_METADATA_MODULE=modulo_metadados` (ou `=metadados`), gravando título/artista/álbum/ano/gênero/faixa/gravadora e a capa incorporada (APIC) no próprio MP3 com Mutagen (ID3v2.3). Falhas de API/capa não derrubam o download: resta o título/artista do nome do arquivo.
- Dependências: adicionado `mutagen>=1.47` ao `requirements.txt`; Pillow documentado como opcional para redimensionar/converter capas.
- Testes: `tests/test_ia2.py` com 22 testes novos (identificação, provedores, IA, capas, validação/processamento de imagens, tags/capa incorporada, falhas de APIs e integração via `AdaptadorMetadados`/`BAIXADOR_METADATA_MODULE`), todos com clientes HTTP falsos e arquivos temporários — nenhum acessa a rede. Total: 37 testes aprovados (`python -m unittest discover -s tests -v`).
- Não testado ao vivo: neste ambiente as APIs musicais externas são bloqueadas pela rede do sandbox (somente GitHub/PyPI/NPM liberados) e yt-dlp/FFmpeg seguem ausentes, portanto identificação/capa reais e download real não foram executados nem declarados como testados. O comportamento de falha foi verificado: erros registrados, retorno seguro e MP3 preservado.

## 2026-11-17 — Etapa 3: interface gráfica, configurações e cookies

- `interface.py`: interface Tkinter (sem terminal; no Windows basta `iniciar_interface.bat`) com abas Baixar (pesquisa, URL, MP3/MP4, resultados, progresso, mensagens), Fila, Histórico e Configurações, sobre `ControladorInterface` — lógica separada das janelas, reutilizando núcleo/IA 2 sem duplicar nada. `python musica.py gui` também abre a interface.
- `preferencias.py`: configurações persistentes centralizadas em `.baixador/preferencias.json` (chaves, cookies, pastas de saída, formato/qualidade, metadados/capas), aplicadas ao núcleo e aos módulos via `Configuracoes` derivada e variáveis de ambiente já respeitadas (`BAIXADOR_IA_*`, `BAIXADOR_SEM_CAPA`, `BAIXADOR_METADATA_MODULE`). Chave de IA protegida com DPAPI no Windows (0600 + codificação nos demais sistemas), nunca em texto puro/logs/código. Programa funciona sem nenhuma API configurada; MusicBrainz/iTunes/Deezer seguem públicos e sem chave, com testar conexão na interface.
- `cookies_youtube.py` + integração ao núcleo: importação com validação do formato Netscape, substituição atômica, verificação e remoção; a cópia gerenciada em `.baixador/cookies.txt` é entregue automaticamente ao yt-dlp (`--cookies`) em downloads (`downloader.py`) e pesquisas (`pesquisa.py`, com `construir_comando` isolado), respeitando também pastas/qualidade personalizadas (`configuracoes.py`). Conteúdo de cookies nunca é lido, registrado ou enviado a terceiros; `.gitignore` reforçado.
- `instalar_windows.bat`/`iniciar_interface.bat`: instalação e abertura simplificadas no Windows.
- Testes: `tests/test_etapa3.py` com 17 testes (16 aprovados, 1 de janela pulado por falta de Tkinter/display neste ambiente): salvar/carregar, chave protegida e máscara, importar/substituir/remover cookies, `--cookies` no yt-dlp (download e pesquisa), inicialização sem APIs, integração do controlador com núcleo e MP3 passando por metadados/capa. Total: 54 testes (53 aprovados + 1 pulado).
- Não testado ao vivo: interface gráfica em janela (sem Tkinter/display aqui — código compilado e lógica integralmente testada via controlador), downloads/pesquisas reais no YouTube e testar conexão com as APIs (rede do sandbox bloqueia esses destinos). Nada disso é declarado como testado.
