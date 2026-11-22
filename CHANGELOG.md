# Histórico de Versões (Changelog)

Este projeto segue [Versionamento Semântico (SemVer)](https://semver.org/lang/pt-BR/).
A versão ativa é centralizada em `aplicacao/versao.py`.

## [1.0.2] — Atualização do link do repositório
* **Rodapé e metadados:** atualizado `REPOSITORIO_URL` em `aplicacao/versao.py` para `https://github.com/SilasTorresRocha/Portfolio_Web`.

## [1.0.1] — Otimizações de Baixo I/O para SDCard / Orange Pi
* **SQLite otimizado para flash/SDCard:** `PRAGMA synchronous = NORMAL` e `PRAGMA temp_store = MEMORY` por conexão mantendo `journal_mode = WAL` persistente ativado na inicialização.
* **Buffer de métricas em RAM:** visitas públicas acumuladas em memória e gravadas em lote (1 única transação) a cada 60s, a cada 30 eventos, sob demanda ao consultar relatórios ou no encerramento do container.
* **Logs mais enxutos em disco:** `GET /midias/*` com status `< 400` silenciado no `aplicacao.log` (erros e tentativas inválidas continuam registrados, assim como toda a trilha `auditoria.log`).
* **Rotação de log do Docker:** limite `max-size: 5m` e `max-file: 2` no `docker-compose.yml`.

## [1.0.0] — Lançamento Inicial Consolidado
* **Vitrine escalável:** limite inicial de 10 tags mais usadas com botão expansível (`+ N tags` / `Mostrar menos`) mantendo a tag filtrada sempre visível.
* **Generalização completa:** placeholders e perfil inicial tornados 100% agnósticos para uso por qualquer área profissional.
* **Versão clicável no rodapé:** exibição discreta da versão atual apontando para o repositório no GitHub (centralizada em `aplicacao/versao.py`).
* **Hardening de produção:** ocultação de links administrativos nas páginas públicas, tela de login neutra (`noindex, nofollow`), desativação de `/docs` e `/openapi.json` em `PORTFOLIO_AMBIENTE=producao`, e supressão de detalhes internos de erro no `/saude`.
* **Documentação & Testes:** `README.md` completo (Docker, Caddy/Cloudflare, arquitetura de segurança), `reset.bat` interativo e suíte de testes isolada em `testes/executar_testes.py`.

## [0.3.5] — Backup Criptográfico, Notificações SMTP e Métricas
* Sistema de Backup e Restauração `.zip` com snapshot online SQLite WAL, `PRAGMA integrity_check`, validação `SHA-256` por arquivo, assinatura `HMAC-SHA256` com confirmação não-bloqueante para troca de chave, proteção anti-Zip Slip/Zip Bomb e snapshot pré-restore.
* Alertas SMTP de força bruta em background com cooldown anti-spam por IP.
* Registro de acessos externos (projetos, anexos PDF e currículo) ignorando administrador autenticado e `PORTFOLIO_IPS_IGNORADOS`, separando bots, com relatório diário automático e seletor de destinatário no painel.

## [0.3.0] — Painel Administrativo `/config` Completo
* CRUD de projetos com checklist de clareza em tempo real (`Problema / Solução / Resultado`), editor Markdown com barra de formatação e pré-visualização sanitizada.
* Upload múltiplo drag-and-drop com conversão automática para WebP + miniaturas (incluindo suporte de entrada a JPEG XL `.jxl`), legendas, ordenação e definição de capa.
* Gestão de anexos PDF (validação por magic bytes `%PDF-`), links externos, perfil público, currículo PDF e cor de destaque.

## [0.2.0] — Vitrine Pública e Página Dedicada `/projeto/{slug}`
* Visual dark mode técnico autoral (IBM Plex Sans + Mono, bordas `1px`, ícones SVG minimalistas).
* Busca instantânea, filtro por tags, galeria com miniaturas e Lightbox em tela cheia com zoom `100%`, meta tags Open Graph, Markdown sanitizado com `nh3` e downloads seguros anti-path traversal.
* Fuso horário configurável (`TZ=America/Sao_Paulo`) e logs limpos sem ruído do healthcheck `/saude`.

## [0.1.0] — Fundação, Banco SQLite, Logs, Auth e Docker
* Estrutura base FastAPI, schema SQLite em modo WAL, logs rotativos (`aplicacao.log` e `auditoria.log`), autenticação por cookie `HttpOnly` assinado, CSRF, rate-limit de login, `.env.exemplo`, `.gitignore` e `Dockerfile`/`docker-compose.yml`.

