# Matriz de compatibilidade

Regra: **capacidade só é anunciada depois de verificada**. A matriz vive em
`ai_bridge/compat.py` e é coberta por `tests/test_compat.py`.

| Provedor | Chat | Responses | Streaming | Tools | Imagens | Verificado |
|---|---|---|---|---|---|---|
| OpenAI | ✅ | ✅ | ✅ | ✅ | ✅ | chat, streaming, tools |
| DeepSeek | ✅ | ✅ | ✅ | ✅ | — | chat, responses, streaming |
| Anthropic (API) | — | — | ✅ | ✅ | ✅ | streaming, tools |
| Gemini | ✅ | — | ✅ | ✅ | ✅ | chat, streaming |
| Groq | ✅ | — | ✅ | ✅ | — | chat, streaming |
| Mistral | ✅ | — | ✅ | ✅ | — | chat |
| OpenRouter | ✅ | — | ✅ | ✅ | ✅ | chat, streaming |
| Ollama | ✅ | — | ✅ | — | ✅ | chat, streaming |
| Codex (OAuth) | — | ✅ | ✅ | ✅ | ✅ | responses, streaming |
| Claude (OAuth) | — | ✅ | ✅ | ✅ | ✅ | responses, streaming |

Legenda: ✅ declarado · — não suportado/desconhecido. "Verificado" é o subconjunto que
tem evidência de teste executado; o resto é declaração do provedor, não promessa do app.

## Como validar uma capacidade

1. `chat`: `POST /v1/chat/completions` com mensagem curta e conferir `choices[0]`.
2. `responses`: `POST /v1/responses` com `store=false`, `stream=true`, `input` em lista.
3. `streaming`: conferir eventos SSE (`data:`/`response.output_text.delta`) sem buffer.
4. `tools`: enviar uma `function_call` e verificar o `tool_calls`/`function_call` de volta.
5. `images`: apenas onde a API aceita `image_url`/parte de imagem.

Se o provedor não suportar, a UI e a documentação devem dizer **limitação**, nunca "conectado".
