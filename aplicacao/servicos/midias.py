"""Processamento, otimização WebP/miniaturas e armazenamento seguro de mídias e PDFs."""

from __future__ import annotations

import io
import uuid
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

try:
    import pillow_jxl  # noqa: F401 - habilita decodificação de .jxl no Pillow quando instalado

    SUPORTE_JXL = True
except ImportError:
    SUPORTE_JXL = False

from aplicacao.configuracoes import Configuracoes, garantir_pastas_dados, obter_configuracoes
from aplicacao.servicos.arquivos import (
    EXTENSOES_ANEXO_PERMITIDAS,
    EXTENSOES_IMAGEM_PERMITIDAS,
    resolver_caminho_midia,
)

EXTENSOES_UPLOAD_IMAGEM = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".jxl"}
LIMITE_IMAGEM_BYTES = 15 * 1024 * 1024  # 15 MB
LIMITE_PDF_BYTES = 20 * 1024 * 1024  # 20 MB

LADO_MAXIMO_PRINCIPAL = 1920
LADO_MAXIMO_MINIATURA = 720
TAMANHO_AVATAR = 320


class ErroUpload(ValueError):
    """Erro de validação durante upload de imagem ou PDF."""


def _preparar_modo_imagem(imagem: Image.Image) -> Image.Image:
    imagem = ImageOps.exif_transpose(imagem)
    if imagem.mode in ("RGBA", "LA") or (imagem.mode == "P" and "transparency" in imagem.info):
        return imagem.convert("RGBA")
    if imagem.mode != "RGB":
        return imagem.convert("RGB")
    return imagem


def _redimensionar_proporcional(imagem: Image.Image, lado_maximo: int) -> Image.Image:
    copia = imagem.copy()
    copia.thumbnail((lado_maximo, lado_maximo), Image.Resampling.LANCZOS)
    return copia


def salvar_imagem_projeto(
    conteudo: bytes,
    nome_arquivo: str,
    projeto_id: int,
    config: Configuracoes | None = None,
) -> tuple[str, str]:
    """Valida, converte para WebP otimizado e gera miniatura para a galeria."""
    if not conteudo:
        raise ErroUpload("Arquivo de imagem vazio.")
    if len(conteudo) > LIMITE_IMAGEM_BYTES:
        raise ErroUpload("Imagem excede o limite máximo de 15 MB.")

    ext = Path(nome_arquivo or "").suffix.lower()
    if ext not in EXTENSOES_UPLOAD_IMAGEM:
        raise ErroUpload(
            "Formato de imagem não suportado. Use PNG, JPG, WebP, GIF ou JXL."
        )
    if ext == ".jxl" and not SUPORTE_JXL:
        raise ErroUpload(
            "Suporte a JPEG XL (.jxl) indisponível neste ambiente. Rode via Docker para habilitar .jxl."
        )

    cfg = config or obter_configuracoes()
    garantir_pastas_dados(cfg)

    try:
        with Image.open(io.BytesIO(conteudo)) as img_aberta:
            img_aberta.load()
            eh_gif_animado = ext == ".gif" and getattr(img_aberta, "is_animated", False)
            img_base = _preparar_modo_imagem(img_aberta)
    except (UnidentifiedImageError, OSError) as erro:
        raise ErroUpload(f"Não foi possível ler a imagem enviada ({nome_arquivo}).") from erro

    subpasta = cfg.pasta_midias / "projetos" / str(projeto_id)
    subpasta.mkdir(parents=True, exist_ok=True)
    identificador = uuid.uuid4().hex[:14]

    if eh_gif_animado:
        nome_principal = f"{identificador}.gif"
        (subpasta / nome_principal).write_bytes(conteudo)
    else:
        nome_principal = f"{identificador}.webp"
        img_principal = _redimensionar_proporcional(img_base, LADO_MAXIMO_PRINCIPAL)
        img_principal.save(
            subpasta / nome_principal,
            format="WEBP",
            quality=85,
            method=6,
        )

    nome_miniatura = f"{identificador}_mini.webp"
    img_miniatura = _redimensionar_proporcional(img_base, LADO_MAXIMO_MINIATURA)
    img_miniatura.save(
        subpasta / nome_miniatura,
        format="WEBP",
        quality=80,
        method=5,
    )

    rel_principal = f"projetos/{projeto_id}/{nome_principal}"
    rel_miniatura = f"projetos/{projeto_id}/{nome_miniatura}"
    return rel_principal, rel_miniatura


