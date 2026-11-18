# COMECE AQUI — usar o baixador amanhã

Guia de 5 minutos. Sem terminal, sem editar código.

> **Pacote `Central_MP3_Teste.zip`:** extraia e dê dois cliques em
> `iniciar.bat`. Se for a primeira vez, rode `configurar.bat` antes (precisa de
> internet). O pacote já vem com tudo — nenhuma chave, cookie ou banco pessoal
> está incluído.

---

## 1. Instalar (só na primeira vez — precisa de internet)

1. Baixe esta pasta do projeto para o seu PC (Code → Download ZIP no GitHub, ou `git clone`).
2. Se ainda não tem Python: <https://www.python.org/downloads/windows/> →
   marque **"Add python.exe to PATH"** na primeira tela do instalador.
3. Dê **dois cliques em `configurar.bat`** e espere terminar.
   Ele instala as bibliotecas e baixa `yt-dlp.exe` + `ffmpeg.exe` sozinho.

> Se aparecer aviso sobre o FFmpeg: baixe em <https://ffmpeg.org/download.html>
> e jogue o `ffmpeg.exe` dentro da pasta `ferramentas\`.

## 2. Abrir

Dois cliques em **`iniciar.bat`**. A janela do programa abre (sem console preto).

## 3. Baixar uma música

1. Aba **Baixar** → digite `artista - música` → **Pesquisar**.
2. Clique no resultado certo. A miniatura aparece embaixo da lista.
3. Escolha **MP3**.
4. Clique em **Baixar selecionado**.
5. No painel **Downloads** você acompanha: `%`, velocidade, tamanho e a etapa
   (Baixando → Convertendo → Gravando metadados).
6. Ao terminar, o arquivo está em **`Musicas\`** — com capa e tags quando as
   APIs públicas confirmam a música. A linha de mensagens diz o que foi
   preenchido; se disser "identificação não confirmada", é porque não houve
   confirmação (o programa **não inventa** álbum/ano).

Vídeo: mesmo fluxo escolhendo **MP4**. Vai para **`Videos\`**.

## 4. Duas coisas que você vai querer ajustar

**Se o arquivo já existe:** o programa **não sobrescreve**. Ele pergunta e, se
você aceitar, salva uma cópia com outro nome. Para mudar o padrão:
*Configurações → Downloads → "Se o arquivo já existir"*.

**Se um vídeo pedir login** (privado, com idade, membros):
1. No navegador, logado na **sua** conta do YouTube, exporte os cookies com uma
   extensão de cookies no formato **Netscape `cookies.txt`**.
2. No programa: *Configurações → COOKIES DO YOUTUBE → Selecionar cookies.txt*.
3. Pronto — vale para todas as pesquisas e downloads seguintes. Quando expirar,
   o programa avisa pela data de importação e você usa "Substituir".

⚠️ O `cookies.txt` é uma credencial da sua conta: fica só no seu PC (`.baixador\`),
nunca é enviado a outros serviços e nunca deve ser compartilhado ou commitado.

## 5. O que dá para fazer na Central Musical

| Quero… | Onde |
|---|---|
| Pesquisar sem colar link | **Pesquisar** → digite e Enter (vídeos, playlists e canais) |
| Ocultar repetidos/compilados | **Pesquisar** → caixas "Esconder repetidos", "Sem compilados (>1 h)" |
| Ver detalhes e miniatura | clique num resultado (ficha aparece embaixo) |
| Abrir e escolher itens de uma playlist | marque a playlist → **Abrir playlist** → **Marcar só os disponíveis** |
| Guardar a playlist do YouTube na biblioteca | **Salvar na biblioteca** (entra só o que já foi baixado) |
| Juntar músicas de várias buscas | **Adicionar à cesta** (a cesta acumula e sobrevive a fechar) |
| Procurar dentro da cesta | **Fila de downloads** → "Procurar na cesta" |
| Trocar MP3/MP4 de vários itens | mesma tela → "Formato dos marcados" → **Aplicar** |
| Escolher a capa | Biblioteca → **Buscar capa** → escolha na prévia → **Usar esta capa** |
| Pular no meio da música | clique na barra do player; Espaço pausa; Ctrl+←/→ ±10 s |
| Ver erros sem terminal | botão **Mensagens** (também em `.baixador\app.log`) |
| Ajustar bitrate com nome claro | **Configurações** → "Bitrate do MP3" |

Nada disso exige editar arquivo nenhum.

## 6. Se algo der errado

| Mensagem | O que fazer |
|---|---|
| `[ERRO] ERROR: ... HTTP Error 404` | A URL não existe/expirou. Copie de novo do navegador. |
| "Sign in to confirm your age" / "private" | Importe o `cookies.txt` (passo 4). |
| "FFmpeg não encontrado" | Rode `configurar.bat` de novo com internet. |
| "yt-dlp não encontrado" | Idem; ou `pip install yt-dlp`. |
| Miniatura em branco | `python -m pip install Pillow`. |
| Nada acontece ao abrir | Rode `configurar.bat`; se persistir, abra `python main.py --classica` numa janela de terminal para ver o erro. |

**Onde ficam os registros:** `.baixador\historico.jsonl` (sucessos),
`.baixador\erros.jsonl` (falhas), `.baixador\preferencias.json` (configurações).
Nenhum deles deve ir para o GitHub.

---

## O que ainda não está pronto (para você saber o que esperar)

- **Identificação musical, capa e IA reais** nunca rodaram com internet
  liberada: o ambiente de desenvolvimento bloqueia YouTube/iTunes/MusicBrainz/
  Deezer. Os testes usam respostas no formato real das APIs, e o comportamento
  de falha está correto — mas o primeiro download de verdade será o primeiro
  teste real disso. Se a capa/álbum não vier, o programa continua certo: mantém
  o áudio e as tags do vídeo.
- **O áudio não foi ouvido aqui**: o `ffplay` não existe no ambiente de
  desenvolvimento. O player é testado na montagem do comando, no seek e no
  estado salvo; a confirmação de som fica para o seu PC.
- **A janela real do Windows não foi aberta**: a interface é testada com Tk
  simulado (cada widget registrado, cada botão clicado). Aparência/fonte podem
  precisar de ajuste fino no seu monitor.
- Se algo falhar no Windows, o mais útil é abrir **Mensagens** na própria
  janela (fica em `.baixador\app.log`) e, se precisar, a saída de
  `python -m baixador.app.musica download "<URL>" --formato mp3` num terminal.
