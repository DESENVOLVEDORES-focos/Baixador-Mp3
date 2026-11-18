
## 2026-11-17 — Etapa A/B (IA 3): auditoria executada, correções e interface utilizável

### Método (diferente das etapas anteriores)
- Ambiente próprio: Python 3.11 + `yt-dlp 2026.10.26` + `ffmpeg n9.0.2`
  (imageio-ffmpeg) + `mutagen` + `Pillow`, instalados de PyPI.
- Como YouTube e APIs de música são bloqueados no sandbox, o download real foi
  validado **servindo mídia local** por `http.server` (`.m4a` 3 s e `.mp4`
  320x240) e apontando o próprio núcleo para ela. Isso exercita yt-dlp, FFmpeg,
  verificação de arquivo, progresso, limpeza e histórico de verdade.
- Cada defeito foi **reproduzido antes** de ser corrigido (ver AUDITORIA.md).

### Reproduções que motivaram as correções
- URL 404 → `NameError: name 'line' is not defined` (traceback) em
  `downloader.py:152`.
- Dois downloads do mesmo item → MP3 regravado (30569 → 30674 bytes) e
  reportado como sucesso, apesar de `--no-overwrites`.
- `typing.get_type_hints` em `musica.py` → `NameError: Any`.
- GUI: coluna "Quando" do histórico vazia (lê `registrado_em`; o histórico grava
  `data_hora`); `ResultadoPesquisa` sem `thumbnail`; barra indeterminada.
- `pyflakes`: 7 avisos, 2 deles bugs reais.

### Implementação
- `downloader.py` reescrito em volta de `Popen` + `--newline`: progresso por
  etapa, `Progresso`/`interpretar_linha`, `ao_progresso`, `politica`
  (pular/renomear/sobrescrever), pasta de trabalho em `.baixador/` e
  `_publicar()` com nome livre; `_resumir_erro` corrigido; `_comunicar` isola a
  conversa com o processo.
- `configuracoes.py`: campo `sobrescrita` (padrão `pular`).
- `musica.py`: `baixar(url, formato, ao_progresso=, politica=)`,
  `[PULADO]`/`[ERRO]` tratados, progresso compacto no `stderr`, `Any` importado,
  variável morta removida, contrato v2 (envia `titulo` ao `processar_mp3`).
- `pesquisa.py`: `thumbnail` (maior disponível; só usa URL canônica do YouTube
  quando não há dado, nunca inventa).
- `interface.py`: painel Downloads (%, velocidade, tamanho, etapa), miniatura
  assíncrona do resultado selecionado, data correta no histórico, resumo
  musical, dica de cookies em erro de login, política de sobrescrita com
  confirmação e oferta de cópia renomeada, botão único de cookies com data,
  `resumo_musical()`/`pasta_dados()` no controlador.
- `thumbs.py` (novo): cache com validação por assinatura de imagem e poda.
- `preferencias.py`: `sobrescrita` persistente e validada.
- Instalação: `configurar.bat` (Python + pip + yt-dlp.exe + ffmpeg.exe + pastas
  + `check`), `iniciar.bat` (entrada única, `pythonw`), `iniciar_interface.bat`
  mantido como compatibilidade; `instalar_windows.bat` removido (substituído).
- `requirements.txt` com Pillow; `requirements-dev.txt`; `.github/workflows/ci.yml`.

### Testes executados (saída real)
- `python -m pyflakes *.py tests/*.py` → vazio.
- `python -m pytest -q` → **87 passed, 1 skipped** (54 anteriores preservados;
  o único skip é a janela Tk, sem Tkinter neste Linux).
- `python -m compileall -q . -x '(\.git|ferramentas)'` → ok.
- Download real MP3: `[OK] .../Musicas/teste [teste].mp3`, progresso
  2.1% → 100% com velocidade e ETA.
- Download real MP4: h264 + aac, duração preservada, sem recompressão.
- Falha real (404): `[ERRO] ERROR: [generic] ... HTTP Error 404`, exit 1, sem
  traceback, registrado em `erros.jsonl`.
- Repetição: `[PULADO] ... nada foi sobrescrito`, arquivo intacto (mesmo mtime e
  tamanho); política `renomear` gerou `teste [teste] (2).mp3` com nome limpo.
- Pastas após todos os testes: apenas `Musicas/teste [teste].mp3` e
  `Videos/video [video].mp4` — zero intermediários.
