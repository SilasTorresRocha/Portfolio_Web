"""Operações administrativas (CRUD de projetos, tags, galeria, anexos, links e perfil)."""

from __future__ import annotations

import re
import sqlite3
import unicodedata
from typing import Any

from aplicacao.banco import agora_iso, obter_conexao
from aplicacao.configuracoes import Configuracoes
from aplicacao.servicos.arquivos import formatar_tamanho_bytes
from aplicacao.servicos.midias import (
    ErroUpload,
    remover_arquivo_midia,
    salvar_avatar_perfil,
    salvar_imagem_projeto,
    salvar_pdf,
)

REGEX_COR_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
TIPOS_LINK_VALIDOS = {"github", "producao", "video", "documentacao", "link"}

CORES_PRESET = (
    ("#3b82f6", "Azul industrial"),
    ("#10b981", "Verde terminal"),
    ("#f59e0b", "Âmbar técnico"),
    ("#06b6d4", "Ciano aço"),
    ("#94a3b8", "Platina neutro"),
)


def gerar_slug(texto: str, padrao: str = "item") -> str:
    sem_acento = unicodedata.normalize("NFKD", texto or "")
    ascii_limpo = "".join(ch for ch in sem_acento if not unicodedata.combining(ch))
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_limpo.lower()).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)
    return slug[:80] or padrao


def _garantir_slug_projeto_unico(
    conexao: sqlite3.Connection,
    slug_base: str,
    ignorar_id: int | None = None,
) -> str:
    candidato = gerar_slug(slug_base, padrao="projeto")
    sufixo = 2
    while True:
        if ignorar_id is None:
            existe = conexao.execute(
                "SELECT id FROM projetos WHERE LOWER(slug) = LOWER(?)",
                (candidato,),
            ).fetchone()
        else:
            existe = conexao.execute(
                "SELECT id FROM projetos WHERE LOWER(slug) = LOWER(?) AND id != ?",
                (candidato, ignorar_id),
            ).fetchone()
        if not existe:
            return candidato
        candidato = f"{gerar_slug(slug_base, padrao='projeto')[:72]}-{sufixo}"
        sufixo += 1


def _validar_url_externa(url: str, obrigatoria: bool = True) -> str:
    limpa = (url or "").strip()
    if not limpa:
        if obrigatoria:
            raise ValueError("Informe uma URL válida.")
        return ""
    if not (limpa.startswith("http://") or limpa.startswith("https://")):
        raise ValueError("URLs devem começar com http:// ou https://.")
    return limpa


def _sincronizar_tags_projeto(
    conexao: sqlite3.Connection,
    projeto_id: int,
    tags_texto: str,
) -> None:
    conexao.execute("DELETE FROM projeto_tags WHERE projeto_id = ?", (projeto_id,))
    nomes_brutos = [item.strip() for item in (tags_texto or "").split(",") if item.strip()]

    vistos: set[str] = set()
    for nome in nomes_brutos:
        nome_curto = nome[:40]
        slug = gerar_slug(nome_curto, padrao="tag")
        if slug in vistos:
            continue
        vistos.add(slug)

        row = conexao.execute(
            "SELECT id FROM tags WHERE LOWER(slug) = LOWER(?) OR LOWER(nome) = LOWER(?)",
            (slug, nome_curto),
        ).fetchone()
        if row:
            tag_id = int(row["id"])
        else:
            cur = conexao.execute(
                "INSERT INTO tags (nome, slug) VALUES (?, ?)",
                (nome_curto, slug),
            )
            tag_id = int(cur.lastrowid)

        conexao.execute(
            "INSERT OR IGNORE INTO projeto_tags (projeto_id, tag_id) VALUES (?, ?)",
            (projeto_id, tag_id),
        )


def calcular_checklist_projeto(projeto: dict[str, Any]) -> dict[str, Any]:
    itens = [
        ("Capa", bool(projeto.get("total_midias") or projeto.get("midias"))),
        ("Resumo", bool((projeto.get("resumo") or "").strip())),
        ("Problema", bool((projeto.get("problema") or "").strip())),
        ("Solução", bool((projeto.get("solucao") or "").strip())),
        ("Resultado", bool((projeto.get("resultado") or "").strip())),
        ("Tags", bool(projeto.get("tags"))),
    ]
    preenchidos = sum(1 for _, ok in itens if ok)
    return {
        "itens": itens,
        "preenchidos": preenchidos,
        "total": len(itens),
    }


