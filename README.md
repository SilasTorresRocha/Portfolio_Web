# Portfólio Técnico Self-Hosted (`v1.0.0`)

Aplicação web self-hosted para apresentar projetos de forma visual, direta e profissional — com galeria de fotos em alta definição (zoom tela cheia), leitura em camadas (**Problema → Solução → Resultado** + Markdown), anexos comprobatórios em PDF, painel administrativo `/config`, backup completo com validação criptográfica e relatórios de acesso por e-mail.

Projetado para rodar **via Docker** com persistência centralizada na pasta `dados/`, pronto para operar localmente ou em produção atrás de **Caddy** + **Cloudflare** sem exigir que o usuário edite código após a primeira subida.

---

## Principais Recursos

### Vitrine Pública (`/`) e Página de Projeto (`/projeto/{slug}`)
* **Estética Dark Mode Técnica:** paleta grafite neutra (`#0c0e12`), bordas finas de `1px`, cor de destaque única configurável no painel e tipografia `IBM Plex Sans` + `IBM Plex Mono`.
* **Busca instantânea e tags escaláveis:** filtro em tempo real por texto (sem sensibilidade a acentos, atalho `/`) e tags ordenadas por uso — exibindo até 10 tags inicialmente com expansão sob demanda (`+ N tags`) caso o portfólio cresça.
* **URLs próprias com Open Graph:** cada `/projeto/{slug}` gera automaticamente meta tags `og:title`, `og:description` e `og:image` para prévias ricas ao compartilhar links no LinkedIn, WhatsApp ou e-mail.
* **Galeria com Miniaturas + Lightbox:** navegação por setas/teclado (`←`, `→`, `Esc`), legendas por foto e zoom `100%` para inspecionar placas, esquemáticos, painéis e detalhes técnicos.
* **Leitura em camadas:** resumo curto no card, bloco estruturado **Problema / Solução / Resultado** (opcional) e detalhamento em Markdown sanitizado.
* **Documentos & Comprovantes (PDF):** visualização inline no navegador ou download direto (declarações oficiais, relatórios, esquemáticos), além de suporte opcional a Currículo PDF no cabeçalho.

### Painel Administrativo (`/config`)
* Gerenciamento completo pelo navegador sem refazer deploy: criar, editar, publicar/ocultar como rascunho, destacar, ordenar e excluir projetos.
* **Checklist de clareza em tempo real:** lembra o autor de preencher Capa, Resumo, Problema, Solução, Resultado e Tags sem bloquear projetos mais simples de outras áreas.
* **Editor Markdown amigável:** barra de formatação clicável + pré-visualização renderizada pelo servidor.
* **Upload otimizado de mídias:** drag-and-drop múltiplo com suporte a PNG, JPG, WebP, GIF e **JPEG XL (`.jxl`)**, correção automática de rotação EXIF e conversão para **WebP otimizado** (máx. 1920px) + **miniatura WebP** (720px) para carregamento rápido e compatibilidade universal entre navegadores.
* **Personalização completa:** edição de perfil, links sociais, foto de perfil, currículo PDF e cor de destaque.
* **Compatível com Cloudflare:** mídia local restrita a imagens WebP e documentos PDF leves; vídeos demonstrativos podem ser vinculados por link externo (ex.: YouTube) sem violar termos de proxy CDN.

---

## Arquitetura e Engenharia de Segurança

Este projeto foi construído com práticas de segurança e confiabilidade voltadas para exposição real na internet:

