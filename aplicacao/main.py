"""Ponto de entrada FastAPI da aplicação de Portfólio Técnico."""

from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI, Request, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from aplicacao.banco import inicializar_banco
from aplicacao.configuracoes import garantir_pastas_dados, obter_configuracoes
from aplicacao.registros import (
    configurar_logs,
    obter_ip_cliente,
    obter_logger_aplicacao,
)
from aplicacao.rotas.administracao import roteador_admin
from aplicacao.rotas.publicas import roteador_publico
from aplicacao.servicos.metricas import agendador_relatorio_diario
from aplicacao.versao import REPOSITORIO_URL, VERSAO

PASTA_APLICACAO = Path(__file__).resolve().parent
PASTA_TEMPLATES = PASTA_APLICACAO / "templates"
PASTA_ESTATICOS = PASTA_APLICACAO / "estaticos"


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    cfg = obter_configuracoes()
    garantir_pastas_dados(cfg)
    logger_app, _ = configurar_logs(cfg)
    inicializar_banco(cfg)

    logger_app.info(
        "Aplicação iniciada | versao=%s | ambiente=%s | dados=%s | proxy=%s | cookie_seguro=%s | smtp=%s",
        VERSAO,
        cfg.ambiente,
        cfg.pasta_dados,
        cfg.confiar_proxy,
        cfg.cookie_seguro,
        cfg.smtp_configurado,
    )
    if cfg.chave_secreta_gerada:
        logger_app.warning(
            "PORTFOLIO_CHAVE_SECRETA não definida no .env; usando chave temporária em memória."
        )
    if not cfg.senha_admin:
        logger_app.warning(
            "PORTFOLIO_SENHA_ADMIN não definida no .env; login em /config permanecerá bloqueado."
        )

    tarefa_relatorio = asyncio.create_task(
        agendador_relatorio_diario(cfg),
        name="agendador-relatorio-diario",
    )

    try:
        yield
    finally:
        tarefa_relatorio.cancel()
        try:
            await tarefa_relatorio
        except asyncio.CancelledError:
            pass
        logger_app.info("Aplicação finalizada.")


def criar_aplicacao() -> FastAPI:
    cfg = obter_configuracoes()
    app = FastAPI(
        title="Portfólio Técnico",
        version=VERSAO,
        docs_url=None if cfg.eh_producao else "/docs",
        openapi_url=None if cfg.eh_producao else "/openapi.json",
        redoc_url=None,
        lifespan=lifespan,
    )

    PASTA_ESTATICOS.mkdir(parents=True, exist_ok=True)
    app.mount("/estaticos", StaticFiles(directory=str(PASTA_ESTATICOS)), name="estaticos")
    templates = Jinja2Templates(directory=str(PASTA_TEMPLATES))
    templates.env.globals["VERSAO"] = VERSAO
    templates.env.globals["REPOSITORIO_URL"] = REPOSITORIO_URL
    app.state.templates = templates

    @app.middleware("http")
    async def middleware_requisicoes(request: Request, call_next) -> Response:
        inicio = time.perf_counter()
        ip = obter_ip_cliente(request, cfg)
        logger_app = obter_logger_aplicacao()

        try:
            resposta: Response = await call_next(request)
        except Exception:
            duracao_ms = (time.perf_counter() - inicio) * 1000
            logger_app.exception(
                "HTTP 500 | ip=%s | %s %s | %.1fms",
                ip,
                request.method,
                request.url.path,
                duracao_ms,
            )
            raise

        duracao_ms = (time.perf_counter() - inicio) * 1000
        resposta.headers.setdefault("X-Content-Type-Options", "nosniff")
        resposta.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        resposta.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")

        ignorar_log_acesso = (
            request.url.path.startswith("/estaticos/")
            or (request.url.path == "/saude" and resposta.status_code < 400)
        )
        if not ignorar_log_acesso:
            logger_app.info(
                "HTTP %s | ip=%s | %s %s | %.1fms",
                resposta.status_code,
                ip,
                request.method,
                request.url.path,
                duracao_ms,
            )

        return resposta

    app.include_router(roteador_publico)
    app.include_router(roteador_admin)
    return app


app = criar_aplicacao()

