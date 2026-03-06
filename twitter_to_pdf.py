#!/usr/bin/env python3
"""
Baixa artigos do Twitter/X e gera PDF formatado.

Uso:
    python3 twitter_to_pdf.py <url_do_artigo>

Exemplo:
    python3 twitter_to_pdf.py https://x.com/mntruell/status/2026736314272591924

Dependências:
    pip3 install playwright
    python3 -m playwright install chromium
"""

import sys
import os
import re
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright


# ──────────────────────────────────────────────
# Configuração do navegador
# ──────────────────────────────────────────────

CHROMIUM_PATH = "/root/.cache/ms-playwright/chromium-1194/chrome-linux/chrome"

# Mapeamento de tipos de bloco DraftJS → tags HTML
BLOCK_TAG = {
    "unstyled": "p",
    "header-one": "h1",
    "header-two": "h2",
    "header-three": "h3",
    "blockquote": "blockquote",
    "code-block": "pre",
    "ordered-list-item": "oli",
    "unordered-list-item": "uli",
}


def _proxy_config():
    """Lê proxy do ambiente (HTTPS_PROXY) e retorna config para Playwright."""
    proxy_url = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    if not proxy_url:
        return None
    p = urlparse(proxy_url)
    if not p.hostname:
        return None
    return {
        "server": f"{p.scheme}://{p.hostname}:{p.port}",
        "username": p.username or "",
        "password": p.password or "",
    }


def _chromium_path():
    """Retorna o caminho do Chromium, verificando opções comuns."""
    # Caminho fixo do ambiente atual
    if os.path.isfile(CHROMIUM_PATH):
        return CHROMIUM_PATH
    # Procurar na cache do Playwright
    cache = os.path.expanduser("~/.cache/ms-playwright")
    if os.path.isdir(cache):
        for entry in sorted(os.listdir(cache), reverse=True):
            if entry.startswith("chromium-"):
                candidate = os.path.join(cache, entry, "chrome-linux", "chrome")
                if os.path.isfile(candidate):
                    return candidate
    # Usar o padrão do Playwright (vai procurar sozinho)
    return None


# ──────────────────────────────────────────────
# JS para extrair conteúdo do artigo no DOM
# ──────────────────────────────────────────────

JS_EXTRAIR_ARTIGO = """
() => {
    // ── Título ──
    const tituloEl = document.querySelector('[data-testid="twitter-article-title"]');
    const titulo = tituloEl ? tituloEl.innerText.trim() : '';

    // ── Autor ──
    const userNameEl = document.querySelector('[data-testid="User-Name"]');
    let autor = '';
    let handle = '';
    if (userNameEl) {
        const partes = userNameEl.innerText.split('\\n');
        autor = partes[0] || '';
        handle = partes.find(p => p.startsWith('@')) || '';
    }

    // ── Data (timestamp do tweet) ──
    const timeEl = document.querySelector('article time');
    const data = timeEl ? timeEl.getAttribute('datetime') : '';

    // ── Blocos de conteúdo (DraftJS) ──
    const conteudo = document.querySelector('[data-testid="longformRichTextComponent"]');
    const blocos = [];

    if (conteudo) {
        // Função para processar formatação inline (negrito, itálico, links)
        const processar = (node) => {
            if (node.nodeType === 3) return node.textContent;
            if (node.nodeType !== 1) return '';

            const tag = node.tagName.toLowerCase();
            const style = node.getAttribute('style') || '';
            let conteudo = '';
            for (const filho of node.childNodes) {
                conteudo += processar(filho);
            }

            if (tag === 'a') {
                const href = node.getAttribute('href') || '';
                return '<a href="' + href + '">' + conteudo + '</a>';
            }
            if (style.includes('font-weight: bold') || style.includes('font-weight:bold')) {
                return '<strong>' + conteudo + '</strong>';
            }
            if (style.includes('font-style: italic') || style.includes('font-style:italic')) {
                return '<em>' + conteudo + '</em>';
            }
            return conteudo;
        };

        const blockEls = conteudo.querySelectorAll('[data-block="true"]');
        blockEls.forEach(block => {
            const cls = block.className || '';
            const tagName = block.tagName.toLowerCase();
            const tipoMatch = cls.match(/longform-([\\w-]+)/);
            let tipo = tipoMatch ? tipoMatch[1] : 'unstyled';

            // Detectar blocos de código em <section> com <pre><code> dentro
            const codeEl = block.querySelector('pre > code');
            if (codeEl) {
                const lang = (codeEl.className || '').replace('language-', '');
                // Limpar whitespace extra do Twitter (trailing + leading comum)
                let lines = (codeEl.textContent || '')
                    .split('\\n')
                    .map(line => line.trimEnd());
                // Remover indentação comum (Twitter adiciona padding)
                const nonEmpty = lines.filter(l => l.length > 0);
                if (nonEmpty.length > 0) {
                    const minIndent = Math.min(...nonEmpty.map(l => l.match(/^(\\s*)/)[1].length));
                    if (minIndent > 0) {
                        lines = lines.map(l => l.length > 0 ? l.substring(minIndent) : l);
                    }
                }
                const codeText = lines.join('\\n').trim();
                blocos.push({ tipo: 'code-block', html: codeText, imgSrc: null, lang: lang });
                return;
            }

            // Detectar blocos de imagem (atomic) - têm img ou tweetPhoto dentro
            const temImagem = block.querySelector('img, [data-testid="tweetPhoto"]');
            if (temImagem && tipo === 'unstyled') {
                tipo = 'atomic';
            }

            // Extrair HTML interno preservando formatação inline
            const innerDiv = block.querySelector('.public-DraftStyleDefault-block');
            let html = '';
            if (innerDiv) {
                html = processar(innerDiv);
            } else {
                html = block.innerText || '';
            }

            // Para blocos atomic, capturar src da imagem diretamente
            let imgSrc = null;
            if (tipo === 'atomic' && temImagem) {
                const imgEl = block.querySelector('img');
                if (imgEl) {
                    imgSrc = imgEl.src || null;
                    if (imgSrc) {
                        imgSrc = imgSrc.replace('name=small', 'name=large')
                                       .replace('name=medium', 'name=large');
                    }
                }
            }

            blocos.push({ tipo, html: html.trim(), imgSrc });
        });
    }

    return { titulo, autor, handle, data, blocos };
}
"""


