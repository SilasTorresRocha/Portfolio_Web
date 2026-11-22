"""Rotas administrativas do painel /config (login, CRUD de projetos, mídias, perfil e logs)."""

from __future__ import annotations

from urllib.parse import urlencode

from fastapi import APIRouter, File, Form, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

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
from aplicacao.servicos.admin_projetos import (
    CORES_PRESET,
    adicionar_anexo_projeto,
    adicionar_link_projeto,
    adicionar_midias_projeto,
    alternar_publicacao_projeto,
    atualizar_midia_projeto,
    atualizar_perfil_admin,
    atualizar_projeto,
    criar_projeto,
    excluir_projeto,
    listar_projetos_admin,
    listar_todas_tags_admin,
    obter_projeto_admin,
    remover_anexo_projeto,
    remover_link_projeto,
    remover_midia_projeto,
    remover_tag_admin,
)
from aplicacao.servicos.backup import (
    ErroBackup,
    confirmar_restauracao_pendente,
    gerar_backup_zip,
    processar_upload_restauracao,
)
from aplicacao.servicos.markdown_seguro import renderizar_markdown_seguro
from aplicacao.servicos.metricas import (
    enviar_relatorio_diario,
    obter_estado_sistema,
    obter_resumo_acessos,
)
from aplicacao.servicos.midias import SUPORTE_JXL, ErroUpload
from aplicacao.servicos.notificacoes import (
    enviar_email_teste,
    notificar_forca_bruta_background,
    obter_config_destino_notificacao,
    salvar_config_destino_notificacao,
)
from aplicacao.versao import VERSAO

roteador_admin = APIRouter(prefix="/config", tags=["administracao"])


def _redirecionar_com_aviso(
    url_base: str,
    *,
    ok: str = "",
    erro: str = "",
    ancora: str = "",
) -> RedirectResponse:
    params = {}
    if ok:
        params["ok"] = ok
    if erro:
        params["erro"] = erro
    destino = f"{url_base}?{urlencode(params)}" if params else url_base
    if ancora:
        destino = f"{destino}#{ancora}"
    return RedirectResponse(url=destino, status_code=303)


def _contexto_base_admin(
    aba_ativa: str,
    *,
    ok: str = "",
    erro: str = "",
) -> dict:
    cfg = obter_configuracoes()
    perfil = obter_perfil(cfg)
    return {
        "perfil": perfil,
        "aba_ativa": aba_ativa,
        "versao": VERSAO,
        "suporte_jxl": SUPORTE_JXL,
        "msg_ok": ok.strip(),
        "msg_erro": erro.strip(),
        "csrf_sair": gerar_token_csrf("sair", cfg),
        "csrf_admin": gerar_token_csrf("admin", cfg),
    }


def _exigir_sessao_e_csrf(request: Request, csrf_token: str) -> tuple[bool, Response | None]:
    cfg = obter_configuracoes()
    if not sessao_autenticada(request, cfg):
        return False, RedirectResponse(url="/config/login", status_code=303)
    if not validar_token_csrf(csrf_token, "admin", cfg):
        ip = obter_ip_cliente(request, cfg)
        registrar_auditoria(ip, "ADMIN_CSRF_INVALIDO", f"rota={request.url.path}")
        return False, _redirecionar_com_aviso(
            "/config",
            erro="Sessão do formulário expirada. Tente novamente.",
        )
    return True, None