def listar_todas_tags_admin(config: Configuracoes | None = None) -> list[dict[str, Any]]:
    with obter_conexao(config) as conexao:
        linhas = conexao.execute(
            """
            SELECT t.id, t.nome, t.slug, COUNT(pt.projeto_id) AS total_projetos
            FROM tags t
            LEFT JOIN projeto_tags pt ON pt.tag_id = t.id
            GROUP BY t.id, t.nome, t.slug
            ORDER BY t.nome ASC
            """
        ).fetchall()
    return [dict(linha) for linha in linhas]


def remover_tag_admin(tag_id: int, config: Configuracoes | None = None) -> str | None:
    with obter_conexao(config) as conexao:
        row = conexao.execute("SELECT nome FROM tags WHERE id = ?", (tag_id,)).fetchone()
        if not row:
            return None
        conexao.execute("DELETE FROM tags WHERE id = ?", (tag_id,))
        return str(row["nome"])


def listar_projetos_admin(config: Configuracoes | None = None) -> list[dict[str, Any]]:
    with obter_conexao(config) as conexao:
        linhas = conexao.execute(
            """
            SELECT * FROM projetos
            ORDER BY destaque DESC, ordem ASC, criado_em DESC
            """
        ).fetchall()

        if not linhas:
            return []

        ids = [row["id"] for row in linhas]
        placeholders = ",".join("?" for _ in ids)

        tags_map: dict[int, list[dict[str, Any]]] = {pid: [] for pid in ids}
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
            tags_map[row["projeto_id"]].append(dict(row))

        capa_map: dict[int, str] = {}
        midias_count: dict[int, int] = {pid: 0 for pid in ids}
        for row in conexao.execute(
            f"""
            SELECT projeto_id, arquivo_miniatura
            FROM midias
            WHERE projeto_id IN ({placeholders})
            ORDER BY eh_capa DESC, ordem ASC, id ASC
            """,
            ids,
        ).fetchall():
            pid = row["projeto_id"]
            midias_count[pid] += 1
            if pid not in capa_map:
                capa_map[pid] = row["arquivo_miniatura"]

        anexos_count: dict[int, int] = {pid: 0 for pid in ids}
        for row in conexao.execute(
            f"""
            SELECT projeto_id, COUNT(*) AS total
            FROM anexos
            WHERE projeto_id IN ({placeholders})
            GROUP BY projeto_id
            """,
            ids,
        ).fetchall():
            anexos_count[row["projeto_id"]] = row["total"]

    projetos: list[dict[str, Any]] = []
    for linha in linhas:
        item = dict(linha)
        pid = item["id"]
        item["tags"] = tags_map.get(pid, [])
        item["capa_miniatura"] = capa_map.get(pid)
        item["total_midias"] = midias_count.get(pid, 0)
        item["total_anexos"] = anexos_count.get(pid, 0)
        item["checklist"] = calcular_checklist_projeto(item)
        projetos.append(item)
    return projetos


def obter_projeto_admin(
    projeto_id: int,
    config: Configuracoes | None = None,
) -> dict[str, Any] | None:
    with obter_conexao(config) as conexao:
        linha = conexao.execute(
            "SELECT * FROM projetos WHERE id = ?",
            (projeto_id,),
        ).fetchone()
        if not linha:
            return None

        projeto = dict(linha)
        projeto["tags"] = [
            dict(r)
            for r in conexao.execute(
                """
                SELECT t.id, t.nome, t.slug
                FROM tags t
                INNER JOIN projeto_tags pt ON pt.tag_id = t.id
                WHERE pt.projeto_id = ?
                ORDER BY t.nome ASC
                """,
                (projeto_id,),
            ).fetchall()
        ]
        projeto["tags_texto"] = ", ".join(t["nome"] for t in projeto["tags"])

        projeto["midias"] = [
            dict(r)
            for r in conexao.execute(
                """
                SELECT * FROM midias
                WHERE projeto_id = ?
                ORDER BY eh_capa DESC, ordem ASC, id ASC
                """,
                (projeto_id,),
            ).fetchall()
        ]

        anexos = []
        for r in conexao.execute(
            "SELECT * FROM anexos WHERE projeto_id = ? ORDER BY ordem ASC, id ASC",
            (projeto_id,),
        ).fetchall():
            a = dict(r)
            a["tamanho_formatado"] = formatar_tamanho_bytes(a["tamanho_bytes"])
            anexos.append(a)
        projeto["anexos"] = anexos

        projeto["links_externos"] = [
            dict(r)
            for r in conexao.execute(
                "SELECT * FROM links_externos WHERE projeto_id = ? ORDER BY ordem ASC, id ASC",
                (projeto_id,),
            ).fetchall()
        ]

    projeto["checklist"] = calcular_checklist_projeto(projeto)
    return projeto


