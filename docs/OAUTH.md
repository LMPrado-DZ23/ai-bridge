# Autenticação OAuth

O AI Bridge aceita dois tipos de credencial por provedor:

| `auth.kind` | Onde fica o segredo | Quando usar |
|---|---|---|
| `api_key` (padrão) | keyring do SO | qualquer API OpenAI-compatible com chave |
| `oauth` | sessão já gravada por um CLI, ou o próprio AI Bridge | assinaturas/planos que só autenticam por OAuth |

```json
{
  "name": "Codex",
  "base_url": "",
  "auth": { "kind": "oauth", "source": "codex" },
  "models": [{ "id": "gpt-6-luna", "label": "GPT-6 Luna" }]
}
```

`base_url` vazio = usa o padrão da fonte. `protocol` é inferido pela fonte
(`responses` para Codex, `anthropic` para Claude, `chat` para o resto) e pode ser
forçado no provedor (`"protocol": "responses"`).

## Como o token é obtido (nesta ordem)

1. **Sessão da CLI** — a fonte lê o arquivo que o CLI já gravou. Se o access token
   expirou, renova com o mesmo endpoint/client_id que a CLI usa e **grava de volta**,
   então CLI e bridge continuam com uma sessão só.
2. **Login próprio do AI Bridge** — se não existe sessão, a UI abre o navegador
   (`oauth_login.begin`), o provedor redireciona para `http://127.0.0.1:<porta>/oauth/callback`
   e o bridge troca o `code` por tokens (PKCE S256) e grava no mesmo arquivo que a CLI usa.
3. **Erro acionável** — sem sessão e sem login feito, o proxy responde `401` com a
   instrução exata (`codex login`, `claude`, `gemini`, `gh auth login`…).

Nada de token vai para `~/.ai-bridge/config.json`, log ou UI: `oauth.status()` devolve
apenas `connected`, `source`, `expires_at` e `account_id`.

## Fontes incluídas

| `source` | CLI / arquivo | Renova? | Protocolo / base URL |
|---|---|---|---|
| `codex` | `codex login` → `~/.codex/auth.json` (ChatGPT) | sim, `auth.openai.com/oauth/token` | `responses` · `chatgpt.com/backend-api/codex` |
| `claude` | Claude Code → `~/.claude/.credentials.json` | sim, `console.anthropic.com/v1/oauth/token` | `anthropic` · `api.anthropic.com/v1` |
| `gemini` | gemini-cli → `~/.gemini/oauth_creds.json` | sim, `oauth2.googleapis.com/token` | `chat` · `generativelanguage.googleapis.com/v1beta/openai` |
| `gcloud` | `gcloud auth application-default login` → ADC | sim (refresh_token do ADC) | `chat` · você informa o `base_url` (ex.: endpoint OpenAI-compat do Vertex) |
| `huggingface` | `huggingface-cli login` → `~/.cache/huggingface/token` | não (token estático) | `chat` · `router.huggingface.co/v1` |
| `cloudflare` | `wrangler login` → `default.toml` (TOML) | sim, `dash.cloudflare.com/oauth2/token` | `chat` · informe `base_url` com `accounts/<id>/ai/v1` |
| `copilot` | `gh auth login` → `hosts.yml` (ou `GH_TOKEN`) | não | `chat` · `api.githubcopilot.com` (envia headers de editor) |

Variáveis de override: `CODEX_HOME`, `AI_BRIDGE_CLAUDE_CREDENTIALS`,
`AI_BRIDGE_GEMINI_CREDENTIALS`, `AI_BRIDGE_GCLOUD_ADC`, `AI_BRIDGE_HF_TOKEN_FILE`,
`AI_BRIDGE_WRANGLER_CONFIG`, `AI_BRIDGE_GH_HOSTS`.

### O que ainda não é suportado (e por quê)

