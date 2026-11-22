"""Sistema de Backup e Restauração .zip com SHA-256, HMAC-SHA256 e proteções anti-ZipSlip/ZipBomb."""

from __future__ import annotations

import hashlib
import hmac
import io
import json
import secrets
import shutil
import sqlite3
import stat
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

from aplicacao.banco import inicializar_banco, obter_conexao
from aplicacao.configuracoes import Configuracoes, garantir_pastas_dados, obter_configuracoes
from aplicacao.registros import _obter_fuso_horario
from aplicacao.versao import VERSAO

FORMATO_BACKUP = "portfolio-backup-v1"
LIMITE_UPLOAD_BACKUP_BYTES = 250 * 1024 * 1024  # 250 MB
LIMITE_DESCOMPACTADO_BYTES = 500 * 1024 * 1024  # 500 MB (anti Zip Bomb)
LIMITE_ARQUIVOS_ZIP = 5000
MAX_SNAPSHOTS_PRE_RESTORE = 3

TABELAS_OBRIGATORIAS = {
    "perfil",
    "projetos",
    "tags",
    "projeto_tags",
    "midias",
    "anexos",
    "links_externos",
}


class ErroBackup(ValueError):
    """Erro de integridade, segurança ou formato durante backup/restauração."""


def _sha256_arquivo(caminho: Path) -> str:
    h = hashlib.sha256()
    with caminho.open("rb") as f:
        while bloco := f.read(65536):
            h.update(bloco)
    return h.hexdigest()


