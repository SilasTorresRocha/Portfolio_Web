"""Consultas públicas do catálogo de projetos, tags, galerias, anexos e links."""

from __future__ import annotations

import unicodedata
from typing import Any

from aplicacao.banco import obter_conexao
from aplicacao.configuracoes import Configuracoes
from aplicacao.servicos.arquivos import formatar_tamanho_bytes
from aplicacao.servicos.markdown_seguro import renderizar_markdown_seguro


def _normalizar_busca(texto: str) -> str:
    sem_acento = unicodedata.normalize("NFKD", texto or "")
    somente_base = "".join(ch for ch in sem_acento if not unicodedata.combining(ch))
    return somente_base.lower().strip()


def obter_iniciais_perfil(nome: str) -> str:
    partes = [p for p in (nome or "").strip().split() if p]
    if not partes:
        return "PT"
    if len(partes) == 1:
        return partes[0][:2].upper()
    return f"{partes[0][0]}{partes[-1][0]}".upper()


def listar_tags_publicas(config: Configuracoes | None = None) -> list[dict[str, Any]]:
    """Lista tags vinculadas a projetos publicados com contagem de projetos."""
    with obter_conexao(config) as conexao:
        linhas = conexao.execute(
            """
            SELECT t.id, t.nome, t.slug, COUNT(DISTINCT p.id) AS total
            FROM tags t
            INNER JOIN projeto_tags pt ON pt.tag_id = t.id
            INNER JOIN projetos p ON p.id = pt.projeto_id AND p.publicado = 1
            GROUP BY t.id, t.nome, t.slug
            ORDER BY total DESC, t.nome ASC
            """
        ).fetchall()
    return [dict(linha) for linha in linhas]


def listar_projetos_publicos(
    busca: str = "",
    tag_slug: str = "",
    config: Configuracoes | None = None,
) -> list[dict[str, Any]]:
    """Retorna projetos publicados ordenados, enriquecidos com capa, tags e contagens."""
    termo_tag = (tag_slug or "").strip().lower()
    termo_busca = _normalizar_busca(busca)

    with obter_conexao(config) as conexao:
        if termo_tag:
            linhas_projetos = conexao.execute(
                """
                SELECT DISTINCT p.*
                FROM projetos p
                INNER JOIN projeto_tags pt ON pt.projeto_id = p.id
                INNER JOIN tags t ON t.id = pt.tag_id
                WHERE p.publicado = 1 AND LOWER(t.slug) = ?
                ORDER BY p.destaque DESC, p.ordem ASC, p.criado_em DESC
                """,
                (termo_tag,),
            ).fetchall()
        else:
            linhas_projetos = conexao.execute(
                """
                SELECT p.*
                FROM projetos p
                WHERE p.publicado = 1
                ORDER BY p.destaque DESC, p.ordem ASC, p.criado_em DESC
                """
            ).fetchall()

        if not linhas_projetos:
            return []

        ids = [linha["id"] for linha in linhas_projetos]
        placeholders = ",".join("?" for _ in ids)

        # Tags de todos os projetos listados
        tags_por_projeto: dict[int, list[dict[str, Any]]] = {pid: [] for pid in ids}
        for row in conexao.execute(
            f"""
            SELECT pt.projeto_id, t.id, t.nome, t.slug
            FROM projeto_tags pt
            INNER JOIN tags t ON t.id = pt.tag_id
            WHERE pt.projeto_id IN ({placeholders})
            ORDER BY t.nome ASC
            """,
            ids,
        ).fetchall():
            tags_por_projeto[row["projeto_id"]].append(
                {"id": row["id"], "nome": row["nome"], "slug": row["slug"]}
            )

        # Capa e contagem de mídias
        capa_por_projeto: dict[int, dict[str, Any]] = {}
        contagem_midias: dict[int, int] = {pid: 0 for pid in ids}
        for row in conexao.execute(
            f"""
            SELECT projeto_id, arquivo_miniatura, arquivo_original, legenda, eh_capa
            FROM midias
            WHERE projeto_id IN ({placeholders})
            ORDER BY eh_capa DESC, ordem ASC, id ASC
            """,
            ids,
        ).fetchall():
            pid = row["projeto_id"]
            contagem_midias[pid] = contagem_midias.get(pid, 0) + 1
            if pid not in capa_por_projeto:
                capa_por_projeto[pid] = {
                    "miniatura": row["arquivo_miniatura"],
                    "original": row["arquivo_original"],
                    "legenda": row["legenda"],
                }

        # Contagem de anexos PDF
        contagem_anexos: dict[int, int] = {pid: 0 for pid in ids}
        for row in conexao.execute(
            f"""
            SELECT projeto_id, COUNT(*) AS total
            FROM anexos
            WHERE projeto_id IN ({placeholders})
            GROUP BY projeto_id
            """,
            ids,
        ).fetchall():
            contagem_anexos[row["projeto_id"]] = row["total"]

    resultado: list[dict[str, Any]] = []
    for linha in linhas_projetos:
        projeto = dict(linha)
        pid = projeto["id"]
        tags = tags_por_projeto.get(pid, [])
        projeto["tags"] = tags
        projeto["tags_slugs"] = [t["slug"] for t in tags]
        projeto["capa"] = capa_por_projeto.get(pid)
        projeto["total_midias"] = contagem_midias.get(pid, 0)
        projeto["total_anexos"] = contagem_anexos.get(pid, 0)

        texto_indexavel = " ".join(
            [
                projeto.get("titulo", ""),
                projeto.get("resumo", ""),
                projeto.get("status", ""),
                projeto.get("ano", ""),
                projeto.get("problema", ""),
                projeto.get("solucao", ""),
                projeto.get("resultado", ""),
                " ".join(t["nome"] for t in tags),
            ]
        )
        projeto["texto_busca"] = _normalizar_busca(texto_indexavel)

        if termo_busca and termo_busca not in projeto["texto_busca"]:
            continue

        resultado.append(projeto)

    return resultado