def extrair_artigo(page):
    """Extrai o conteúdo do artigo do DOM da página."""
    return page.evaluate(JS_EXTRAIR_ARTIGO)


def baixar_imagem_base64(page, url):
    """Baixa uma imagem via fetch no contexto do browser e retorna base64 data URI."""
    resultado = page.evaluate("""
        async (url) => {
            try {
                const resp = await fetch(url);
                if (!resp.ok) return null;
                const blob = await resp.blob();
                return await new Promise((resolve) => {
                    const reader = new FileReader();
                    reader.onloadend = () => resolve(reader.result);
                    reader.readAsDataURL(blob);
                });
            } catch (e) {
                return null;
            }
        }
    """, url)
    return resultado


# ──────────────────────────────────────────────
# Montar HTML limpo com CSS
# ──────────────────────────────────────────────

CSS_ARTIGO = """
@page {
    size: A4;
    margin: 2cm 2.5cm;
}
* {
    box-sizing: border-box;
}
body {
    font-family: Georgia, 'Times New Roman', serif;
    font-size: 16px;
    line-height: 1.7;
    color: #1a1a1a;
    max-width: 100%;
    margin: 0;
    padding: 0;
}
.cabecalho {
    border-bottom: 2px solid #1da1f2;
    padding-bottom: 16px;
    margin-bottom: 28px;
}
.cabecalho h1 {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
    font-size: 28px;
    font-weight: 700;
    line-height: 1.3;
    margin: 0 0 12px 0;
    color: #0f1419;
}
.meta {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
    font-size: 14px;
    color: #536471;
}
.meta .autor {
    font-weight: 600;
    color: #0f1419;
}
.meta .handle {
    color: #536471;
}
.meta .link-original {
    color: #1da1f2;
    text-decoration: none;
    font-size: 12px;
}
h1, h2, h3 {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
    color: #0f1419;
    margin-top: 32px;
    margin-bottom: 12px;
    page-break-after: avoid;
}
.corpo h1 { font-size: 24px; }
.corpo h2 { font-size: 20px; }
.corpo h3 { font-size: 18px; }
p {
    margin: 0 0 16px 0;
}
blockquote {
    border-left: 4px solid #1da1f2;
    margin: 16px 0;
    padding: 12px 20px;
    background: #f7f9fa;
    color: #333;
    font-style: italic;
}
pre {
    background: #0d1117;
    color: #c9d1d9;
    padding: 16px;
    border-radius: 6px;
    overflow-x: auto;
    font-family: 'Courier New', Consolas, monospace;
    font-size: 13px;
    line-height: 1.5;
    white-space: pre-wrap;
    word-wrap: break-word;
    margin: 16px 0;
}
pre code {
    background: none;
    padding: 0;
    font-size: inherit;
    color: inherit;
}
.code-lang {
    display: block;
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
    font-size: 12px;
    color: #8b949e;
    margin-bottom: 8px;
    padding-bottom: 6px;
    border-bottom: 1px solid #21262d;
}
ol, ul {
    margin: 0 0 16px 0;
    padding-left: 24px;
}
li {
    margin-bottom: 8px;
}
img {
    max-width: 100%;
    height: auto;
    border-radius: 8px;
    margin: 16px 0;
    display: block;
}
a {
    color: #1da1f2;
    text-decoration: none;
}
.imagem-legenda {
    text-align: center;
    margin: 20px 0;
}
"""


