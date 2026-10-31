# Instalação no Windows

## Opção 1 — portátil (disponível hoje)

1. Baixe `AI-Bridge-Windows.exe` em https://github.com/LMPrado-DZ23/ai-bridge/releases/latest
2. Coloque em qualquer pasta e execute.
3. Opcional: botão direito → **Fixar na barra de tarefas** (mecanismo oficial do Windows).

Requisitos: Windows 10/11 x64 com WebView2 (presente por padrão).

## Opção 2 — instalador (script pronto, build no CI)

O instalador é gerado por `installer/ai-bridge.nsi` (NSIS 3) e empacotado pelo workflow
`.github/workflows/installer.yml`, acionado manualmente (**não publica release**).

O que ele faz (por usuário, sem UAC):

| Item | Comportamento |
|---|---|
| Destino | `%LOCALAPPDATA%\Programs\AI Bridge` |
| Menu Iniciar | **AI Bridge** e **AI Bridge (bandeja)** |
| Área de trabalho | atalho opcional |
| Autostart | opcional (`HKCU\...\Run`, reversível pelo app) |
| Desinstalador | registrado em “Aplicativos e recursos” |
| Configurações | `~/.ai-bridge` é **preservada** na desinstalação |

Para gerar localmente:

```powershell
python -m PyInstaller build.spec --noconfirm --clean
makensis installer\ai-bridge.nsi     # gera dist\AI-Bridge-Setup.exe
```

Se `makensis` não estiver instalado: `choco install nsis -y` (requer Chocolatey).
Sem ele, o build local do instalador fica **BLOCKED_BY_EXTERNAL_DEPENDENCY** — o CI resolve.

## Verificação de integridade

O job do instalador grava `dist/SHA256SUMS.txt`. Confira com:

```powershell
Get-FileHash .\AI-Bridge-Setup.exe -Algorithm SHA256
```

## Fixar na barra de tarefas

O Windows não permite fixar programaticamente sem APIs não documentadas; o caminho oficial é
abrir o app e usar **botão direito no ícone → Fixar na barra de tarefas**. O instalador deixa o
atalho no Menu Iniciar para isso.

## Desinstalar

Configurações → Aplicativos → AI Bridge → Desinstalar (ou `Uninstall.exe` na pasta).
As configurações em `~/.ai-bridge` permanecem; apague a pasta se quiser remover tudo.
