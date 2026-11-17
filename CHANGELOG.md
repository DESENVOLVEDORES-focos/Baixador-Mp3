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