def montar_html(dados, url_original):
    """Monta o HTML completo do artigo com CSS inline."""
    # Formatar data
    data_formatada = ""
    if dados["data"]:
        try:
            from datetime import datetime
            dt = datetime.fromisoformat(dados["data"].replace("Z", "+00:00"))
            data_formatada = dt.strftime("%d/%m/%Y")
        except Exception:
            data_formatada = dados["data"]

    # Cabeçalho
    html_parts = [
        f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<style>{CSS_ARTIGO}</style>
</head>
<body>
<div class="cabecalho">
    <h1>{_escape(dados['titulo'])}</h1>
    <div class="meta">
        <span class="autor">{_escape(dados['autor'])}</span>
        <span class="handle">{_escape(dados['handle'])}</span>
        {f' &middot; <span>{data_formatada}</span>' if data_formatada else ''}
        <br>
        <a class="link-original" href="{_escape(url_original)}">{_escape(url_original)}</a>
    </div>
</div>
<div class="corpo">
"""
    ]

    # Corpo do artigo
    lista_aberta = None  # 'ol' ou 'ul'
    code_aberto = False  # Agrupamento de blocos code-block
    legenda_anterior = None  # Para detectar legendas duplicadas

    for bloco in dados["blocos"]:
        tipo = bloco["tipo"]
        conteudo = bloco["html"]

        # Se o bloco não é item de lista, fechar lista aberta
        if tipo not in ("ordered-list-item", "unordered-list-item") and lista_aberta:
            html_parts.append(f"</{lista_aberta}>")
            lista_aberta = None

        # Se o bloco não é code-block, fechar bloco de código aberto
        if tipo != "code-block" and code_aberto:
            html_parts.append("</code></pre>")
            code_aberto = False

        if tipo == "atomic":
            # Bloco de imagem inline
            img_b64 = bloco.get("imgBase64")
            if img_b64:
                html_parts.append(f'<div class="imagem-legenda">')
                if conteudo and not conteudo.isspace():
                    html_parts.append(f'<img src="{img_b64}" alt="{_escape(conteudo)}">')
                    html_parts.append(f'<p><em>{conteudo}</em></p>')
                    legenda_anterior = conteudo
                else:
                    html_parts.append(f'<img src="{img_b64}">')
                html_parts.append(f'</div>')
            elif conteudo and not conteudo.isspace():
                html_parts.append(f"<p>{conteudo}</p>")

        elif tipo == "unstyled":
            # Pular parágrafo se for idêntico à legenda da imagem anterior
            if conteudo and conteudo == legenda_anterior:
                legenda_anterior = None
                continue
            legenda_anterior = None
            if conteudo:
                html_parts.append(f"<p>{conteudo}</p>")

        elif tipo == "header-one":
            html_parts.append(f"<h1>{conteudo}</h1>")

        elif tipo == "header-two":
            html_parts.append(f"<h2>{conteudo}</h2>")

        elif tipo == "header-three":
            html_parts.append(f"<h3>{conteudo}</h3>")

        elif tipo == "blockquote":
            html_parts.append(f"<blockquote>{conteudo}</blockquote>")

        elif tipo == "code-block":
            if not code_aberto:
                lang = bloco.get("lang") or ""
                lang_label = f'<span class="code-lang">{_escape(lang)}</span>' if lang else ""
                html_parts.append(f"<pre>{lang_label}<code>")
                code_aberto = True
            else:
                html_parts.append("\n")
            html_parts.append(_escape(conteudo))

        elif tipo == "ordered-list-item":
            if lista_aberta != "ol":
                if lista_aberta:
                    html_parts.append(f"</{lista_aberta}>")
                html_parts.append("<ol>")
                lista_aberta = "ol"
            html_parts.append(f"<li>{conteudo}</li>")

        elif tipo == "unordered-list-item":
            if lista_aberta != "ul":
                if lista_aberta:
                    html_parts.append(f"</{lista_aberta}>")
                html_parts.append("<ul>")
                lista_aberta = "ul"
            html_parts.append(f"<li>{conteudo}</li>")

        else:
            if conteudo and not conteudo.isspace():
                html_parts.append(f"<p>{conteudo}</p>")

    # Fechar blocos abertos no final
    if code_aberto:
        html_parts.append("</code></pre>")
    if lista_aberta:
        html_parts.append(f"</{lista_aberta}>")

    html_parts.append("</div></body></html>")
    return "\n".join(html_parts)


def _escape(texto):
    """Escapa caracteres HTML básicos."""
    return (
        texto.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


# ──────────────────────────────────────────────
# Gerar PDF
# ──────────────────────────────────────────────

def gerar_pdf(page, html, caminho_pdf):
    """Carrega HTML numa nova página e gera PDF."""
    page.set_content(html, wait_until="networkidle")
    page.pdf(
        path=caminho_pdf,
        format="A4",
        margin={"top": "2cm", "right": "2.5cm", "bottom": "2cm", "left": "2.5cm"},
        print_background=True,
    )


# ──────────────────────────────────────────────
# Nomear arquivo de saída
# ──────────────────────────────────────────────

def nome_arquivo(dados, url):
    """Gera nome do arquivo PDF baseado no autor e título."""
    # Extrair ID do tweet da URL
    match = re.search(r"/status/(\d+)", url)
    tweet_id = match.group(1) if match else "artigo"

    autor = dados.get("autor", "").strip()
    titulo = dados.get("titulo", "").strip()

    # Limpar para nome de arquivo
    def limpar(texto, max_len=40):
        texto = re.sub(r"[^\w\s-]", "", texto)
        texto = re.sub(r"\s+", "_", texto.strip())
        return texto[:max_len]

    partes = []
    if autor:
        partes.append(limpar(autor, 20))
    if titulo:
        partes.append(limpar(titulo, 50))
    else:
        partes.append(tweet_id)

    return "_".join(partes) + ".pdf"


# ──────────────────────────────────────────────
# Fluxo principal
# ──────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print("Uso: python3 twitter_to_pdf.py <url>")
        print("Exemplo: python3 twitter_to_pdf.py https://x.com/mntruell/status/2026736314272591924")
        sys.exit(1)

    url = sys.argv[1]

    # Validar URL
    if not re.match(r"https?://(x\.com|twitter\.com)/", url):
        print("Erro: URL deve ser do Twitter/X (x.com ou twitter.com)")
        sys.exit(1)

    print(f"Baixando artigo: {url}")

    proxy = _proxy_config()
    chromium = _chromium_path()

    with sync_playwright() as pw:
        # Configurar launch
        launch_args = {"headless": True}
        if chromium:
            launch_args["executable_path"] = chromium
        if proxy:
            launch_args["proxy"] = proxy

        browser = pw.chromium.launch(**launch_args)
        context = browser.new_context(
            ignore_https_errors=True,
            viewport={"width": 1280, "height": 900},
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"
            ),
        )
        page = context.new_page()

        # 1. Navegar até o artigo
        print("  Carregando página...")
        page.goto(url, timeout=30000, wait_until="networkidle")

        # Aguardar o conteúdo do artigo aparecer
        try:
            page.wait_for_selector(
                '[data-testid="twitterArticleReadView"], [data-testid="tweetText"]',
                timeout=10000,
            )
        except Exception:
            print("  Aviso: seletor do artigo não encontrado, tentando extrair mesmo assim...")

        # 2. Scroll pela página para forçar carregamento lazy de code blocks
        page.evaluate("""async () => {
            const delay = ms => new Promise(r => setTimeout(r, ms));
            let y = 0;
            const maxY = document.body.scrollHeight;
            while (y < maxY) {
                y += 600;
                window.scrollTo(0, y);
                await delay(150);
            }
            window.scrollTo(0, 0);
            await delay(300);
        }""")

        # 3. Extrair conteúdo
        print("  Extraindo conteúdo...")
        dados = extrair_artigo(page)

        if not dados["blocos"]:
            print("Erro: não foi possível extrair o conteúdo do artigo.")
            print("  Verifique se a URL é de um artigo (long-form post) do Twitter/X.")
            browser.close()
            sys.exit(1)

        # Contar imagens nos blocos atomic
        n_imagens = sum(1 for b in dados["blocos"] if b.get("imgSrc"))

        print(f"  Título: {dados['titulo']}")
        print(f"  Autor: {dados['autor']} {dados['handle']}")
        print(f"  Blocos: {len(dados['blocos'])}")
        print(f"  Imagens: {n_imagens}")

        # 3. Baixar imagens dos blocos atomic como base64
        img_count = 0
        for bloco in dados["blocos"]:
            if bloco.get("imgSrc"):
                img_count += 1
                print(f"  Baixando imagem {img_count}/{n_imagens}...")
                bloco["imgBase64"] = baixar_imagem_base64(page, bloco["imgSrc"])

        # 4. Montar HTML
        print("  Montando documento...")
        html = montar_html(dados, url)

        # 5. Gerar PDF numa nova página
        print("  Gerando PDF...")
        pdf_page = context.new_page()
        caminho = nome_arquivo(dados, url)
        gerar_pdf(pdf_page, html, caminho)

        browser.close()

    print(f"\nPDF gerado: {caminho}")


if __name__ == "__main__":
    main()
