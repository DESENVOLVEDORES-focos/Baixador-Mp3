# Auditoria técnica — Baixador-Mp3

**Data:** 2026-11-17
**Auditado por:** IA 3 (sessão de comando), branch `arena/0095e284-baixador-mp3`
**Branches inspecionadas:** `origin/main`, `origin/arena/4df082d0-baixador-mp3` (IA 1), `origin/arena/58df5ecb-baixador-mp3` (IA 2)

Este documento é baseado em **execução**, não em leitura de relatórios. Tudo que está marcado
como "confirmado" foi reproduzido neste ambiente com yt-dlp 2026.10.26, FFmpeg n9.0.2 e Mutagen
reais, usando um servidor HTTP local como fonte de mídia. Tudo que **não** pôde ser testado está
explicitamente listado como não testado.

---

## 1. Veredito em uma página

O trabalho das duas IAs é **bom no núcleo e honesto na documentação**, mas o produto **ainda não
funciona como aplicativo**. Três coisas dominam os problemas:

1. **Não existe integração entre as branches no GitHub.** A IA 2 afirma ter feito merge do núcleo da
   IA 1 ("merge do seu nucleo incluido"), mas a branch da IA 2 é um *squash* que **não tem a IA 1
   como ancestral** (`git merge-base` vazio). Na prática: `main` está 6 commits atrás, as duas
   branches nunca foram unidas e a única branch que tem o projeto completo é a da IA 2 (copiada à mão).
2. **Existe um bug que quebra o caminho mais importante do programa.** Todo download que **falha**
   (vídeo indisponível, URL privada, geo-bloqueio, cookies vencidos, sem internet) termina em
   `NameError: name 'line' is not defined` — um traceback em vez da mensagem de erro. Isso foi
   reproduzido 100% das vezes.
3. **A interface não pode ser chamada de "profissional" ainda.** Não há progresso por etapa (a barra é
   indeterminada e o `yt-dlp` roda até o fim antes de a interface saber de qualquer coisa), não há
   thumbnails, não há velocidade/tamanho/tempo restante, e há uma coluna do Histórico que fica
   **sempre vazia** por causa de uma chave inexistente.

Nada disso é catastrófico: a arquitetura é sólida, o contrato `processar_mp3` funciona de verdade e
não há segredo vazando. Mas há trabalho real de **Etapa A (consolidação)**, **Etapa B (refinamento
de interface)** e **Etapa C/D (testes reais)** antes de chamar de versão final.

---

## 2. Mapa das branches (fatos, não relatos)

```
17f42da  Initial commit                         <- main (e HEAD de origin/main)
 └─ 55a0581  Add greeting for IA 2
     └─ 98a3bee  feat: motor de downloads e pesquisa      ┐
         └─ 4d09906  feat: fila persistente + integracao   │ IA 1 (origin/arena/4df082d0)
             └─ 930146d  test: documenta e testa o nucleo  ┘  (15 testes)

918a359 (não presente no clone raso)            <- base do squash da IA 2
 └─ 04a5121  docs(etapa3): README/CHANGELOG/LOG   <- IA 2 (origin/arena/58df5ecb) — única branch
                                                      com o projeto inteiro, mas com histórico achatado
```

| Verificação | Resultado |
|---|---|
| `git merge-base origin/arena/4df082d0 origin/arena/58df5ecb` | **vazio** → sem ancestral comum (squash) |
| `git diff --stat origin/main origin/arena/58df5ecb` | 27 arquivos, +4378 linhas (main está muito atrás) |
| `main` possui o projeto? | Não: só 2 arquivos (`oi.txt`, README mínimo) |
| PRs abertos / merges | Nenhum. Nunca houve merge na main. |
| Arquivos do núcleo idênticos nas duas branches | `fila.py`, `historico.py`, `integracao.py`, `tests/test_core.py` |
| Arquivos do núcleo **alterados** pela IA 2 | `configuracoes.py`, `downloader.py`, `pesquisa.py`, `musica.py`, `README.md`, `requirements.txt`, `.gitignore` |

