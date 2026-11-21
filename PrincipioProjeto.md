# Princípios do Projeto — Portfólio Técnico Self-Hosted

Este documento define as diretrizes de design, experiência de uso, arquitetura, segurança e organização de código que norteiam este projeto. Toda nova funcionalidade ou ajuste visual deve respeitar estes princípios.

---

## 1. Propósito e Público-Alvo

* **Uso imediato:** Apresentar projetos técnicos (hardware, eletrônica, IoT, redes, infraestrutura e software) de forma visual, direta e escaneável para recrutadores, engenheiros e avaliadores técnicos.
* **Uso futuro (código aberto / genérico):** Qualquer pessoa — mesmo fora da área de tecnologia — deve conseguir subir a aplicação e gerenciar todo o conteúdo, perfil e aparência diretamente pelo painel `/config`, sem precisar editar código nem refazer deploy após a primeira subida.
* **Princípio de leitura rápida:** Ninguém lê paredões de texto logo de cara. A interface prioriza impacto visual (fotos reais), leitura em camadas (resumo → contexto rápido → detalhes técnicos sob demanda) e comprovação documental.

---

## 2. Identidade Visual — Dark Mode Técnico (Sem "Cara de IA")

A interface deve parecer uma ferramenta/catálogo de engenharia real (referências: Linear, GitHub, Vercel, documentação técnica e datasheets industriais), evitando deliberadamente clichês comuns de templates gerados por IA.

### O que EVITAR
* Degradês roxo/azul/ciano neon em fundos, botões ou títulos.
* Brilhos artificiais (*glow*), sombras coloridas e efeito *glassmorphism* exagerado.
* Emojis espalhados na interface (`🚀`, `✨`, `🔥`, `💡`) em títulos, menus ou botões.
* Textos genéricos de marketing inflado.
* Animações exageradas ou cards que "pulam" demais ao passar o mouse.

### O que SEGUIR
* **Paleta grafite/carvão neutra:**
  * Fundo principal escuro fosco (`#0c0e12`).
  * Superfícies em camadas sutis (`#14171d` e `#1b1f27`).
  * Bordas finas de `1px` bem definidas (`#262b35`).
  * Texto principal branco suave (`#eceff4`) e secundário cinza técnico (`#8b949e`), garantindo alto contraste sem cansar a vista.
* **Uma única cor de destaque contida (sem degradê):**
  * Padrão inicial em azul técnico/industrial sóbrio, configurável pelo `/config` para adaptar o portfólio a outras áreas ou identidades.
* **Tipografia de engenharia:**
  * Fonte sem serifa limpa para leitura (`IBM Plex Sans` ou `Inter`).
  * Fonte monoespaçada (`IBM Plex Mono` ou `JetBrains Mono`) aplicada com critério em metadados: tags, datas, status (`EM PRODUÇÃO`), contadores de galeria (`02 / 06`) e tamanho de arquivos (`PDF · 142 KB`).
* **Ícones limpos:** Apenas ícones SVG minimalistas de traço fino (sem emojis na UI).
* **Protagonismo para as mídias:** O fundo escuro neutro existe para destacar fotos de PCBs, painéis elétricos, telas, protótipos e diagramas.
* **Transições discretas:** Microinterações rápidas e contidas (`150ms`), priorizando resposta imediata e clareza.

---

## 3. Experiência de Navegação e Estrutura de Conteúdo

### Vitrine Principal (`/`)
* **Cabeçalho enxuto e editável no `/config`:** Foto/avatar, nome, subtítulo curto, breve apresentação e links rápidos (GitHub, LinkedIn, e-mail, currículo PDF, etc.).
* **Busca e filtros leves:** Barra de busca instantânea (lupa) combinada com filtro por tags clicáveis.
* **Grade responsiva de cards:** Fácil de escanear no desktop e no celular, exibindo apenas:
  * Foto de capa em destaque.
  * Selo/status opcional (ex.: `EM PRODUÇÃO`, `HARDWARE`).
  * Título e resumo curto (1–2 linhas).
  * Tags associadas.

### Página Dedicada do Projeto (`/projeto/{slug}`)
* **URL própria e compartilhável:** Permite enviar o link direto de um projeto específico em currículos, e-mails ou LinkedIn.
* **Pré-visualização rica (Open Graph):** Cada página gera automaticamente meta tags (`og:title`, `og:description`, `og:image`) com os dados e a capa daquele projeto.
* **Galeria com miniaturas + Lightbox (zoom em tela cheia):**
  * Foto principal grande acompanhada de miniaturas clicáveis abaixo e legenda individual por imagem.
  * Clique na foto abre visualização em tela cheia com navegação por setas/teclado, ideal para inspecionar placas, esquemáticos e detalhes técnicos.
* **Leitura em camadas (escaneável primeiro, profundo se quiser):**
  1. **Resumo curto** (mesmo contexto rápido do card).
  2. **Bloco estruturado opcional:** **Problema / Contexto**, **Solução** e **Resultado / Impacto**.
  3. **Descrição detalhada em Markdown:** Compilado e sanitizado no servidor, com barra simples de formatação e pré-visualização no `/config` para atender tanto usuários técnicos quanto leigos.