def obter_projeto_por_slug(
    slug: str,
    *,
    incluir_rascunho: bool = False,
    config: Configuracoes | None = None,
) -> dict[str, Any] | None:
    """Carrega um projeto completo (tags, galeria, anexos PDF, links e HTML seguro)."""
    slug_limpo = (slug or "").strip().lower()
    if not slug_limpo:
        return None

    filtro_publicado = "" if incluir_rascunho else "AND publicado = 1"

    with obter_conexao(config) as conexao:
        linha = conexao.execute(
            f"SELECT * FROM projetos WHERE LOWER(slug) = ? {filtro_publicado}",
            (slug_limpo,),
        ).fetchone()
        if linha is None:
            return None

        projeto = dict(linha)
        pid = projeto["id"]

        projeto["tags"] = [
            dict(row)
            for row in conexao.execute(
                """
                SELECT t.id, t.nome, t.slug
                FROM tags t
                INNER JOIN projeto_tags pt ON pt.tag_id = t.id
                WHERE pt.projeto_id = ?
                ORDER BY t.nome ASC
                """,
                (pid,),
            ).fetchall()
        ]

        projeto["midias"] = [
            dict(row)
            for row in conexao.execute(
                """
                SELECT id, arquivo_original, arquivo_miniatura, legenda, eh_capa, ordem
                FROM midias
                WHERE projeto_id = ?
                ORDER BY eh_capa DESC, ordem ASC, id ASC
                """,
                (pid,),
            ).fetchall()
        ]

        anexos = []
        for row in conexao.execute(
            """
            SELECT id, titulo, nome_arquivo_original, caminho_arquivo, tamanho_bytes, ordem
            FROM anexos
            WHERE projeto_id = ?
            ORDER BY ordem ASC, id ASC
            """,
            (pid,),
        ).fetchall():
            item = dict(row)
            item["tamanho_formatado"] = formatar_tamanho_bytes(item["tamanho_bytes"])
            anexos.append(item)
        projeto["anexos"] = anexos

        projeto["links_externos"] = [
            dict(row)
            for row in conexao.execute(
                """
                SELECT id, rotulo, url, tipo, ordem
                FROM links_externos
                WHERE projeto_id = ?
                ORDER BY ordem ASC, id ASC
                """,
                (pid,),
            ).fetchall()
        ]

    projeto["capa"] = projeto["midias"][0] if projeto["midias"] else None
    projeto["tem_psr"] = any(
        (projeto.get(campo) or "").strip() for campo in ("problema", "solucao", "resultado")
    )
    projeto["descricao_html"] = renderizar_markdown_seguro(
        projeto.get("descricao_markdown", "")
    )
    return projeto


def obter_anexo_por_id(
    anexo_id: int,
    *,
    incluir_rascunho: bool = False,
    config: Configuracoes | None = None,
) -> dict[str, Any] | None:
    """Busca metadados de um anexo PDF respeitando visibilidade do projeto."""
    filtro_publicado = "" if incluir_rascunho else "AND p.publicado = 1"
    with obter_conexao(config) as conexao:
        linha = conexao.execute(
            f"""
            SELECT a.*, p.publicado
            FROM anexos a
            INNER JOIN projetos p ON p.id = a.projeto_id
            WHERE a.id = ? {filtro_publicado}
            """,
            (anexo_id,),
        ).fetchone()
    return dict(linha) if linha else None