def salvar_avatar_perfil(
    conteudo: bytes,
    nome_arquivo: str,
    config: Configuracoes | None = None,
) -> str:
    """Valida e gera foto de perfil quadrada (320x320) em WebP."""
    if not conteudo:
        raise ErroUpload("Arquivo de foto vazio.")
    if len(conteudo) > LIMITE_IMAGEM_BYTES:
        raise ErroUpload("A foto de perfil excede o limite máximo de 15 MB.")

    ext = Path(nome_arquivo or "").suffix.lower()
    if ext not in EXTENSOES_UPLOAD_IMAGEM:
        raise ErroUpload("Formato de foto não suportado. Use PNG, JPG, WebP ou JXL.")
    if ext == ".jxl" and not SUPORTE_JXL:
        raise ErroUpload("Suporte a .jxl requer execução via Docker.")

    cfg = config or obter_configuracoes()
    garantir_pastas_dados(cfg)

    try:
        with Image.open(io.BytesIO(conteudo)) as img_aberta:
            img_aberta.load()
            img_base = _preparar_modo_imagem(img_aberta)
            img_quadrada = ImageOps.fit(
                img_base,
                (TAMANHO_AVATAR, TAMANHO_AVATAR),
                method=Image.Resampling.LANCZOS,
            )
    except (UnidentifiedImageError, OSError) as erro:
        raise ErroUpload("Não foi possível processar a imagem de perfil enviada.") from erro

    subpasta = cfg.pasta_midias / "perfil"
    subpasta.mkdir(parents=True, exist_ok=True)
    nome_final = f"avatar_{uuid.uuid4().hex[:12]}.webp"
    img_quadrada.save(subpasta / nome_final, format="WEBP", quality=86, method=6)
    return f"perfil/{nome_final}"


def salvar_pdf(
    conteudo: bytes,
    nome_arquivo: str,
    subpasta: str = "anexos",
    config: Configuracoes | None = None,
) -> tuple[str, int]:
    """Valida assinatura mágica %PDF- e salva o documento em dados/midias/."""
    if not conteudo:
        raise ErroUpload("Arquivo PDF vazio.")
    if len(conteudo) > LIMITE_PDF_BYTES:
        raise ErroUpload("O arquivo PDF excede o limite máximo de 20 MB.")

    ext = Path(nome_arquivo or "").suffix.lower()
    if ext != ".pdf":
        raise ErroUpload("Apenas arquivos com extensão .pdf são aceitos como documento.")

    # Verifica assinatura mágica PDF no início do arquivo
    if not conteudo[:1024].lstrip().startswith(b"%PDF-"):
        raise ErroUpload("O arquivo enviado não possui cabeçalho PDF válido.")

    cfg = config or obter_configuracoes()
    garantir_pastas_dados(cfg)

    destino_dir = cfg.pasta_midias / subpasta
    destino_dir.mkdir(parents=True, exist_ok=True)
    nome_final = f"{uuid.uuid4().hex[:14]}.pdf"
    (destino_dir / nome_final).write_bytes(conteudo)

    return f"{subpasta}/{nome_final}", len(conteudo)


def remover_arquivo_midia(
    caminho_relativo: str | None,
    config: Configuracoes | None = None,
) -> None:
    """Remove arquivo persistido dentro de dados/midias/ de forma segura."""
    if not caminho_relativo:
        return
    extensoes = EXTENSOES_IMAGEM_PERMITIDAS | EXTENSOES_ANEXO_PERMITIDAS
    arquivo = resolver_caminho_midia(
        caminho_relativo,
        extensoes_permitidas=extensoes,
        config=config,
    )
    if arquivo and arquivo.exists():
        try:
            arquivo.unlink()
        except OSError:
            pass

