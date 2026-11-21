"""Rotas administrativas do painel /config (autenticação, diagnóstico e logs)."""

from __future__ import annotations

from fastapi import APIRouter, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from aplicacao.autenticacao import (
    controlador_tentativas,
    definir_cookie_sessao,
    gerar_token_csrf,
    remover_cookie_sessao,
    senha_admin_configurada,
    sessao_autenticada,
    validar_token_csrf,
    verificar_senha,
)
from aplicacao.banco import obter_perfil, obter_resumo_banco
from aplicacao.configuracoes import obter_configuracoes
from aplicacao.registros import ler_ultimos_logs, obter_ip_cliente, registrar_auditoria

roteador_admin = APIRouter(prefix="/config", tags=["administracao"])


@roteador_admin.get("", response_class=HTMLResponse)
@roteador_admin.get("/", response_class=HTMLResponse, include_in_schema=False)
async def painel_config(
    request: Request,
    aba_log: str = Query(default="auditoria"),
) -> Response:
    if not sessao_autenticada(request):
        return RedirectResponse(url="/config/login", status_code=303)

    cfg = obter_configuracoes()
    perfil = obter_perfil(cfg)
    resumo_banco = obter_resumo_banco(cfg)
    tipo_log = "aplicacao" if aba_log == "aplicacao" else "auditoria"
    linhas_log = ler_ultimos_logs(tipo=tipo_log, limite=60, config=cfg)

    templates = request.app.state.templates
    return templates.TemplateResponse(
        request=request,
        name="config_painel.html",
        context={
            "perfil": perfil,
            "titulo_pagina": "Painel /config",
            "resumo_banco": resumo_banco,
            "config": cfg,
            "tipo_log": tipo_log,
            "linhas_log": linhas_log,
            "csrf_sair": gerar_token_csrf("sair", cfg),
        },
    )


@roteador_admin.get("/login", response_class=HTMLResponse)
async def pagina_login(request: Request) -> Response:
    if sessao_autenticada(request):
        return RedirectResponse(url="/config", status_code=303)

    cfg = obter_configuracoes()
    perfil = obter_perfil(cfg)
    templates = request.app.state.templates
    return templates.TemplateResponse(
        request=request,
        name="config_login.html",
        context={
            "perfil": perfil,
            "titulo_pagina": "Acesso /config",
            "erro": None,
            "senha_configurada": senha_admin_configurada(cfg),
            "csrf_token": gerar_token_csrf("login", cfg),
        },
    )


@roteador_admin.post("/login", response_class=HTMLResponse)
async def efetuar_login(
    request: Request,
    senha: str = Form(default=""),
    csrf_token: str = Form(default=""),
) -> Response:
    cfg = obter_configuracoes()
    ip = obter_ip_cliente(request, cfg)
    perfil = obter_perfil(cfg)
    templates = request.app.state.templates

    def _renderizar_erro(mensagem: str, status_code: int = 401) -> HTMLResponse:
        return templates.TemplateResponse(
            request=request,
            name="config_login.html",
            status_code=status_code,
            context={
                "perfil": perfil,
                "titulo_pagina": "Acesso /config",
                "erro": mensagem,
                "senha_configurada": senha_admin_configurada(cfg),
                "csrf_token": gerar_token_csrf("login", cfg),
            },
        )

    if not validar_token_csrf(csrf_token, "login", cfg):
        registrar_auditoria(ip, "LOGIN_CSRF_INVALIDO", "Token CSRF ausente ou expirado")
        return _renderizar_erro("Sessão do formulário expirada. Recarregue a página e tente novamente.", 400)

    if not senha_admin_configurada(cfg):
        registrar_auditoria(ip, "LOGIN_BLOQUEADO_SEM_SENHA", "PORTFOLIO_SENHA_ADMIN não definida no .env")
        return _renderizar_erro(
            "Defina PORTFOLIO_SENHA_ADMIN no arquivo .env antes de acessar o painel.",
            503,
        )

    bloqueado, segundos_restantes = controlador_tentativas.esta_bloqueado(ip, cfg)
    if bloqueado:
        registrar_auditoria(
            ip,
            "LOGIN_BLOQUEADO_RATE_LIMIT",
            f"bloqueio_restante={segundos_restantes}s",
        )
        return _renderizar_erro(
            f"Muitas tentativas inválidas. Aguarde {segundos_restantes}s para tentar novamente.",
            429,
        )

    if not verificar_senha(senha, cfg):
        tentativas = controlador_tentativas.registrar_falha(ip, cfg)
        registrar_auditoria(
            ip,
            "LOGIN_RECUSADO",
            f"tentativa={tentativas}/{cfg.max_tentativas_login}",
        )
        return _renderizar_erro("Senha inválida.", 401)

    controlador_tentativas.limpar_ip(ip)
    registrar_auditoria(ip, "LOGIN_SUCESSO", "Acesso concedido ao /config")

    resposta = RedirectResponse(url="/config", status_code=303)
    definir_cookie_sessao(resposta, cfg)
    return resposta


@roteador_admin.post("/sair")
async def efetuar_logout(
    request: Request,
    csrf_token: str = Form(default=""),
) -> Response:
    cfg = obter_configuracoes()
    ip = obter_ip_cliente(request, cfg)

    if not validar_token_csrf(csrf_token, "sair", cfg):
        registrar_auditoria(ip, "LOGOUT_CSRF_INVALIDO")
        return RedirectResponse(url="/config", status_code=303)

    registrar_auditoria(ip, "LOGOUT", "Sessão encerrada pelo usuário")
    resposta = RedirectResponse(url="/config/login", status_code=303)
    remover_cookie_sessao(resposta)
    return resposta

