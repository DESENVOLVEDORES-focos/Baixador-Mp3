# Contrato de integração — IA 1 (núcleo) / IA 2 (metadados)

## Limites de responsabilidade

- O núcleo baixa MP3/MP4, verifica o arquivo final, mantém fila e histórico.
- A IA 2 pesquisa/identifica capa e informações musicais e grava os metadados/capa. O núcleo não implementa essas funcionalidades em duplicidade.
- Nenhuma integração deve remover ou sobrescrever o arquivo original sem uma operação segura. Se a IA 2 produzir um caminho alternativo, ele deve apontar para um arquivo existente e não vazio.

## Interface Python estável

O ponto de entrada para integração é `integracao.ProcessadorMetadados`:

```python
from pathlib import Path
from typing import Any, Mapping

class ProcessadorMetadados:
    def processar_mp3(
        self,
        caminho: Path,
        metadados: Mapping[str, Any],
    ) -> Path | None:
        ...
```

- `caminho`: MP3 concluído, absoluto e verificado pelo núcleo.
- `metadados`: dicionário com `url`, `formato` (`"mp3"`), `caminho`, `inicio` e `conclusao`. A IA 2 pode consultar o arquivo/origem para obter dados adicionais. Não se pressupõe que os dados de pesquisa estejam disponíveis no downloader.
- Retorno `None`: o processador alterou o MP3 no próprio caminho.
- Retorno `Path`: caminho final do MP3 processado. Deve existir e ter tamanho maior que zero.
- Exceção: o núcleo registra aviso/erro de integração, mas mantém o download original e não o apaga.

### Integração sem editar o núcleo

Defina `BAIXADOR_METADATA_MODULE` com o nome importável de um módulo que exponha uma função `processar_mp3(caminho, metadados)`. Exemplo no Windows PowerShell:

```powershell
$env:BAIXADOR_METADATA_MODULE = "modulo_metadados"
python musica.py download "https://..." --formato mp3
```

O módulo deve estar instalado ou no `PYTHONPATH`. Sem essa variável, o núcleo funciona normalmente e deixa o MP3 pronto para enriquecimento posterior. A interface também aceita injeção direta de um objeto `ProcessadorMetadados` em `AdaptadorMetadados`, útil para testes.

## Pesquisa e fila

- `pesquisa.Pesquisador.pesquisar(consulta, limite)` retorna `list[ResultadoPesquisa]`, com `id`, `titulo`, `canal`, `duracao`, `url` e `disponibilidade`.
- `fila.FilaDownloads` persiste itens em JSON; os formatos permitidos são `mp3` e `mp4`.
- Pesquisa não afirma que um canal é oficial sem evidência disponibilizada pelo extrator. A seleção final é feita pelo usuário.
