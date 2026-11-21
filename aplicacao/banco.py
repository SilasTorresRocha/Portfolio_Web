"""Conexão SQLite, criação do schema e consultas estruturais do portfólio."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator

from aplicacao.configuracoes import Configuracoes, garantir_pastas_dados, obter_configuracoes

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS perfil (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    nome TEXT NOT NULL,
    subtitulo TEXT NOT NULL DEFAULT '',
    bio TEXT NOT NULL DEFAULT '',
    foto_caminho TEXT DEFAULT NULL,
    titulo_site TEXT NOT NULL DEFAULT 'Portfólio Técnico',
    cor_destaque TEXT NOT NULL DEFAULT '#3b82f6',
    email TEXT NOT NULL DEFAULT '',
    github_url TEXT NOT NULL DEFAULT '',
    linkedin_url TEXT NOT NULL DEFAULT '',
    curriculo_caminho TEXT DEFAULT NULL,
    atualizado_em TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS projetos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT NOT NULL UNIQUE,
    titulo TEXT NOT NULL,
    resumo TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT '',
    ano TEXT NOT NULL DEFAULT '',
    problema TEXT NOT NULL DEFAULT '',
    solucao TEXT NOT NULL DEFAULT '',
    resultado TEXT NOT NULL DEFAULT '',
    descricao_markdown TEXT NOT NULL DEFAULT '',
    publicado INTEGER NOT NULL DEFAULT 1,
    destaque INTEGER NOT NULL DEFAULT 0,
    ordem INTEGER NOT NULL DEFAULT 0,
    criado_em TEXT NOT NULL,
    atualizado_em TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nome TEXT NOT NULL UNIQUE,
    slug TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS projeto_tags (
    projeto_id INTEGER NOT NULL REFERENCES projetos(id) ON DELETE CASCADE,
    tag_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY (projeto_id, tag_id)
);

CREATE TABLE IF NOT EXISTS midias (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    projeto_id INTEGER NOT NULL REFERENCES projetos(id) ON DELETE CASCADE,
    arquivo_original TEXT NOT NULL,
    arquivo_miniatura TEXT NOT NULL,
    legenda TEXT NOT NULL DEFAULT '',
    eh_capa INTEGER NOT NULL DEFAULT 0,
    ordem INTEGER NOT NULL DEFAULT 0,
    criado_em TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS anexos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    projeto_id INTEGER NOT NULL REFERENCES projetos(id) ON DELETE CASCADE,
    titulo TEXT NOT NULL,
    nome_arquivo_original TEXT NOT NULL,
    caminho_arquivo TEXT NOT NULL,
    tamanho_bytes INTEGER NOT NULL DEFAULT 0,
    ordem INTEGER NOT NULL DEFAULT 0,
    criado_em TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS links_externos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    projeto_id INTEGER NOT NULL REFERENCES projetos(id) ON DELETE CASCADE,
    rotulo TEXT NOT NULL,
    url TEXT NOT NULL,
    tipo TEXT NOT NULL DEFAULT 'link',
    ordem INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_projetos_publicado_ordem
    ON projetos (publicado, destaque DESC, ordem ASC, criado_em DESC);
CREATE INDEX IF NOT EXISTS idx_midias_projeto
    ON midias (projeto_id, eh_capa DESC, ordem ASC);
CREATE INDEX IF NOT EXISTS idx_anexos_projeto
    ON anexos (projeto_id, ordem ASC);
CREATE INDEX IF NOT EXISTS idx_links_projeto
    ON links_externos (projeto_id, ordem ASC);
"""


def agora_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@contextmanager
def obter_conexao(config: Configuracoes | None = None) -> Iterator[sqlite3.Connection]:
    """Abre conexão SQLite configurada com WAL e integridade referencial."""
    cfg = config or obter_configuracoes()
    garantir_pastas_dados(cfg)
    conexao = sqlite3.connect(
        cfg.arquivo_banco,
        timeout=10.0,
        check_same_thread=False,
    )
    conexao.row_factory = sqlite3.Row
    try:
        conexao.execute("PRAGMA foreign_keys = ON;")
        conexao.execute("PRAGMA journal_mode = WAL;")
        conexao.execute("PRAGMA busy_timeout = 5000;")
        yield conexao
        conexao.commit()
    except Exception:
        conexao.rollback()
        raise
    finally:
        conexao.close()


def inicializar_banco(config: Configuracoes | None = None) -> None:
    """Cria tabelas, índices e garante o registro inicial de perfil."""
    cfg = config or obter_configuracoes()
    with obter_conexao(cfg) as conexao:
        conexao.executescript(SCHEMA_SQL)
        existente = conexao.execute("SELECT id FROM perfil WHERE id = 1").fetchone()
        if existente is None:
            conexao.execute(
                """
                INSERT INTO perfil (
                    id, nome, subtitulo, bio, titulo_site, cor_destaque, atualizado_em
                ) VALUES (1, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "Seu Nome",
                    "Engenharia · Projetos Técnicos e Sistemas",
                    "Configure seu perfil, projetos, fotos e comprovantes diretamente pelo painel /config.",
                    "Portfólio Técnico",
                    "#3b82f6",
                    agora_iso(),
                ),
            )


def obter_perfil(config: Configuracoes | None = None) -> dict:
    """Retorna os dados atuais do perfil público."""
    with obter_conexao(config) as conexao:
        linha = conexao.execute("SELECT * FROM perfil WHERE id = 1").fetchone()
        return dict(linha) if linha else {}


def obter_resumo_banco(config: Configuracoes | None = None) -> dict:
    """Retorna estatísticas rápidas do banco SQLite para diagnóstico e saúde."""
    cfg = config or obter_configuracoes()
    with obter_conexao(cfg) as conexao:
        total_projetos = conexao.execute("SELECT COUNT(*) FROM projetos").fetchone()[0]
        projetos_publicados = conexao.execute(
            "SELECT COUNT(*) FROM projetos WHERE publicado = 1"
        ).fetchone()[0]
        total_tags = conexao.execute("SELECT COUNT(*) FROM tags").fetchone()[0]
        total_midias = conexao.execute("SELECT COUNT(*) FROM midias").fetchone()[0]
        total_anexos = conexao.execute("SELECT COUNT(*) FROM anexos").fetchone()[0]
        modo_journal = conexao.execute("PRAGMA journal_mode;").fetchone()[0]

    tamanho_bytes = cfg.arquivo_banco.stat().st_size if cfg.arquivo_banco.exists() else 0
    return {
        "arquivo": str(cfg.arquivo_banco),
        "tamanho_kb": round(tamanho_bytes / 1024, 1),
        "journal_mode": modo_journal,
        "total_projetos": total_projetos,
        "projetos_publicados": projetos_publicados,
        "total_tags": total_tags,
        "total_midias": total_midias,
        "total_anexos": total_anexos,
    }

