"""Carregamento e validação das configurações a partir do arquivo .env."""

from __future__ import annotations

import os
import re
import secrets
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

RAIZ_PROJETO = Path(__file__).resolve().parent.parent
load_dotenv(RAIZ_PROJETO / ".env")

REGEX_HORA = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


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


def _ler_hora(nome: str, padrao: str = "21:00") -> str:
    valor = os.getenv(nome, padrao).strip()
    return valor if REGEX_HORA.match(valor) else padrao


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
    smtp_ativo: bool
    smtp_host: str
    smtp_porta: int
    smtp_usuario: str
    smtp_senha: str
    smtp_destinatario: str
    relatorio_hora: str
    relatorio_enviar_se_zerado: bool
    ips_ignorados: tuple[str, ...]

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
    def pasta_backups_seguranca(self) -> Path:
        return self.pasta_dados / "backups_pre_restore"

    @property
    def arquivo_banco(self) -> Path:
        return self.pasta_banco / "portfolio.db"

    @property
    def sessao_segundos(self) -> int:
        return self.sessao_horas * 3600

    @property
    def eh_producao(self) -> bool:
        return self.ambiente.lower() == "producao"

    @property
    def smtp_configurado(self) -> bool:
        return bool(
            self.smtp_ativo
            and self.smtp_host
            and self.smtp_usuario
            and self.smtp_senha
            and self.smtp_destinatario
        )


def garantir_pastas_dados(config: Configuracoes) -> None:
    """Garante que a árvore persistente em dados/ exista."""
    for pasta in (
        config.pasta_dados,
        config.pasta_banco,
        config.pasta_midias,
        config.pasta_logs,
        config.pasta_backups_seguranca,
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

    smtp_usuario = os.getenv("SMTP_USUARIO", "").strip()
    smtp_senha = os.getenv("SMTP_SENHA", "").strip()
    smtp_host = os.getenv("SMTP_HOST", "").strip()
    if not smtp_host and smtp_usuario:
        # Padrão conveniente para contas Gmail quando SMTP_HOST não foi informado
        smtp_host = "smtp.gmail.com"
    smtp_porta = _ler_inteiro("SMTP_PORTA", 587, minimo=1)
    smtp_destinatario = os.getenv("SMTP_DESTINATARIO", "").strip() or smtp_usuario
    smtp_ativo = _ler_booleano("SMTP_ATIVO", True)

    ips_brutos = os.getenv("PORTFOLIO_IPS_IGNORADOS", "127.0.0.1,::1")
    ips_ignorados = tuple(
        item.strip() for item in ips_brutos.split(",") if item.strip()
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
        smtp_ativo=smtp_ativo,
        smtp_host=smtp_host,
        smtp_porta=smtp_porta,
        smtp_usuario=smtp_usuario,
        smtp_senha=smtp_senha,
        smtp_destinatario=smtp_destinatario,
        relatorio_hora=_ler_hora("PORTFOLIO_RELATORIO_HORA", "21:00"),
        relatorio_enviar_se_zerado=_ler_booleano(
            "PORTFOLIO_RELATORIO_ENVIAR_SE_ZERADO", False
        ),
        ips_ignorados=ips_ignorados,
    )