def _assinar_manifesto(manifesto: dict[str, Any], chave_secreta: str) -> str:
    canonico = json.dumps(manifesto, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hmac.new(chave_secreta.encode("utf-8"), canonico, hashlib.sha256).hexdigest()


def _validar_integridade_sqlite(caminho_db: Path) -> None:
    try:
        conn = sqlite3.connect(caminho_db)
        try:
            resultado = conn.execute("PRAGMA integrity_check;").fetchone()
            if not resultado or str(resultado[0]).lower() != "ok":
                raise ErroBackup(f"Banco SQLite falhou no integrity_check: {resultado}")

            tabelas = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            faltando = TABELAS_OBRIGATORIAS - tabelas
            if faltando:
                raise ErroBackup(
                    f"Banco SQLite incompleto; tabelas ausentes: {', '.join(sorted(faltando))}"
                )
        finally:
            conn.close()
    except sqlite3.Error as erro:
        raise ErroBackup(f"Arquivo SQLite inválido ou corrompido: {erro}") from erro


def gerar_backup_zip(config: Configuracoes | None = None) -> tuple[bytes, str, dict[str, Any]]:
    """Cria backup .zip consistente (SQLite online backup + dados/midias + SHA-256 + HMAC)."""
    cfg = config or obter_configuracoes()
    garantir_pastas_dados(cfg)

    agora_local = datetime.now(tz=_obter_fuso_horario())
    carimbo = agora_local.strftime("%Y-%m-%d_%H-%M")
    nome_zip = f"backup-portfolio-{carimbo}.zip"

    with tempfile.TemporaryDirectory(prefix="portfolio_bkp_") as dir_tmp:
        caminho_db_tmp = Path(dir_tmp) / "portfolio.db"

        # Snapshot online consistente (seguro mesmo em modo WAL ativo)
        with obter_conexao(cfg) as origem:
            destino = sqlite3.connect(caminho_db_tmp)
            try:
                origem.backup(destino)
            finally:
                destino.close()

        _validar_integridade_sqlite(caminho_db_tmp)

        with obter_conexao(cfg) as conn:
            total_projetos = conn.execute("SELECT COUNT(*) FROM projetos").fetchone()[0]
            total_midias = conn.execute("SELECT COUNT(*) FROM midias").fetchone()[0]
            total_anexos = conn.execute("SELECT COUNT(*) FROM anexos").fetchone()[0]

        hashes_arquivos: dict[str, str] = {
            "banco/portfolio.db": _sha256_arquivo(caminho_db_tmp)
        }

        arquivos_midia: list[tuple[str, Path]] = []
        base_midias = cfg.pasta_midias.resolve()
        if base_midias.exists():
            for caminho in sorted(base_midias.rglob("*")):
                if not caminho.is_file() or caminho.name == ".gitkeep":
                    continue
                rel = caminho.relative_to(base_midias).as_posix()
                chave_zip = f"midias/{rel}"
                hashes_arquivos[chave_zip] = _sha256_arquivo(caminho)
                arquivos_midia.append((chave_zip, caminho))

        manifesto = {
            "formato": FORMATO_BACKUP,
            "versao_app": VERSAO,
            "criado_em": agora_local.isoformat(timespec="seconds"),
            "resumo": {
                "projetos": int(total_projetos),
                "midias": int(total_midias),
                "anexos": int(total_anexos),
                "total_arquivos": len(hashes_arquivos),
            },
            "arquivos": hashes_arquivos,
        }

        envelope = {
            "manifesto": manifesto,
            "assinatura": {
                "algoritmo": "HMAC-SHA256",
                "hmac": _assinar_manifesto(manifesto, cfg.chave_secreta),
            },
        }

        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            zf.writestr(
                "manifesto.json",
                json.dumps(envelope, ensure_ascii=False, indent=2).encode("utf-8"),
            )
            zf.write(caminho_db_tmp, arcname="banco/portfolio.db")
            for chave_zip, caminho_disco in arquivos_midia:
                zf.write(caminho_disco, arcname=chave_zip)

    return buffer.getvalue(), nome_zip, manifesto["resumo"]


def _validar_nome_entrada_zip(nome: str) -> str:
    if not nome or "\x00" in nome:
        raise ErroBackup("Entrada inválida encontrada no arquivo ZIP.")
    normalizado = nome.replace("\\", "/")
    if normalizado.startswith("/") or ":" in normalizado.split("/")[0]:
        raise ErroBackup(f"Caminho absoluto bloqueado no ZIP (Zip Slip): {nome}")
    partes = [p for p in normalizado.split("/") if p]
    if any(p in {".", ".."} for p in partes):
        raise ErroBackup(f"Caminho relativo inseguro bloqueado no ZIP (Zip Slip): {nome}")
    return "/".join(partes)


def _extrair_zip_seguro(conteudo_zip: bytes, destino: Path) -> set[str]:
    if not conteudo_zip:
        raise ErroBackup("Arquivo de backup vazio.")
    if len(conteudo_zip) > LIMITE_UPLOAD_BACKUP_BYTES:
        raise ErroBackup("Arquivo de backup excede o limite máximo de 250 MB.")

    try:
        zf = zipfile.ZipFile(io.BytesIO(conteudo_zip), mode="r")
    except zipfile.BadZipFile as erro:
        raise ErroBackup("O arquivo enviado não é um .zip válido.") from erro

    arquivos_extraidos: set[str] = set()
    bytes_totais = 0
    base_dest = destino.resolve()

    with zf:
        infos = [info for info in zf.infolist() if not info.is_dir()]
        if len(infos) > LIMITE_ARQUIVOS_ZIP:
            raise ErroBackup("Backup excede o limite máximo de arquivos permitido (proteção Zip Bomb).")

        for info in infos:
            # Bloqueia links simbólicos dentro do ZIP
            modo = info.external_attr >> 16
            if stat.S_ISLNK(modo):
                raise ErroBackup(f"Link simbólico não permitido no backup: {info.filename}")

            rel = _validar_nome_entrada_zip(info.filename)
            if rel != "manifesto.json" and rel != "banco/portfolio.db" and not rel.startswith("midias/"):
                raise ErroBackup(f"Arquivo inesperado no backup: {rel}")

            if info.file_size > LIMITE_DESCOMPACTADO_BYTES:
                raise ErroBackup("Entrada excede o tamanho máximo descompactado (proteção Zip Bomb).")

            alvo = (base_dest / rel).resolve()
            try:
                alvo.relative_to(base_dest)
            except ValueError as erro:
                raise ErroBackup(f"Tentativa de escape de diretório bloqueada: {rel}") from erro

            alvo.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info, "r") as src, alvo.open("wb") as dst:
                while bloco := src.read(65536):
                    bytes_totais += len(bloco)
                    if bytes_totais > LIMITE_DESCOMPACTADO_BYTES:
                        raise ErroBackup(
                            "Conteúdo descompactado excede 500 MB (proteção Zip Bomb)."
                        )
                    dst.write(bloco)

            arquivos_extraidos.add(rel)

    return arquivos_extraidos


