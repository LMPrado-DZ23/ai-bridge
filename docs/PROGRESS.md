# AI Bridge Professional Edition — progresso e evidências

Atualizado em 2026-10-31. Commits **locais** (sem push por regra da missão).

## Ondas concluídas

| Onda | Entrega | Commit | Evidência |
|---|---|---|---|
| 1 | Redimensionamento por 8 bordas + layout sem overflow + bandeja | `5de16f0` | resize 685×762→800×760; `hOverflow=false` em 546 px |
| 2 | Configurações, autostart reversível, fechar-para-bandeja, config corrompida | `711ee3c` | registro HKCU False→True→False |
| 3 | Métricas do proxy + tela Monitoramento | `f21cc37` | stats reais 0/0/0 ms e proxy na porta |
| 4 | Host guard + binding loopback | `0086068` | evil host→403; loopback→200 |
| 5 | Matriz de compatibilidade verificada | `b4b0d85` | `verified ⊆ declarado` |
| 6 | Instalador NSIS + CI manual + guia | `4791df5` | YAML válido; tokens NSIS; **build não executado** |
| 7 | Roteamento + fallback opt-in | `b07e2f7` | fallback off por padrão |
| 8 | Contadores por provedor/modelo | `5aff6c5` | by_provider/by_model |
| 9 | Smoke test de desktop | `935b6a2` | minimize iconic; max 2560×1600; volta 1028×1294 |
| 10 | Logs persistidos com rotação | `871db3e`, `09724a9` | whitelist sem prompt/token |
| 11 | Tela de Logs | `f80f21b` | wiring testado |

## Critérios de aceite

| Critério | Estado |
|---|---|
| Projeto original preservado | ✅ (evolutivo, sem reescrita; 211 testes) |
| Layout sem corte/overflow | ✅ medido em 560 px |
| Redimensionar com o mouse | ✅ 8 zonas + smoke test |
| Minimizar | ✅ `IsIconic` |
| Minimizar para bandeja | ✅ `hide_window` + tray |
| Restaurar pela bandeja | ✅ menu Abrir |
| Proxy ativo na bandeja | ✅ tray status “Proxy ativo · porta N” |
| Sair encerra processos | ✅ `quit()` para tray/window |
| Instalável no Windows | ⚠️ script pronto; **build não validado** (sem makensis local) |
| Menu Iniciar | ✅ atalhos criados no instalador (não validado) |
| Autostart configurável | ✅ HKCU Run reversível |
| Claude Code funcional | ⚠️ BLOCKED_BY_EXTERNAL (login/app do usuário) |
| Claude Desktop funcional | ⚠️ BLOCKED_BY_EXTERNAL |
| Codex Desktop funcional | ✅ provider `ai_bridge` + catálogo; validação de login feita antes |
| Configurações restauráveis | ✅ connect/disconnect e backups |
| Modelos descobertos/limitações | ✅ `discovery` + `compat` |
| API keys não expostas | ✅ keyring; nunca no config |
| OAuth validado | ✅ Codex real; PKCE/callback por fonte |
| Testes existentes passando | ✅ 211 |
| Novos testes cobrindo o novo | ✅ por onda |
| Build de produção | ⚠️ CI só roda com push autorizado |
| Documentação atualizada | ✅ README, OAUTH, AUDITORIA, COMPATIBILITY, ROUTING, LOGS, INSTALL-WINDOWS |

## Pendências e bloqueios

- **Push/release**: proibido sem autorização explícita do dono.
- **Instalador**: compilar/validar no CI (`choco install nsis` + `makensis`).
- **Roteamento no proxy**: mudança de contrato (seleção por nome), exige testes de streaming.
- **Claude Desktop/Code reais**: dependem do app instalado e do login do usuário.
- **Multi-monitor/DPI**: exige ambiente externo.

## Comandos

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q          # 211 passed
.\.venv\Scripts\python.exe scripts\desktop_smoke.py    # lifecycle real
.\.venv\Scripts\python.exe entry.py                    # app
```
