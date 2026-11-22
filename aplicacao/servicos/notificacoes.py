"""Envio de notificações por e-mail via SMTP (alertas de segurança, testes e relatórios)."""

from __future__ import annotations

import re
import smtplib
import ssl
import threading
import time
from datetime import datetime
from email.message import EmailMessage

from aplicacao.banco import agora_iso, obter_conexao, obter_perfil
from aplicacao.configuracoes import Configuracoes, obter_configuracoes
from aplicacao.registros import (
    _obter_fuso_horario,
    obter_logger_aplicacao,
    registrar_auditoria,
)
from aplicacao.versao import VERSAO

_lock_cooldown = threading.Lock()
_ultimo_alerta_por_ip: dict[str, float] = {}

MODOS_DESTINO_VALIDOS = {"smtp", "perfil", "personalizado"}
REGEX_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _ler_estado(chave: str, config: Configuracoes | None = None) -> str:
    try:
        with obter_conexao(config) as conexao:
            row = conexao.execute(
                "SELECT valor FROM estado_sistema WHERE chave = ?",
                (chave,),
            ).fetchone()
        return str(row["valor"]).strip() if row else ""
    except Exception:
        return ""


def _gravar_estado(chave: str, valor: str, config: Configuracoes | None = None) -> None:
    with obter_conexao(config) as conexao:
        conexao.execute(
            """
            INSERT INTO estado_sistema (chave, valor, atualizado_em)
            VALUES (?, ?, ?)
            ON CONFLICT(chave) DO UPDATE SET valor = excluded.valor, atualizado_em = excluded.atualizado_em
            """,
            (chave, valor, agora_iso()),
        )


def obter_config_destino_notificacao(config: Configuracoes | None = None) -> dict[str, str]:
    """Retorna o modo configurado no painel e resolve o destinatário efetivo."""
    cfg = config or obter_configuracoes()
    perfil = obter_perfil(cfg)
    email_perfil = (perfil.get("email") or "").strip()
    email_smtp = (cfg.smtp_destinatario or cfg.smtp_usuario or "").strip()

    modo = _ler_estado("notificacao_modo_destino", cfg)
    if modo not in MODOS_DESTINO_VALIDOS:
        modo = "smtp"
    email_personalizado = _ler_estado("notificacao_email_personalizado", cfg)

    if modo == "perfil" and email_perfil:
        efetivo = email_perfil
        origem = "E-mail de contato (Perfil)"
    elif modo == "personalizado" and email_personalizado:
        efetivo = email_personalizado
        origem = "E-mail específico para relatórios"
    else:
        efetivo = email_smtp
        origem = "E-mail da API SMTP (.env)"

    return {
        "modo": modo,
        "email_perfil": email_perfil,
        "email_smtp": email_smtp,
        "email_personalizado": email_personalizado,
        "efetivo": efetivo,
        "origem": origem,
    }


def salvar_config_destino_notificacao(
    modo: str,
    email_personalizado: str = "",
    config: Configuracoes | None = None,
) -> dict[str, str]:
    """Valida e persiste a escolha do destinatário das notificações no SQLite."""
    cfg = config or obter_configuracoes()
    modo_limpo = (modo or "smtp").strip().lower()
    if modo_limpo not in MODOS_DESTINO_VALIDOS:
        raise ValueError("Opção de destinatário inválida.")

    email_limpo = (email_personalizado or "").strip()[:160]
    if modo_limpo == "personalizado":
        if not email_limpo or not REGEX_EMAIL.match(email_limpo):
            raise ValueError("Informe um endereço de e-mail válido para os relatórios.")
    elif modo_limpo == "perfil":
        email_perfil = (obter_perfil(cfg).get("email") or "").strip()
        if not email_perfil:
            raise ValueError(
                "Preencha primeiro o 'E-mail de contato' na aba Perfil & Aparência."
            )

    _gravar_estado("notificacao_modo_destino", modo_limpo, cfg)
    if email_limpo:
        _gravar_estado("notificacao_email_personalizado", email_limpo, cfg)
    elif modo_limpo != "personalizado":
        # Mantém salvo ou limpa somente se vazio e não usado
        pass

    return obter_config_destino_notificacao(cfg)


