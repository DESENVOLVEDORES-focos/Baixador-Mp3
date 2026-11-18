# Changelog

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
