"""Resolução segura de arquivos em dados/midias e formatação de metadados."""

from __future__ import annotations

import re
from pathlib import Path

from aplicacao.configuracoes import Configuracoes, obter_configuracoes

EXTENSOES_IMAGEM_PERMITIDAS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"}
EXTENSOES_ANEXO_PERMITIDAS = {".pdf"}

TIPOS_MIME_IMAGEM = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".svg": "image/svg+xml",
}


def resolver_caminho_midia(
    caminho_relativo: str,
    *,
    extensoes_permitidas: set[str] | None = None,
    config: Configuracoes | None = None,
) -> Path | None:
    """Resolve um caminho relativo dentro de dados/midias evitando path traversal."""
    if not caminho_relativo or "\x00" in caminho_relativo:
        return None

    cfg = config or obter_configuracoes()
    base = cfg.pasta_midias.resolve()
    normalizado = caminho_relativo.replace("\\", "/").lstrip("/")

    try:
        destino = (base / normalizado).resolve()
        destino.relative_to(base)
    except (ValueError, OSError):
        return None

    if not destino.is_file():
        return None

    if extensoes_permitidas is not None:
        if destino.suffix.lower() not in extensoes_permitidas:
            return None

    return destino


def formatar_tamanho_bytes(tamanho_bytes: int) -> str:
    """Formata tamanho de arquivo em formato técnico legível (ex.: 142 KB, 1.4 MB)."""
    valor = max(0, int(tamanho_bytes or 0))
    if valor < 1024:
        return f"{valor} B"
    kb = valor / 1024
    if kb < 1024:
        return f"{kb:.0f} KB" if kb >= 10 else f"{kb:.1f} KB"
    mb = kb / 1024
    return f"{mb:.1f} MB"


def sanitizar_nome_download(nome_original: str, padrao: str = "documento.pdf") -> str:
    """Remove caracteres inseguros de nomes de arquivo para Content-Disposition."""
    nome = Path(nome_original or padrao).name
    limpo = re.sub(r"[^A-Za-z0-9._ -]+", "_", nome).strip(" ._")
    if not limpo:
        return padrao
    if not limpo.lower().endswith(".pdf"):
        limpo = f"{limpo}.pdf"
    return limpo