| CLI | Status | Motivo |
|---|---|---|
| Cursor / Windsurf | ❌ | não expõem API pública de inferência para terceiros; a sessão OAuth só serve ao editor |
| Amazon Q Developer | ❌ | API proprietária do Q + AWS SSO device flow (SigV4); exige adaptador dedicado |
| Cloudflare Wrangler | ✅ | lê/renova o `default.toml` e regrava o token; `base_url` precisa do `account_id` |
| Firebase / Gemini Code Assist | ⏳ | mesmo OAuth do Google; dá para apontar via `gcloud` (ADC) quando o endpoint de inferência for OpenAI-compatible |
| GitHub Copilot | ⚠️ | funciona com o token do `gh`, mas o uso fora do editor é sensível nos termos do GitHub; valide antes de usar em produção |

## Adicionar uma CLI nova (adaptador genérico)

Crie uma subclasse de `OAuthSource` em `ai_bridge/oauth.py` e registre em `SOURCES`:

```python
class MinhaCliSource(OAuthSource):
    name = 'minhacli'
    default_base_url = 'https://api.exemplo.com/v1'
    default_protocol = 'chat'
    token_url = 'https://api.exemplo.com/oauth/token'
    client_id = 'client-publico-do-cli'
    scope = 'inference'
    def credentials_path(self): return _home('.minhacli', 'tokens.json')
    def load(self): ...      # devolve Token(access_token=..., refresh_token=..., expires_at=...)
    def save(self, token): ...  # grava no mesmo arquivo do CLI
```

Se o CLI só grava `access_token` sem refresh, o token vale até expirar — nesse caso
`save()` pode ser no-op e o usuário refaz o login quando cair.

## Fluxo de login próprio (PKCE)

```python
from ai_bridge import oauth_login, config
provider = config.get_provider('Codex')
begun = oauth_login.begin(provider, 'http://127.0.0.1:38771/oauth/callback')
# abra begun['url'] no navegador; o callback em /oauth/callback finaliza e grava os tokens
```

Na UI isso é o botão **“Entrar com …”** (`get_oauth_login_url` do bridge).

## Na interface

- **Adicionar provedor → Autenticação**: `API key` ou `OAuth (reaproveitar login da CLI)`.
- Escolhendo OAuth, o campo de chave some e aparece a **Fonte OAuth** (codex, claude,
  gemini, gcloud, huggingface, copilot) + botão **Entrar com…**.
- A lista de provedores mostra o estado (`OAuth · codex ✓` ou `— sem sessão`) e um
  botão **Entrar** quando não há sessão, ou **Reautenticar** quando há: a reautenticação
  força o refresh e, se o refresh falhar, cai direto no login do navegador.
- **Testar conexão** em provedor OAuth valida/renova a sessão em vez de chamar `/models`.
- Presets prontos: `Codex (OAuth)`, `Claude Code (OAuth)`, `Gemini (OAuth)`, `Hugging Face (OAuth)`.

O botão "Entrar com…" salva o provedor antes de abrir o navegador quando ele ainda é novo,
porque o callback precisa encontrar o provedor salvo para saber qual fonte usar.


## Notas de campo (testado com sessão real)

- **Codex/ChatGPT (Responses)**: o backend exige `"store": false` e **streaming**
  (`"stream": true`). O bridge já injeta `store: false` quando o cliente omite; para
  não-stream o próprio backend responde `Stream must be set to true` (clientes Codex
  sempre streamam).
- **Formato do `input`**: precisa ser uma lista de itens
  (`[{"type":"message","role":"user","content":[{"type":"input_text","text":"..."}]}]`),
  não uma string — é o formato que o Codex envia.
- **DeepSeek via API key**: `/v1/messages` (Anthropic) e `/chat/completions` funcionam;
  atenção a `max_tokens` baixo, que pode ser consumido por `reasoning_content` e devolver
  `content` vazio.

## Testes

```bash
python -m pytest tests/test_oauth.py tests/test_proxy_oauth.py -v
```

Os testes usam fixtures (`tmp_path` + `CODEX_HOME`/`AI_BRIDGE_*`), nunca credenciais reais.