def _agora_local_formatado() -> str:
    return datetime.now(tz=_obter_fuso_horario()).strftime("%d/%m/%Y %H:%M:%S")


def enviar_email(
    assunto: str,
    corpo_texto: str,
    corpo_html: str | None = None,
    config: Configuracoes | None = None,
) -> tuple[bool, str]:
    """Envia e-mail autenticado via SMTP (STARTTLS 587 ou SSL 465)."""
    cfg = config or obter_configuracoes()
    logger = obter_logger_aplicacao()

    if not cfg.smtp_configurado:
        return False, "SMTP não configurado no .env (defina SMTP_USUARIO e SMTP_SENHA)."

    destino = obter_config_destino_notificacao(cfg)["efetivo"]
    if not destino:
        return False, "Nenhum destinatário de e-mail definido."

    mensagem = EmailMessage()
    mensagem["Subject"] = assunto
    mensagem["From"] = cfg.smtp_usuario
    mensagem["To"] = destino
    mensagem.set_content(corpo_texto, subtype="plain", charset="utf-8")
    if corpo_html:
        mensagem.add_alternative(corpo_html, subtype="html", charset="utf-8")

    try:
        contexto_tls = ssl.create_default_context()
        if cfg.smtp_porta == 465:
            with smtplib.SMTP_SSL(
                cfg.smtp_host, cfg.smtp_porta, timeout=15, context=contexto_tls
            ) as servidor:
                servidor.login(cfg.smtp_usuario, cfg.smtp_senha)
                servidor.send_message(mensagem)
        else:
            with smtplib.SMTP(cfg.smtp_host, cfg.smtp_porta, timeout=15) as servidor:
                servidor.ehlo()
                servidor.starttls(context=contexto_tls)
                servidor.ehlo()
                servidor.login(cfg.smtp_usuario, cfg.smtp_senha)
                servidor.send_message(mensagem)
        return True, "E-mail enviado com sucesso."
    except Exception as erro:
        logger.error("Falha ao enviar e-mail SMTP (%s:%s): %s", cfg.smtp_host, cfg.smtp_porta, erro)
        return False, f"Erro ao enviar e-mail SMTP: {erro}"


def enviar_email_teste(config: Configuracoes | None = None) -> tuple[bool, str]:
    cfg = config or obter_configuracoes()
    agora = _agora_local_formatado()
    assunto = "[Portfólio] Teste de notificação SMTP"
    texto = (
        f"Teste de envio SMTP realizado com sucesso.\n\n"
        f"Data/hora: {agora}\n"
        f"Versão: v{VERSAO}\n"
        f"Servidor SMTP: {cfg.smtp_host}:{cfg.smtp_porta}\n"
        f"Relatório diário programado para: {cfg.relatorio_hora}\n"
    )
    html = f"""
    <div style="font-family: -apple-system, Segoe UI, sans-serif; background:#0c0e12; color:#eceff4; padding:24px; border-radius:6px; max-width:560px;">
      <p style="font-family: monospace; font-size:11px; color:#3b82f6; margin:0 0 8px;">PORTFÓLIO TÉCNICO · v{VERSAO}</p>
      <h2 style="margin:0 0 12px; font-size:18px;">Notificações SMTP operacionais</h2>
      <p style="color:#9aa3b2; font-size:14px; margin:0 0 16px;">
        O envio de alertas de segurança (força bruta) e do relatório diário de acessos está ativo.
      </p>
      <table style="width:100%; border-collapse:collapse; font-family: monospace; font-size:12px; color:#d7dce5;">
        <tr><td style="padding:6px 0; color:#8b949e;">Data/hora</td><td style="padding:6px 0; text-align:right;">{agora}</td></tr>
        <tr><td style="padding:6px 0; color:#8b949e;">Servidor</td><td style="padding:6px 0; text-align:right;">{cfg.smtp_host}:{cfg.smtp_porta}</td></tr>
        <tr><td style="padding:6px 0; color:#8b949e;">Relatório diário</td><td style="padding:6px 0; text-align:right;">{cfg.relatorio_hora}</td></tr>
      </table>
    </div>
    """
    return enviar_email(assunto, texto, html, config=cfg)


