# Ícones do catálogo

27 ícones do [Lucide](https://lucide.dev), fixados no commit
`20aef31db93fe4d9f398dbb15b120d99c48eef95` e servidos pelo próprio aplicativo.
Não há CDN, pesquisa externa ou pacote JavaScript adicional em tempo de uso.

- `LICENSE`: texto completo das licenças ISC e MIT do projeto, com os avisos de autoria.
- `origem.json`: URL e SHA-256 dos arquivos originais importados.
- `icons/`: SVGs originais, sem alterações nos desenhos.
- `catalogo.svg`: sprite com os desenhos reunidos em elementos `symbol`.

Para regenerar o sprite: `python scripts/gerar_catalogo_icones.py`, na raiz.
O script confere os hashes dos originais antes de gerar. Os arquivos desta pasta
usam fim de linha LF, inclusive em checkouts do Windows.

São ilustrações genéricas de produtos, sem logotipos de fabricantes. Os nomes
comerciais continuam nos cadastros da pousada. O crédito e a licença permanecem
distribuídos junto dos arquivos, conforme a [licença do Lucide](https://lucide.dev/license).