* **Evidências, Links e Comprovantes:**
  * Links externos (repositório GitHub, sistema em produção, vídeo no YouTube, etc.).
  * Seção **"Documentos & Comprovantes"** para anexos PDF (declarações oficiais, esquemáticos, relatórios), com título amigável, tamanho do arquivo e botões para **Visualizar** e **Baixar**.

---

## 4. Mídias, Desempenho e Compatibilidade com Cloudflare

* **Imagens hospedadas localmente (`dados/midias/`):** Formatos PNG, JPG e WebP com otimização/redimensionamento automático no upload (Pillow) e geração de miniaturas para carregamento rápido nos cards, mantendo alta qualidade no zoom.
* **Anexos PDF hospedados localmente (`dados/midias/`):** Documentos leves de comprovação e documentação técnica servidos com cabeçalhos seguros.
* **Vídeos (fora do servidor local na V1):** Para respeitar os termos de uso do proxy gratuito da Cloudflare (e economizar banda/armazenamento em self-hosting), não hospedaremos streaming de vídeo `.mp4` na V1. Caso o projeto possua vídeo demonstrativo, ele deve ser vinculado via link externo (ex.: YouTube, inclusive em modo "Não listado").

---

## 5. Painel Administrativo (`/config`)

Todo o gerenciamento ocorre pela interface web após a aplicação estar rodando:

* **Autenticação baseada no `.env`:** Senha configurada por variável de ambiente, sessão em cookie `HttpOnly` assinado e limite de tentativas de login (proteção básica contra força bruta).
* **Gestão de Projetos:** Criar, editar, publicar/deixar como rascunho, ordenar (destacar projetos prioritários) e excluir.
* **Lembrete de Completude (não bloqueante):** Ao criar/editar um projeto, o formulário exibe campos dedicados com placeholders orientativos para **Problema**, **Solução** e **Resultado**, além de um indicador discreto de preenchimento (`Capa`, `Resumo`, `Problema/Solução/Resultado`, `Tags`). O objetivo é lembrar o autor sem impedir o salvamento de projetos mais simples ou de outras áreas.
* **Gestão de Galeria e Anexos:** Upload múltiplo (arrastar e soltar), definição da imagem de capa, reordenação, edição de legendas e remoção de imagens/PDFs.
* **Perfil & Aparência:** Edição dos dados do cabeçalho, links sociais, título do site e cor de destaque.
* **Auditoria / Logs:** Visualização rápida dos registros recentes diretamente no `/config`.

---

## 6. Arquitetura, Persistência, Segurança e Convenções

### Stack Tecnológica
* **Backend:** Python + FastAPI + Uvicorn.
* **Banco de Dados:** SQLite (arquivo único, sem servidor externo, simples para self-hosting e deploys gratuitos).
* **Frontend:** Templates HTML (Jinja2) + CSS próprio/organizado + JavaScript enxuto (sem etapa de build pesada em Node.js).
* **Empacotamento:** Docker (`Dockerfile` + `docker-compose.yml`), pronto para rodar local e atrás de proxy reverso (**Caddy** / **Cloudflare**).

### Persistência de Dados (`dados/`)
Todos os arquivos persistentes ficam concentrados em uma única pasta mapeada via volume Docker (`./dados:/app/dados`):

```text
dados/
├── .gitkeep
├── banco/        # Banco SQLite (portfolio.db)
│   └── .gitkeep
├── midias/       # Imagens otimizadas, miniaturas e anexos PDF
│   └── .gitkeep
└── logs/         # Logs rotativos de acesso, auditoria (/config) e erros
    └── .gitkeep
```

* `.gitignore` ignora `.env` e todo o conteúdo gerado em `dados/**`, mantendo versionados apenas os arquivos `.gitkeep` e `.env.exemplo`.

### Segurança e Logs
* Logs rotativos registrando acessos relevantes, tentativas de login, ações administrativas (criar/editar/excluir) e erros.
* Suporte configurável via `.env` para captura do IP real quando atrás de proxy reverso confiável (`CF-Connecting-IP` / `X-Forwarded-For` no Caddy/Cloudflare).
* Validação rigorosa de tipos/tamanhos de arquivo no upload, prevenção de *path traversal* ao servir mídias e sanitização do HTML gerado a partir do Markdown (prevenção de XSS).

### Convenção de Nomenclatura
* **Pastas, arquivos, funções e variáveis preferencialmente em português** (ex.: `rotas/`, `modelos.py`, `banco.py`, `servicos/`, `salvar_imagem`, `listar_projetos`).
* **Exceções naturais em inglês** quando o termo já é padrão técnico consolidado no contexto (ex.: `main.py`, `slug`, `payload`, `offset`, `engine`, `Dockerfile`, `docker-compose.yml`).

