/* ==========================================================================
   Portfólio Técnico — Interações leves da Vitrine e Galeria com Lightbox
   ========================================================================== */

(function () {
  "use strict";

  function normalizarTexto(texto) {
    return (texto || "")
      .normalize("NFKD")
      .replace(/[\u0300-\u036f]/g, "")
      .toLowerCase()
      .trim();
  }

  /* ------------------------------------------------------------------------
     1. Filtro instantâneo na Vitrine (busca + tags clicáveis)
     ------------------------------------------------------------------------ */
  function iniciarVitrine() {
    const campoBusca = document.getElementById("campo-busca");
    const botaoLimpar = document.getElementById("botao-limpar-busca");
    const contador = document.getElementById("contador-projetos");
    const grade = document.getElementById("grade-projetos");
    const estadoSemResultado = document.getElementById("estado-sem-resultado");
    const botaoResetFiltros = document.getElementById("botao-reset-filtros");
    const botoesTag = Array.from(document.querySelectorAll("[data-filtro-tag]"));
    const botaoExpandirTags = document.getElementById("botao-expandir-tags");
    const tagsExtras = Array.from(document.querySelectorAll("[data-tag-extra='1']"));

    if (!grade) return;

    if (botaoExpandirTags && tagsExtras.length > 0) {
      const qtdExtras = botaoExpandirTags.dataset.qtdExtras || String(tagsExtras.length);
      botaoExpandirTags.addEventListener("click", () => {
        const expandido = botaoExpandirTags.dataset.expandido === "1";
        const novoEstado = !expandido;
        botaoExpandirTags.dataset.expandido = novoEstado ? "1" : "0";
        tagsExtras.forEach((el) => {
          const slug = (el.dataset.filtroTag || "").toLowerCase();
          el.hidden = !novoEstado && slug !== tagAtiva;
        });
        botaoExpandirTags.textContent = novoEstado ? "Mostrar menos" : `+ ${qtdExtras} tags`;
      });
    }

    const cartoes = Array.from(grade.querySelectorAll(".cartao-projeto"));
    if (cartoes.length === 0) return;

    let tagAtiva = (grade.dataset.tagInicial || "").trim().toLowerCase();

    function atualizarEstadoUrl(termo, tag) {
      if (!window.history || !window.history.replaceState) return;
      const params = new URLSearchParams();
      if (termo) params.set("q", termo);
      if (tag) params.set("tag", tag);
      const novaUrl = params.toString() ? `/?${params.toString()}` : "/";
      window.history.replaceState(null, "", novaUrl);
    }

    function aplicarFiltros() {
      const termoBruto = campoBusca ? campoBusca.value.trim() : "";
      const termo = normalizarTexto(termoBruto);
      let visiveis = 0;

      cartoes.forEach((cartao) => {
        const textoBusca = cartao.dataset.busca || "";
        const tagsCartao = (cartao.dataset.tags || "").split(",").filter(Boolean);

        const bateBusca = !termo || textoBusca.includes(termo);
        const bateTag = !tagAtiva || tagsCartao.includes(tagAtiva);
        const mostrar = bateBusca && bateTag;

        cartao.hidden = !mostrar;
        if (mostrar) visiveis += 1;
      });

      if (botaoLimpar) {
        botaoLimpar.hidden = termoBruto.length === 0;
      }

      if (contador) {
        const total = cartoes.length;
        const label = total === 1 ? "projeto" : "projetos";
        contador.textContent =
          visiveis === total
            ? `${String(total).padStart(2, "0")} ${label}`
            : `${String(visiveis).padStart(2, "0")} / ${String(total).padStart(2, "0")} exibidos`;
      }

      if (estadoSemResultado) {
        estadoSemResultado.hidden = visiveis > 0;
      }

      botoesTag.forEach((btn) => {
        const slug = (btn.dataset.filtroTag || "").toLowerCase();
        btn.classList.toggle("ativa", slug === tagAtiva);
        btn.setAttribute("aria-pressed", slug === tagAtiva ? "true" : "false");
      });

      atualizarEstadoUrl(termoBruto, tagAtiva);
    }

    if (campoBusca) {
      campoBusca.addEventListener("input", aplicarFiltros);
    }

    if (botaoLimpar && campoBusca) {
      botaoLimpar.addEventListener("click", () => {
        campoBusca.value = "";
        aplicarFiltros();
        campoBusca.focus();
      });
    }

    botoesTag.forEach((btn) => {
      btn.addEventListener("click", (evento) => {
        evento.preventDefault();
        const slug = (btn.dataset.filtroTag || "").toLowerCase();
        tagAtiva = slug === tagAtiva && slug !== "" ? "" : slug;
        aplicarFiltros();
      });
    });

    if (botaoResetFiltros) {
      botaoResetFiltros.addEventListener("click", () => {
        if (campoBusca) campoBusca.value = "";
        tagAtiva = "";
        aplicarFiltros();
      });
    }

    // Atalho "/" para focar busca (estilo GitHub/Linear)
    document.addEventListener("keydown", (evento) => {
      if (
        evento.key === "/" &&
        campoBusca &&
        document.activeElement !== campoBusca &&
        !["INPUT", "TEXTAREA"].includes(document.activeElement?.tagName || "")
      ) {
        evento.preventDefault();
        campoBusca.focus();
      }
    });

    aplicarFiltros();
  }

  /* ------------------------------------------------------------------------
     2. Galeria com Miniaturas + Lightbox (Zoom Tela Cheia)
     ------------------------------------------------------------------------ */
  function iniciarGaleria() {
    const containerGaleria = document.getElementById("galeria-projeto");
    if (!containerGaleria) return;

    const dadosEl = document.getElementById("dados-galeria");
    if (!dadosEl) return;

    let itens = [];
    try {
      itens = JSON.parse(dadosEl.textContent || "[]");
    } catch {
      return;
    }
    if (!Array.isArray(itens) || itens.length === 0) return;

    const imgPrincipal = document.getElementById("galeria-imagem-ativa");
    const palco = document.getElementById("galeria-palco");
    const contadorEl = document.getElementById("galeria-contador");
    const legendaEl = document.getElementById("galeria-legenda");
    const btnAnt = document.getElementById("galeria-ant");
    const btnProx = document.getElementById("galeria-prox");
    const btnExpandir = document.getElementById("galeria-expandir");
    const miniaturas = Array.from(containerGaleria.querySelectorAll(".galeria-miniatura"));

    const lightbox = document.getElementById("lightbox");
    const lbImg = document.getElementById("lightbox-imagem");
    const lbContador = document.getElementById("lightbox-contador");
    const lbLegenda = document.getElementById("lightbox-legenda");
    const lbFechar = document.getElementById("lightbox-fechar");
    const lbZoom = document.getElementById("lightbox-zoom");
    const lbAnt = document.getElementById("lightbox-ant");
    const lbProx = document.getElementById("lightbox-prox");

    let indiceAtual = 0;

    function formatarContador(idx) {
      const a = String(idx + 1).padStart(2, "0");
      const b = String(itens.length).padStart(2, "0");
      return `${a} / ${b}`;
    }

    function atualizarGaleria(novoIndice) {
      indiceAtual = (novoIndice + itens.length) % itens.length;
      const item = itens[indiceAtual];
      const textoContador = formatarContador(indiceAtual);

      if (imgPrincipal) {
        imgPrincipal.src = item.original;
        imgPrincipal.alt = item.legenda || "Imagem do projeto";
      }
      if (contadorEl) contadorEl.textContent = textoContador;
      if (legendaEl) {
        legendaEl.textContent = item.legenda || "Clique na imagem para ampliar em tela cheia.";
      }

      miniaturas.forEach((btn, idx) => {
        const ativa = idx === indiceAtual;
        btn.classList.toggle("ativa", ativa);
        btn.setAttribute("aria-current", ativa ? "true" : "false");
      });

      if (lightbox && !lightbox.hidden) {
        atualizarLightbox();
      }
    }

    function atualizarLightbox() {
      const item = itens[indiceAtual];
      if (lbImg) {
        lbImg.src = item.original;
        lbImg.alt = item.legenda || "Imagem ampliada";
        lbImg.classList.remove("ampliada");
      }
      if (lbContador) lbContador.textContent = formatarContador(indiceAtual);
      if (lbLegenda) lbLegenda.textContent = item.legenda || "";
      if (lbZoom) lbZoom.textContent = "Ampliar 100%";
    }

    function abrirLightbox() {
      if (!lightbox) return;
      atualizarLightbox();
      lightbox.hidden = false;
      document.body.classList.add("sem-rolagem");
    }

    function fecharLightbox() {
      if (!lightbox) return;
      lightbox.hidden = true;
      document.body.classList.remove("sem-rolagem");
    }

    function alternarZoom() {
      if (!lbImg) return;
      const ampliada = lbImg.classList.toggle("ampliada");
      if (lbZoom) lbZoom.textContent = ampliada ? "Ajustar à tela" : "Ampliar 100%";
    }

    miniaturas.forEach((btn, idx) => {
      btn.addEventListener("click", () => atualizarGaleria(idx));
    });

    if (btnAnt) {
      btnAnt.addEventListener("click", (e) => {
        e.stopPropagation();
        atualizarGaleria(indiceAtual - 1);
      });
    }

    if (btnProx) {
      btnProx.addEventListener("click", (e) => {
        e.stopPropagation();
        atualizarGaleria(indiceAtual + 1);
      });
    }

    if (palco) {
      palco.addEventListener("click", abrirLightbox);
    }

    if (btnExpandir) {
      btnExpandir.addEventListener("click", abrirLightbox);
    }

    if (lbFechar) lbFechar.addEventListener("click", fecharLightbox);
    if (lbZoom) lbZoom.addEventListener("click", alternarZoom);
    if (lbImg) lbImg.addEventListener("click", alternarZoom);
    if (lbAnt) lbAnt.addEventListener("click", () => atualizarGaleria(indiceAtual - 1));
    if (lbProx) lbProx.addEventListener("click", () => atualizarGaleria(indiceAtual + 1));

    if (lightbox) {
      lightbox.addEventListener("click", (evento) => {
        if (evento.target === lightbox) fecharLightbox();
      });
    }

    document.addEventListener("keydown", (evento) => {
      if (!lightbox || lightbox.hidden) return;
      if (evento.key === "Escape") fecharLightbox();
      if (evento.key === "ArrowLeft") atualizarGaleria(indiceAtual - 1);
      if (evento.key === "ArrowRight") atualizarGaleria(indiceAtual + 1);
    });
  }

  document.addEventListener("DOMContentLoaded", () => {
    iniciarVitrine();
    iniciarGaleria();
  });
})();