- Enriquecimento com APIs bloqueadas: MP3 preservado, tags do nome do arquivo,
  `fonte=nome_do_arquivo`, sem inventar álbum/ano/capa.
- `import interface, musica, thumbs...` → ok (a interface não quebra ao importar
  sem Tkinter; `python interface.py` encerra com mensagem clara).

### Dúvida de contrato resolvida
- A IA 2 pediu `titulo`/`canal` no dicionário do `processar_mp3`: o núcleo agora
  envia `titulo` (nome do arquivo sem extensão). `canal` fica pendente porque o
  núcleo não recebe os metadados da pesquisa no fluxo de download — registrado
  para a próxima etapa, sem inventar campo vazio.

### Pendências (não declaradas como prontas)
- Abrir a janela em Windows real e conferir visual/microinterações.
- Identificação musical e capa reais (rede liberada) e download no YouTube.
- Checklist da Etapa D (AUDITORIA.md) no computador do usuário.
- Gerenciador de APIs multi-serviço (Etapa C) ainda não implementado.

# Diário de desenvolvimento

## 2026-11-17 — Etapa 1: inspeção, implementação e testes do núcleo

### Inspeção
- Verificada a branch ativa: `arena/4df082d0-baixador-mp3`; diretório inicialmente limpo além dos arquivos existentes. Remoto `origin` aponta para o repositório Baixador-Mp3.
- No checkout havia somente `README.md` e `oi.txt`; o `musica.py` fornecido não existia como arquivo no checkout. O código colado na solicitação foi usado como referência comportamental, sem substituir os arquivos existentes.
- Ambiente encontrado: Python 3.11.2; pytest não instalado; yt-dlp/FFmpeg não detectados. Os testes unitários foram executados com `unittest`, mocks e arquivos temporários; não foi executado download real.
- A branch desta sessão é fixada pelo Agent Mode. Não foi criada/trocada a branch sugerida `feature/core-downloader`; o trabalho permanece exclusivamente na branch ativa.

### Implementação
- `configuracoes.py`: centraliza caminhos relativos ao projeto, pastas de saída/dados e descoberta de executáveis para Windows/PATH/módulo Python; não exige cookies.
- `downloader.py`: implementa MP3 e MP4 com argv sem shell, retries do yt-dlp, FFmpeg, nome contendo ID, `--no-overwrites`, conversão MP3 qualidade 0 e remux MP4. Confirma arquivo final com extensão e tamanho válidos; não usa limpeza ampla nem marca saída ausente como sucesso.
- `pesquisa.py`: usa `ytsearch`, limita e deduplica resultados; canal verificado só é priorizado quando o extrator retorna flag booleana explícita.
- `fila.py`: mantém fila JSON persistente com gravação atômica, deduplicação ativa, estados, retries/reabertura de falhas e recuperação de itens processando há mais de seis horas após encerramento abrupto.
- `historico.py`: grava eventos JSON Lines e mantém erros de download/integração em arquivo separado.
- `integracao.py`: define `ProcessadorMetadados.processar_mp3(caminho, metadados)` e carregamento opcional por `BAIXADOR_METADATA_MODULE`; falha na IA 2 não remove o MP3 já baixado.
- `musica.py`: adiciona CLI para pesquisar/selecionar, baixar, enfileirar, processar fila, consultar histórico, reabrir falhas e verificar ferramentas.
- `tests/test_core.py`: adiciona testes para segurança de URL/argv, confirmação de arquivo, busca, marcação verificada, fila/retries, histórico e interface de metadados.
- `README.md`, `INTEGRATION.md`, `requirements.txt`, `.gitignore`, `CHANGELOG.md`: documentam instalação, uso, limite de responsabilidade, interface externa e arquivos locais ignorados.

### Decisões e problemas tratados
- Ausência de `musica.py` real: criado ponto de entrada novo usando o código incluído na solicitação como referência.
- Busca não inventa resultados nem presume canal oficial pelo nome; ordena verificados apenas com evidência explícita do extrator.
- MP4 recebe `--remux-video mp4` além da mesclagem para garantir contêiner MP4 também no fallback de fluxo único compatível.
- Arquivos parciais são mantidos pelo comportamento padrão do yt-dlp para retomada; somente arquivo final não vazio é considerado concluído.
- Branch sugerida não pode ser selecionada porque o ambiente fixa a branch da sessão; não foi alterada `main` nem branch da IA 2.

