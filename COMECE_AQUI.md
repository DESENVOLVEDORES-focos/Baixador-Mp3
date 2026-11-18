# COMECE AQUI — usar o baixador amanhã

Guia de 5 minutos. Sem terminal, sem editar código.

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

## 5. Se algo der errado

| Mensagem | O que fazer |
|---|---|
| `[ERRO] ERROR: ... HTTP Error 404` | A URL não existe/expirou. Copie de novo do navegador. |
| "Sign in to confirm your age" / "private" | Importe o `cookies.txt` (passo 4). |
| "FFmpeg não encontrado" | Rode `configurar.bat` de novo com internet. |
| "yt-dlp não encontrado" | Idem; ou `pip install yt-dlp`. |
| Miniatura em branco | `python -m pip install Pillow`. |
| Nada acontece ao abrir | Rode `configurar.bat`; se persistir, abra `python interface.py` numa janela de terminal para ver o erro. |

**Onde ficam os registros:** `.baixador\historico.jsonl` (sucessos),
`.baixador\erros.jsonl` (falhas), `.baixador\preferencias.json` (configurações).
Nenhum deles deve ir para o GitHub.

---

## O que ainda não está pronto (para você saber o que esperar)

- **Identificação musical e capa reais** nunca rodaram em ambiente com internet
  liberada: aqui o sandbox bloqueia YouTube/iTunes/MusicBrainz/Deezer. Os testes
  usam respostas reais gravadas, e o comportamento de falha está correto — mas o
  primeiro download de verdade vai ser o primeiro teste real disso. Se a capa
  não aparecer, o programa continua certo: mantém o áudio e as tags do vídeo.
- **Gerenciador de várias APIs** (várias chaves, editar, remover, testar) ainda
  é a Etapa C do [`COMANDOS.md`](COMANDOS.md).
- Se algo falhar no Windows, o log mais útil é a saída de
  `python musica.py download "<URL>" --formato mp3` num terminal.
