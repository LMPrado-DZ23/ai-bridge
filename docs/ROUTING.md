# Roteamento e fallback

O roteamento é **determinístico e explícito** (`ai_bridge/routing.py`, coberto por
`tests/test_routing.py`).

## Ordem

1. `explicit` (lista de nomes) manda, na ordem dada.
2. O restante segue o campo `priority` (menor primeiro) e, em empate, o nome.
3. Provedores com `enabled: false` nunca entram.
4. Sem provedor habilitado → `RoutingError` (erro claro, não silêncio).

## Fallback

- **Desligado por padrão** (`allow_fallback: false`, `max_attempts: 1`).
  O proxy tenta somente o provedor selecionado.
- Para ligar: `allow_fallback: true` + `max_attempts: N` (limitado ao número de candidatos).
- `fallback_candidates()` devolve apenas provedores ainda não tentados, na ordem resolvida.
- Motivo: fallback silencioso pode enviar código/contexto a outro provedor sem consentimento.
  A UI deve mostrar quando o fallback está ligado.

## Integração futura

O proxy ainda usa o provedor do prefixo do modelo (`Provider/modelo`); ligar a política ao
proxy exige uma mudança de contrato (seleção por nome de provedor, não por prefixo) e será
feita com testes de streaming antes de entrar em produção.
