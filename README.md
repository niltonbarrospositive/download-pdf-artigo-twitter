# Download PDF - Artigo Twitter/X

Ferramenta para baixar artigos (long-form posts) do Twitter/X e convertê-los em PDF formatado, preservando texto, imagens, blocos de código, listas e formatação inline.

## Funcionalidades

- Extrai artigos completos do Twitter/X (long-form posts)
- Preserva formatação: negrito, itálico, links, headings
- Suporta blocos de código com syntax highlight (dark theme)
- Baixa e embute imagens inline (base64)
- Suporta listas ordenadas e não-ordenadas
- Suporta blockquotes
- Gera PDF em formato A4 com layout limpo e profissional
- Nomeia o arquivo automaticamente com autor + título

## Requisitos

- Python 3.10+
- Playwright + Chromium

## Instalação

```bash
# Instalar dependências Python
pip install -r requirements.txt

# Instalar o navegador Chromium para o Playwright
python3 -m playwright install chromium
```

## Uso

```bash
python3 twitter_to_pdf.py <url_do_artigo>
```

### Exemplos

```bash
# Artigo simples
python3 twitter_to_pdf.py https://x.com/mntruell/status/2026736314272591924

# Também aceita URLs do twitter.com
python3 twitter_to_pdf.py https://twitter.com/levie/status/2030714592238956960
```

O PDF é gerado no diretório atual com o nome no formato `Autor_Titulo_do_artigo.pdf`.

Para organizar os PDFs gerados, mova-os para a pasta `pdf_exportados/`:

```bash
mv *.pdf pdf_exportados/
```

## Como funciona

1. **Navegação**: Usa Playwright (Chromium headless) para abrir a URL do artigo
2. **Scroll**: Rola a página para forçar carregamento lazy de imagens e blocos de código
3. **Extração**: Executa JavaScript no DOM para extrair blocos DraftJS (título, autor, data, texto, imagens, código)
4. **Imagens**: Baixa imagens via fetch no contexto do browser e converte para base64
5. **HTML**: Monta um documento HTML limpo com CSS próprio (tipografia, cores, layout A4)
6. **PDF**: Renderiza o HTML em uma nova página do Playwright e gera o PDF

## Estrutura do projeto

```
download-pdf-artigo-twitter/
├── twitter_to_pdf.py    # Script principal
├── requirements.txt     # Dependências (playwright)
├── pdf_exportados/      # Pasta para PDFs gerados (ignorada pelo git)
├── .gitignore
└── README.md
```

## Tipos de conteúdo suportados

| Tipo | Suporte |
|------|---------|
| Texto simples | Sim |
| Negrito / Itálico | Sim |
| Links | Sim |
| Headings (H1, H2, H3) | Sim |
| Blocos de código | Sim (dark theme) |
| Imagens inline | Sim (base64) |
| Listas ordenadas | Sim |
| Listas não-ordenadas | Sim |
| Blockquotes | Sim |

## Limitações

- Funciona apenas com **artigos** (long-form posts) do Twitter/X, não com tweets regulares
- Requer conexão com a internet para acessar o Twitter/X e baixar imagens
- O Twitter/X pode bloquear acessos automatizados em alguns casos