**Consequência prática:** a branch `arena/58df5ecb` é a única candidata a base de integração — mas
o histórico está achatado, então "revisar o merge da IA 1" pela árvore é impossível; é preciso
revisar o **conteúdo** (feito neste documento) e depois consolidar de forma linear e verificável.

Observação adicional: `origin/arena/4df082d0` **não contém** `configuracoes.py` com suporte a
cookies/pastas e nem o adaptador carregável — essa versão está preservada dentro da branch da IA 2.
A IA 1 não recebeu retorno e não continuou; os dois `ia2.txt` estão sem resposta em `oi.txt`.

---

## 3. O que foi testado de verdade (com evidência)

Ambiente: `yt-dlp 2026.10.26` (PyPI), `ffmpeg n9.0.2` (imageio-ffmpeg), `mutagen`, Python 3.11.
Fonte de mídia: `http://127.0.0.1:8932/` servindo `teste.m4a` (3 s, AAC 128k, título
`"Queen - Bohemian Rhapsody (Official Video)"`) e `video.mp4` (320x240 h264 + AAC).

| # | Cenário | Esperado | Obtido | Status |
|---|---|---|---|---|
| 1 | `musica.py download <m4a> --formato mp3` | MP3 válido em `Musicas/` | `Musicas/teste [teste].mp3`, 30 KB, decodifica | ✅ PASSA |
| 2 | `musica.py download <mp4> --formato mp4` | MP4 com vídeo+áudio | `Videos/video [video].mp4`, h264+aac, 2 s | ✅ PASSA |
| 3 | MP3 com `BAIXADOR_METADATA_MODULE=modulo_metadados` | Tags gravadas, sem perder o arquivo | `title=teste teste` gravado via ID3 | ✅ PASSA |
| 4 | Idem, mas com APIs de música bloqueadas | Não inventar dados, não perder download | título derivado do nome do arquivo, capa ausente, arquivo íntegro | ✅ PASSA (comportamento correto) |
| 5 | Download de URL inexistente (falha real) | Mensagem de erro tratada | **`NameError: name 'line' is not defined`** + traceback | ❌ **FALHA GRAVE** |
| 6 | Repetir o download do mesmo arquivo | Não sobrescrever (README promete) | arquivo **sobrescrito** (30569 → 30674 bytes) e reportado como sucesso | ❌ **FALHA** |
| 7 | Pesquisa (`Pesquisador.pesquisar`) com yt-dlp falhando | Erro claro | lança `ErroPesquisa` corretamente (este caminho está certo, mas rode o item 8) | ⚠️ ver #8 |
| 8 | Research via `ytsearch` bloqueado | — | impossível testar YouTube aqui (TLS bloqueado no sandbox) | ⛔ não testado |
| 9 | 54 testes existentes (`pytest`/`unittest`) | 54 | **53 passed, 1 skipped** | ✅ PASSA |
| 10 | `pyflakes` em todos os módulos | 0 | 7 avisos, sendo **2 bugs reais** e 1 import faltante | ❌ |
| 11 | Janela Tkinter real | abre | **impossível**: sem `python3-tk` neste Linux (pacote indisponível) | ⛔ não testado |
| 12 | APIs música (iTunes/MusicBrainz/Deezer), YouTube, cookies reais | — | rede do sandbox bloqueia (só GitHub/PyPI/NPM) | ⛔ não testado |

Sobre o item 8: `yt-dlp` retornou `returncode=1` + `ERROR: query "teste" page 1: ...` e
`entries=[null]`. O `Pesquisador` **acerta** ao levantar `ErroPesquisa` nesse caso (o
`returncode` é checado), mas o `yt-dlp` às vezes termina com `0` e `entries: [null]` (foi o que
aconteceu no primeiro teste manual com `ytsearch2:`). Esse caso **não está coberto** por teste —
ver P-11 em `COMANDOS.md`.