### Testes executados
- `python -m unittest discover -s tests -v`: 15 testes aprovados.
- `python -m compileall -q configuracoes.py downloader.py pesquisa.py fila.py historico.py integracao.py musica.py tests`: passou.
- `python musica.py --help`: passou e apresentou os subcomandos.
- `git diff --check`: sem erros de whitespace.
- Download real MP3/MP4: não executado, pois yt-dlp e FFmpeg não estão instalados/detectados no ambiente.

### Pendências
- Revisar diff integral, fazer commits descritivos por etapa e enviar apenas para a branch ativa; confirmar sucesso do push.
- Teste manual de download requer yt-dlp, FFmpeg e conteúdo com permissão de download.
- Coordenar a implementação concreta da IA 2 para validar o adaptador de metadados em conjunto.
- Avaliar recuperação de itens que permaneçam em estado `processando` após encerramento abrupto do processo e coordenação para múltiplos workers.

## 2026-11-17 — Etapa 2 (IA 2): inspeção do núcleo, metadados/capas e integração

### Inspeção
- Lidos `INTEGRATION.md`, `integracao.py`, `musica.py`, `configuracoes.py`, `downloader.py`, `pesquisa.py`, `fila.py`, `historico.py`, `tests/test_core.py`, `requirements.txt`, `README.md`, `CHANGELOG.md` e este log na branch da IA 1 (`arena/4df082d0-baixador-mp3`, até `930146d`).
- Contrato confirmado: `ProcessadorMetadados.processar_mp3(caminho, metadados) -> Path | None`; retorno `None` = enriquecer no próprio caminho; carregamento sem editar o núcleo por `BAIXADOR_METADATA_MODULE` expondo `processar_mp3(caminho, metadados)`; `metadados` do núcleo traz `url`, `formato`, `caminho`, `inicio`, `conclusao` (sem título/canal — por isso a IA 2 interpreta o nome do arquivo gerado pelo yt-dlp, `"%(title).180B [%(id)s].%(ext)s"`).
- Feito merge da branch da IA 1 na branch desta sessão (`arena/58df5ecb-baixador-mp3`) — branch independente da IA 1, conforme a Etapa 1 já registrou: a branch da sessão é fixada pelo Agent Mode, então não foi criada a sugerida `feature/music-metadata` nem tocada a `main`/branch da IA 1.
- Ambiente: Python 3.11.2; rede do sandbox libera apenas GitHub/PyPI/NPM (APIs musicais bloqueadas com erro TLS); `mutagen 1.48.1` e `Pillow` instalados via PyPI somente para os testes locais.

### Implementação
- `inteligencia.py`: `analisar_titulo` (remove `[id]` do nome do arquivo, ruídos como "(Official Video)"/"[HD]", extrai `feat.`, usa canal `- Topic` como artista), `InfoMusica`, cliente HTTP stdlib injetável, provedores iTunes/MusicBrainz/Deezer com confiança (similaridade normalizada sem acentos) e mescla restrita à mesma faixa; IA opcional compatível com OpenAI restrita a interpretar o título.
- `capas.py`: ordem iTunes 1200 → Cover Art Archive (`front-1200` pelo ID do lançamento) → Deezer `cover_xl` → thumbnail do YouTube como último recurso não-oficial; validação por magic bytes + dimensões PNG (IHDR) e JPEG (SOF) sem depender de Pillow; processamento opcional com Pillow (máx. 1200px, JPEG q90).
- `metadados.py`: Mutagen ID3v2.3 (TIT2/TPE1/TPE2/TALB/TDRC/TCON/TRCK/TPUB/TSRC + APIC capa frontal), apenas campos conhecidos; `ProcessadorMusical.processar_mp3` orquestra identificar → capa → gravar, devolve `None` e nunca perde o download por falha de API/capa. `modulo_metadados.py` é a fachada indicada no exemplo do `INTEGRATION.md`.
- `requirements.txt`: `mutagen>=1.47`; Pillow apenas comentado como opcional.

### Decisões e problemas tratados
- O núcleo não entrega título/canal no dicionário de integração; a fonte primária passa a ser o nome do arquivo do yt-dlp, que embute o título original — documentado aqui para a IA 1 avaliar incluir `titulo`/`canal` no futuro, sem quebrar o contrato atual.
- APIs externas bloqueadas no sandbox: implementadas contra fixtures no formato real das respostas e clientes injetáveis; a tentativa ao vivo foi executada, falhou por rede (TLS) nos 3 provedores, foi registrada em `ultimos_erros` e o retorno seguro (`None` + fallback pelo nome do arquivo) foi confirmado — nada disso é declarado como "testado ao vivo".
- JPEG de teste inicial tinha menos de 100 bytes e foi rejeitado pelo validador (correto); a fixture foi ajustada com segmento COM, sem afrouxar a validação.