# ----------------------------------------------------------------------------
# Autenticação (/config/login e /config/sair)
# ----------------------------------------------------------------------------

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
            "titulo_pagina": "Acesso restrito",
            "erro": None,
            "senha_configurada": senha_admin_configurada(cfg),
            "csrf_token": gerar_token_csrf("login", cfg),
            "versao": VERSAO,
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
                "titulo_pagina": "Acesso restrito",
                "erro": mensagem,
                "senha_configurada": senha_admin_configurada(cfg),
                "csrf_token": gerar_token_csrf("login", cfg),
                "versao": VERSAO,
            },
        )

    if not validar_token_csrf(csrf_token, "login", cfg):
        registrar_auditoria(ip, "LOGIN_CSRF_INVALIDO", "Token CSRF ausente ou expirado")
        return _renderizar_erro(
            "Sessão do formulário expirada. Recarregue a página e tente novamente.",
            400,
        )

    if not senha_admin_configurada(cfg):
        registrar_auditoria(ip, "LOGIN_BLOQUEADO_SEM_SENHA", "PORTFOLIO_SENHA_ADMIN não definida")
        return _renderizar_erro(
            "Acesso temporariamente indisponível.",
            503,
        )

    bloqueado, segundos_restantes = controlador_tentativas.esta_bloqueado(ip, cfg)
    if bloqueado:
        registrar_auditoria(
            ip,
            "LOGIN_BLOQUEADO_RATE_LIMIT",
            f"bloqueio_restante={segundos_restantes}s",
        )
        notificar_forca_bruta_background(
            ip=ip,
            tentativas=cfg.max_tentativas_login,
            bloqueio_segundos=segundos_restantes,
            user_agent=request.headers.get("user-agent", ""),
            config=cfg,
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
        if tentativas >= cfg.max_tentativas_login:
            notificar_forca_bruta_background(
                ip=ip,
                tentativas=tentativas,
                bloqueio_segundos=cfg.janela_bloqueio_segundos,
                user_agent=request.headers.get("user-agent", ""),
                config=cfg,
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


# ----------------------------------------------------------------------------
# Painel Principal — Lista de Projetos e Tags (/config)
# ----------------------------------------------------------------------------

@roteador_admin.get("", response_class=HTMLResponse)
@roteador_admin.get("/", response_class=HTMLResponse, include_in_schema=False)
async def painel_projetos(
    request: Request,
    ok: str = Query(default=""),
    erro: str = Query(default=""),
) -> Response:
    if not sessao_autenticada(request):
        return RedirectResponse(url="/config/login", status_code=303)

    cfg = obter_configuracoes()
    ctx = _contexto_base_admin("projetos", ok=ok, erro=erro)
    ctx.update(
        {
            "titulo_pagina": "Projetos · /config",
            "projetos": listar_projetos_admin(cfg),
            "tags": listar_todas_tags_admin(cfg),
            "resumo_banco": obter_resumo_banco(cfg),
        }
    )
    return request.app.state.templates.TemplateResponse(
        request=request,
        name="config_projetos.html",
        context=ctx,
    )


# ----------------------------------------------------------------------------
# CRUD de Projetos
# ----------------------------------------------------------------------------

@roteador_admin.get("/projetos/novo", response_class=HTMLResponse)
async def formulario_novo_projeto(
    request: Request,
    erro: str = Query(default=""),
) -> Response:
    if not sessao_autenticada(request):
        return RedirectResponse(url="/config/login", status_code=303)

    cfg = obter_configuracoes()
    ctx = _contexto_base_admin("novo", erro=erro)
    ctx.update(
        {
            "titulo_pagina": "Novo Projeto · /config",
            "modo": "criar",
            "projeto": {
                "publicado": 1,
                "destaque": 0,
                "ordem": 0,
                "tags_texto": "",
                "midias": [],
                "anexos": [],
                "links_externos": [],
            },
            "todas_tags": listar_todas_tags_admin(cfg),
        }
    )
    return request.app.state.templates.TemplateResponse(
        request=request,
        name="config_projeto_form.html",
        context=ctx,
    )


@roteador_admin.post("/projetos/novo")
async def salvar_novo_projeto(
    request: Request,
    csrf_token: str = Form(default=""),
    titulo: str = Form(default=""),
    slug: str = Form(default=""),
    resumo: str = Form(default=""),
    status: str = Form(default=""),
    ano: str = Form(default=""),
    problema: str = Form(default=""),
    solucao: str = Form(default=""),
    resultado: str = Form(default=""),
    descricao_markdown: str = Form(default=""),
    tags_texto: str = Form(default=""),
    publicado: str | None = Form(default=None),
    destaque: str | None = Form(default=None),
    ordem: int = Form(default=0),
) -> Response:
    valido, resp_erro = _exigir_sessao_e_csrf(request, csrf_token)
    if not valido and resp_erro is not None:
        return resp_erro

    cfg = obter_configuracoes()
    ip = obter_ip_cliente(request, cfg)
    try:
        projeto_id, slug_final = criar_projeto(
            titulo=titulo,
            slug=slug,
            resumo=resumo,
            status=status,
            ano=ano,
            problema=problema,
            solucao=solucao,
            resultado=resultado,
            descricao_markdown=descricao_markdown,
            tags_texto=tags_texto,
            publicado=publicado is not None,
            destaque=destaque is not None,
            ordem=ordem,
            config=cfg,
        )
    except ValueError as err:
        return _redirecionar_com_aviso("/config/projetos/novo", erro=str(err))

    registrar_auditoria(ip, "PROJETO_CRIADO", f"id={projeto_id} slug={slug_final}")
    return _redirecionar_com_aviso(
        f"/config/projetos/{projeto_id}/editar",
        ok="Projeto criado! Agora você já pode enviar fotos para a galeria, anexos PDF e links.",
        ancora="galeria",
    )


@roteador_admin.get("/projetos/{projeto_id}/editar", response_class=HTMLResponse)
async def formulario_editar_projeto(
    request: Request,
    projeto_id: int,
    ok: str = Query(default=""),
    erro: str = Query(default=""),
) -> Response:
    if not sessao_autenticada(request):
        return RedirectResponse(url="/config/login", status_code=303)

    cfg = obter_configuracoes()
    projeto = obter_projeto_admin(projeto_id, cfg)
    if projeto is None:
        return _redirecionar_com_aviso("/config", erro="Projeto não encontrado.")

    ctx = _contexto_base_admin("projetos", ok=ok, erro=erro)
    ctx.update(
        {
            "titulo_pagina": f"Editar: {projeto['titulo']} · /config",
            "modo": "editar",
            "projeto": projeto,
            "todas_tags": listar_todas_tags_admin(cfg),
        }
    )
    return request.app.state.templates.TemplateResponse(
        request=request,
        name="config_projeto_form.html",
        context=ctx,
    )


@roteador_admin.post("/projetos/{projeto_id}/editar")
async def salvar_edicao_projeto(
    request: Request,
    projeto_id: int,
    csrf_token: str = Form(default=""),
    titulo: str = Form(default=""),
    slug: str = Form(default=""),
    resumo: str = Form(default=""),
    status: str = Form(default=""),
    ano: str = Form(default=""),
    problema: str = Form(default=""),
    solucao: str = Form(default=""),
    resultado: str = Form(default=""),
    descricao_markdown: str = Form(default=""),
    tags_texto: str = Form(default=""),
    publicado: str | None = Form(default=None),
    destaque: str | None = Form(default=None),
    ordem: int = Form(default=0),
) -> Response:
    valido, resp_erro = _exigir_sessao_e_csrf(request, csrf_token)
    if not valido and resp_erro is not None:
        return resp_erro

    cfg = obter_configuracoes()
    ip = obter_ip_cliente(request, cfg)
    try:
        slug_final = atualizar_projeto(
            projeto_id,
            titulo=titulo,
            slug=slug,
            resumo=resumo,
            status=status,
            ano=ano,
            problema=problema,
            solucao=solucao,
            resultado=resultado,
            descricao_markdown=descricao_markdown,
            tags_texto=tags_texto,
            publicado=publicado is not None,
            destaque=destaque is not None,
            ordem=ordem,
            config=cfg,
        )
    except (ValueError, LookupError) as err:
        return _redirecionar_com_aviso(
            f"/config/projetos/{projeto_id}/editar",
            erro=str(err),
        )

    registrar_auditoria(ip, "PROJETO_ATUALIZADO", f"id={projeto_id} slug={slug_final}")
    return _redirecionar_com_aviso(
        f"/config/projetos/{projeto_id}/editar",
        ok="Alterações do projeto salvas com sucesso.",
    )


@roteador_admin.post("/projetos/{projeto_id}/publicacao")
async def rota_alternar_publicacao(
    request: Request,
    projeto_id: int,
    csrf_token: str = Form(default=""),
) -> Response:
    valido, resp_erro = _exigir_sessao_e_csrf(request, csrf_token)
    if not valido and resp_erro is not None:
        return resp_erro

    cfg = obter_configuracoes()
    ip = obter_ip_cliente(request, cfg)
    resultado = alternar_publicacao_projeto(projeto_id, cfg)
    if resultado is None:
        return _redirecionar_com_aviso("/config", erro="Projeto não encontrado.")

    slug, publicado = resultado
    estado_txt = "publicado" if publicado else "movido para rascunho"
    registrar_auditoria(ip, "PROJETO_PUBLICACAO", f"id={projeto_id} slug={slug} publicado={publicado}")
    return _redirecionar_com_aviso("/config", ok=f"Projeto '{slug}' {estado_txt}.")


@roteador_admin.post("/projetos/{projeto_id}/excluir")
async def rota_excluir_projeto(
    request: Request,
    projeto_id: int,
    csrf_token: str = Form(default=""),
) -> Response:
    valido, resp_erro = _exigir_sessao_e_csrf(request, csrf_token)
    if not valido and resp_erro is not None:
        return resp_erro

    cfg = obter_configuracoes()
    ip = obter_ip_cliente(request, cfg)
    slug = excluir_projeto(projeto_id, cfg)
    if slug is None:
        return _redirecionar_com_aviso("/config", erro="Projeto não encontrado.")

    registrar_auditoria(ip, "PROJETO_EXCLUIDO", f"id={projeto_id} slug={slug}")
    return _redirecionar_com_aviso("/config", ok=f"Projeto '{slug}' e seus arquivos foram excluídos.")


# ----------------------------------------------------------------------------
# Galeria de Imagens do Projeto
# ----------------------------------------------------------------------------

@roteador_admin.post("/projetos/{projeto_id}/midias")
async def rota_enviar_midias(
    request: Request,
    projeto_id: int,
    csrf_token: str = Form(default=""),
    imagens: list[UploadFile] = File(default=[]),
) -> Response:
    valido, resp_erro = _exigir_sessao_e_csrf(request, csrf_token)
    if not valido and resp_erro is not None:
        return resp_erro

    cfg = obter_configuracoes()
    ip = obter_ip_cliente(request, cfg)
    arquivos: list[tuple[bytes, str]] = []
    for arquivo in imagens:
        if arquivo and arquivo.filename:
            conteudo = await arquivo.read()
            if conteudo:
                arquivos.append((conteudo, arquivo.filename))

    try:
        total = adicionar_midias_projeto(projeto_id, arquivos, cfg)
    except (ErroUpload, LookupError) as err:
        return _redirecionar_com_aviso(
            f"/config/projetos/{projeto_id}/editar",
            erro=str(err),
            ancora="galeria",
        )

    registrar_auditoria(ip, "MIDIAS_ENVIADAS", f"projeto_id={projeto_id} quantidade={total}")
    sufixo = "imagem enviada e otimizada" if total == 1 else "imagens enviadas e otimizadas"
    return _redirecionar_com_aviso(
        f"/config/projetos/{projeto_id}/editar",
        ok=f"{total} {sufixo} em WebP.",
        ancora="galeria",
    )


@roteador_admin.post("/projetos/{projeto_id}/midias/{midia_id}/editar")
async def rota_editar_midia(
    request: Request,
    projeto_id: int,
    midia_id: int,
    csrf_token: str = Form(default=""),
    legenda: str = Form(default=""),
    ordem: int = Form(default=0),
    definir_capa: str | None = Form(default=None),
) -> Response:
    valido, resp_erro = _exigir_sessao_e_csrf(request, csrf_token)
    if not valido and resp_erro is not None:
        return resp_erro

    cfg = obter_configuracoes()
    ip = obter_ip_cliente(request, cfg)
    ok = atualizar_midia_projeto(
        projeto_id,
        midia_id,
        legenda=legenda,
        ordem=ordem,
        definir_capa=definir_capa == "1",
        config=cfg,
    )
    if not ok:
        return _redirecionar_com_aviso(
            f"/config/projetos/{projeto_id}/editar",
            erro="Imagem não encontrada.",
            ancora="galeria",
        )

    registrar_auditoria(
        ip,
        "MIDIA_ATUALIZADA",
        f"projeto_id={projeto_id} midia_id={midia_id} capa={definir_capa == '1'}",
    )
    return _redirecionar_com_aviso(
        f"/config/projetos/{projeto_id}/editar",
        ok="Imagem atualizada.",
        ancora="galeria",
    )


@roteador_admin.post("/projetos/{projeto_id}/midias/{midia_id}/excluir")
async def rota_excluir_midia(
    request: Request,
    projeto_id: int,
    midia_id: int,
    csrf_token: str = Form(default=""),
) -> Response:
    valido, resp_erro = _exigir_sessao_e_csrf(request, csrf_token)
    if not valido and resp_erro is not None:
        return resp_erro

    cfg = obter_configuracoes()
    ip = obter_ip_cliente(request, cfg)
    removida = remover_midia_projeto(projeto_id, midia_id, cfg)
    if not removida:
        return _redirecionar_com_aviso(
            f"/config/projetos/{projeto_id}/editar",
            erro="Imagem não encontrada.",
            ancora="galeria",
        )

    registrar_auditoria(ip, "MIDIA_EXCLUIDA", f"projeto_id={projeto_id} midia_id={midia_id}")
    return _redirecionar_com_aviso(
        f"/config/projetos/{projeto_id}/editar",
        ok="Imagem removida da galeria.",
        ancora="galeria",
    )


# ----------------------------------------------------------------------------
# Anexos PDF do Projeto
# ----------------------------------------------------------------------------

@roteador_admin.post("/projetos/{projeto_id}/anexos")
async def rota_enviar_anexo(
    request: Request,
    projeto_id: int,
    csrf_token: str = Form(default=""),
    titulo: str = Form(default=""),
    arquivo: UploadFile = File(...),
) -> Response:
    valido, resp_erro = _exigir_sessao_e_csrf(request, csrf_token)
    if not valido and resp_erro is not None:
        return resp_erro

    cfg = obter_configuracoes()
    ip = obter_ip_cliente(request, cfg)
    conteudo = await arquivo.read()
    try:
        anexo_id = adicionar_anexo_projeto(
            projeto_id,
            titulo=titulo,
            conteudo=conteudo,
            nome_arquivo=arquivo.filename or "documento.pdf",
            config=cfg,
        )
    except (ErroUpload, LookupError) as err:
        return _redirecionar_com_aviso(
            f"/config/projetos/{projeto_id}/editar",
            erro=str(err),
            ancora="anexos",
        )

    registrar_auditoria(ip, "ANEXO_ENVIADO", f"projeto_id={projeto_id} anexo_id={anexo_id}")
    return _redirecionar_com_aviso(
        f"/config/projetos/{projeto_id}/editar",
        ok="Documento PDF anexado com sucesso.",
        ancora="anexos",
    )


@roteador_admin.post("/projetos/{projeto_id}/anexos/{anexo_id}/excluir")
async def rota_excluir_anexo(
    request: Request,
    projeto_id: int,
    anexo_id: int,
    csrf_token: str = Form(default=""),
) -> Response:
    valido, resp_erro = _exigir_sessao_e_csrf(request, csrf_token)
    if not valido and resp_erro is not None:
        return resp_erro

    cfg = obter_configuracoes()
    ip = obter_ip_cliente(request, cfg)
    if not remover_anexo_projeto(projeto_id, anexo_id, cfg):
        return _redirecionar_com_aviso(
            f"/config/projetos/{projeto_id}/editar",
            erro="Documento não encontrado.",
            ancora="anexos",
        )

    registrar_auditoria(ip, "ANEXO_EXCLUIDO", f"projeto_id={projeto_id} anexo_id={anexo_id}")
    return _redirecionar_com_aviso(
        f"/config/projetos/{projeto_id}/editar",
        ok="Documento PDF removido.",
        ancora="anexos",
    )


# ----------------------------------------------------------------------------
# Links Externos do Projeto
# ----------------------------------------------------------------------------

@roteador_admin.post("/projetos/{projeto_id}/links")
async def rota_adicionar_link(
    request: Request,
    projeto_id: int,
    csrf_token: str = Form(default=""),
    rotulo: str = Form(default=""),
    url: str = Form(default=""),
    tipo: str = Form(default="link"),
) -> Response:
    valido, resp_erro = _exigir_sessao_e_csrf(request, csrf_token)
    if not valido and resp_erro is not None:
        return resp_erro

    cfg = obter_configuracoes()
    ip = obter_ip_cliente(request, cfg)
    try:
        link_id = adicionar_link_projeto(
            projeto_id,
            rotulo=rotulo,
            url=url,
            tipo=tipo,
            config=cfg,
        )
    except (ValueError, LookupError) as err:
        return _redirecionar_com_aviso(
            f"/config/projetos/{projeto_id}/editar",
            erro=str(err),
            ancora="links",
        )

    registrar_auditoria(ip, "LINK_ADICIONADO", f"projeto_id={projeto_id} link_id={link_id}")
    return _redirecionar_com_aviso(
        f"/config/projetos/{projeto_id}/editar",
        ok="Link adicionado ao projeto.",
        ancora="links",
    )


@roteador_admin.post("/projetos/{projeto_id}/links/{link_id}/excluir")
async def rota_excluir_link(
    request: Request,
    projeto_id: int,
    link_id: int,
    csrf_token: str = Form(default=""),
) -> Response:
    valido, resp_erro = _exigir_sessao_e_csrf(request, csrf_token)
    if not valido and resp_erro is not None:
        return resp_erro

    cfg = obter_configuracoes()
    ip = obter_ip_cliente(request, cfg)
    if not remover_link_projeto(projeto_id, link_id, cfg):
        return _redirecionar_com_aviso(
            f"/config/projetos/{projeto_id}/editar",
            erro="Link não encontrado.",
            ancora="links",
        )

    registrar_auditoria(ip, "LINK_EXCLUIDO", f"projeto_id={projeto_id} link_id={link_id}")
    return _redirecionar_com_aviso(
        f"/config/projetos/{projeto_id}/editar",
        ok="Link removido.",
        ancora="links",
    )


# ----------------------------------------------------------------------------
# Tags
# ----------------------------------------------------------------------------

@roteador_admin.post("/tags/{tag_id}/excluir")
async def rota_excluir_tag(
    request: Request,
    tag_id: int,
    csrf_token: str = Form(default=""),
) -> Response:
    valido, resp_erro = _exigir_sessao_e_csrf(request, csrf_token)
    if not valido and resp_erro is not None:
        return resp_erro

    cfg = obter_configuracoes()
    ip = obter_ip_cliente(request, cfg)
    nome = remover_tag_admin(tag_id, cfg)
    if not nome:
        return _redirecionar_com_aviso("/config", erro="Tag não encontrada.")

    registrar_auditoria(ip, "TAG_EXCLUIDA", f"tag_id={tag_id} nome={nome}")
    return _redirecionar_com_aviso("/config", ok=f"Tag '{nome}' removida.")


# ----------------------------------------------------------------------------
# Perfil & Aparência (/config/perfil)
# ----------------------------------------------------------------------------

@roteador_admin.get("/perfil", response_class=HTMLResponse)
async def pagina_perfil(
    request: Request,
    ok: str = Query(default=""),
    erro: str = Query(default=""),
) -> Response:
    if not sessao_autenticada(request):
        return RedirectResponse(url="/config/login", status_code=303)

    ctx = _contexto_base_admin("perfil", ok=ok, erro=erro)
    ctx.update(
        {
            "titulo_pagina": "Perfil & Aparência · /config",
            "cores_preset": CORES_PRESET,
        }
    )
    return request.app.state.templates.TemplateResponse(
        request=request,
        name="config_perfil.html",
        context=ctx,
    )


@roteador_admin.post("/perfil")
async def salvar_perfil(
    request: Request,
    csrf_token: str = Form(default=""),
    nome: str = Form(default=""),
    subtitulo: str = Form(default=""),
    bio: str = Form(default=""),
    titulo_site: str = Form(default=""),
    cor_destaque: str = Form(default="#3b82f6"),
    email: str = Form(default=""),
    github_url: str = Form(default=""),
    linkedin_url: str = Form(default=""),
    remover_foto: str | None = Form(default=None),
    remover_curriculo: str | None = Form(default=None),
    foto: UploadFile | None = File(default=None),
    curriculo: UploadFile | None = File(default=None),
) -> Response:
    valido, resp_erro = _exigir_sessao_e_csrf(request, csrf_token)
    if not valido and resp_erro is not None:
        return resp_erro

    cfg = obter_configuracoes()
    ip = obter_ip_cliente(request, cfg)

    nova_foto = None
    if foto and foto.filename:
        bytes_foto = await foto.read()
        if bytes_foto:
            nova_foto = (bytes_foto, foto.filename)

    novo_curriculo = None
    if curriculo and curriculo.filename:
        bytes_cv = await curriculo.read()
        if bytes_cv:
            novo_curriculo = (bytes_cv, curriculo.filename)

    try:
        atualizar_perfil_admin(
            nome=nome,
            subtitulo=subtitulo,
            bio=bio,
            titulo_site=titulo_site,
            cor_destaque=cor_destaque,
            email=email,
            github_url=github_url,
            linkedin_url=linkedin_url,
            nova_foto=nova_foto,
            remover_foto=remover_foto is not None,
            novo_curriculo=novo_curriculo,
            remover_curriculo=remover_curriculo is not None,
            config=cfg,
        )
    except (ValueError, ErroUpload) as err:
        return _redirecionar_com_aviso("/config/perfil", erro=str(err))

    registrar_auditoria(ip, "PERFIL_ATUALIZADO", f"nome={nome.strip()} cor={cor_destaque}")
    return _redirecionar_com_aviso("/config/perfil", ok="Perfil e aparência atualizados.")


# ----------------------------------------------------------------------------
# Logs & Diagnóstico (/config/logs)
# ----------------------------------------------------------------------------

@roteador_admin.get("/logs", response_class=HTMLResponse)
async def pagina_logs(
    request: Request,
    aba_log: str = Query(default="auditoria"),
) -> Response:
    if not sessao_autenticada(request):
        return RedirectResponse(url="/config/login", status_code=303)

    cfg = obter_configuracoes()
    tipo_log = "aplicacao" if aba_log == "aplicacao" else "auditoria"
    ctx = _contexto_base_admin("logs")
    ctx.update(
        {
            "titulo_pagina": "Logs & Sistema · /config",
            "config": cfg,
            "resumo_banco": obter_resumo_banco(cfg),
            "tipo_log": tipo_log,
            "linhas_log": ler_ultimos_logs(tipo=tipo_log, limite=80, config=cfg),
        }
    )
    return request.app.state.templates.TemplateResponse(
        request=request,
        name="config_logs.html",
        context=ctx,
    )


# ----------------------------------------------------------------------------
# Backup, Restauração, Notificações SMTP e Métricas (/config/backup)
# ----------------------------------------------------------------------------

@roteador_admin.get("/backup", response_class=HTMLResponse)
async def pagina_backup_e_relatorios(
    request: Request,
    ok: str = Query(default=""),
    erro: str = Query(default=""),
) -> Response:
    if not sessao_autenticada(request):
        return RedirectResponse(url="/config/login", status_code=303)

    cfg = obter_configuracoes()
    ctx = _contexto_base_admin("backup", ok=ok, erro=erro)
    ctx.update(
        {
            "titulo_pagina": "Backup & Relatórios · /config",
            "config": cfg,
            "resumo_banco": obter_resumo_banco(cfg),
            "metricas_hoje": obter_resumo_acessos(dias=1, config=cfg),
            "metricas_7d": obter_resumo_acessos(dias=7, config=cfg),
            "ultimo_relatorio": obter_estado_sistema("ultimo_relatorio_diario", cfg),
            "destino_notif": obter_config_destino_notificacao(cfg),
            "confirmacao_pendente": None,
        }
    )
    return request.app.state.templates.TemplateResponse(
        request=request,
        name="config_backup.html",
        context=ctx,
    )


@roteador_admin.post("/backup/baixar")
async def rota_baixar_backup(
    request: Request,
    csrf_token: str = Form(default=""),
) -> Response:
    valido, resp_erro = _exigir_sessao_e_csrf(request, csrf_token)
    if not valido and resp_erro is not None:
        return resp_erro

    cfg = obter_configuracoes()
    ip = obter_ip_cliente(request, cfg)
    try:
        dados_zip, nome_arquivo, resumo = gerar_backup_zip(cfg)
    except ErroBackup as err:
        return _redirecionar_com_aviso("/config/backup", erro=str(err))

    registrar_auditoria(
        ip,
        "BACKUP_EXPORTADO",
        f"arquivo={nome_arquivo} projetos={resumo['projetos']} arquivos={resumo['total_arquivos']}",
    )
    return Response(
        content=dados_zip,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{nome_arquivo}"',
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "no-store",
        },
    )


@roteador_admin.post("/backup/restaurar", response_class=HTMLResponse)
async def rota_restaurar_backup(
    request: Request,
    csrf_token: str = Form(default=""),
    arquivo: UploadFile = File(...),
) -> Response:
    valido, resp_erro = _exigir_sessao_e_csrf(request, csrf_token)
    if not valido and resp_erro is not None:
        return resp_erro

    cfg = obter_configuracoes()
    ip = obter_ip_cliente(request, cfg)
    conteudo = await arquivo.read()

    try:
        resultado = processar_upload_restauracao(
            conteudo,
            confirmar_chave_diferente=False,
            config=cfg,
        )
    except ErroBackup as err:
        registrar_auditoria(ip, "BACKUP_RESTORE_RECUSADO", str(err))
        return _redirecionar_com_aviso("/config/backup", erro=str(err))

    if resultado["status"] == "requer_confirmacao":
        registrar_auditoria(ip, "BACKUP_HMAC_DIVERGENTE", "Aguardando confirmação manual")
        ctx = _contexto_base_admin("backup")
        ctx.update(
            {
                "titulo_pagina": "Confirmar Restauração · /config",
                "config": cfg,
                "resumo_banco": obter_resumo_banco(cfg),
                "metricas_hoje": obter_resumo_acessos(dias=1, config=cfg),
                "metricas_7d": obter_resumo_acessos(dias=7, config=cfg),
                "ultimo_relatorio": obter_estado_sistema("ultimo_relatorio_diario", cfg),
                "destino_notif": obter_config_destino_notificacao(cfg),
                "confirmacao_pendente": resultado,
            }
        )
        return request.app.state.templates.TemplateResponse(
            request=request,
            name="config_backup.html",
            context=ctx,
        )

    resumo = resultado["manifesto"]["resumo"]
    registrar_auditoria(
        ip,
        "BACKUP_RESTAURADO",
        f"hmac_valido=True projetos={resumo['projetos']} arquivos={resumo['total_arquivos']}",
    )
    return _redirecionar_com_aviso(
        "/config/backup",
        ok=(
            f"Backup restaurado com assinatura HMAC válida! "
            f"{resumo['projetos']} projeto(s) e {resumo['total_arquivos']} arquivo(s) recuperados."
        ),
    )


@roteador_admin.post("/backup/confirmar-restauracao")
async def rota_confirmar_restauracao(
    request: Request,
    csrf_token: str = Form(default=""),
    token: str = Form(default=""),
    confirma_chave: str | None = Form(default=None),
) -> Response:
    valido, resp_erro = _exigir_sessao_e_csrf(request, csrf_token)
    if not valido and resp_erro is not None:
        return resp_erro

    if confirma_chave != "1":
        return _redirecionar_com_aviso(
            "/config/backup",
            erro="Marque a caixa de confirmação para restaurar um backup com chave diferente.",
        )

    cfg = obter_configuracoes()
    ip = obter_ip_cliente(request, cfg)
    try:
        resultado = confirmar_restauracao_pendente(token, cfg)
    except ErroBackup as err:
        return _redirecionar_com_aviso("/config/backup", erro=str(err))

    resumo = resultado["manifesto"]["resumo"]
    registrar_auditoria(
        ip,
        "BACKUP_RESTAURADO_CHAVE_DIFERENTE",
        f"projetos={resumo['projetos']} arquivos={resumo['total_arquivos']}",
    )
    return _redirecionar_com_aviso(
        "/config/backup",
        ok=(
            f"Backup restaurado após confirmação manual (SHA-256 e SQLite validados). "
            f"{resumo['projetos']} projeto(s) recuperados."
        ),
    )


@roteador_admin.post("/notificacoes/destino")
async def rota_salvar_destino_notificacoes(
    request: Request,
    csrf_token: str = Form(default=""),
    modo_destino: str = Form(default="smtp"),
    email_personalizado: str = Form(default=""),
) -> Response:
    valido, resp_erro = _exigir_sessao_e_csrf(request, csrf_token)
    if not valido and resp_erro is not None:
        return resp_erro

    cfg = obter_configuracoes()
    ip = obter_ip_cliente(request, cfg)
    try:
        destino = salvar_config_destino_notificacao(
            modo=modo_destino,
            email_personalizado=email_personalizado,
            config=cfg,
        )
    except ValueError as err:
        return _redirecionar_com_aviso("/config/backup", erro=str(err), ancora="notificacoes")

    registrar_auditoria(
        ip,
        "DESTINO_NOTIFICACOES_ATUALIZADO",
        f"modo={destino['modo']} destinatario={destino['efetivo']}",
    )
    return _redirecionar_com_aviso(
        "/config/backup",
        ok=f"Destinatário atualizado para {destino['efetivo']} ({destino['origem']}).",
        ancora="notificacoes",
    )


@roteador_admin.post("/notificacoes/teste")
async def rota_testar_smtp(
    request: Request,
    csrf_token: str = Form(default=""),
) -> Response:
    valido, resp_erro = _exigir_sessao_e_csrf(request, csrf_token)
    if not valido and resp_erro is not None:
        return resp_erro

    cfg = obter_configuracoes()
    ip = obter_ip_cliente(request, cfg)
    destino = obter_config_destino_notificacao(cfg)["efetivo"]
    ok, detalhe = enviar_email_teste(cfg)
    if ok:
        registrar_auditoria(ip, "SMTP_TESTE_OK", f"destinatario={destino}")
        return _redirecionar_com_aviso(
            "/config/backup",
            ok=f"E-mail de teste enviado para {destino}.",
            ancora="notificacoes",
        )
    registrar_auditoria(ip, "SMTP_TESTE_FALHA", detalhe)
    return _redirecionar_com_aviso("/config/backup", erro=detalhe, ancora="notificacoes")


@roteador_admin.post("/notificacoes/relatorio")
async def rota_enviar_relatorio_agora(
    request: Request,
    csrf_token: str = Form(default=""),
) -> Response:
    valido, resp_erro = _exigir_sessao_e_csrf(request, csrf_token)
    if not valido and resp_erro is not None:
        return resp_erro

    cfg = obter_configuracoes()
    destino = obter_config_destino_notificacao(cfg)["efetivo"]
    ok, detalhe = enviar_relatorio_diario(forcar=True, config=cfg)
    if ok:
        return _redirecionar_com_aviso(
            "/config/backup",
            ok=f"Relatório de acessos enviado para {destino}.",
            ancora="notificacoes",
        )
    return _redirecionar_com_aviso("/config/backup", erro=detalhe, ancora="notificacoes")


# ----------------------------------------------------------------------------
# API interna de pré-visualização Markdown (autenticada)
# ----------------------------------------------------------------------------

@roteador_admin.post("/api/preview-markdown")
async def preview_markdown(
    request: Request,
    csrf_token: str = Form(default=""),
    texto: str = Form(default=""),
) -> JSONResponse:
    cfg = obter_configuracoes()
    if not sessao_autenticada(request, cfg):
        return JSONResponse(status_code=401, content={"erro": "Não autenticado."})
    if not validar_token_csrf(csrf_token, "admin", cfg):
        return JSONResponse(status_code=400, content={"erro": "Token CSRF inválido."})
    return JSONResponse(content={"html": renderizar_markdown_seguro(texto)})