---

## 4. Defeitos confirmados por evidência

### A. Etapa A — núcleo (bloqueadores)

**A1 — `NameError` em toda falha de download.** `downloader.py:152`
```python
linhas = [linha.strip() for linha in saida.splitlines() if line.strip()]  # 'line' não existe
```
Reproduzido no item 5. Impacto: o caminho de erro **mais comum** do programa (vídeo indisponível,
cookies vencidos, sem internet) estoura traceback na CLI e, na interface, aparece como
`[ERRO] name 'line' is not defined` em vez da causa real. `_resumir_erro` não tem **nenhum** teste.

**A2 — `musica.py` quebra em `get_type_hints`/introspecção.** `musica.py:136`
`_mostrar_resultados(resultados: list[Any])` sem `from typing import Any` (só funciona por causa de
`from __future__ import annotations`). Confirmado: `NameError: name 'Any' is not defined`.
Qualquer ferramenta de tipagem, doc gerada ou `typing.get_type_hints` quebra. Além disso, variável
`reabrir` não usada em `main()` (`musica.py:129`).

**A3 — `--no-overwrites` não protege o arquivo já finalizado.** Confirmado no item 6: o yt-dlp
baixa de novo e substitui o MP3 existente, e o núcleo reporta "sucesso" apontando para o arquivo
novo. Contradiz diretamente o README ("Arquivos existentes não são sobrescritos") e o requisito
"Não sobrescrever arquivos sem autorização". Precisa de verificação prévia de existência e de uma
política explícita (pular / renomear / perguntar).

**A4 — Arquivos intermediários ficam na pasta de destino.** Teste manual: `yt-dlp` com
`bestaudio` deixou `Musicas/teste [teste].m4a` (48 KB) ao lado do MP3 quando não havia
`--extract-audio`; no fluxo real do programa o `.m4a`/`.webm` pode sobrar em `Musicas/` em falhas
parciais. Falta limpeza/verificação de resíduos e uma varredura de `.part`.

**A5 — Sucesso sem arquivo novo não é distinguido.** `_encontrar_saida` aceita **qualquer** arquivo
com a extensão certa no stdout, sem conferir se aquele arquivo é o desta execução (mtime/hash).
Combinado com A3, "sucesso" pode significar "o arquivo de ontem continua lá".

**A6 — Sem `--newline`/progresso máquina-legível.** `downloader.py` usa `subprocess.run(...,
capture_output=True)` — não há como saber progresso, velocidade ou tamanho durante o download. É a
causa raiz da interface não ter progresso real (ver B1).

### B. Etapa B — interface (não é "profissional" como pedido)

**B1 — Sem progresso de verdade.** Barra `indeterminate` girando + texto "Baixando...". O requisito
pede **porcentagem, velocidade, tamanho recebido e etapa atual**. Hoje nada disso existe: a thread
bloqueia em `subprocess.run` e só retorna no fim.

**B2 — Sem thumbnails.** `ResultadoPesquisa` não tem campo `thumbnail` (confirmado:
`['id','titulo','canal','duracao','url','disponibilidade','canal_verificado']`), então a lista de
resultados é só texto. O requisito pede thumbnails.

**B3 — Coluna "Quando" do Histórico sempre vazia.** `interface.py` procura
`registro.get("registrado_em")`, mas `Historico.registrar` grava `data_hora` (confirmado:
GUI mostraria `""` para registros de erro, e a data de *início* para sucessos — datas inconsistentes
entre linhas). Correção trivial, mas é o tipo de coisa que faz o app parecer quebrado.

**B4 — Nenhuma etapa do processamento é mostrada.** O requisito diz "O usuário deverá conseguir
acompanhar o andamento de cada etapa" (download → conversão → identificação → capa → metadados).
Hoje a interface mostra um único "Baixando…" e depois um "[OK]".