def criar_projeto(
    *,
    titulo: str,
    slug: str = "",
    resumo: str = "",
    status: str = "",
    ano: str = "",
    problema: str = "",
    solucao: str = "",
    resultado: str = "",
    descricao_markdown: str = "",
    tags_texto: str = "",
    publicado: bool = True,
    destaque: bool = False,
    ordem: int = 0,
    config: Configuracoes | None = None,
) -> tuple[int, str]:
    titulo_limpo = (titulo or "").strip()
    if not titulo_limpo:
        raise ValueError("O título do projeto é obrigatório.")

    agora = agora_iso()
    with obter_conexao(config) as conexao:
        slug_final = _garantir_slug_projeto_unico(conexao, slug.strip() or titulo_limpo)
        cur = conexao.execute(
            """
            INSERT INTO projetos (
                slug, titulo, resumo, status, ano,
                problema, solucao, resultado, descricao_markdown,
                publicado, destaque, ordem, criado_em, atualizado_em
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                slug_final,
                titulo_limpo,
                resumo.strip(),
                status.strip().upper()[:40],
                ano.strip()[:20],
                problema.strip(),
                solucao.strip(),
                resultado.strip(),
                descricao_markdown.strip(),
                1 if publicado else 0,
                1 if destaque else 0,
                int(ordem),
                agora,
                agora,
            ),
        )
        projeto_id = int(cur.lastrowid)
        _sincronizar_tags_projeto(conexao, projeto_id, tags_texto)
    return projeto_id, slug_final


def atualizar_projeto(
    projeto_id: int,
    *,
    titulo: str,
    slug: str = "",
    resumo: str = "",
    status: str = "",
    ano: str = "",
    problema: str = "",
    solucao: str = "",
    resultado: str = "",
    descricao_markdown: str = "",
    tags_texto: str = "",
    publicado: bool = True,
    destaque: bool = False,
    ordem: int = 0,
    config: Configuracoes | None = None,
) -> str:
    titulo_limpo = (titulo or "").strip()
    if not titulo_limpo:
        raise ValueError("O título do projeto é obrigatório.")

    with obter_conexao(config) as conexao:
        existente = conexao.execute(
            "SELECT id FROM projetos WHERE id = ?",
            (projeto_id,),
        ).fetchone()
        if not existente:
            raise LookupError("Projeto não encontrado.")

        slug_final = _garantir_slug_projeto_unico(
            conexao,
            slug.strip() or titulo_limpo,
            ignorar_id=projeto_id,
        )
        conexao.execute(
            """
            UPDATE projetos
            SET slug = ?, titulo = ?, resumo = ?, status = ?, ano = ?,
                problema = ?, solucao = ?, resultado = ?, descricao_markdown = ?,
                publicado = ?, destaque = ?, ordem = ?, atualizado_em = ?
            WHERE id = ?
            """,
            (
                slug_final,
                titulo_limpo,
                resumo.strip(),
                status.strip().upper()[:40],
                ano.strip()[:20],
                problema.strip(),
                solucao.strip(),
                resultado.strip(),
                descricao_markdown.strip(),
                1 if publicado else 0,
                1 if destaque else 0,
                int(ordem),
                agora_iso(),
                projeto_id,
            ),
        )
        _sincronizar_tags_projeto(conexao, projeto_id, tags_texto)
    return slug_final


def alternar_publicacao_projeto(
    projeto_id: int,
    config: Configuracoes | None = None,
) -> tuple[str, bool] | None:
    with obter_conexao(config) as conexao:
        row = conexao.execute(
            "SELECT slug, publicado FROM projetos WHERE id = ?",
            (projeto_id,),
        ).fetchone()
        if not row:
            return None
        novo_estado = 0 if row["publicado"] else 1
        conexao.execute(
            "UPDATE projetos SET publicado = ?, atualizado_em = ? WHERE id = ?",
            (novo_estado, agora_iso(), projeto_id),
        )
        return str(row["slug"]), bool(novo_estado)


def excluir_projeto(projeto_id: int, config: Configuracoes | None = None) -> str | None:
    caminhos_para_remover: list[str] = []
    with obter_conexao(config) as conexao:
        row = conexao.execute(
            "SELECT slug FROM projetos WHERE id = ?",
            (projeto_id,),
        ).fetchone()
        if not row:
            return None
        slug = str(row["slug"])

        for m in conexao.execute(
            "SELECT arquivo_original, arquivo_miniatura FROM midias WHERE projeto_id = ?",
            (projeto_id,),
        ).fetchall():
            caminhos_para_remover.append(m["arquivo_original"])
            if m["arquivo_miniatura"] != m["arquivo_original"]:
                caminhos_para_remover.append(m["arquivo_miniatura"])

        for a in conexao.execute(
            "SELECT caminho_arquivo FROM anexos WHERE projeto_id = ?",
            (projeto_id,),
        ).fetchall():
            caminhos_para_remover.append(a["caminho_arquivo"])

        conexao.execute("DELETE FROM projetos WHERE id = ?", (projeto_id,))

    for caminho in caminhos_para_remover:
        remover_arquivo_midia(caminho, config)
    return slug


# ----------------------------------------------------------------------------
# Galeria de imagens do projeto
# ----------------------------------------------------------------------------

def adicionar_midias_projeto(
    projeto_id: int,
    arquivos: list[tuple[bytes, str]],
    config: Configuracoes | None = None,
) -> int:
    if not arquivos:
        raise ErroUpload("Selecione ao menos uma imagem para enviar.")

    with obter_conexao(config) as conexao:
        existe = conexao.execute("SELECT id FROM projetos WHERE id = ?", (projeto_id,)).fetchone()
        if not existe:
            raise LookupError("Projeto não encontrado.")

        row_meta = conexao.execute(
            "SELECT COUNT(*) AS total, COALESCE(MAX(ordem), 0) AS max_ordem FROM midias WHERE projeto_id = ?",
            (projeto_id,),
        ).fetchone()
        ja_tem_capa = conexao.execute(
            "SELECT 1 FROM midias WHERE projeto_id = ? AND eh_capa = 1 LIMIT 1",
            (projeto_id,),
        ).fetchone() is not None
        proxima_ordem = int(row_meta["max_ordem"]) + 1

        enviadas = 0
        agora = agora_iso()
        for conteudo, nome in arquivos:
            rel_original, rel_miniatura = salvar_imagem_projeto(
                conteudo, nome, projeto_id, config=config
            )
            marcar_capa = 1 if (not ja_tem_capa and enviadas == 0) else 0
            if marcar_capa:
                ja_tem_capa = True
            conexao.execute(
                """
                INSERT INTO midias (
                    projeto_id, arquivo_original, arquivo_miniatura, legenda, eh_capa, ordem, criado_em
                ) VALUES (?, ?, ?, '', ?, ?, ?)
                """,
                (projeto_id, rel_original, rel_miniatura, marcar_capa, proxima_ordem, agora),
            )
            proxima_ordem += 1
            enviadas += 1

        conexao.execute(
            "UPDATE projetos SET atualizado_em = ? WHERE id = ?",
            (agora, projeto_id),
        )
    return enviadas


def atualizar_midia_projeto(
    projeto_id: int,
    midia_id: int,
    *,
    legenda: str | None = None,
    ordem: int | None = None,
    definir_capa: bool = False,
    config: Configuracoes | None = None,
) -> bool:
    with obter_conexao(config) as conexao:
        row = conexao.execute(
            "SELECT id FROM midias WHERE id = ? AND projeto_id = ?",
            (midia_id, projeto_id),
        ).fetchone()
        if not row:
            return False

        if definir_capa:
            conexao.execute(
                "UPDATE midias SET eh_capa = 0 WHERE projeto_id = ?",
                (projeto_id,),
            )
            conexao.execute(
                "UPDATE midias SET eh_capa = 1 WHERE id = ?",
                (midia_id,),
            )

        if legenda is not None:
            conexao.execute(
                "UPDATE midias SET legenda = ? WHERE id = ?",
                (legenda.strip()[:260], midia_id),
            )

        if ordem is not None:
            conexao.execute(
                "UPDATE midias SET ordem = ? WHERE id = ?",
                (int(ordem), midia_id),
            )

        conexao.execute(
            "UPDATE projetos SET atualizado_em = ? WHERE id = ?",
            (agora_iso(), projeto_id),
        )
    return True


def remover_midia_projeto(
    projeto_id: int,
    midia_id: int,
    config: Configuracoes | None = None,
) -> bool:
    caminhos: list[str] = []
    with obter_conexao(config) as conexao:
        row = conexao.execute(
            "SELECT arquivo_original, arquivo_miniatura, eh_capa FROM midias WHERE id = ? AND projeto_id = ?",
            (midia_id, projeto_id),
        ).fetchone()
        if not row:
            return False

        caminhos.append(row["arquivo_original"])
        if row["arquivo_miniatura"] != row["arquivo_original"]:
            caminhos.append(row["arquivo_miniatura"])
        era_capa = bool(row["eh_capa"])

        conexao.execute("DELETE FROM midias WHERE id = ?", (midia_id,))

        if era_capa:
            proxima = conexao.execute(
                "SELECT id FROM midias WHERE projeto_id = ? ORDER BY ordem ASC, id ASC LIMIT 1",
                (projeto_id,),
            ).fetchone()
            if proxima:
                conexao.execute("UPDATE midias SET eh_capa = 1 WHERE id = ?", (proxima["id"],))

        conexao.execute(
            "UPDATE projetos SET atualizado_em = ? WHERE id = ?",
            (agora_iso(), projeto_id),
        )

    for caminho in caminhos:
        remover_arquivo_midia(caminho, config)
    return True


# ----------------------------------------------------------------------------
# Anexos PDF do projeto
# ----------------------------------------------------------------------------

def adicionar_anexo_projeto(
    projeto_id: int,
    *,
    titulo: str,
    conteudo: bytes,
    nome_arquivo: str,
    config: Configuracoes | None = None,
) -> int:
    titulo_limpo = (titulo or "").strip() or (nome_arquivo or "Documento PDF")
    with obter_conexao(config) as conexao:
        existe = conexao.execute("SELECT id FROM projetos WHERE id = ?", (projeto_id,)).fetchone()
        if not existe:
            raise LookupError("Projeto não encontrado.")

        caminho_rel, tamanho = salvar_pdf(
            conteudo, nome_arquivo, subpasta=f"anexos/{projeto_id}", config=config
        )
        max_ordem = conexao.execute(
            "SELECT COALESCE(MAX(ordem), 0) FROM anexos WHERE projeto_id = ?",
            (projeto_id,),
        ).fetchone()[0]

        agora = agora_iso()
        cur = conexao.execute(
            """
            INSERT INTO anexos (
                projeto_id, titulo, nome_arquivo_original, caminho_arquivo, tamanho_bytes, ordem, criado_em
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                projeto_id,
                titulo_limpo[:160],
                (nome_arquivo or "documento.pdf")[:160],
                caminho_rel,
                tamanho,
                int(max_ordem) + 1,
                agora,
            ),
        )
        conexao.execute(
            "UPDATE projetos SET atualizado_em = ? WHERE id = ?",
            (agora, projeto_id),
        )
        return int(cur.lastrowid)


