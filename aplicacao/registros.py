"""Sistema de logs rotativos (aplicação e auditoria) com suporte a proxy reverso."""

from __future__ import annotations

import logging
from collections import deque
from logging.handlers import RotatingFileHandler
from pathlib import Path

from fastapi import Request

from aplicacao.configuracoes import Configuracoes, garantir_pastas_dados, obter_configuracoes

NOME_LOGGER_APLICACAO = "portfolio.aplicacao"
NOME_LOGGER_AUDITORIA = "portfolio.auditoria"
TAMANHO_MAXIMO_LOG_BYTES = 5 * 1024 * 1024  # 5 MB
QUANTIDADE_BACKUPS_LOG = 5

_formato_padrao = logging.Formatter(
    fmt="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


def _limpar_handlers(logger: logging.Logger) -> None:
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        try:
            handler.close()
        except Exception:
            pass


def configurar_logs(config: Configuracoes | None = None) -> tuple[logging.Logger, logging.Logger]:
    """Inicializa loggers rotativos em dados/logs/."""
    cfg = config or obter_configuracoes()
    garantir_pastas_dados(cfg)

    nivel = getattr(logging, cfg.nivel_log, logging.INFO)

    logger_app = logging.getLogger(NOME_LOGGER_APLICACAO)
    logger_app.setLevel(nivel)
    logger_app.propagate = False
    _limpar_handlers(logger_app)

    handler_arquivo_app = RotatingFileHandler(
        cfg.pasta_logs / "aplicacao.log",
        maxBytes=TAMANHO_MAXIMO_LOG_BYTES,
        backupCount=QUANTIDADE_BACKUPS_LOG,
        encoding="utf-8",
    )
    handler_arquivo_app.setFormatter(_formato_padrao)

    handler_console = logging.StreamHandler()
    handler_console.setFormatter(_formato_padrao)

    logger_app.addHandler(handler_arquivo_app)
    logger_app.addHandler(handler_console)

    logger_auditoria = logging.getLogger(NOME_LOGGER_AUDITORIA)
    logger_auditoria.setLevel(logging.INFO)
    logger_auditoria.propagate = False
    _limpar_handlers(logger_auditoria)

    handler_arquivo_auditoria = RotatingFileHandler(
        cfg.pasta_logs / "auditoria.log",
        maxBytes=TAMANHO_MAXIMO_LOG_BYTES,
        backupCount=QUANTIDADE_BACKUPS_LOG,
        encoding="utf-8",
    )
    handler_arquivo_auditoria.setFormatter(_formato_padrao)
    logger_auditoria.addHandler(handler_arquivo_auditoria)
    logger_auditoria.addHandler(handler_console)

    return logger_app, logger_auditoria


def obter_logger_aplicacao() -> logging.Logger:
    return logging.getLogger(NOME_LOGGER_APLICACAO)


def obter_logger_auditoria() -> logging.Logger:
    return logging.getLogger(NOME_LOGGER_AUDITORIA)


def obter_ip_cliente(request: Request, config: Configuracoes | None = None) -> str:
    """Retorna o IP real do cliente respeitando a configuração de proxy confiável."""
    cfg = config or obter_configuracoes()
    if cfg.confiar_proxy:
        for cabecalho in cfg.cabecalhos_ip_proxy:
            valor = request.headers.get(cabecalho)
            if valor:
                # Em X-Forwarded-For o primeiro IP da lista representa o cliente original
                primeiro_ip = valor.split(",")[0].strip()
                if primeiro_ip:
                    return primeiro_ip

    if request.client and request.client.host:
        return request.client.host
    return "desconhecido"


def _sanitizar_texto_log(texto: str) -> str:
    return texto.replace("\r", " ").replace("\n", " ").strip()


def registrar_auditoria(ip: str, evento: str, detalhes: str = "") -> None:
    """Registra eventos sensíveis/administrativos em dados/logs/auditoria.log."""
    logger = obter_logger_auditoria()
    ip_limpo = _sanitizar_texto_log(ip)
    evento_limpo = _sanitizar_texto_log(evento)
    detalhes_limpos = _sanitizar_texto_log(detalhes)

    if detalhes_limpos:
        logger.info("AUDITORIA | ip=%s | evento=%s | %s", ip_limpo, evento_limpo, detalhes_limpos)
    else:
        logger.info("AUDITORIA | ip=%s | evento=%s", ip_limpo, evento_limpo)


def ler_ultimos_logs(
    tipo: str = "auditoria",
    limite: int = 80,
    config: Configuracoes | None = None,
) -> list[str]:
    """Lê as últimas linhas do arquivo de log escolhido (mais recentes primeiro)."""
    cfg = config or obter_configuracoes()
    nome_arquivo = "auditoria.log" if tipo == "auditoria" else "aplicacao.log"
    caminho: Path = cfg.pasta_logs / nome_arquivo

    if not caminho.exists():
        return []

    limite_seguro = max(1, min(limite, 500))
    with caminho.open("r", encoding="utf-8", errors="replace") as arquivo:
        linhas = deque(arquivo, maxlen=limite_seguro)

    return [linha.rstrip("\r\n") for linha in reversed(linhas)]

