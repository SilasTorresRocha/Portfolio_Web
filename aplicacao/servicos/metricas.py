"""Registro leve de acessos (ignorando dono/IPs configurados) e relatório diário por e-mail."""

from __future__ import annotations

import asyncio
import html
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlparse

from fastapi import Request

from aplicacao.autenticacao import sessao_autenticada
from aplicacao.banco import agora_iso, obter_conexao
from aplicacao.configuracoes import Configuracoes, obter_configuracoes
from aplicacao.registros import (
    _obter_fuso_horario,
    obter_ip_cliente,
    obter_logger_aplicacao,
    registrar_auditoria,
)
from aplicacao.servicos.notificacoes import enviar_email
from aplicacao.versao import VERSAO

PADROES_BOT = (
    "bot",
    "crawler",
    "spider",
    "slurp",
    "curl/",
    "wget/",
    "python-requests",
    "python-urllib",
    "httpx/",
    "uptime",
    "headless",
    "lighthouse",
    "facebookexternalhit",
    "whatsapp",
    "linkedinbot",
    "telegrambot",
    "discordbot",
    "twitterbot",
    "bingpreview",
    "googleother",
    "semrush",
    "ahrefs",
)


def data_local_hoje() -> str:
    return datetime.now(tz=_obter_fuso_horario()).strftime("%Y-%m-%d")


def _detectar_bot(user_agent: str) -> bool:
    ua = (user_agent or "").lower().strip()
    if not ua:
        return True
    return any(padrao in ua for padrao in PADROES_BOT)


def _extrair_origem(request: Request) -> str:
    referer = (request.headers.get("referer") or "").strip()
    if not referer:
        return "direto"
    try:
        host_ref = (urlparse(referer).hostname or "").lower()
        host_atual = (request.url.hostname or "").lower()
        if not host_ref or host_ref == host_atual:
            return "direto"
        return host_ref[:100]
    except Exception:
        return "direto"


