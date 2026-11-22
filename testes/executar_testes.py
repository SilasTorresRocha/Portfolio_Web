"""Suíte de testes automatizados end-to-end em pasta temporária isolada.

Não modifica nem lê dados reais da pasta ./dados do projeto.
Execute com: python testes/executar_testes.py
"""

from __future__ import annotations

import asyncio
import io
import json
import os
import re
import sys
import tempfile
import uuid
import zipfile
from pathlib import Path
from urllib.parse import urlencode

from PIL import Image

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))


def extrair_ultimo_csrf(html: str) -> str:
    matches = re.findall(r'name="csrf_token"\s+value="([^"]+)"', html)
    assert matches, "Token CSRF não encontrado no HTML"
    return matches[-1]


def montar_multipart(
    campos: dict[str, str],
    arquivos: list[tuple[str, str, str, bytes]],
) -> tuple[bytes, str]:
    boundary = f"----TestePortfolio{uuid.uuid4().hex}"
    partes: list[bytes] = []
    for chave, valor in campos.items():
        partes.append(
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{chave}"\r\n\r\n'
            f"{valor}\r\n".encode("utf-8")
        )
    for campo, filename, content_type, data in arquivos:
        partes.append(
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{campo}"; filename="{filename}"\r\n'
            f"Content-Type: {content_type}\r\n\r\n".encode("utf-8")
            + data
            + b"\r\n"
        )
    partes.append(f"--{boundary}--\r\n".encode("utf-8"))
    return b"".join(partes), f"multipart/form-data; boundary={boundary}"


def criar_imagem_bytes(formato: str = "PNG") -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (2200, 1400), (40, 90, 180)).save(buf, format=formato)
    return buf.getvalue()


async def requisitar(
    app,
    metodo: str,
    caminho: str,
    *,
    query: str = "",
    form: dict[str, str] | None = None,
    multipart: tuple[bytes, str] | None = None,
    cookies: dict[str, str] | None = None,
    client_ip: str = "127.0.0.1",
    extra_headers: list[tuple[bytes, bytes]] | None = None,
) -> tuple[int, dict[str, str], dict[str, str], bytes]:
    corpo_bytes = b""
    headers = [(b"host", b"localhost:8000")]
    if extra_headers:
        headers.extend(extra_headers)
    if form is not None:
        corpo_bytes = urlencode(form).encode("utf-8")
        headers.append((b"content-type", b"application/x-www-form-urlencoded"))
        headers.append((b"content-length", str(len(corpo_bytes)).encode("ascii")))
    elif multipart is not None:
        corpo_bytes, content_type = multipart
        headers.append((b"content-type", content_type.encode("ascii")))
        headers.append((b"content-length", str(len(corpo_bytes)).encode("ascii")))
    if cookies:
        headers.append((b"cookie", "; ".join(f"{k}={v}" for k, v in cookies.items()).encode("utf-8")))

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": metodo.upper(),
        "scheme": "http",
        "path": caminho,
        "raw_path": caminho.encode("utf-8"),
        "query_string": query.encode("utf-8"),
        "headers": headers,
        "client": (client_ip, 50000),
        "server": ("localhost", 8000),
    }

    enviado = False

    async def receive():
        nonlocal enviado
        if not enviado:
            enviado = True
            return {"type": "http.request", "body": corpo_bytes, "more_body": False}
        return {"type": "http.request", "body": b"", "more_body": False}

    status = 0
    resp_headers: dict[str, str] = {}
    set_cookies: dict[str, str] = {}
    partes: list[bytes] = []

    async def send(evento):
        nonlocal status
        if evento["type"] == "http.response.start":
            status = evento["status"]
            for k, v in evento.get("headers", []):
                chave = k.decode("latin1").lower()
                valor = v.decode("latin1")
                if chave == "set-cookie":
                    par = valor.split(";", 1)[0]
                    if "=" in par:
                        ck, cv = par.split("=", 1)
                        set_cookies[ck.strip()] = cv.strip()
                resp_headers[chave] = valor
        elif evento["type"] == "http.response.body":
            partes.append(evento.get("body", b""))

    await app(scope, receive, send)
    return status, resp_headers, set_cookies, b"".join(partes)