* **Backup & Restauração com Integridade (`SHA-256`) e Autenticidade (`HMAC-SHA256`):**
  * **Snapshot online consistente:** o banco SQLite (em modo `WAL`) é exportado via API nativa `sqlite3.Connection.backup()`, evitando corrupção mesmo com o sistema em uso, seguido de `PRAGMA integrity_check`.
  * **Verificação obrigatória de integridade:** `manifesto.json` registra o hash **SHA-256** de 100% dos arquivos (`banco/portfolio.db` + todas as mídias e PDFs). Qualquer corrupção de 1 bit ou arquivo extra não declarado bloqueia a restauração antes de tocar nos dados atuais.
  * **Assinatura `HMAC-SHA256` não-bloqueante:** o manifesto canônico é assinado com `PORTFOLIO_CHAVE_SECRETA`. Na mesma instância, valida autenticidade automaticamente; ao migrar de servidor ou trocar o `.env`, a integridade SHA-256 + SQLite continua exigida, mas o sistema exibe aviso claro e solicita confirmação explícita para concluir — garantindo segurança sem trancar o proprietário fora do próprio backup.
  * **Proteção contra ataques em arquivos compactados:** validação estrita anti-**Zip Slip** (bloqueio de caminhos absolutos, `..` e symlinks) e anti-**Zip Bomb** (limite de 5.000 arquivos e 500 MB descompactados medidos em tempo real durante a leitura).
  * **Segurança de dados:** `.env` nunca é incluído no `.zip` de backup, e um snapshot automático é gravado em `dados/backups_pre_restore/` antes de aplicar qualquer restauração.
* **Autenticação e Hardening:**
  * Sessão administrativa em cookie `HttpOnly` + `SameSite=Lax` + `Secure` (em HTTPS) assinado com `itsdangerous`.
  * Comparação de senha em tempo constante (`hmac.compare_digest`), proteção **CSRF** por contexto em todas as rotas `POST` e limite de tentativas de login em janela deslizante por IP (`HTTP 429`).
  * **Alerta de força bruta via SMTP** disparado em *background* com *cooldown* anti-spam por IP.
  * **Zero exposição desnecessária:** nenhum link administrativo aparece na vitrine pública; rotas `/config*` usam `noindex, nofollow`; tela de login neutra sem vazar nomes de variáveis do `.env`; e `PORTFOLIO_AMBIENTE=producao` desativa automaticamente `/docs`, `/openapi.json` e detalhes internos de erro em `/saude`.
* **Validação de Uploads e Prevenção de XSS / Path Traversal:**
  * Documentos PDF passam por validação de **magic bytes (`%PDF-`)** além da extensão e limite de tamanho (20 MB).
  * Imagens são decodificadas e re-encodadas do zero em WebP pelo Pillow (removendo metadados/payloads embutidos).
  * Markdown compilado é sanitizado no servidor com **`nh3`**, bloqueando `<script>`, manipuladores de evento e esquemas `javascript:`.
  * Toda leitura/remoção de arquivos em `dados/midias/` valida `Path.resolve().relative_to(...)` contra *path traversal*.
* **Observabilidade, Métricas e Auditoria:**
  * Logs rotativos separados em `dados/logs/aplicacao.log` e `dados/logs/auditoria.log` com suporte configurável a proxy reverso confiável (`CF-Connecting-IP`, `X-Forwarded-For`) e fuso horário via `TZ`.
  * Métricas leves de visitas em projetos, documentos PDF e currículo — ignorando automaticamente o administrador autenticado e `PORTFOLIO_IPS_IGNORADOS`, separando bots/crawlers e enviando **relatório diário automático via SMTP** (com escolha do destinatário direto pelo painel).

---

## Como Subir (Docker — Método Oficial)

