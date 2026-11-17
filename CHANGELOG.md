# Changelog

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