**B5 — A interface nunca recebe o resultado do enriquecimento.** `Aplicacao.baixar` retorna
`(bool, aviso)` só com texto; não há como exibir "álbum X, ano Y, capa incorporada". O
`ProcessadorMusical.ultimo_resumo` existe mas não chega à interface (o adaptador descarta).

**B6 — Resultados aparecem mas o usuário não vê a URL/ID, e não há duplo clique, teclado, nem
ordenação.** Detalhes de UX que o requisito de "aplicativo profissional" implica.

**B7 — Configurações:** há um único provedor de IA (OpenAI) e só a chave dele; o requisito fala em
"gerenciar APIs" (adicionar/editar/remover/testar). Além disso, `_salvar_config` reconstrói o
`Aplicacao` inteiro a cada salvamento (perde a fila em memória do worker e recria objetos a toque).

**B8 — Cookies:** funcionalmente bom, mas "Selecionar" e "Substituir" chamam exatamente a mesma
função (dois botões, um comportamento) e não há indicação de expiração/validade dos cookies — o que
é o erro mais comum do usuário ("baixei com cookies e ainda dá erro").

### C. Etapa C — APIs e cookies

**C1 — Só existe um tipo de API com chave (IA).** Não há "gerenciar APIs" de fato: sem lista de
serviços, sem estado por serviço, sem armazenamento genérico de credenciais. O requisito pede
adicionar/editar/remover/mostrar/ocultar/salvar/testar/ver estado.

**C2 — Cookies: `--cookies` só é entregue ao yt-dlp; falta feedback de autenticação.** Não há
verificação "os cookies ainda funcionam?" (teste real contra o YouTube), nem aviso quando o download
falha por falta de autenticação e existe cookies configurado.

**C3 — Segredos: bom no Windows (DPAPI), fraco fora dele.** `proteger_segredo` cai para
`base64` + `chmod 0600` — chamar de "proteção" é generoso: é ofuscação. Está documentado, o que é
honesto, mas a interface não avisa o usuário disso quando roda fora do Windows.

**C4 — Risco de vazamento em log de erro:** `aviso`/`mensagem` de falha de integração e o `saida`
do yt-dlp vão crus para o histórico e para a tela. Se o yt-dlp ecoar uma URL com token, isso fica
gravado em `.baixador/erros.jsonl`. Falta sanitização de segredos antes de registrar.

### D. Qualidade de código (executivo)

`pyflakes *.py tests/*.py` → 7 ocorrências:

```
capas.py:28        'inteligencia.ProvedorITunes' imported but unused
downloader.py:152  undefined name 'line'                 <- A1 (bug)
inteligencia.py:29 'dataclasses.field' imported but unused
interface.py:20    'os' imported but unused
musica.py:129      local variable 'reabrir' is assigned to but never used
musica.py:136      undefined name 'Any'                  <- A2 (bug)
preferencias.py:29 'dataclasses.field' imported but unused
```

Não há `pyflakes`/`ruff`/`mypy` no `requirements.txt` e nem script de verificação — por isso A1 e A2
passaram. Também não há CI (GitHub Actions), então nada impede regressão.

---

## 5. O que está bom (e deve ser preservado)

Isso importa tanto quanto os defeitos, porque as próximas IAs não devem reescrever o que funciona:

- **Arquitetura em camadas correta.** `Configuracoes` → `Downloader`/`Pesquisador` → `FilaDownloads`/
  `Historico` → `AdaptadorMetadados`; a interface fala com `ControladorInterface` (sem Tkinter dentro
  da lógica), o que torna a GUI testável sem tela. Isso é design de nível profissional.
- **O contrato de integração funciona de verdade.** Testei `processar_mp3(caminho, metadados)` com
  Mutagen real: tags gravadas, arquivo preservado, falha de API não perde o download.