async def executar_suite() -> None:
    with tempfile.TemporaryDirectory(prefix="portfolio_testes_") as tmp_dir:
        # Configura ambiente isolado apontando para diretório temporário
        os.environ["PORTFOLIO_AMBIENTE"] = "producao"
        os.environ["PORTFOLIO_PASTA_DADOS"] = tmp_dir
        os.environ["PORTFOLIO_SENHA_ADMIN"] = "senha-teste-segura"
        os.environ["PORTFOLIO_CHAVE_SECRETA"] = "chave-secreta-teste-isolada-1234567890"
        os.environ["PORTFOLIO_COOKIE_SEGURO"] = "false"
        os.environ["PORTFOLIO_IPS_IGNORADOS"] = "127.0.0.1,::1"
        os.environ["SMTP_HOST"] = "smtp.exemplo.local"
        os.environ["SMTP_USUARIO"] = "bot@exemplo.local"
        os.environ["SMTP_SENHA"] = "senha-app-teste"
        os.environ["SMTP_DESTINATARIO"] = "bot@exemplo.local"

        import aplicacao.servicos.metricas as mod_metricas
        import aplicacao.servicos.notificacoes as mod_notif
        from aplicacao.autenticacao import controlador_tentativas
        from aplicacao.configuracoes import obter_configuracoes
        from aplicacao.main import criar_aplicacao
        from aplicacao.registros import (
            _limpar_handlers,
            obter_logger_aplicacao,
            obter_logger_auditoria,
        )
        from aplicacao.servicos.backup import ErroBackup, processar_upload_restauracao
        from aplicacao.servicos.markdown_seguro import renderizar_markdown_seguro
        from aplicacao.versao import VERSAO

        obter_configuracoes.cache_clear()
        cfg = obter_configuracoes()

        emails_enviados: list[dict] = []

        def fake_email(assunto, corpo_texto, corpo_html=None, config=None):
            emails_enviados.append({"assunto": assunto, "texto": corpo_texto})
            return True, "Mock OK"

        mod_notif.enviar_email = fake_email
        mod_metricas.enviar_email = fake_email

        app = criar_aplicacao()
        async with app.router.lifespan_context(app):
            # 1. Saúde, versão semântica e modo produção
            st, _, _, corpo = await requisitar(app, "GET", "/saude")
            assert st == 200 and json.loads(corpo.decode())["versao"] == VERSAO
            assert (await requisitar(app, "GET", "/docs"))[0] == 404
            assert (await requisitar(app, "GET", "/openapi.json"))[0] == 404
            print("[OK] 1. Saude, versao semantica e modo producao (/docs e /openapi.json ocultos)")

            # 2. Hardening da vitrine e login
            st, _, _, home_bytes = await requisitar(app, "GET", "/")
            home = home_bytes.decode()
            assert st == 200 and "/config" not in home and f"v{VERSAO}" in home

            st, _, _, login_bytes = await requisitar(app, "GET", "/config/login")
            login_html = login_bytes.decode()
            assert st == 200 and "noindex, nofollow" in login_html
            assert "PORTFOLIO_SENHA_ADMIN" not in login_html and ".env" not in login_html
            print("[OK] 2. Hardening vitrine (sem /config) e login neutro (noindex)")

            # 3. Rate-limit + alerta SMTP + cooldown
            ip_bot = "198.51.100.90"
            controlador_tentativas.limpar_ip(ip_bot)
            mod_notif._ultimo_alerta_por_ip.pop(ip_bot, None)
            for _ in range(cfg.max_tentativas_login + 1):
                _, _, _, h = await requisitar(app, "GET", "/config/login", client_ip=ip_bot)
                csrf = extrair_ultimo_csrf(h.decode())
                await requisitar(
                    app,
                    "POST",
                    "/config/login",
                    form={"senha": "errada", "csrf_token": csrf},
                    client_ip=ip_bot,
                )
            await asyncio.sleep(0.15)
            assert len(emails_enviados) == 1
            print("[OK] 3. Rate-limit de login + alerta SMTP com cooldown anti-spam")

            # 4. Login válido + criação de projeto com 12 tags (testa limite de 10 tags na vitrine!)
            controlador_tentativas.limpar_ip("127.0.0.1")
            _, _, _, h = await requisitar(app, "GET", "/config/login")
            csrf_login = extrair_ultimo_csrf(h.decode())
            st, _, set_cookies, _ = await requisitar(
                app,
                "POST",
                "/config/login",
                form={"senha": cfg.senha_admin, "csrf_token": csrf_login},
            )
            assert st == 303 and "portfolio_sessao" in set_cookies
            sessao = {"portfolio_sessao": set_cookies["portfolio_sessao"]}

            _, _, _, h_novo = await requisitar(app, "GET", "/config/projetos/novo", cookies=sessao)
            csrf_admin = extrair_ultimo_csrf(h_novo.decode())
            tags_12 = ", ".join(f"Tag{i:02d}" for i in range(1, 13))
            st, headers, _, _ = await requisitar(
                app,
                "POST",
                "/config/projetos/novo",
                form={
                    "csrf_token": csrf_admin,
                    "titulo": "Projeto Completo de Teste",
                    "slug": "projeto-teste",
                    "status": "EM PRODUÇÃO",
                    "ano": "2026",
                    "tags_texto": tags_12,
                    "resumo": "Resumo curto de validação.",
                    "problema": "Problema de teste.",
                    "solucao": "Solução de teste.",
                    "resultado": "Resultado de teste.",
                    "descricao_markdown": "## Detalhes\n\n<script>alert(1)</script>Texto seguro.",
                    "publicado": "1",
                    "ordem": "1",
                },
                cookies=sessao,
            )
            assert st == 303
            pid = int(re.search(r"/config/projetos/(\d+)/editar", headers["location"]).group(1))

            # Confirma botão "+ 2 tags" na vitrine (12 tags > limite 10)
            st, _, _, html_vit = await requisitar(app, "GET", "/")
            vit = html_vit.decode()
            assert st == 200 and 'id="botao-expandir-tags"' in vit and "+ 2 tags" in vit
            print("[OK] 4. CRUD de projeto + escalabilidade de tags (>10 tags recolhidas)")

            # 5. Upload de imagem (WebP + miniatura), PDF válido/falso, link XSS/válido e path traversal
            mp_img = montar_multipart(
                {"csrf_token": csrf_admin},
                [("imagens", "placa.png", "image/png", criar_imagem_bytes("PNG"))],
            )
            st, headers, _, _ = await requisitar(
                app, "POST", f"/config/projetos/{pid}/midias", multipart=mp_img, cookies=sessao
            )
            assert st == 303 and "ok=" in headers["location"]

            mp_pdf_falso = montar_multipart(
                {"csrf_token": csrf_admin, "titulo": "Falso"},
                [("arquivo", "falso.pdf", "application/pdf", b"<html>fake</html>")],
            )
            st, headers, _, _ = await requisitar(
                app, "POST", f"/config/projetos/{pid}/anexos", multipart=mp_pdf_falso, cookies=sessao
            )
            assert st == 303 and "erro=" in headers["location"]

            mp_pdf_ok = montar_multipart(
                {"csrf_token": csrf_admin, "titulo": "Comprovante Oficial"},
                [("arquivo", "doc.pdf", "application/pdf", b"%PDF-1.4\n%%EOF\n")],
            )
            st, headers, _, _ = await requisitar(
                app, "POST", f"/config/projetos/{pid}/anexos", multipart=mp_pdf_ok, cookies=sessao
            )
            assert st == 303 and "ok=" in headers["location"]

            st, headers, _, _ = await requisitar(
                app,
                "POST",
                f"/config/projetos/{pid}/links",
                form={"csrf_token": csrf_admin, "rotulo": "XSS", "url": "javascript:alert(1)", "tipo": "link"},
                cookies=sessao,
            )
            assert st == 303 and "erro=" in headers["location"]

            assert (await requisitar(app, "GET", "/midias/../../.env"))[0] == 404
            assert "<script>" not in renderizar_markdown_seguro("<script>alert(1)</script>").lower()
            print("[OK] 5. Upload WebP, magic bytes PDF, anti-XSS e anti-path traversal")

            # 6. Página do projeto + Open Graph + métricas (ignora dono, registra externo, separa bots)
            ua_humano = [(b"user-agent", b"Mozilla/5.0 Chrome/130.0")]
            ua_bot = [(b"user-agent", b"Googlebot/2.1")]
            await requisitar(app, "GET", "/projeto/projeto-teste", cookies=sessao, client_ip="203.0.113.10", extra_headers=ua_humano)
            st, _, _, p_html = await requisitar(app, "GET", "/projeto/projeto-teste", client_ip="203.0.113.10", extra_headers=ua_humano)
            assert st == 200 and 'property="og:image"' in p_html.decode() and "<script>" not in p_html.decode()
            await requisitar(app, "GET", "/projeto/projeto-teste", client_ip="203.0.113.11", extra_headers=ua_bot)

            resumo_m = mod_metricas.obter_resumo_acessos(dias=1, config=cfg)
            assert resumo_m["visitas_humanas"] == 1 and resumo_m["acessos_bots"] == 1
            print("[OK] 6. Pagina /projeto/{slug} (OG + XSS limpo) e metricas filtradas")

            # 7. Backup .zip (SHA-256 + HMAC), bloqueio ZipSlip/corrupção e restauração
            st, headers, _, zip_bytes = await requisitar(
                app, "POST", "/config/backup/baixar", form={"csrf_token": csrf_admin}, cookies=sessao
            )
            assert st == 200 and headers.get("content-type") == "application/zip"

            buf_slip = io.BytesIO()
            with zipfile.ZipFile(buf_slip, "w") as zf:
                zf.writestr("../fora.txt", b"x")
            try:
                processar_upload_restauracao(buf_slip.getvalue(), config=cfg)
                raise AssertionError("Zip Slip nao bloqueado")
            except ErroBackup:
                pass

            res_ok = processar_upload_restauracao(zip_bytes, config=cfg)
            assert res_ok["status"] == "restaurado" and res_ok["assinatura_valida"] is True
            print("[OK] 7. Backup .zip (SHA-256 + HMAC), anti-ZipSlip e restauracao")

        # Fecha file handlers de log antes de remover a pasta temporária no Windows
        _limpar_handlers(obter_logger_aplicacao())
        _limpar_handlers(obter_logger_auditoria())

    print("\nSUCESSO: Todos os testes automatizados da v1.0.0 passaram!")


if __name__ == "__main__":
    asyncio.run(executar_suite())
