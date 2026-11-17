# COMANDOS — prompts prontos para comandar as IAs

Documento operacional da IA 3 (sessão de comando). Cada bloco abaixo é **copiável** e vai direto
para a IA responsável. Cada um termina com *Definição de pronto* (o que vou checar) e *Proibido*
(o que não pode acontecer).

Base factual: [`AUDITORIA.md`](AUDITORIA.md). Branch de integração: `arena/58df5ecb-baixador-mp3`
(única com o projeto inteiro). Nunca trabalhar na `main`.

---

## REGRAS GERAIS (valem para todas as IAs, em todo prompt)

```
1. Trabalhe SOMENTE na sua branch fixa. Nunca na main. Nunca em branch de outra IA.
2. Não reescreva arquivo que não é seu escopo. Se precisar mudar um arquivo da outra IA,
   faça a menor alteração possível, retrocompatível, e registre em DEVELOPMENT_LOG.md
   ("mudança no arquivo X da IA N: motivo, linha, teste que cobre").
3. Não declare nada como "testado" sem colar a saída real do comando. "Não testado por
   limitação do ambiente" é uma resposta aceitável e esperada; "funciona" sem prova não é.
4. Toda correção de bug entra com um teste que FALHA antes da correção e passa depois.
   Cole as duas saídas no relatório.
5. Antes de encerrar: `python -m pyflakes *.py tests/*.py` deve sair VAZIO e
   `python -m pytest -q` deve passar 100%. Cole a saída.
6. Nunca commitar: cookies.txt, preferencias.json, .baixador/, Musicas/, Videos/,
   chaves de API, tokens. Se aparecer no diff, remova antes do commit.
7. Encerrar com: commits enviados (hashes reais), o que ficou pendente, e uma mensagem
   em ia1.txt (se você é a IA 1) / ia2.txt (se você é a IA 2) para a outra IA.
```

---

## ETAPA A — IA 1: núcleo confiável (bloqueador)

```
CONTEXTO: auditoria da IA 3 (leia AUDITORIA.md, seção 4) executou de verdade o seu núcleo com
yt-dlp 2026.10.26 + FFmpeg 9.0.2 + Mutagen, servindo mídia por HTTP local. O download feliz
funciona (MP3 e MP4). O caminho de ERRO está quebrado.

TAREFAS (todas obrigatórias, na ordem):

A1. BUG FATAL — downloader.py:152, _resumir_erro():
    `[linha.strip() for linha in saida.splitlines() if line.strip()]`
    usa `line`, que não existe. TODO download que falha estoura NameError em vez de devolver
    mensagem. Reprodução exata: baixar uma URL que retorna 404.
    Correção + teste que simula returncode != 0 e verifica que ErroDownload carrega a linha
    "ERROR: ..." resumida (e não NameError).

A2. BUG — musica.py:136: `_mostrar_resultados(resultados: list[Any])` sem importar Any.
    Confirmado: `typing.get_type_hints()` levanta NameError. Adicione o import e um teste
    que chame get_type_hints nos pontos públicos de musica.py. Aproveite e remova a variável
    morta `reabrir` em main() (musica.py:129) e o import não usado em interface.py:20 —
    na verdade esse é da IA 2, apenas ANOTE no ia1.txt.

A3. NÃO SOBRESCREVER (o README promete e não acontece): reproduzi − baixar o mesmo arquivo
    duas vezes reescreveu o MP3 (30569 → 30674 bytes) e reportou "sucesso". O `--no-overwrites`
    do yt-dlp não cobre o arquivo JÁ finalizado pelo pós-processamento. Implemente política
    explícita em Configuracoes (ex.: sobrescrita = "pular" | "renomear" | "perguntar",
    padrão "perguntar" que na CLI vira "pular" sem TTY) e teste os três casos com um yt-dlp
    fake. Resultado "pulado" deve ser um status próprio no histórico, não "sucesso".

A4. RESÍDUOS: garanta que nenhum .m4a/.webm/.part fique órfão na pasta de destino após
    falha ou após conversão. Varra e limpe os intermediários conhecidos; nunca apague
    o arquivo final. Teste.

A5. VERIFICAÇÃO REAL DO ARQUIVO: _encontrar_saida aceita qualquer arquivo com a extensão
    certa no stdout. Confirme que o caminho retornado foi produzido/atualizado NESTA execução
    (mtime >= início ou id no nome). Sem isso, "sucesso" pode apontar para o arquivo de ontem.
    Teste com um arquivo pré-existente e stdout apontando para ele.

A6. CONTRATO DE PROGRESSO (necessário para a Etapa B da IA 2 — faça agora, é mudança de
    contrato interno): adicione a Downloader.baixar(..., ao_progresso: Callable | None = None,
    parâmetro opcional, retrocompatível) e troque subprocess.run por subprocess.Popen lendo
    stdout linha a linha com --newline, parseando o padrão do yt-dlp
    ([download]  42.3% of 3.45MiB at 1.20MiB/s ETA 00:02) mais as linhas de pós-processamento
    ([ExtractAudio], [Metadata], [EmbedThumbnail]). Nada de progresso inventado: se a linha
    não casar a regex, simplesmente não emita. Teste o parser com fixtures REAIS de stdout
    (cole a saída no teste), incluindo linha malformada e ausência de progresso.
    ATENÇÃO: manter o comportamento atual quando ao_progresso=None; seus 15 testes antigos
    devem continuar passando sem alteração.

A7. CI: adicione .github/workflows/ci.yml rodando em windows-latest e ubuntu-latest:
    pip install -r requirements.txt mutagen pytest pyflakes; pyflakes; compileall; pytest -q.
    Sem isso, os bugs A1/A2 voltam na próxima etapa. Cole o link do run verde.

A8. requirements.txt: separe dependências de dev (pytest, pyflakes) em requirements-dev.txt.

NÃO FAÇA: não mexa em inteligencia.py/capas.py/metadados.py/preferencias.py/cookies_youtube.py
(da IA 2). Não troque Tkinter. Não refaça a fila/histórico.

DEFINIÇÃO DE PRONTO (vou verificar exatamente isto):
  - `python -m pyflakes *.py tests/*.py` → saída vazia
  - `python -m pytest -q` → todos passando, incluindo os novos testes de erro
  - URL 404 → mensagem "ERROR: ..." limpa, exit 1, SEM traceback
  - dois downloads do mesmo arquivo → não sobrescreve, status "pulado"
  - `baixar(..., ao_progresso=print)` mostra % subindo em tempo real (cole a saída)
  - CI verde nos dois SOs (cole o link)
  - ia1.txt atualizado explicando à IA 2 o novo parâmetro ao_progresso
```

---

## ETAPA A' — IA 2: rebase sobre o núcleo corrigido (sem perder seu trabalho)

```
CONTEXTO: sua branch arena/58df5ecb é hoje um squash (04a5121) que NÃO tem a IA 1 como
ancestral (git merge-base com arena/4df082d0 é vazio), apesar de você ter registrado "merge do
nucleo incluido". Consequência: não existe base comum para revisar/mergear, e a auditoria
encontrou 3 bugs no núcleo que já estão na SUA árvore (AUDITORIA.md, seção 4).

TAREFAS:

A'1. Refaça a base corretamente: comece da branch da IA 1 já corrigida (Etapa A) e traga seus
     módulos por cima, ou faça rebase mantendo histórico linear com merge commit real da IA 1.
     O resultado OBRIGATÓRIO: `git merge-base <sua branch> <branch da IA 1>` retorna um commit
     (não vazio) e `git log --graph` mostra ancestralidade real. Cole os dois comandos e a saída.

A'2. NÃO sobrescreva as correções da IA 1 em configuracoes.py / downloader.py / pesquisa.py /
     musica.py. Se precisar reaplicar suas adições (qualidade_mp3, caminho_cookies, campos
     opcionais, gui), faça como patch pequeno sobre a versão corrigida.

A'3. Prove que os 54 testes continuam verdes SOBRE o núcleo novo (não sobre a cópia antiga).
     Se algum teste seu dependia do comportamento errado (ex.: sucesso com arquivo
     pré-existente), ajuste o teste — não o núcleo.

A'4. Contrato v2 do processar_mp3 (você mesmo pediu no ia2.txt, e está certo): o núcleo passa a
     enviar titulo, canal, duracao e thumbnail além de url/formato/caminho/inicio/conclusao.
     Implemente o LADO DA IA 2 de forma tolerante (campos ausentes = comportamento atual) e
     prefira metadados["titulo"] ao nome do arquivo quando existir. Teste os dois caminhos
     (com e sem os campos novos). Avise no ia2.txt que o lado da IA 1 é a Etapa A6/A'4.

DEFINIÇÃO DE PRONTO: merge-base não vazio (cole a saída), graph com ancestralidade, 54+ testes
verdes sobre o núcleo corrigido, pyflakes vazio, nenhum arquivo da IA 1 revertido.
```

---

## ETAPA B — IA 2: interface de nível profissional

```
CONTEXTO: a interface atual tem as abas certas e a lógica separada (bom!), mas a auditoria
confirmou: (B1) a barra é indeterminada e não existe %/velocidade/tamanho/etapa; (B2)
ResultadoPesquisa não tem thumbnail; (B3) a coluna "Quando" do Histórico está SEMPRE VAZIA
porque a interface lê registro["registrado_em"] e o histórico grava "data_hora"; (B4) nenhuma
etapa do processamento aparece; (B5) o resumo musical (álbum/ano/capa) nunca chega à tela.

Decisão do usuário sobre a stack visual: [PREENCHER — Tkinter/ttk ou moderna]. Se ele ainda não
respondeu, implemente B1–B5 em Tkinter (a lógica está separada; a camada visual troca depois).

TAREFAS:

B1. Tela de downloads real, usando o ao_progresso que a IA 1 entregou na Etapa A6:
    por item: título, formato, barra com %, velocidade, tamanho recebido/total, ETA e a ETAPA
    ATUAL em português (Baixando → Convertendo → Identificando música → Buscando capa →
    Gravando metadados → Concluído/Falhou). Nada de valor inventado: campo indisponível = "—".
    Se o progresso não puder ser lido, mostre a etapa sem % (não invente números).

B2. Thumbnails: thumbnail em ResultadoPesquisa (vem em item["thumbnails"]/["thumbnail"] do
    yt-dlp flat) e exibição na lista de resultados. Sem Pillow não há como redimensionar:
    use o thumb do yt-dlp em tamanho compatível e degrade com elegância se Pillow faltar.
    Cache local em .baixador/thumbs/ com limite de tamanho. NUNCA trave a UI baixando imagem:
    thumbnail é baixada em thread e aparece quando chega.

B3. Corrija a data do Histórico (data_hora) e mostre também destino e situação. Adicione
    "abrir pasta do arquivo" no duplo clique, com tratamento para arquivo inexistente.

B4. Etapas: o pós-processamento da IA 2 deve reportar progresso (callback) — identificando,
    capa, tags — e a UI deve mostrar isso na mesma linha do item.

B5. Resumo musical na tela: ao concluir, mostre "Queen — Bohemian Rhapsody · A Night at the
    Opera (1975) · capa incorporada ✔" (e o oposto explícito quando não houve confirmação:
    "identificação não confirmada — apenas título do arquivo"). Isso exige expor
    ProcessadorMusical.ultimo_resumo ao adaptador — mudança retrocompatível.

B6. Configurações: separe "Salvar" de "reconstruir o núcleo" (não recrie Aplicacao inteira a
    cada clique); desabilite o botão durante o salvamento; valide campos mostrando o erro no
    campo, não em messagebox genérica.

B7. Dois botões iguais nos cookies ("Selecionar" e "Substituir") → mantenha um, com rótulo
    dinâmico, e mostre a idade/validade do arquivo importado (data da cópia) + o que fazer
    quando o download falhar por autenticação.

DEFINIÇÃO DE PRONTO: cole capturas de tela (ou, sem display, a saída de um teste que instancia
o controlador e imprime o estado das linhas da tabela de downloads em 3 momentos distintos);
histórico mostrando data correta; teste automatizado para B2 (thumbnail no dataclass) e B3
(coluna com data). pyflakes vazio, todos os testes verdes.
```

---

## ETAPA C — IA 2: gerenciamento real de APIs

```
CONTEXTO: hoje existe UMA chave (IA/OpenAI). O requisito do usuário é uma seção de APIs com
adicionar/editar/remover/mostrar/ocultar/salvar/testar/estado, para todos os serviços que o
projeto realmente usa — nem mais, nem menos. Não invente integração que o código não usa.

TAREFAS:

C1. Serviços reais a registrar: "Inteligência artificial (compatível com OpenAI)" — exige chave;
    "MusicBrainz", "iTunes", "Deezer" — públicos, sem chave, apenas status/teste;
    "YouTube (cookies)" — credencial de arquivo, não chave. Nada além disso.

C2. Armazenamento genérico de credenciais (mesmo cofre DPAPI de preferencias.py), com migração
    automática do campo ia_api_key atual (não perder a chave de quem já configurou).

C3. UI: lista de serviços com estado (configurado/não configurado/erro de autenticação), botão
    editar, remover, mostrar/ocultar e "testar conexão" com resultado em linha (não em popup).

C4. Diagnóstico útil: diferenciar 401/403 (chave inválida) de timeout/sem rede de URL errada.
    Mensagem por caso. Nunca logar a chave; mascarar sempre no texto do erro.

C5. Sanitização de segredos em logs: antes de gravar mensagem em histórico/erros.jsonl, remova
    parâmetros sensíveis de URL (token=, key=, sig=, Authorization) e qualquer chave conhecida.
    Teste com uma string contendo token e confirme que o arquivo gravado não a contém.

DEFINIÇÃO DE PRONTO: teste de ciclo completo (adicionar → salvar → arquivo em disco NÃO contém
a chave em texto puro → carregar → remover), teste de sanitização, pyflakes vazio, testes verdes.
```

---

## ETAPA D — checklist de teste real (humano no Windows + IA quando possível)

Isto **não** pode ser feito por IA sozinha. Enquanto não houver evidência, o produto não é
"final". Preencher com data, print e resultado:

```
[ ] Windows 11 limpo: instalar_windows.bat do zero (Python presente e ausente)
[ ] iniciar_interface.bat abre a janela sem console
[ ] Pesquisa real "Queen - Bohemian Rhapsody" retorna resultados COM thumbnail
[ ] MP3: download → % aparece → etapas aparecem → arquivo em Musicas/
[ ] MP3 final: capa visível no Explorer/Windows Media Player, tags corretas (álbum/ano/gênero)
[ ] MP4: vídeo com áudio, sem recompressão desnecessária (comparar bitrate com a origem)
[ ] Falha proposital (URL privada) → mensagem clara, sem traceback, item "falhou" no histórico
[ ] Download repetido → pergunta/pula, não sobrescreve
[ ] Cookies: importar cookies.txt real → download que exigia login funciona
[ ] Cookies vencidos → erro explicativo ("reimporte o cookies.txt"), não erro genérico
[ ] Sem internet durante o download → retomada/erro claro, arquivo .part não corrompe
[ ] APIs de música bloqueadas (simular offline) → MP3 sai com nome do arquivo, sem inventar
[ ] Chave de IA inválida → 401 explicado, programa continua funcionando
[ ] Fechar e reabrir → todas as configurações, cookies e histórico continuam
[ ] .baixador/preferencias.json NÃO contém nenhuma chave legível
[ ] git log / GitHub: nenhum cookies.txt, chave ou mídia commitada
```

---

## ETAPA E — IA 1: integração para a main (só depois de A, A', B, C)

```
CONTEXTO: main está em 17f42da (2 arquivos). Nunca houve merge. A branch de integração é
arena/58df5ecb. Não faça merge direto: abra um PR.

TAREFAS:
E1. Abra PR de arena/58df5ecb → main com descrição contendo: o que cada IA entregou, os bugs
    corrigidos na Etapa A (com a reprodução), e o resultado do CI.
E2. Atualize README (instalação real, incl. FFmpeg, e o que NÃO foi testado), CHANGELOG e
    DEVELOPMENT_LOG com as etapas A/A'/B/C, com o mesmo padrão de honestidade já usado.
E3. Alinhe a estrutura de arquivos com o pedido do usuário SEM renomear o que funciona:
    criar iniciar.bat/configurar.bat como entrada única (que chamam os .bat atuais) e as pastas
    Musicas/ Videos/ Capas/ ferramentas/ com .gitkeep — nada de pasta vazia inventada.
E4. Só depois de CI verde e revisão do checklist D: merge (--merge, sem force) e tag v1.0.
```

---

## O que EU (IA 3) faço em cada rodada

Para verificar o que as IAs dizem, sem confiar no relatório:

```bash
git fetch origin 'refs/heads/*:refs/remotes/origin/*'
git log --oneline --graph --all
git merge-base <branch A> <branch B>          # tem que ser não vazio
git ls-remote origin | grep heads              # 3 branches + main
python -m venv /tmp/v && /tmp/v/bin/pip install -q pytest mutagen yt-dlp pyflakes imageio-ffmpeg
/tmp/v/bin/python -m pyflakes *.py tests/*.py  # tem que ser vazio
/tmp/v/bin/python -m pytest -q
# download real sem YouTube: servir mídia local e apontar o baixador para ela
python3 -m http.server 8932 &                   # com teste.m4a e video.mp4 na pasta
/tmp/v/bin/python musica.py download http://127.0.0.1:8932/naoexiste.m4a --formato mp3  # erro limpo
```

Se um relatório não bater com o repositório, o relatório está errado — já aconteceu uma vez
(o "merge do núcleo" da IA 2, que na verdade é um squash sem ancestralidade).