### Testes executados
- `python -m unittest discover -s tests -v`: 37 testes aprovados (15 do núcleo da IA 1 sem regressão + 22 da IA 2).
- `python -m compileall -q inteligencia.py capas.py metadados.py modulo_metadados.py tests`: passou.
- Verificação manual com MP3 temporário: tags ID3 e APIC gravados e relidos pelo Mutagen (título/artista/álbum/ano/gênero/faixa/gravadora/capa), e PNG real 600x600 gerado, validado e processado.

### Pendências
- Teste ao vivo (identificação + capa reais e download real via núcleo) requer rede liberada para MusicBrainz/iTunes/Deezer/YouTube e yt-dlp/FFmpeg instalados.
- Sugestão à IA 1: incluir `titulo`/`canal`/`duracao` no dicionário enviado a `processar_mp3` em versão futura do contrato, para identificação ainda mais precisa que o nome do arquivo.

## 2026-11-17 — Etapa 3: integração, interface gráfica e configurações

### Inspeção
- Relidos README, INTEGRATION, CHANGELOG, este log, `integracao.py` e `configuracoes.py`, e conferidas as branches: IA 1 segue em `930146d` (sem mudanças desde o merge da Etapa 2); nenhuma interface gráfica existia (`grep` por tkinter/gui vazio). Tkinter não existe no Python deste sandbox (Linux sem `python3-tk`) — a GUI é Tkinter porque acompanha o Python oficial no Windows e não adiciona dependências.

### Implementação
- `preferencias.py`: `Preferencias` + salvar/carregar atômico em `<dados>/preferencias.json`; cofre com DPAPI via `ctypes` (`CryptProtectData`) no Windows e codificação + `chmod 0600` nos demais; `mascarar_segredo` para a interface; `aplicar_ao_ambiente` (mesmas variáveis que IA 1/IA 2 já respeitam) e `derivar_configuracoes`.
- `configuracoes.py` (IA 1, adições retrocompatíveis): campos opcionais `diretorio_musicas/diretorio_videos/caminho_cookies/qualidade_mp3`, propriedades `musicas/videos` respeitando a preferência, `resolver_cookies()` (configurado → `BAIXADOR_COOKIES` → `<dados>/cookies.txt`) e `argumentos_cookies()` tolerante aos fakes de teste existentes. Os 15 testes da IA 1 seguem passando.
- `cookies_youtube.py`: validação Netscape (7 campos/tabulação, `#HttpOnly_`, contagem total/YouTube sem expor conteúdo), importação validada com cópia atômica e 0600, status e remoção.
- `downloader.py`: `*argumentos_cookies(...)` e `--audio-quality` vindo das preferências (padrão `"0"`, comportamento original). `pesquisa.py`: `construir_comando()` isolado com os mesmos cookies. `musica.py`: `Aplicacao()` sem config explícita carrega as preferências (CLI também respeita cookies/pastas/chaves salvas) e novo subcomando `gui`.
- `interface.py`: `ControladorInterface` (toda a lógica, sem Tkinter, reutilizando `Aplicacao/FilaDownloads/Historico` e o adaptador de metadados) + `AplicativoGrafico` (abas Baixar/Fila/Histórico/Configurações rolável, tarefas em thread com barra de progresso, mensagens de sucesso/erro; Configurações com APIs — chave com mostrar/ocultar/salvar/testar e estado — provedores públicos sem chave com testar, COOKIES DO YOUTUBE com selecionar/substituir/verificar/remover e aviso de credencial, e Downloads com pastas/formato/qualidade/limite/metadados/capas).
- `instalar_windows.bat` e `iniciar_interface.bat`; `.gitignore` com `**/cookies.txt`, `**/preferencias.json` e afins (a pasta `.baixador/` já era ignorada).

### Decisões e problemas tratados
- Não existe IA 3 separada: a Etapa 3 foi executada pela mesma sessão (IA 2), na branch fixa `arena/58df5ecb-baixador-mp3`, sem tocar `main` nem a branch da IA 1.
- Segredos: DPAPI real no Windows; fora dele não há cofre do SO disponível sem dependências, então o arquivo fica restrito (0600) dentro de `.baixador/` (ignorado pelo Git) e isso está documentado — nenhum segredo em código-fonte.
- Conflitos entre IA 1/IA 2: nenhum funcional encontrado; o único atrito histórico (núcleo não enviar título/canal ao `processar_mp3`) segue contornado pelo nome do arquivo, sem mudar o contrato.