def remover_anexo_projeto(
    projeto_id: int,
    anexo_id: int,
    config: Configuracoes | None = None,
) -> bool:
    caminho = None
    with obter_conexao(config) as conexao:
        row = conexao.execute(
            "SELECT caminho_arquivo FROM anexos WHERE id = ? AND projeto_id = ?",
            (anexo_id, projeto_id),
        ).fetchone()
        if not row:
            return False
        caminho = row["caminho_arquivo"]
        conexao.execute("DELETE FROM anexos WHERE id = ?", (anexo_id,))
        conexao.execute(
            "UPDATE projetos SET atualizado_em = ? WHERE id = ?",
            (agora_iso(), projeto_id),
        )

    remover_arquivo_midia(caminho, config)
    return True


# ----------------------------------------------------------------------------
# Links externos do projeto
# ----------------------------------------------------------------------------

def adicionar_link_projeto(
    projeto_id: int,
    *,
    rotulo: str,
    url: str,
    tipo: str = "link",
    config: Configuracoes | None = None,
) -> int:
    rotulo_limpo = (rotulo or "").strip()
    if not rotulo_limpo:
        raise ValueError("Informe o rótulo do link (ex.: Repositório GitHub).")
    url_valida = _validar_url_externa(url, obrigatoria=True)
    tipo_final = tipo if tipo in TIPOS_LINK_VALIDOS else "link"

    with obter_conexao(config) as conexao:
        existe = conexao.execute("SELECT id FROM projetos WHERE id = ?", (projeto_id,)).fetchone()
        if not existe:
            raise LookupError("Projeto não encontrado.")
        max_ordem = conexao.execute(
            "SELECT COALESCE(MAX(ordem), 0) FROM links_externos WHERE projeto_id = ?",
            (projeto_id,),
        ).fetchone()[0]
        cur = conexao.execute(
            """
            INSERT INTO links_externos (projeto_id, rotulo, url, tipo, ordem)
            VALUES (?, ?, ?, ?, ?)
            """,
            (projeto_id, rotulo_limpo[:80], url_valida, tipo_final, int(max_ordem) + 1),
        )
        conexao.execute(
            "UPDATE projetos SET atualizado_em = ? WHERE id = ?",
            (agora_iso(), projeto_id),
        )
        return int(cur.lastrowid)


