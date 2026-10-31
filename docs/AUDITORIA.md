# Guia de auditoria — AI Bridge

Este documento orienta uma auditoria independente do repositório. Ele descreve o
escopo, como executar, o que verificar e quais limitações são **conhecidas e aceitas**
(não são bugs a redescobrir).

## Escopo da entrega

O AI Bridge é um proxy local (`127.0.0.1`) que conecta clientes (Claude Code,
Claude Desktop e Codex Desktop) a provedores de IA. Ele fala o protocolo do cliente
(Anthropic Messages, OpenAI Chat Completions ou OpenAI Responses) e autentica no
provedor de três formas:

1. **API key** no keyring do sistema operacional;
2. **variável de ambiente** (`env_key`, estilo DeepSeek Harness);
3. **OAuth**: reaproveita a sessão gravada pela CLI (`codex`, `claude`, `gemini`,
   `gcloud`, `hf`, `wrangler`, `gh`) e a renova no mesmo endpoint/client que a CLI,
   gravando de volta; se não houver sessão, faz login PKCE próprio com callback local
   na URL registrada do client.

Além disso: descoberta automática de modelos (`GET /models`, `/api/tags`),
filtro de gratuitos, importação de provedores do perfil do DeepSeek Harness,
catálogo unificado para o Codex e interface desktop (pywebview) em dois passos.

## Como executar

```bash
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt     # Windows
.venv\Scripts\python -m pytest tests -q           # 163 testes, sem rede
.venv\Scripts\python entry.py                     # abre a interface
```

CI (GitHub Actions): `.github/workflows/ci.yml` roda lint + testes;
`.github/workflows/build.yml` gera binários Windows/macOS/Linux e publica o release `latest`.

## O que verificar (em ordem de risco)

| Área | Arquivo | O que checar |
|---|---|---|
| Credenciais | `ai_bridge/oauth.py` | tokens nunca em log/JSON; refresh grava de volta preservando campos do CLI; `status()` não vaza segredo; escopos por fonte |
| Login PKCE | `ai_bridge/oauth_login.py` | redirect por fonte; servidor local só em loopback; `state` de uso único; timeout/TTL; callback inválido responde 400 |
| Proxy | `ai_bridge/proxy.py` | headers por provedor; passthrough SSE sem retradução; retry único em 401; `store:false` só no backend ChatGPT; `/v1/models` sem credencial |
| Configuração | `ai_bridge/config.py` | provider OAuth não grava chave no keyring; migrações; `env_key` sem valor não vira header vazio |
| Integração Codex | `ai_bridge/codex.py` | catálogo único, reversibilidade de `connect`/`disconnect`, não sobrescrever provider que não é dele |
| Importação DSH | `ai_bridge/dsh_import.py` | só lê YAML (nunca segredo), normaliza `baseURL` sem `/v1`, ignora provedor sem URL |
| Descoberta | `ai_bridge/discovery.py` | parse OpenAI/Anthropic/Ollama; classificação de grátis; headers vazios descartados |
| UI | `ai_bridge/ui/*` | XSS (todo texto passa por `escHtml`); fechar = sair (não esconder); bandeja; acessibilidade básica (foco, labels, contraste) |
| Testes | `tests/` | isolamento (conftest não toca config real nem keyring); cobertura dos caminhos acima |

## Limitações conhecidas (não são bugs)

- **Sem `/models` no backend ChatGPT**: o provedor OAuth `codex` usa a lista do preset;
  descoberta automática retorna mensagem explicativa.
- **Grátis é heurística**: as APIs não expõem preço; marcamos `:free`, `free-`, `/free`
  e endpoints locais (Ollama). Gemini/Groq têm cota grátis que a API não informa.
- **Login exige ação humana**: escolher a conta no navegador. O bridge recebe o código,
  troca por tokens e grava; não há como automatizar o clique da conta.
- **Amazon Q / Firebase**: sem adaptador (AWS SSO device flow / Vertex exigem trabalho
  dedicado). **Cursor/Windsurf** não têm API pública de inferência.
- **Copilot**: funciona com o token do `gh`, mas o uso fora do editor é sensível nos
  termos do GitHub.
- **`[features] apps = false`** foi necessário no Codex para a DeepSeek (schema do
  DocuSign é rejeitado); afeta apenas a configuração local do Codex, não o repositório.

## Critérios de aceite da auditoria

1. Nenhum segredo (token, chave, senha) no repositório ou em logs.
2. `pytest -q` verde em ambiente limpo (sem rede, sem cofres).
3. Nenhum caminho em que a UI escreva token em `config.json` ou exponha valor de chave.
4. `connect`/`disconnect` do Codex reversíveis e sem tocar em provider alheio.
5. Callback OAuth restrito a loopback, `state` validado e servidor encerrado.
6. Erros do provedor chegam ao usuário sem derrubar o processo nem vazar credencial.

## Como apontar um problema

Abra uma issue com: arquivo:linha, entrada reproduzível (payload/URL sem credenciais),
resultado esperado × obtido e o teste que deveria cobrir o caso.

## Smoke test de desktop (Windows)

`scripts/desktop_smoke.py` abre a janela real e exercita o ciclo de vida sem clique humano:
proxy no ar, geometria, minimizar, restaurar, maximizar, restaurar de volta, redimensionar
e criação do ícone de bandeja. Grava JSON e sai com código 0 quando tudo passa.

```powershell
.\.venv\Scripts\python.exe scripts\desktop_smoke.py --out smoke.json
```

Última execução (2026-10-31): `ok=true`, minimize `iconic=true`, maximize `2560×1600`,
restauração de volta a `1028×1294`, resize `650×820` aplicado, `tray_created.ok=true`.
