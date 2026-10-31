; AI Bridge — instalador Windows (NSIS 3 / Modern UI 2)
; Build: makensis installer\ai-bridge.nsi  (a partir da raiz do repositório)
; Requer dist\AI-Bridge.exe gerado por `pyinstaller build.spec`.

Unicode true
!include "MUI2.nsh"
!include "FileFunc.nsh"

!define APP_NAME "AI Bridge"
!define APP_EXE "AI-Bridge.exe"
!define APP_VERSION "latest"
!define APP_PUBLISHER "DZ23"
!define APP_URL "https://github.com/LMPrado-DZ23/ai-bridge"
!define UNINST_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\AIBridge"
!define RUN_KEY "Software\Microsoft\Windows\CurrentVersion\Run"

Name "${APP_NAME}"
!ifndef ROOT
  !define ROOT "${__FILEDIR__}\.."
!endif
OutFile "${ROOT}\dist\AI-Bridge-Setup.exe"
InstallDir "$LOCALAPPDATA\Programs\AI Bridge"
InstallDirRegKey HKCU "Software\AI Bridge" "InstallDir"
RequestExecutionLevel user
SetCompressor /SOLID lzma

; ── Páginas ────────────────────────────────────────────────────────────────
!define MUI_ABORTWARNING
!define MUI_ICON "${ROOT}\ai_bridge\ui\assets\icons\ai-bridge.ico"
!define MUI_UNICON "${ROOT}\ai_bridge\ui\assets\icons\ai-bridge.ico"

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_COMPONENTS
!insertmacro MUI_PAGE_INSTFILES

!define MUI_FINISHPAGE_RUN "$INSTDIR\${APP_EXE}"
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "PortugueseBR"

; ── Instalação ─────────────────────────────────────────────────────────────
Section "AI Bridge (obrigatório)" SecCore
  SectionIn RO
  SetOutPath "$INSTDIR"
  File "${ROOT}\dist\${APP_EXE}"
  File "${ROOT}\ai_bridge\ui\assets\icons\ai-bridge.ico"

  WriteRegStr HKCU "Software\AI Bridge" "InstallDir" "$INSTDIR"

  ; Menu Iniciar
  CreateDirectory "$SMPROGRAMS\AI Bridge"
  CreateShortcut "$SMPROGRAMS\AI Bridge\AI Bridge.lnk" "$INSTDIR\${APP_EXE}" "" "$INSTDIR\ai-bridge.ico" 0
  CreateShortcut "$SMPROGRAMS\AI Bridge\AI Bridge (bandeja).lnk" "$INSTDIR\${APP_EXE}" "--tray" "$INSTDIR\ai-bridge.ico" 0

  ; Desinstalador + registro de aplicativos
  WriteUninstaller "$INSTDIR\Uninstall.exe"
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayName" "${APP_NAME}"
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayVersion" "${APP_VERSION}"
  WriteRegStr HKCU "${UNINST_KEY}" "Publisher" "${APP_PUBLISHER}"
  WriteRegStr HKCU "${UNINST_KEY}" "URLInfoAbout" "${APP_URL}"
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayIcon" "$INSTDIR\ai-bridge.ico"
  WriteRegStr HKCU "${UNINST_KEY}" "UninstallString" '"$INSTDIR\Uninstall.exe"'
  WriteRegDWORD HKCU "${UNINST_KEY}" "NoModify" 1
  WriteRegDWORD HKCU "${UNINST_KEY}" "NoRepair" 1
SectionEnd

Section "Atalho na área de trabalho" SecDesktop
  CreateShortcut "$DESKTOP\AI Bridge.lnk" "$INSTDIR\${APP_EXE}" "" "$INSTDIR\ai-bridge.ico" 0
SectionEnd

Section "Iniciar com o Windows (na bandeja)" SecAutostart
  WriteRegStr HKCU "${RUN_KEY}" "AI Bridge" '"$INSTDIR\${APP_EXE}" --tray'
SectionEnd

!insertmacro MUI_FUNCTION_DESCRIPTION_BEGIN
  !insertmacro MUI_DESCRIPTION_TEXT ${SecCore} "Aplicativo, atalhos do Menu Iniciar e desinstalador."
  !insertmacro MUI_DESCRIPTION_TEXT ${SecDesktop} "Cria um atalho na área de trabalho."
  !insertmacro MUI_DESCRIPTION_TEXT ${SecAutostart} "Inicia o AI Bridge na bandeja junto com o Windows (reversível pelo próprio app)."
!insertmacro MUI_FUNCTION_DESCRIPTION_END

; ── Desinstalação ──────────────────────────────────────────────────────────
Section "Uninstall"
  Delete "$DESKTOP\AI Bridge.lnk"
  Delete "$SMPROGRAMS\AI Bridge\AI Bridge.lnk"
  Delete "$SMPROGRAMS\AI Bridge\AI Bridge (bandeja).lnk"
  RMDir "$SMPROGRAMS\AI Bridge"

  DeleteRegValue HKCU "${RUN_KEY}" "AI Bridge"
  DeleteRegKey HKCU "${UNINST_KEY}"
  DeleteRegKey HKCU "Software\AI Bridge"

  Delete "$INSTDIR\${APP_EXE}"
  Delete "$INSTDIR\ai-bridge.ico"
  Delete "$INSTDIR\Uninstall.exe"
  RMDir "$INSTDIR"

  ; Configurações do usuário (~/.ai-bridge) são preservadas de propósito.
SectionEnd
