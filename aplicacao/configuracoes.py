"""Carregamento e validação das configurações a partir do arquivo .env."""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

RAIZ_PROJETO = Path(__file__).resolve().parent.parent
load_dotenv(RAIZ_PROJETO / ".env")


def _ler_booleano(nome: str, padrao: bool = False) -> bool:
    valor = os.getenv(nome)
    if valor is None:
        return padrao
    return valor.strip().lower() in {"1", "true", "sim", "yes", "on"}


def _ler_inteiro(nome: str, padrao: int, minimo: int = 1) -> int:
    valor = os.getenv(nome)
    if valor is None or not valor.strip():
        return padrao
    try:
        numero = int(valor.strip())
        return max(minimo, numero)
    except ValueError:
        return padrao


@dataclass(frozen=True)
class Configuracoes:
    ambiente: str
    host: str
    porta: int
    pasta_dados: Path
    senha_admin: str
    chave_secreta: str
    chave_secreta_gerada: bool
    sessao_horas: int
    cookie_seguro: bool
    confiar_proxy: bool
    cabecalhos_ip_proxy: tuple[str, ...]
    max_tentativas_login: int
    janela_bloqueio_segundos: int
    nivel_log: str
    url_base: str

    @property
    def pasta_banco(self) -> Path:
        return self.pasta_dados / "banco"

    @property
    def pasta_midias(self) -> Path:
        return self.pasta_dados / "midias"

    @property
    def pasta_logs(self) -> Path:
        return self.pasta_dados / "logs"

    @property
    def arquivo_banco(self) -> Path:
        return self.pasta_banco / "portfolio.db"

    @property
    def sessao_segundos(self) -> int:
        return self.sessao_horas * 3600

    @property
    def eh_producao(self) -> bool:
        return self.ambiente.lower() == "producao"


def garantir_pastas_dados(config: Configuracoes) -> None:
    """Garante que a árvore persistente em dados/ exista."""
    for pasta in (
        config.pasta_dados,
        config.pasta_banco,
        config.pasta_midias,
        config.pasta_logs,
    ):
        pasta.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def obter_configuracoes() -> Configuracoes:
    ambiente = os.getenv("PORTFOLIO_AMBIENTE", "desenvolvimento").strip().lower()
    host = os.getenv("PORTFOLIO_HOST", "0.0.0.0").strip() or "0.0.0.0"
    porta = _ler_inteiro("PORTFOLIO_PORTA", 8000, minimo=1)

    pasta_dados_env = os.getenv("PORTFOLIO_PASTA_DADOS", "dados").strip() or "dados"
    pasta_dados = Path(pasta_dados_env)
    if not pasta_dados.is_absolute():
        pasta_dados = (RAIZ_PROJETO / pasta_dados).resolve()

    senha_admin = os.getenv("PORTFOLIO_SENHA_ADMIN", "").strip()

    chave_secreta = os.getenv("PORTFOLIO_CHAVE_SECRETA", "").strip()
    chave_secreta_gerada = False
    if not chave_secreta:
        chave_secreta = secrets.token_urlsafe(48)
        chave_secreta_gerada = True

    cabecalhos_brutos = os.getenv(
        "PORTFOLIO_CABECALHO_IP_PROXY",
        "CF-Connecting-IP,X-Forwarded-For",
    )
    cabecalhos_ip = tuple(
        item.strip() for item in cabecalhos_brutos.split(",") if item.strip()
    )

    return Configuracoes(
        ambiente=ambiente,
        host=host,
        porta=porta,
        pasta_dados=pasta_dados,
        senha_admin=senha_admin,
        chave_secreta=chave_secreta,
        chave_secreta_gerada=chave_secreta_gerada,
        sessao_horas=_ler_inteiro("PORTFOLIO_SESSAO_HORAS", 12, minimo=1),
        cookie_seguro=_ler_booleano("PORTFOLIO_COOKIE_SEGURO", False),
        confiar_proxy=_ler_booleano("PORTFOLIO_CONFIAR_PROXY", False),
        cabecalhos_ip_proxy=cabecalhos_ip,
        max_tentativas_login=_ler_inteiro("PORTFOLIO_MAX_TENTATIVAS_LOGIN", 5, minimo=1),
        janela_bloqueio_segundos=_ler_inteiro(
            "PORTFOLIO_JANELA_BLOQUEIO_SEGUNDOS", 300, minimo=10
        ),
        nivel_log=os.getenv("PORTFOLIO_NIVEL_LOG", "INFO").strip().upper() or "INFO",
        url_base=os.getenv("PORTFOLIO_URL_BASE", "").strip().rstrip("/"),
    )

