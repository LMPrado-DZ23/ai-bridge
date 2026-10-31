# ChatGPT Web no AI Bridge (via codex-chatgpt-web)

O AI Bridge tem um preset **ChatGPT Web (codex-chatgpt-web)** que aponta para o endpoint
local do launcher `codex-chatgpt-web` (`http://127.0.0.1:17841/v1`, protocolo Responses).
Ele usa a **sessão do ChatGPT Web já logada no launcher** — o AI Bridge não lê nem copia cookies.

## Requisitos

1. `codex-chatgpt-web` instalado e com login concluído no launcher.
2. Launcher aberto (ele sobe o servidor em `127.0.0.1:17841` e o navegador embutido).
3. Conta com modelos Web disponíveis (Free → Luna/Think; pagas → Sol etc.).

## Uso

1. AI Bridge → **Adicionar provedor → ChatGPT Web (codex-chatgpt-web)**.
2. Clique **Testar conexão**: deve listar modelos via `/models`.
3. Salve e conecte o Codex ao AI Bridge (`connect`); os modelos web aparecem no mesmo catálogo.

## Estado da validação (2026-10-31)

- `serve` sozinho (sem launcher) responde `/health` 200, mas `/v1/models` e `/v1/responses`
  devolvem **502** (`model_catalog_failed`) — o launcher/browser host não está ativo.
- Portanto: **preset integrado, teste ao vivo BLOCKED_BY_EXTERNAL** até o launcher estar aberto
  e logado. Com ele aberto, o teste é `Testar conexão` → modelos → salvar → Codex.

## Limite conhecido

A conta Free tem budget de ~28k tokens no transporte; o payload mínimo do Codex com nossas
ferramentas passa de 43k. Em conta paga (Plus/Pro) o limite sobe e o fluxo funciona.
