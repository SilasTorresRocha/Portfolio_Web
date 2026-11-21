"""Ponto de entrada FastAPI da aplicação de Portfólio Técnico."""

from __future__ import annotations

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
        "Aplicação iniciada | ambiente=%s | dados=%s | confiar_proxy=%s | cookie_seguro=%s",
        cfg.ambiente,
        cfg.pasta_dados,
        cfg.confiar_proxy,
        cfg.cookie_seguro,
    )
    if cfg.chave_secreta_gerada:
        logger_app.warning(
            "PORTFOLIO_CHAVE_SECRETA não definida no .env; usando chave temporária em memória."
        )
    if not cfg.senha_admin:
        logger_app.warning(
            "PORTFOLIO_SENHA_ADMIN não definida no .env; login em /config permanecerá bloqueado."
        )

    yield

    logger_app.info("Aplicação finalizada.")


def criar_aplicacao() -> FastAPI:
    cfg = obter_configuracoes()
    app = FastAPI(
        title="Portfólio Técnico",
        docs_url="/docs" if not cfg.eh_producao else None,
        redoc_url=None,
        lifespan=lifespan,
    )

    PASTA_ESTATICOS.mkdir(parents=True, exist_ok=True)
    app.mount("/estaticos", StaticFiles(directory=str(PASTA_ESTATICOS)), name="estaticos")
    app.state.templates = Jinja2Templates(directory=str(PASTA_TEMPLATES))

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

        if not request.url.path.startswith("/estaticos/"):
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

