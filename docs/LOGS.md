# Logs

`ai_bridge/eventlog.py` grava `~/.ai-bridge/logs/events.jsonl` com apenas metadados:
`ts`, `path`, `method`, `status`, `ms`, `provider`, `model`.

- **Nunca** grava prompt, corpo de resposta, token, API key ou cookie (campo fora da lista é descartado).
- Rotação em 1 MB, mantendo o arquivo atual + 2 backups (`events.1.jsonl`, `events.2.jsonl`).
- `read_recent(limit)` lê o atual e os backups, do mais novo para o mais antigo.
- Falhas de I/O não derrubam requisição (o append é best-effort).
- `bridge.get_logs(limit)` expõe os eventos para a UI.

Limpeza: apagar a pasta `~/.ai-bridge/logs` (ou `eventlog.clear()` em código).
