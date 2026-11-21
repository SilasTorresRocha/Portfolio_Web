"""Rotas públicas (vitrine e verificação de saúde)."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse

from aplicacao.banco import obter_perfil, obter_resumo_banco
from aplicacao.configuracoes import obter_configuracoes

roteador_publico = APIRouter()


@roteador_publico.get("/", response_class=HTMLResponse)
async def pagina_inicial(request: Request) -> HTMLResponse:
    perfil = obter_perfil()
    resumo = obter_resumo_banco()
    templates = request.app.state.templates
    return templates.TemplateResponse(
        request=request,
        name="inicio_placeholder.html",
        context={
            "perfil": perfil,
            "resumo": resumo,
            "titulo_pagina": perfil.get("titulo_site", "Portfólio Técnico"),
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

