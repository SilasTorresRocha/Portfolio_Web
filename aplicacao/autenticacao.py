"""Autenticação do painel /config com cookie assinado, CSRF e limite de tentativas."""

from __future__ import annotations

import hmac
import secrets
import threading
import time
from collections import defaultdict, deque

from fastapi import Request, Response
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from aplicacao.configuracoes import Configuracoes, obter_configuracoes

NOME_COOKIE_SESSAO = "portfolio_sessao"
SAL_SESSAO = "portfolio-admin-sessao-v1"
SAL_CSRF = "portfolio-admin-csrf-v1"
VALIDADE_CSRF_SEGUNDOS = 7200  # 2 horas


class ControladorTentativasLogin:
    """Limita tentativas consecutivas de login por IP em janela deslizante."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._falhas_por_ip: dict[str, deque[float]] = defaultdict(deque)

    def _podar(self, ip: str, agora: float, janela: int) -> deque[float]:
        fila = self._falhas_por_ip[ip]
        limite = agora - janela
        while fila and fila[0] < limite:
            fila.popleft()
        return fila

    def esta_bloqueado(self, ip: str, config: Configuracoes | None = None) -> tuple[bool, int]:
        cfg = config or obter_configuracoes()
        agora = time.monotonic()
        with self._lock:
            fila = self._podar(ip, agora, cfg.janela_bloqueio_segundos)
            if len(fila) >= cfg.max_tentativas_login:
                restante = int(cfg.janela_bloqueio_segundos - (agora - fila[0]))
                return True, max(1, restante)
            return False, 0

    def registrar_falha(self, ip: str, config: Configuracoes | None = None) -> int:
        cfg = config or obter_configuracoes()
        agora = time.monotonic()
        with self._lock:
            fila = self._podar(ip, agora, cfg.janela_bloqueio_segundos)
            fila.append(agora)
            return len(fila)

    def limpar_ip(self, ip: str) -> None:
        with self._lock:
            self._falhas_por_ip.pop(ip, None)


controlador_tentativas = ControladorTentativasLogin()


def _obter_serializador(sal: str, config: Configuracoes | None = None) -> URLSafeTimedSerializer:
    cfg = config or obter_configuracoes()
    return URLSafeTimedSerializer(secret_key=cfg.chave_secreta, salt=sal)


def senha_admin_configurada(config: Configuracoes | None = None) -> bool:
    cfg = config or obter_configuracoes()
    return bool(cfg.senha_admin)


def verificar_senha(senha_informada: str, config: Configuracoes | None = None) -> bool:
    """Compara a senha informada com PORTFOLIO_SENHA_ADMIN em tempo constante."""
    cfg = config or obter_configuracoes()
    if not cfg.senha_admin or not senha_informada:
        return False
    return hmac.compare_digest(senha_informada, cfg.senha_admin)


def gerar_token_sessao(config: Configuracoes | None = None) -> str:
    serializador = _obter_serializador(SAL_SESSAO, config)
    payload = {
        "papel": "admin",
        "nonce": secrets.token_hex(12),
    }
    return serializador.dumps(payload)


def validar_token_sessao(token: str | None, config: Configuracoes | None = None) -> dict | None:
    if not token:
        return None
    cfg = config or obter_configuracoes()
    serializador = _obter_serializador(SAL_SESSAO, cfg)
    try:
        payload = serializador.loads(token, max_age=cfg.sessao_segundos)
    except (BadSignature, SignatureExpired):
        return None
    if not isinstance(payload, dict) or payload.get("papel") != "admin":
        return None
    return payload


def sessao_autenticada(request: Request, config: Configuracoes | None = None) -> bool:
    token = request.cookies.get(NOME_COOKIE_SESSAO)
    return validar_token_sessao(token, config) is not None


def definir_cookie_sessao(response: Response, config: Configuracoes | None = None) -> None:
    cfg = config or obter_configuracoes()
    token = gerar_token_sessao(cfg)
    response.set_cookie(
        key=NOME_COOKIE_SESSAO,
        value=token,
        max_age=cfg.sessao_segundos,
        httponly=True,
        samesite="lax",
        secure=cfg.cookie_seguro,
        path="/",
    )


def remover_cookie_sessao(response: Response) -> None:
    response.delete_cookie(key=NOME_COOKIE_SESSAO, path="/")


def gerar_token_csrf(contexto: str = "config", config: Configuracoes | None = None) -> str:
    serializador = _obter_serializador(SAL_CSRF, config)
    return serializador.dumps({"ctx": contexto, "nonce": secrets.token_hex(8)})


def validar_token_csrf(
    token: str | None,
    contexto: str = "config",
    config: Configuracoes | None = None,
) -> bool:
    if not token:
        return False
    serializador = _obter_serializador(SAL_CSRF, config)
    try:
        payload = serializador.loads(token, max_age=VALIDADE_CSRF_SEGUNDOS)
    except (BadSignature, SignatureExpired):
        return False
    return isinstance(payload, dict) and payload.get("ctx") == contexto