- **Disciplina factual da IA 2.** Nada de álbum/ano/gênero inventado: só dados de API, com limiar de
  confiança, e a IA (quando usada) só interpreta o título. Isso atende "Não inventar informações
  musicais". Idem para capa: valida assinatura/dimensões reais e **não** usa imagem aleatória.
- **Segurança de credenciais na direção certa.** Cookies validados por formato Netscape antes de
  copiar, copiados atomicamente com 0600, nunca logados (só contagem), entregues só ao yt-dlp local,
  `.gitignore` reforçado (`**/cookies.txt`, `.baixador/`), DPAPI no Windows.
- **Fila persistente séria.** Gravação atômica (`os.replace`), deduplicação de item ativo, retries
  com limite, recuperação de *lease* de worker morto (>6 h).
- **Honestidade dos relatórios.** As duas IAs registraram explicitamente o que **não** testaram
  (APIs bloqueadas, sem Tkinter, sem yt-dlp). Isso é raro e deve continuar sendo exigido.
- **Testes existentes são reais** (53 passando), com mocks, arquivos temporários e leitura de tags
  de volta pelo Mutagen — não são testes de fachada.

---

## 6. Matriz de aderência ao prompt master

| Requisito do seu documento | Estado | Evidência |
|---|---|---|
| 1/2 — Fluxo MP3 completo (download→identificação→capa→tags→pasta) | 🟡 parcialmente **funcional** | testado até tags; identificação/capa não testáveis aqui |
| 2 — Fluxo MP4 com melhor combinação e sem recompressão | ✅ | teste #2 (h264+aac, remux) |
| 5 — Pesquisa avançada (título, canal, duração, thumbnail, oficial) | 🟡 falta **thumbnail**; resto ok | #B2 |
| 6 — Capas oficiais, sem imagem aleatória, incerteza = não incorpora | ✅ no código e nos testes | `capas.py`, `tests/test_ia2.py` |
| 7 — Interface: inicial, resultados, downloads, histórico, configurações | 🟡 existe tudo, **sem progresso/etapas/thumbnails** | #B1–B6 |
| 8 — Gerenciamento de APIs (add/edit/remove/testar/estado) | ❌ só chave única de IA | #C1 |
| 9 — Cookies.txt (importar/validar/substituir/remover/integrar/seguro) | ✅ funcional | `cookies_youtube.py`, 17 testes |
| 10 — Configurações persistentes | ✅ | `preferencias.py` |
| 11 — Estrutura modular / `iniciar.bat` + `configurar.bat` | 🟡 nomes diferentes (`iniciar_interface.bat`, `instalar_windows.bat`); falta `ferramentas/`, `Capas/` | árvore |
| 13 — Portabilidade/instalação: baixar FFmpeg e yt-dlp automaticamente | ❌ só instala pip; FFmpeg é manual | `.bat` |
| 14 — GitHub: commits frequentes, branches, sem merge na main, sem sobrescrever trabalho | ❌ squash sem ancestralidade; 0 merges; sem CI | seção 2 |
| 16 — "Não declarar concluído sem teste" | ✅ cumprido pelas duas IAs | CHANGELOG/DEVELOPMENT_LOG |
| 16 — Testes automatizados | 🟡 54 testes, mas **não cobrem** os caminhos que quebraram (A1–A5) | seção 4 |
| 16 — Tratamento adequado de erros | ❌ | #A1 |
| 16 — Não sobrescrever arquivos | ❌ | #A3 |
| 17 — "sem exigir scripts separados" | 🟡 CLI + GUI convivem, mas a instalação ainda é manual | `.bat` |

Legenda: ✅ atende e foi verificado · 🟡 atende em parte · ❌ não atende

---

## 7. Riscos de longo prazo (o que vai doer depois)

1. **Histórico achatado e 3 "fontes de verdade".** Enquanto não houver uma `main` consolidada com
   histórico linear, toda nova IA vai recomeçar copiando árvore — foi exatamente o que a IA 2 fez.
   Isso vai gerar conflito silencioso (duas versões de `configuracoes.py`) e regressão invisível.