def registrar_acesso(
    request: Request,
    *,
    tipo: str,
    referencia: str = "",
    config: Configuracoes | None = None,
) -> bool:
    """Registra visita pública ignorando admin logado e IPs configurados em PORTFOLIO_IPS_IGNORADOS."""
    cfg = config or obter_configuracoes()

    # 1. Ignora sempre quando o administrador está autenticado no /config
    if sessao_autenticada(request, cfg):
        return False

    # 2. Ignora IPs locais / confiáveis listados no .env
    ip = obter_ip_cliente(request, cfg)
    if ip in cfg.ips_ignorados:
        return False

    user_agent = (request.headers.get("user-agent") or "")[:240]
    eh_bot = 1 if _detectar_bot(user_agent) else 0
    origem = _extrair_origem(request)
    caminho = request.url.path[:200]

    try:
        with obter_conexao(cfg) as conexao:
            conexao.execute(
                """
                INSERT INTO acessos (
                    criado_em, data_local, tipo, caminho, referencia, ip, origem, eh_bot, user_agent
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    agora_iso(),
                    data_local_hoje(),
                    tipo[:30],
                    caminho,
                    (referencia or "")[:160],
                    ip[:80],
                    origem,
                    eh_bot,
                    user_agent,
                ),
            )
        return True
    except Exception as erro:
        obter_logger_aplicacao().warning("Falha ao gravar métrica de acesso: %s", erro)
        return False


def _contar_alertas_login_no_periodo(
    datas: list[str],
    config: Configuracoes | None = None,
) -> dict[str, int]:
    cfg = config or obter_configuracoes()
    caminho = cfg.pasta_logs / "auditoria.log"
    recusados = 0
    bloqueados = 0
    if not caminho.exists() or not datas:
        return {"recusados": 0, "bloqueados": 0}

    prefixos = tuple(datas)
    with caminho.open("r", encoding="utf-8", errors="replace") as arquivo:
        for linha in arquivo:
            if not linha.startswith(prefixos):
                continue
            if "evento=LOGIN_RECUSADO" in linha:
                recusados += 1
            elif "evento=LOGIN_BLOQUEADO_RATE_LIMIT" in linha:
                bloqueados += 1
    return {"recusados": recusados, "bloqueados": bloqueados}


def obter_resumo_acessos(
    *,
    dias: int = 1,
    data_alvo: str | None = None,
    config: Configuracoes | None = None,
) -> dict[str, Any]:
    """Consolida métricas de acesso humano, bots, projetos, PDFs e origens."""
    cfg = config or obter_configuracoes()
    agora_local = datetime.now(tz=_obter_fuso_horario())

    if data_alvo:
        datas = [data_alvo]
        rotulo_periodo = data_alvo
    else:
        qtd = max(1, min(dias, 90))
        datas = [
            (agora_local - timedelta(days=offset)).strftime("%Y-%m-%d")
            for offset in range(qtd)
        ]
        rotulo_periodo = datas[0] if qtd == 1 else f"últimos {qtd} dias"

    placeholders = ",".join("?" for _ in datas)
    with obter_conexao(cfg) as conexao:
        visitas_humanas = conexao.execute(
            f"SELECT COUNT(*) FROM acessos WHERE data_local IN ({placeholders}) AND eh_bot = 0",
            datas,
        ).fetchone()[0]
        visitantes_unicos = conexao.execute(
            f"SELECT COUNT(DISTINCT ip) FROM acessos WHERE data_local IN ({placeholders}) AND eh_bot = 0",
            datas,
        ).fetchone()[0]
        acessos_bots = conexao.execute(
            f"SELECT COUNT(*) FROM acessos WHERE data_local IN ({placeholders}) AND eh_bot = 1",
            datas,
        ).fetchone()[0]

        projetos_vistos = [
            dict(r)
            for r in conexao.execute(
                f"""
                SELECT referencia AS slug, COUNT(*) AS total
                FROM acessos
                WHERE data_local IN ({placeholders}) AND eh_bot = 0 AND tipo = 'projeto'
                GROUP BY referencia
                ORDER BY total DESC, referencia ASC
                LIMIT 10
                """,
                datas,
            ).fetchall()
        ]

        documentos_vistos = [
            dict(r)
            for r in conexao.execute(
                f"""
                SELECT referencia AS titulo, tipo, COUNT(*) AS total
                FROM acessos
                WHERE data_local IN ({placeholders})
                  AND eh_bot = 0
                  AND tipo IN ('anexo_ver', 'anexo_baixar', 'curriculo')
                GROUP BY referencia, tipo
                ORDER BY total DESC, referencia ASC
                LIMIT 10
                """,
                datas,
            ).fetchall()
        ]

        origens = [
            dict(r)
            for r in conexao.execute(
                f"""
                SELECT origem, COUNT(*) AS total
                FROM acessos
                WHERE data_local IN ({placeholders}) AND eh_bot = 0
                GROUP BY origem
                ORDER BY total DESC
                LIMIT 8
                """,
                datas,
            ).fetchall()
        ]

        vitrine_total = conexao.execute(
            f"SELECT COUNT(*) FROM acessos WHERE data_local IN ({placeholders}) AND eh_bot = 0 AND tipo = 'vitrine'",
            datas,
        ).fetchone()[0]

    alertas = _contar_alertas_login_no_periodo(datas, cfg)
    return {
        "periodo": rotulo_periodo,
        "datas": datas,
        "visitas_humanas": int(visitas_humanas),
        "visitantes_unicos": int(visitantes_unicos),
        "vitrine_total": int(vitrine_total),
        "acessos_bots": int(acessos_bots),
        "projetos_vistos": projetos_vistos,
        "documentos_vistos": documentos_vistos,
        "origens": origens,
        "alertas_login": alertas,
    }


def obter_estado_sistema(chave: str, config: Configuracoes | None = None) -> str | None:
    with obter_conexao(config) as conexao:
        row = conexao.execute(
            "SELECT valor FROM estado_sistema WHERE chave = ?",
            (chave,),
        ).fetchone()
    return str(row["valor"]) if row else None


def salvar_estado_sistema(chave: str, valor: str, config: Configuracoes | None = None) -> None:
    with obter_conexao(config) as conexao:
        conexao.execute(
            """
            INSERT INTO estado_sistema (chave, valor, atualizado_em)
            VALUES (?, ?, ?)
            ON CONFLICT(chave) DO UPDATE SET valor = excluded.valor, atualizado_em = excluded.atualizado_em
            """,
            (chave, valor, agora_iso()),
        )


def enviar_relatorio_diario(
    *,
    forcar: bool = False,
    data_alvo: str | None = None,
    config: Configuracoes | None = None,
) -> tuple[bool, str]:
    """Compila e envia o relatório diário por e-mail sem duplicar no mesmo dia."""
    cfg = config or obter_configuracoes()
    if not cfg.smtp_configurado:
        return False, "SMTP não configurado no .env."

    dia = data_alvo or data_local_hoje()
    if not forcar and obter_estado_sistema("ultimo_relatorio_diario", cfg) == dia:
        return False, "Relatório deste dia já foi enviado."

    resumo = obter_resumo_acessos(data_alvo=dia, config=cfg)
    houve_atividade = (
        resumo["visitas_humanas"] > 0
        or resumo["alertas_login"]["recusados"] > 0
        or resumo["alertas_login"]["bloqueados"] > 0
    )

    if not forcar and not cfg.relatorio_enviar_se_zerado and not houve_atividade:
        salvar_estado_sistema("ultimo_relatorio_diario", dia, cfg)
        return False, "Sem acessos ou alertas hoje; envio ignorado conforme configuração."

    linhas_txt = [
        f"Relatório diário do Portfólio — {dia}",
        "",
        f"Acessos humanos: {resumo['visitas_humanas']} ({resumo['visitantes_unicos']} IP(s) únicos)",
        f"Vitrine (/): {resumo['vitrine_total']} acesso(s)",
        f"Bots/crawlers separados: {resumo['acessos_bots']}",
        f"Alertas /config: {resumo['alertas_login']['recusados']} falha(s), {resumo['alertas_login']['bloqueados']} bloqueio(s)",
        "",
    ]

    if resumo["projetos_vistos"]:
        linhas_txt.append("Projetos visualizados:")
        for p in resumo["projetos_vistos"]:
            linhas_txt.append(f"  - /projeto/{p['slug']}: {p['total']}")
        linhas_txt.append("")

    if resumo["documentos_vistos"]:
        linhas_txt.append("Documentos PDF / Currículo acessados:")
        for d in resumo["documentos_vistos"]:
            linhas_txt.append(f"  - {d['titulo']} ({d['tipo']}): {d['total']}")
        linhas_txt.append("")

    if resumo["origens"]:
        linhas_txt.append("Principais origens (Referer):")
        for o in resumo["origens"]:
            linhas_txt.append(f"  - {o['origem']}: {o['total']}")

    itens_proj_html = "".join(
        f"<tr><td style='padding:5px 0;'>/projeto/{html.escape(p['slug'])}</td><td style='padding:5px 0; text-align:right;'>{p['total']}</td></tr>"
        for p in resumo["projetos_vistos"]
    ) or "<tr><td style='padding:5px 0; color:#8b949e;'>Nenhum projeto visualizado</td><td></td></tr>"

    itens_doc_html = "".join(
        f"<tr><td style='padding:5px 0;'>{html.escape(d['titulo'])} ({html.escape(d['tipo'])})</td><td style='padding:5px 0; text-align:right;'>{d['total']}</td></tr>"
        for d in resumo["documentos_vistos"]
    ) or "<tr><td style='padding:5px 0; color:#8b949e;'>Nenhum documento aberto</td><td></td></tr>"

    itens_orig_html = "".join(
        f"<tr><td style='padding:5px 0;'>{html.escape(o['origem'])}</td><td style='padding:5px 0; text-align:right;'>{o['total']}</td></tr>"
        for o in resumo["origens"]
    ) or "<tr><td style='padding:5px 0; color:#8b949e;'>Sem registros</td><td></td></tr>"

    corpo_html = f"""
    <div style="font-family: -apple-system, Segoe UI, sans-serif; background:#0c0e12; color:#eceff4; padding:24px; border-radius:6px; max-width:600px; border:1px solid #262b35;">
      <p style="font-family: monospace; font-size:11px; color:#3b82f6; margin:0 0 6px;">RELATÓRIO DIÁRIO · {dia} · v{VERSAO}</p>
      <h2 style="margin:0 0 16px; font-size:19px;">Resumo de acessos do Portfólio</h2>

      <table style="width:100%; border-collapse:collapse; font-family: monospace; font-size:13px; margin-bottom:18px;">
        <tr><td style="padding:6px 0; color:#9aa3b2;">Acessos humanos</td><td style="padding:6px 0; text-align:right; font-weight:600;">{resumo['visitas_humanas']} ({resumo['visitantes_unicos']} únicos)</td></tr>
        <tr><td style="padding:6px 0; color:#9aa3b2;">Vitrine (/)</td><td style="padding:6px 0; text-align:right;">{resumo['vitrine_total']}</td></tr>
        <tr><td style="padding:6px 0; color:#9aa3b2;">Bots (separados)</td><td style="padding:6px 0; text-align:right;">{resumo['acessos_bots']}</td></tr>
        <tr><td style="padding:6px 0; color:#9aa3b2;">Alertas de login /config</td><td style="padding:6px 0; text-align:right;">{resumo['alertas_login']['recusados']} falha(s) · {resumo['alertas_login']['bloqueados']} bloqueio(s)</td></tr>
      </table>

      <p style="font-family: monospace; font-size:11px; color:#8b949e; margin:16px 0 6px; text-transform:uppercase;">Projetos acessados</p>
      <table style="width:100%; border-collapse:collapse; font-family: monospace; font-size:12px;">{itens_proj_html}</table>

      <p style="font-family: monospace; font-size:11px; color:#8b949e; margin:16px 0 6px; text-transform:uppercase;">Documentos PDF &amp; Currículo</p>
      <table style="width:100%; border-collapse:collapse; font-family: monospace; font-size:12px;">{itens_doc_html}</table>

      <p style="font-family: monospace; font-size:11px; color:#8b949e; margin:16px 0 6px; text-transform:uppercase;">Origens (Referer)</p>
      <table style="width:100%; border-collapse:collapse; font-family: monospace; font-size:12px;">{itens_orig_html}</table>
    </div>
    """

    assunto = f"[Portfólio] Relatório diário ({dia}) — {resumo['visitas_humanas']} acesso(s)"
    ok, detalhe = enviar_email(assunto, "\n".join(linhas_txt), corpo_html, config=cfg)
    if ok:
        salvar_estado_sistema("ultimo_relatorio_diario", dia, cfg)
        salvar_estado_sistema("ultimo_relatorio_enviado_em", agora_iso(), cfg)
        registrar_auditoria("sistema", "RELATORIO_DIARIO_ENVIADO", f"dia={dia} visitas={resumo['visitas_humanas']}")
    return ok, detalhe


async def agendador_relatorio_diario(config: Configuracoes) -> None:
    """Loop assíncrono leve que dispara o relatório diário no horário configurado."""
    logger = obter_logger_aplicacao()
    hora_alvo, minuto_alvo = [int(p) for p in config.relatorio_hora.split(":")]

    while True:
        try:
            await asyncio.sleep(60)
            if not config.smtp_configurado:
                continue
            agora = datetime.now(tz=_obter_fuso_horario())
            if (agora.hour, agora.minute) >= (hora_alvo, minuto_alvo):
                hoje = agora.strftime("%Y-%m-%d")
                if obter_estado_sistema("ultimo_relatorio_diario", config) != hoje:
                    await asyncio.to_thread(enviar_relatorio_diario, forcar=False, data_alvo=hoje, config=config)
        except asyncio.CancelledError:
            break
        except Exception as erro:
            logger.error("Erro no agendador de relatório diário: %s", erro)

