"""Rotas públicas: vitrine, página dedicada do projeto, mídias, anexos PDF e saúde."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from aplicacao.autenticacao import sessao_autenticada
from aplicacao.banco import obter_perfil, obter_resumo_banco
from aplicacao.configuracoes import obter_configuracoes
from aplicacao.servicos.arquivos import (
    EXTENSOES_ANEXO_PERMITIDAS,
    EXTENSOES_IMAGEM_PERMITIDAS,
    TIPOS_MIME_IMAGEM,
    resolver_caminho_midia,
    sanitizar_nome_download,
)
from aplicacao.servicos.catalogo import (
    listar_projetos_publicos,
    listar_tags_publicas,
    obter_anexo_por_id,
    obter_iniciais_perfil,
    obter_projeto_por_slug,
)
from aplicacao.versao import VERSAO

roteador_publico = APIRouter()


def _url_base_publica(request: Request) -> str:
    cfg = obter_configuracoes()
    if cfg.url_base:
        return cfg.url_base.rstrip("/")
    return str(request.base_url).rstrip("/")


@roteador_publico.get("/", response_class=HTMLResponse)
async def pagina_inicial(
    request: Request,
    q: str = Query(default="", max_length=120),
    tag: str = Query(default="", max_length=80),
) -> HTMLResponse:
    cfg = obter_configuracoes()
    perfil = obter_perfil(cfg)
    tags = listar_tags_publicas(cfg)
    projetos = listar_projetos_publicos(busca=q, tag_slug=tag, config=cfg)
    total_publicados = len(listar_projetos_publicos(config=cfg)) if (q or tag) else len(projetos)

    url_base = _url_base_publica(request)
    og_imagem = (
        f"{url_base}/midias/{perfil['foto_caminho']}"
        if perfil.get("foto_caminho")
        else ""
    )

    templates = request.app.state.templates
    return templates.TemplateResponse(
        request=request,
        name="vitrine.html",
        context={
            "perfil": perfil,
            "iniciais_perfil": obter_iniciais_perfil(perfil.get("nome", "")),
            "tags": tags,
            "projetos": projetos,
            "total_publicados": total_publicados,
            "busca_atual": q.strip(),
            "tag_atual": tag.strip().lower(),
            "titulo_pagina": perfil.get("titulo_site") or perfil.get("nome") or "Portfólio Técnico",
            "og_titulo": perfil.get("nome") or "Portfólio Técnico",
            "og_descricao": perfil.get("bio") or perfil.get("subtitulo") or "Portfólio técnico de projetos.",
            "og_url": f"{url_base}/",
            "og_imagem": og_imagem,
        },
    )


@roteador_publico.get("/projeto/{slug}", response_class=HTMLResponse)
async def pagina_projeto(request: Request, slug: str) -> HTMLResponse:
    cfg = obter_configuracoes()
    perfil = obter_perfil(cfg)
    eh_admin = sessao_autenticada(request, cfg)
    projeto = obter_projeto_por_slug(slug, incluir_rascunho=eh_admin, config=cfg)
    templates = request.app.state.templates

    if projeto is None:
        return templates.TemplateResponse(
            request=request,
            name="nao_encontrado.html",
            status_code=404,
            context={
                "perfil": perfil,
                "titulo_pagina": "Projeto não encontrado",
                "mensagem": "O projeto solicitado não existe ou ainda não está publicado.",
            },
        )

    url_base = _url_base_publica(request)
    capa = projeto.get("capa")
    og_imagem = f"{url_base}/midias/{capa['arquivo_original']}" if capa else ""
    og_descricao = (
        projeto.get("resumo")
        or projeto.get("solucao")
        or projeto.get("problema")
        or f"Projeto técnico por {perfil.get('nome', 'Autor')}."
    )

    return templates.TemplateResponse(
        request=request,
        name="projeto_detalhe.html",
        context={
            "perfil": perfil,
            "projeto": projeto,
            "eh_admin": eh_admin,
            "titulo_pagina": f"{projeto['titulo']} · {perfil.get('titulo_site') or 'Portfólio'}",
            "og_titulo": projeto["titulo"],
            "og_descricao": og_descricao[:220],
            "og_url": f"{url_base}/projeto/{projeto['slug']}",
            "og_imagem": og_imagem,
        },
    )


@roteador_publico.get("/midias/{caminho:path}")
async def servir_midia(caminho: str) -> FileResponse:
    cfg = obter_configuracoes()
    arquivo = resolver_caminho_midia(
        caminho,
        extensoes_permitidas=EXTENSOES_IMAGEM_PERMITIDAS,
        config=cfg,
    )
    if arquivo is None:
        raise HTTPException(status_code=404, detail="Mídia não encontrada.")

    media_type = TIPOS_MIME_IMAGEM.get(arquivo.suffix.lower(), "application/octet-stream")
    return FileResponse(
        path=arquivo,
        media_type=media_type,
        headers={
            "Cache-Control": "public, max-age=86400",
            "X-Content-Type-Options": "nosniff",
        },
    )


def _servir_anexo_pdf(request: Request, anexo_id: int, disposicao: str) -> FileResponse:
    cfg = obter_configuracoes()
    eh_admin = sessao_autenticada(request, cfg)
    anexo = obter_anexo_por_id(anexo_id, incluir_rascunho=eh_admin, config=cfg)
    if anexo is None:
        raise HTTPException(status_code=404, detail="Documento não encontrado.")

    arquivo = resolver_caminho_midia(
        anexo["caminho_arquivo"],
        extensoes_permitidas=EXTENSOES_ANEXO_PERMITIDAS,
        config=cfg,
    )
    if arquivo is None:
        raise HTTPException(status_code=404, detail="Arquivo PDF indisponível.")

    nome_download = sanitizar_nome_download(anexo.get("nome_arquivo_original", "documento.pdf"))
    return FileResponse(
        path=arquivo,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'{disposicao}; filename="{nome_download}"',
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "public, max-age=3600",
        },
    )


@roteador_publico.get("/anexos/{anexo_id}/ver")
async def visualizar_anexo(request: Request, anexo_id: int) -> FileResponse:
    return _servir_anexo_pdf(request, anexo_id, disposicao="inline")


@roteador_publico.get("/anexos/{anexo_id}/baixar")
async def baixar_anexo(request: Request, anexo_id: int) -> FileResponse:
    return _servir_anexo_pdf(request, anexo_id, disposicao="attachment")


@roteador_publico.get("/curriculo")
async def visualizar_curriculo() -> FileResponse:
    cfg = obter_configuracoes()
    perfil = obter_perfil(cfg)
    caminho_curriculo = perfil.get("curriculo_caminho")
    if not caminho_curriculo:
        raise HTTPException(status_code=404, detail="Currículo não configurado.")

    arquivo = resolver_caminho_midia(
        caminho_curriculo,
        extensoes_permitidas=EXTENSOES_ANEXO_PERMITIDAS,
        config=cfg,
    )
    if arquivo is None:
        raise HTTPException(status_code=404, detail="Arquivo de currículo não encontrado.")

    return FileResponse(
        path=arquivo,
        media_type="application/pdf",
        headers={
            "Content-Disposition": 'inline; filename="curriculo.pdf"',
            "X-Content-Type-Options": "nosniff",
        },
    )


@roteador_publico.get("/saude")
async def verificar_saude() -> JSONResponse:
    cfg = obter_configuracoes()
    try:
        resumo = obter_resumo_banco(cfg)
        return JSONResponse(
            status_code=200,
            content={
                "status": "ok",
                "versao": VERSAO,
                "banco": "ok",
                "ambiente": cfg.ambiente,
                "projetos_publicados": resumo["projetos_publicados"],
            },
        )
    except Exception as erro:
        return JSONResponse(
            status_code=503,
            content={
                "status": "erro",
                "banco": "indisponivel",
                "detalhe": str(erro),
            },
        )
