/* ==========================================================================
   Painel /config — Checklist ao vivo, editor Markdown, drag-and-drop e cor
   ========================================================================== */

(function () {
  "use strict";

  /* 1. Checklist discreto de completude + contador de resumo */
  function iniciarChecklist() {
    const form = document.getElementById("form-projeto");
    if (!form) return;

    const campoResumo = document.getElementById("campo-resumo");
    const contadorResumo = document.getElementById("contador-resumo");
    const campoProblema = document.getElementById("campo-problema");
    const campoSolucao = document.getElementById("campo-solucao");
    const campoResultado = document.getElementById("campo-resultado");
    const campoTags = document.getElementById("campo-tags");
    const barraProgresso = document.getElementById("checklist-progresso");
    const resumoChecklist = document.getElementById("checklist-contagem");

    const temCapa = form.dataset.temCapa === "1";

    function marcarItem(chave, ok) {
      const el = document.querySelector(`[data-check-item="${chave}"]`);
      if (!el) return;
      el.classList.toggle("ok", ok);
      const indicador = el.querySelector(".check-indicador");
      if (indicador) indicador.textContent = ok ? "OK" : "--";
    }

    function atualizar() {
      const estados = {
        capa: temCapa,
        resumo: Boolean(campoResumo && campoResumo.value.trim().length > 0),
        problema: Boolean(campoProblema && campoProblema.value.trim().length > 0),
        solucao: Boolean(campoSolucao && campoSolucao.value.trim().length > 0),
        resultado: Boolean(campoResultado && campoResultado.value.trim().length > 0),
        tags: Boolean(campoTags && campoTags.value.trim().length > 0),
      };

      let totalOk = 0;
      const total = Object.keys(estados).length;
      Object.entries(estados).forEach(([chave, ok]) => {
        marcarItem(chave, ok);
        if (ok) totalOk += 1;
      });

      if (resumoChecklist) {
        resumoChecklist.textContent = `${totalOk} / ${total}`;
      }
      if (barraProgresso) {
        barraProgresso.style.width = `${Math.round((totalOk / total) * 100)}%`;
      }
      if (campoResumo && contadorResumo) {
        const len = campoResumo.value.trim().length;
        contadorResumo.textContent = `${len} / 160 recomendados`;
        contadorResumo.classList.toggle("alerta-limite", len > 180);
      }
    }

    [campoResumo, campoProblema, campoSolucao, campoResultado, campoTags].forEach((campo) => {
      if (campo) campo.addEventListener("input", atualizar);
    });

    // Pílulas de tags existentes: clique adiciona ao campo sem duplicar
    document.querySelectorAll("[data-sugestao-tag]").forEach((btn) => {
      btn.addEventListener("click", () => {
        if (!campoTags) return;
        const nomeTag = (btn.dataset.sugestaoTag || "").trim();
        if (!nomeTag) return;
        const atuais = campoTags.value
          .split(",")
          .map((t) => t.trim())
          .filter(Boolean);
        const jaExiste = atuais.some((t) => t.toLowerCase() === nomeTag.toLowerCase());
        if (!jaExiste) {
          atuais.push(nomeTag);
          campoTags.value = atuais.join(", ");
          atualizar();
        }
      });
    });

    atualizar();
  }

  /* 2. Editor Markdown com barra simples + pré-visualização via servidor */
  function iniciarEditorMarkdown() {
    const textarea = document.getElementById("campo-markdown");
    const previewBox = document.getElementById("markdown-preview");
    const btnEscrever = document.getElementById("tab-md-escrever");
    const btnPreview = document.getElementById("tab-md-preview");
    const csrfInput = document.querySelector('#form-projeto input[name="csrf_token"]');

    if (!textarea) return;

    function inserirTrecho(antes, depois, padrao) {
      const inicio = textarea.selectionStart;
      const fim = textarea.selectionEnd;
      const selecionado = textarea.value.slice(inicio, fim) || padrao;
      const novoTexto =
        textarea.value.slice(0, inicio) + antes + selecionado + depois + textarea.value.slice(fim);
      textarea.value = novoTexto;
      textarea.focus();
      const posInicio = inicio + antes.length;
      textarea.setSelectionRange(posInicio, posInicio + selecionado.length);
    }

    const acoes = {
      h2: () => inserirTrecho("## ", "\n", "Seção técnica"),
      h3: () => inserirTrecho("### ", "\n", "Subseção"),
      negrito: () => inserirTrecho("**", "**", "texto em destaque"),
      italico: () => inserirTrecho("*", "*", "ênfase"),
      lista: () => inserirTrecho("- ", "\n- ", "Item técnico"),
      codigo: () => inserirTrecho("`", "`", "termo-tecnico"),
      bloco: () => inserirTrecho("```\n", "\n```\n", "// código ou comando"),
      citacao: () => inserirTrecho("> ", "\n", "Observação importante"),
      link: () => inserirTrecho("[", "](https://)", "Texto do link"),
      tabela: () =>
        inserirTrecho(
          "| Item | Especificação |\n| --- | --- |\n| ",
          " | Valor |\n",
          "Parâmetro"
        ),
    };

    document.querySelectorAll("[data-md-acao]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const acao = btn.dataset.mdAcao;
        if (acao && acoes[acao]) {
          if (previewBox && !previewBox.hidden) {
            mostrarModoEscrever();
          }
          acoes[acao]();
        }
      });
    });

    function mostrarModoEscrever() {
      textarea.hidden = false;
      if (previewBox) previewBox.hidden = true;
      if (btnEscrever) btnEscrever.classList.add("ativa");
      if (btnPreview) btnPreview.classList.remove("ativa");
    }

    async function mostrarModoPreview() {
      if (!previewBox) return;
      textarea.hidden = true;
      previewBox.hidden = false;
      if (btnEscrever) btnEscrever.classList.remove("ativa");
      if (btnPreview) btnPreview.classList.add("ativa");

      if (!textarea.value.trim()) {
        previewBox.innerHTML = '<p class="texto-vazio-preview">Nenhum texto Markdown digitado ainda.</p>';
        return;
      }

      previewBox.innerHTML = '<p class="texto-vazio-preview">Renderizando pré-visualização...</p>';
      try {
        const dados = new FormData();
        dados.append("texto", textarea.value);
        dados.append("csrf_token", csrfInput ? csrfInput.value : "");

        const resp = await fetch("/config/api/preview-markdown", {
          method: "POST",
          body: dados,
          credentials: "same-origin",
        });
        if (!resp.ok) throw new Error("Falha ao renderizar");
        const json = await resp.json();
        previewBox.innerHTML = json.html || '<p class="texto-vazio-preview">Sem conteúdo.</p>';
      } catch {
        previewBox.innerHTML =
          '<p class="texto-vazio-preview">Não foi possível gerar a pré-visualização agora.</p>';
      }
    }

    if (btnEscrever) btnEscrever.addEventListener("click", mostrarModoEscrever);
    if (btnPreview) btnPreview.addEventListener("click", mostrarModoPreview);
  }

  /* 3. Drag-and-drop para upload múltiplo de fotos */
  function iniciarDropzone() {
    const zona = document.getElementById("zona-upload-midias");
    const input = document.getElementById("input-upload-midias");
    const info = document.getElementById("info-arquivos-selecionados");

    if (!zona || !input) return;

    function atualizarLista(files) {
      if (!info) return;
      if (!files || files.length === 0) {
        info.textContent = "PNG, JPG, WebP, GIF ou JXL · até 15 MB por imagem";
        return;
      }
      const nomes = Array.from(files).map((f) => f.name);
      info.textContent = `${files.length} arquivo(s) selecionado(s): ${nomes.slice(0, 3).join(", ")}${
        nomes.length > 3 ? ` +${nomes.length - 3}` : ""
      }`;
    }

    input.addEventListener("change", () => atualizarLista(input.files));

    ["dragenter", "dragover"].forEach((ev) => {
      zona.addEventListener(ev, (e) => {
        e.preventDefault();
        zona.classList.add("arrastando");
      });
    });

    ["dragleave", "drop"].forEach((ev) => {
      zona.addEventListener(ev, (e) => {
        e.preventDefault();
        zona.classList.remove("arrastando");
      });
    });

    zona.addEventListener("drop", (e) => {
      const files = e.dataTransfer?.files;
      if (files && files.length > 0) {
        input.files = files;
        atualizarLista(files);
      }
    });
  }

  /* 4. Sincronização de cor de destaque em Perfil & Aparência */
  function iniciarSeletorCor() {
    const picker = document.getElementById("input-cor-picker");
    const texto = document.getElementById("input-cor-texto");
    if (!picker || !texto) return;

    function aplicar(hex) {
      if (!/^#[0-9a-fA-F]{6}$/.test(hex)) return;
      picker.value = hex;
      texto.value = hex;
      document.documentElement.style.setProperty("--cor-destaque", hex);
      document.querySelectorAll("[data-preset-cor]").forEach((b) => {
        b.classList.toggle("ativa", b.dataset.presetCor.toLowerCase() === hex.toLowerCase());
      });
    }

    picker.addEventListener("input", () => aplicar(picker.value));
    texto.addEventListener("input", () => aplicar(texto.value.trim()));
    document.querySelectorAll("[data-preset-cor]").forEach((btn) => {
      btn.addEventListener("click", () => aplicar(btn.dataset.presetCor));
    });
  }

  document.addEventListener("DOMContentLoaded", () => {
    iniciarChecklist();
    iniciarEditorMarkdown();
    iniciarDropzone();
    iniciarSeletorCor();
  });
})();