> **Requisito:** [Docker](https://docs.docker.com/get-docker/) com Docker Compose.

### 1. Clone o repositório e crie o `.env`
```bash
git clone <url-do-repositorio>
cd <pasta-do-projeto>
cp .env.exemplo .env
```
*(No Windows PowerShell: `Copy-Item .env.exemplo .env`)*

### 2. Configure o `.env`
Edite o arquivo `.env` e defina pelo menos:
* `PORTFOLIO_SENHA_ADMIN`: sua senha forte para o `/config`.
* `PORTFOLIO_CHAVE_SECRETA`: string longa e aleatória (ex.: `python -c "import secrets; print(secrets.token_urlsafe(48))"`).
* *(Opcional)* `SMTP_USUARIO` e `SMTP_SENHA` (no Gmail, use uma **Senha de App**) para alertas de força bruta e relatório diário.

### 3. Suba o container
```bash
docker compose up -d --build
```

* **Vitrine pública:** `http://localhost:8000`
* **Painel administrativo:** acesse diretamente `http://localhost:8000/config`
* **Healthcheck:** `http://localhost:8000/saude`

Todos os dados persistentes ficam na pasta `./dados` mapeada no container:
```text
dados/
├── banco/                # SQLite (portfolio.db)
├── midias/               # Imagens WebP, miniaturas, avatar, currículo e PDFs
├── logs/                 # aplicacao.log e auditoria.log (rotativos)
└── backups_pre_restore/  # Snapshots automáticos antes de restaurações
```

---

## Deploy em Produção (Caddy + Cloudflare)

No `.env` de produção, ajuste:
```env
PORTFOLIO_AMBIENTE=producao
TZ=America/Sao_Paulo
PORTFOLIO_COOKIE_SEGURO=true
PORTFOLIO_CONFIAR_PROXY=true
PORTFOLIO_CABECALHO_IP_PROXY=CF-Connecting-IP,X-Forwarded-For
PORTFOLIO_URL_BASE=https://portfolio.seudominio.com.br
```

Exemplo mínimo de `Caddyfile`:
```caddy
portfolio.seudominio.com.br {
    reverse_proxy 127.0.0.1:8000
}
```

---

## Estrutura do Projeto e Convenções

```text
aplicacao/
├── main.py                # Inicialização FastAPI, middleware HTTP/segurança e agendador diário
├── versao.py              # Fonte única da versão semântica (SemVer) e URL do repositório
├── configuracoes.py       # Leitura e validação de variáveis de ambiente (.env)
├── banco.py               # Conexão SQLite (WAL, foreign_keys) e schema
├── registros.py           # Logs rotativos (aplicação e auditoria) + IP real de proxy
├── autenticacao.py        # Sessão assinada (HttpOnly), CSRF e rate-limit de login
├── rotas/
│   ├── publicas.py        # Vitrine, /projeto/{slug}, /midias, /anexos, /curriculo, /saude
│   └── administracao.py   # Painel /config (projetos, galeria, PDFs, perfil, backup, logs)
├── servicos/
│   ├── catalogo.py        # Consultas públicas e filtros
│   ├── admin_projetos.py  # CRUD administrativo e checklist de completude
│   ├── midias.py          # Otimização WebP/miniaturas, suporte .jxl e magic bytes PDF
│   ├── arquivos.py        # Resolução segura de caminhos anti-path traversal
│   ├── markdown_seguro.py # Compilação Markdown + sanitização HTML (nh3)
│   ├── backup.py          # Backup/Restore .zip (SHA-256, HMAC, ZipSlip/ZipBomb)
│   ├── notificacoes.py    # Envio SMTP, destino configurável e alerta força bruta
│   └── metricas.py        # Registro de acessos, filtro de dono/bots e relatório diário
├── estaticos/             # CSS autoral dark mode técnico + JS enxuto
└── templates/             # Templates Jinja2
testes/
└── executar_testes.py     # Suíte automatizada isolada (não altera dados/)
```

### Versionamento Semântico
A versão da aplicação fica centralizada em [aplicacao/versao.py](aplicacao/versao.py) (`VERSAO` e `REPOSITORIO_URL`) e é refletida automaticamente no rodapé do site, no `/saude`, no `/config` e nos logs. Consulte o histórico completo em [CHANGELOG.md](CHANGELOG.md) e as diretrizes de design em [PrincipioProjeto.md](PrincipioProjeto.md).

---

## Testes Automatizados

Para executar a suíte completa de validação (em diretório temporário isolado, sem afetar seus dados em `dados/`):
```bash
python testes/executar_testes.py
```

No Windows, para zerar completamente os dados locais em `dados/` preservando o `.env` (útil para testar restauração de backup do zero), utilize o utilitário interativo `reset.bat`.