def _validar_estrutura_extraida(
    pasta_extraida: Path,
    arquivos_extraidos: set[str],
    config: Configuracoes,
) -> tuple[dict[str, Any], bool]:
    caminho_manifesto = pasta_extraida / "manifesto.json"
    if not caminho_manifesto.is_file():
        raise ErroBackup("Backup inválido: manifesto.json ausente.")

    try:
        envelope = json.loads(caminho_manifesto.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as erro:
        raise ErroBackup("manifesto.json corrompido ou ilegível.") from erro

    manifesto = envelope.get("manifesto")
    assinatura = envelope.get("assinatura") or {}
    if not isinstance(manifesto, dict) or manifesto.get("formato") != FORMATO_BACKUP:
        raise ErroBackup("Formato de backup incompatível com esta aplicação.")

    arquivos_manifesto = manifesto.get("arquivos")
    if not isinstance(arquivos_manifesto, dict) or "banco/portfolio.db" not in arquivos_manifesto:
        raise ErroBackup("manifesto.json não declara banco/portfolio.db.")

    # Confere se conjunto de arquivos extraídos bate exatamente com o manifesto
    extraidos_dados = arquivos_extraidos - {"manifesto.json"}
    esperados = set(arquivos_manifesto.keys())
    faltantes = esperados - extraidos_dados
    extras = extraidos_dados - esperados
    if faltantes:
        raise ErroBackup(f"Backup incompleto; arquivos ausentes: {', '.join(sorted(faltantes)[:5])}")
    if extras:
        raise ErroBackup(f"Backup contém arquivos não declarados no manifesto: {', '.join(sorted(extras)[:5])}")

    # Validação obrigatória SHA-256 de TODOS os arquivos
    for rel, hash_esperado in arquivos_manifesto.items():
        hash_real = _sha256_arquivo(pasta_extraida / rel)
        if not hmac.compare_digest(hash_real, str(hash_esperado)):
            raise ErroBackup(f"Arquivo corrompido (SHA-256 divergente): {rel}")

    # Validação obrigatória de integridade e schema do SQLite
    _validar_integridade_sqlite(pasta_extraida / "banco/portfolio.db")

    # Validação da assinatura HMAC-SHA256 com a PORTFOLIO_CHAVE_SECRETA atual
    hmac_informado = str(assinatura.get("hmac") or "")
    hmac_esperado = _assinar_manifesto(manifesto, config.chave_secreta)
    assinatura_valida = bool(hmac_informado) and hmac.compare_digest(hmac_informado, hmac_esperado)

    return manifesto, assinatura_valida


def _salvar_snapshot_pre_restore(config: Configuracoes) -> Path:
    bytes_bkp, _, _ = gerar_backup_zip(config)
    agora = datetime.now(tz=_obter_fuso_horario()).strftime("%Y-%m-%d_%H-%M-%S")
    destino = config.pasta_backups_seguranca / f"pre-restore-{agora}.zip"
    destino.write_bytes(bytes_bkp)

    # Mantém somente os N snapshots mais recentes
    snapshots = sorted(
        config.pasta_backups_seguranca.glob("pre-restore-*.zip"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for antigo in snapshots[MAX_SNAPSHOTS_PRE_RESTORE:]:
        try:
            antigo.unlink()
        except OSError:
            pass
    return destino


def _aplicar_restauracao(pasta_extraida: Path, config: Configuracoes) -> None:
    _salvar_snapshot_pre_restore(config)

    # 1. Restaura SQLite usando a API online backup() para evitar locks no Windows/WAL
    origem_db = sqlite3.connect(pasta_extraida / "banco/portfolio.db")
    try:
        with obter_conexao(config) as destino_db:
            origem_db.backup(destino_db)
    finally:
        origem_db.close()

    # Garante eventuais tabelas mais novas caso o backup seja de versão anterior
    inicializar_banco(config)

    # 2. Substitui conteúdo de dados/midias preservando .gitkeep
    pasta_midias = config.pasta_midias
    pasta_midias.mkdir(parents=True, exist_ok=True)
    for item in list(pasta_midias.iterdir()):
        if item.name == ".gitkeep":
            continue
        if item.is_dir():
            shutil.rmtree(item, ignore_errors=True)
        else:
            try:
                item.unlink()
            except OSError:
                pass

    origem_midias = pasta_extraida / "midias"
    if origem_midias.exists():
        for arquivo in origem_midias.rglob("*"):
            if not arquivo.is_file():
                continue
            rel = arquivo.relative_to(origem_midias)
            destino = pasta_midias / rel
            destino.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(arquivo, destino)


def _limpar_pendentes_antigos(config: Configuracoes) -> None:
    agora = datetime.now().timestamp()
    for arq in config.pasta_backups_seguranca.glob("_pendente_*.zip"):
        try:
            if (agora - arq.stat().st_mtime) > 900:  # 15 minutos
                arq.unlink()
        except OSError:
            pass


def processar_upload_restauracao(
    conteudo_zip: bytes,
    *,
    confirmar_chave_diferente: bool = False,
    config: Configuracoes | None = None,
) -> dict[str, Any]:
    """Valida um backup .zip e restaura (ou devolve token de confirmação se HMAC diferir)."""
    cfg = config or obter_configuracoes()
    garantir_pastas_dados(cfg)
    _limpar_pendentes_antigos(cfg)

    with tempfile.TemporaryDirectory(prefix="portfolio_restore_") as dir_tmp:
        pasta_tmp = Path(dir_tmp)
        arquivos = _extrair_zip_seguro(conteudo_zip, pasta_tmp)
        manifesto, assinatura_valida = _validar_estrutura_extraida(pasta_tmp, arquivos, cfg)

        if not assinatura_valida and not confirmar_chave_diferente:
            token = secrets.token_hex(12)
            caminho_pendente = cfg.pasta_backups_seguranca / f"_pendente_{token}.zip"
            caminho_pendente.write_bytes(conteudo_zip)
            return {
                "status": "requer_confirmacao",
                "token": token,
                "assinatura_valida": False,
                "manifesto": manifesto,
            }

        _aplicar_restauracao(pasta_tmp, cfg)
        return {
            "status": "restaurado",
            "assinatura_valida": assinatura_valida,
            "manifesto": manifesto,
        }


def confirmar_restauracao_pendente(
    token: str,
    config: Configuracoes | None = None,
) -> dict[str, Any]:
    """Aplica um backup previamente validado que aguardava confirmação de chave diferente."""
    cfg = config or obter_configuracoes()
    if not token or not token.isalnum() or len(token) > 40:
        raise ErroBackup("Token de restauração inválido.")

    caminho = cfg.pasta_backups_seguranca / f"_pendente_{token}.zip"
    if not caminho.is_file():
        raise ErroBackup("Backup pendente expirado ou não encontrado. Envie o arquivo novamente.")

    try:
        conteudo = caminho.read_bytes()
        resultado = processar_upload_restauracao(
            conteudo,
            confirmar_chave_diferente=True,
            config=cfg,
        )
    finally:
        try:
            caminho.unlink()
        except OSError:
            pass
    return resultado