def notificar_forca_bruta_background(
    ip: str,
    tentativas: int,
    bloqueio_segundos: int,
    user_agent: str = "",
    config: Configuracoes | None = None,
) -> bool:
    """Envia alerta de força bruta em thread separada com cooldown anti-spam por IP."""
    cfg = config or obter_configuracoes()
    if not cfg.smtp_configurado:
        return False

    agora_mono = time.monotonic()
    cooldown = max(300, cfg.janela_bloqueio_segundos)
    with _lock_cooldown:
        ultimo = _ultimo_alerta_por_ip.get(ip)
        if ultimo is not None and (agora_mono - ultimo) < cooldown:
            return False
        _ultimo_alerta_por_ip[ip] = agora_mono

    horario = _agora_local_formatado()
    ua_limpo = (user_agent or "não informado")[:200]

    def _tarefa() -> None:
        assunto = f"[Portfólio] Alerta de segurança: tentativas de login bloqueadas ({ip})"
        texto = (
            f"O painel /config detectou múltiplas tentativas inválidas de login.\n\n"
            f"IP de origem: {ip}\n"
            f"Tentativas falhas: {tentativas}/{cfg.max_tentativas_login}\n"
            f"Bloqueio ativo: {bloqueio_segundos}s\n"
            f"Data/hora: {horario}\n"
            f"User-Agent: {ua_limpo}\n"
        )
        html = f"""
        <div style="font-family: -apple-system, Segoe UI, sans-serif; background:#0c0e12; color:#eceff4; padding:24px; border-radius:6px; max-width:560px; border:1px solid #262b35;">
          <p style="font-family: monospace; font-size:11px; color:#ef4444; margin:0 0 8px;">ALERTA DE SEGURANÇA · /CONFIG</p>
          <h2 style="margin:0 0 12px; font-size:18px;">Bloqueio contra força bruta acionado</h2>
          <p style="color:#9aa3b2; font-size:14px; margin:0 0 16px;">
            O endereço abaixo excedeu o limite de tentativas de senha e foi bloqueado temporariamente.
          </p>
          <table style="width:100%; border-collapse:collapse; font-family: monospace; font-size:12px; color:#eceff4;">
            <tr><td style="padding:6px 0; color:#8b949e;">IP</td><td style="padding:6px 0; text-align:right;">{ip}</td></tr>
            <tr><td style="padding:6px 0; color:#8b949e;">Tentativas</td><td style="padding:6px 0; text-align:right;">{tentativas}/{cfg.max_tentativas_login}</td></tr>
            <tr><td style="padding:6px 0; color:#8b949e;">Bloqueio</td><td style="padding:6px 0; text-align:right;">{bloqueio_segundos}s</td></tr>
            <tr><td style="padding:6px 0; color:#8b949e;">Horário</td><td style="padding:6px 0; text-align:right;">{horario}</td></tr>
            <tr><td style="padding:6px 0; color:#8b949e;">User-Agent</td><td style="padding:6px 0; text-align:right;">{ua_limpo}</td></tr>
          </table>
        </div>
        """
        ok, detalhe = enviar_email(assunto, texto, html, config=cfg)
        if ok:
            destino_final = obter_config_destino_notificacao(cfg)["efetivo"]
            registrar_auditoria(ip, "ALERTA_SMTP_FORCA_BRUTA", f"destinatario={destino_final}")
        else:
            registrar_auditoria(ip, "ALERTA_SMTP_FALHA", detalhe)

    thread = threading.Thread(target=_tarefa, daemon=True, name="alerta-smtp-login")
    thread.start()
    return True