def remover_link_projeto(
    projeto_id: int,
    link_id: int,
    config: Configuracoes | None = None,
) -> bool:
    with obter_conexao(config) as conexao:
        cur = conexao.execute(
            "DELETE FROM links_externos WHERE id = ? AND projeto_id = ?",
            (link_id, projeto_id),
        )
        if cur.rowcount == 0:
            return False
        conexao.execute(
            "UPDATE projetos SET atualizado_em = ? WHERE id = ?",
            (agora_iso(), projeto_id),
        )
    return True


# ----------------------------------------------------------------------------
# Perfil público e aparência
# ----------------------------------------------------------------------------

def atualizar_perfil_admin(
    *,
    nome: str,
    subtitulo: str = "",
    bio: str = "",
    titulo_site: str = "",
    cor_destaque: str = "#3b82f6",
    email: str = "",
    github_url: str = "",
    linkedin_url: str = "",
    nova_foto: tuple[bytes, str] | None = None,
    remover_foto: bool = False,
    novo_curriculo: tuple[bytes, str] | None = None,
    remover_curriculo: bool = False,
    config: Configuracoes | None = None,
) -> None:
    nome_limpo = (nome or "").strip()
    if not nome_limpo:
        raise ValueError("O nome do perfil é obrigatório.")

    cor_limpa = (cor_destaque or "#3b82f6").strip()
    if not REGEX_COR_HEX.match(cor_limpa):
        raise ValueError("Cor de destaque inválida. Use formato hexadecimal como #3b82f6.")

    github_limpo = _validar_url_externa(github_url, obrigatoria=False)
    linkedin_limpo = _validar_url_externa(linkedin_url, obrigatoria=False)

    arquivos_antigos: list[str] = []
    with obter_conexao(config) as conexao:
        atual = dict(conexao.execute("SELECT * FROM perfil WHERE id = 1").fetchone())
        foto_caminho = atual.get("foto_caminho")
        curriculo_caminho = atual.get("curriculo_caminho")

        if remover_foto and foto_caminho:
            arquivos_antigos.append(foto_caminho)
            foto_caminho = None
        if nova_foto is not None:
            caminho_novo = salvar_avatar_perfil(nova_foto[0], nova_foto[1], config=config)
            if foto_caminho:
                arquivos_antigos.append(foto_caminho)
            foto_caminho = caminho_novo

        if remover_curriculo and curriculo_caminho:
            arquivos_antigos.append(curriculo_caminho)
            curriculo_caminho = None
        if novo_curriculo is not None:
            caminho_cv, _ = salvar_pdf(
                novo_curriculo[0], novo_curriculo[1], subpasta="perfil", config=config
            )
            if curriculo_caminho:
                arquivos_antigos.append(curriculo_caminho)
            curriculo_caminho = caminho_cv

        conexao.execute(
            """
            UPDATE perfil
            SET nome = ?, subtitulo = ?, bio = ?, foto_caminho = ?,
                titulo_site = ?, cor_destaque = ?, email = ?,
                github_url = ?, linkedin_url = ?, curriculo_caminho = ?,
                atualizado_em = ?
            WHERE id = 1
            """,
            (
                nome_limpo[:120],
                subtitulo.strip()[:180],
                bio.strip()[:600],
                foto_caminho,
                (titulo_site or "").strip()[:80] or nome_limpo[:80],
                cor_limpa,
                email.strip()[:120],
                github_limpo,
                linkedin_limpo,
                curriculo_caminho,
                agora_iso(),
            ),
        )

    for caminho in arquivos_antigos:
        remover_arquivo_midia(caminho, config)

