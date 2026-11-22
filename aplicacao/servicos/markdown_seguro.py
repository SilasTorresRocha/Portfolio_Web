"""Compilação de Markdown com sanitização estrita de HTML contra XSS."""

from __future__ import annotations

import html

try:
    import markdown as lib_markdown
except ImportError:  # pragma: no cover - fallback caso ambiente local não tenha libs instaladas
    lib_markdown = None

try:
    import nh3 as lib_nh3
except ImportError:  # pragma: no cover
    lib_nh3 = None

TAGS_HTML_PERMITIDAS = {
    "p",
    "br",
    "hr",
    "h2",
    "h3",
    "h4",
    "h5",
    "strong",
    "b",
    "em",
    "i",
    "del",
    "code",
    "pre",
    "blockquote",
    "ul",
    "ol",
    "li",
    "a",
    "table",
    "thead",
    "tbody",
    "tr",
    "th",
    "td",
}

ATRIBUTOS_HTML_PERMITIDOS = {
    "a": {"href", "title"},
    "code": {"class"},
    "th": {"align"},
    "td": {"align"},
}


def renderizar_markdown_seguro(texto_markdown: str) -> str:
    """Converte Markdown em HTML limpo e seguro contra injeção de scripts."""
    conteudo = (texto_markdown or "").strip()
    if not conteudo:
        return ""

    if lib_markdown is None or lib_nh3 is None:
        # Fallback seguro caso o servidor rode sem markdown/nh3 instalados
        paragrafos = [
            f"<p>{html.escape(bloco).replace(chr(10), '<br>')}</p>"
            for bloco in conteudo.split("\n\n")
            if bloco.strip()
        ]
        return "\n".join(paragrafos)

    html_bruto = lib_markdown.markdown(
        conteudo,
        extensions=["fenced_code", "tables", "sane_lists", "nl2br"],
        output_format="html",
    )

    return lib_nh3.clean(
        html_bruto,
        tags=TAGS_HTML_PERMITIDAS,
        attributes=ATRIBUTOS_HTML_PERMITIDOS,
        url_schemes={"http", "https", "mailto"},
        link_rel="noopener noreferrer",
    )