2. **Sem CI.** A1 e A2 (dois bugs de nome) passaram por duas etapas. Um workflow de 20 linhas
   rodando `pytest` + `ruff` + `compileall` em Windows e Linux teria pegado os dois.
3. **Sem teste do caminho de erro.** O único trecho que todo usuário vai encontrar (vídeo bloqueado,
   cookies vencidos) não tem teste.
4. **Interface acoplada ao `subprocess.run` bloqueante.** Enquanto o núcleo não expuser progresso
   (callback/streaming), a interface não consegue fazer a tela de downloads que você pediu. Isso é
   uma mudança de **contrato interno**, então precisa ser feita agora, antes de a GUI crescer.
5. **"Profissional" visual ainda não existe.** Tkinter/ttk puro com `Treeview` de texto entrega
   funcionalidade, mas não a aparência de aplicativo moderno que você descreveu. Precisa de
   decisão explícita: (a) permanecer em Tkinter com `ttk` + tema (customtkinter/tkinter + imagens) ou
   (b) migrar para algo mais moderno (ex.: `pywebview`/`Flet`/`PySide6`). O custo de migrar cresce a
   cada etapa — decidir **agora**.

---

## 8. Decisões que preciso de você (bloqueiam a Etapa B)

1. **Interface:** manter Tkinter (zero dependências novas, mas aparência limitada) ou adotar uma
   stack com aparência moderna (mais uma dependência, ex.: PySide6 ou Flet)? A arquitetura atual
   (`ControladorInterface` sem Tkinter) permite trocar a camada visual **sem** reescrever a lógica —
   por isso a decisão precisa ser tomada antes de crescer a GUI.
2. **Sobrescrita:** quando o arquivo já existe, o padrão deve ser *pular*, *renomear* (`(2)`) ou
   perguntar? (o prompt diz "não sobrescrever sem autorização" — sugiro perguntar com opção "lembrar").
3. **FFmpeg/yt-dlp automáticos:** o `configurar.bat` deve baixar os binários (builds oficiais/`imageio-ffmpeg`)
   ou continuar orientando o usuário a instalar manualmente? (envolve licença/pinning de versão).
4. **Consolidação da `main`:** autorizar a criação de um PR de integração (`arena/58df5ecb` →
   `main`) depois das correções, com histórico linear e verificável?

---

## 9. Ordem de execução recomendada

| Fase | Quem | Conteúdo | Critério de aceite |
|---|---|---|---|
| **A** | IA 1 | A1–A6 + testes do caminho de erro + CI (ruff/pytest, Windows+Linux) | `pyflakes` = 0; novo teste reproduz o `NameError` e falha antes/passa depois; download repetido não sobrescreve |
| **A'** | IA 2 | Rebase da branch sobre o núcleo corrigido + contrato v2 (título/canal/duração no dicionário) | 54 testes verdes **sobre o núcleo novo**, sem reescrever arquivos da IA 1 |
| **B** | IA 2 | Progresso por etapa (callback), thumbnails, coluna do histórico, exibição do resumo musical | GUI mostra %/velocidade/etapa; `ResultadoPesquisa.thumbnail`; histórico com data correta |
| **C** | IA 2 | Gerenciador de APIs (lista de serviços, cofre genérico) + status de cookies | adicionar/editar/remover/testar cada serviço; nada em texto puro/log |
| **D** | humano + IA | Testes reais: Windows real, YouTube real, cookies reais, MP3 com capa real | checklist D preenchido com evidência (print/log), sem "achismo" |
| **E** | IA 1 + você | PR de integração para `main`, docs finais, release | `main` com histórico linear, CI verde, tag de versão |

Os prompts prontos para comandar cada IA, incluindo o texto de "definição de pronto" e o que é
proibido, estão em **[`COMANDOS.md`](COMANDOS.md)**.