### Testes executados
- `python -m unittest discover -s tests`: 54 testes — 53 aprovados, 1 pulado (`TestJanelaTk`, sem Tkinter/display neste ambiente; a máscara da chave é testada via `mascarar_segredo` e o `show="•"` é lógica padrão do widget).
- `python -m py_compile interface.py preferencias.py cookies_youtube.py`: passou; `python interface.py` sem Tkinter encerra com mensagem clara (exit 1) em vez de traceback; `python musica.py --help` lista o novo `gui`.
- Não executados (registrado, não fingido): abertura real da janela, downloads/pesquisas reais no YouTube e testar conexão ao vivo — rede/display/yt-dlp/FFmpeg indisponíveis neste sandbox.

### Pendências
- Validar a janela em um Windows real (dois cliques no `.bat`) e o DPAPI nesse sistema.
- Mesma pendência da Etapa 2: teste ao vivo completo com rede liberada e yt-dlp/FFmpeg.

## 2026-11-17 — Identificação pelo resultado escolhido, nomes e diagnóstico

### Método
- Mesmo ambiente da etapa anterior (yt-dlp 2026.10.26, FFmpeg 9.0.2 via
  imageio-ffmpeg, Mutagen, Pillow), mídia por `http.server` local.
- Cada melhoria foi validada baixando de verdade; os defeitos abaixo apareceram
  **no teste real**, não em revisão de código.

### Defeitos encontrados durante a validação real
1. `yt-dlp não encontrado` caía em "erro desconhecido" → classificador passou a
   reconhecer mensagens do próprio núcleo (yt-dlp/FFmpeg ausente, URL inválida).
2. `Queen - Bohemian Rhapsody (Official Video)` saía com o nome inteiro, sem
   limpeza → `limpar_titulo_video` remove marcadores de publicação e preserva
   tags de versão.
3. Nome do arquivo com título repetido entre colchetes gerava
   `Queen - Bohemian Rhapsody Queen - ...` → cauda técnica removida.
4. `nome_arquivo` prefixava o artista quando o título já começava por ele
   (`Queen - Queen - …`) → comparação sem diferenciar maiúsculas.
5. Primeira versão da limpeza apagava `(Ao Vivo em SP)` — informação musical
   real. Lista de ruídos separada da lista de versões resolve.

### Decisões
- **Renomear só na publicação** (`_publicar`), nunca antes do download: o nome
  do arquivo é pista de identificação.
- **Contexto vence o nome do arquivo** na identificação, mas o nome do arquivo
  ainda manda na hora de montar o nome final quando já é `Artista - Título`.
- **Subpastas por álbum são cosméticas**: nunca podem custar um download —
  qualquer exceção devolve o caminho original.
- **Nada de credenciais em log**: `Historico.registrar` sanitiza URL e mensagem;
  teste confere que um segredo plantado não aparece no arquivo.

### Verificação
- `pytest -q`: 128 passed, 1 skipped, 8 subtests; `pyflakes` limpo.
- Manual: `Musicas/Queen - Bohemian Rhapsody.mp3` (nome e tags corretos),
  `Videos/Video Clip - Cena Legal.mp4`, segundo download do mesmo item
  **pulado**, 404 → "O endereço não existe mais…", subpasta
  `Musicas/Queen/A Night at the Opera/` quando há álbum confirmado.

### Cookies: verificação de ponta a ponta
- `importar_cookies` → status → `argumentos_cookies` conferidos com um
  `cookies.txt` Netscape real: a cópia vai para `.baixador\cookies.txt`, o
  status mostra `3 cookie(s), 3 do YouTube/Google` e o yt-dlp recebe
  `--cookies <caminho>`. Download real de `.m4a` → MP3 concluído com essa flag.
- A contagem "do YouTube" inclui `google.com` de propósito (cookies de sessão
  do Google são necessários junto com os do YouTube).
- Defeito encontrado no uso: arquivo largado na pasta do programa era ignorado.
  `resolver_cookies` passou a considerá-lo e `status` também.
- Teste de regressão: `TestCookiesNaPasta` (3 casos: solto na pasta, inválido,
  ausente).
