; ============================================================
; 股大师安装器钩子 — AI 对话功能选择
;
; 功能：
; 1. 安装向导第一页询问用户是否启用 AI 对话功能
; 2. POSTINSTALL 阶段写入 installer_flags.json
; 3. 启用 AI 时：自动下载安装 Ollama 并拉取本地模型
; 4. 未启用 AI 时：仅部署持仓管理功能
; ============================================================

; ---- 变量声明 ----
; AIEnabled: "1"=启用 AI, 空/"0"=仅持仓管理（静默安装默认关闭，避免意外下载模型）
Var AICheckbox
Var AIEnabled
Var OllamaInstallPath

; ============================================================
; AI 选择页（安装向导第一页）
; ============================================================
Page custom PageAISelect PageAILeave

Function PageAISelect
  !insertmacro MUI_HEADER_TEXT "AI 对话功能" "选择是否启用 AI 对话功能"

  nsDialogs::Create 1018
  Pop $0

  ; 说明文字
  ${NSD_CreateLabel} 0 0 100% 24u "是否启用 AI 对话功能？"
  Pop $0

  ${NSD_CreateLabel} 0 28u 100% 36u "启用后将安装 Ollama 本地推理引擎并下载约 1GB 的对话模型。\n不启用则仅提供持仓管理、行情查询、提醒等核心功能。"
  Pop $0

  ; 复选框
  ${NSD_CreateCheckbox} 0 72u 100% 18u "启用 AI 对话功能（推荐：有独立显卡或大内存时开启）"
  Pop $AICheckbox
  ; 默认勾选
  SendMessage $AICheckbox ${BM_SETCHECK} ${BST_CHECKED} 0

  nsDialogs::Show
FunctionEnd

Function PageAILeave
  ${NSD_GetState} $AICheckbox $AIEnabled
FunctionEnd

; ============================================================
; 安装后钩子：写入标记 + 部署 AI 模型
; ============================================================
!macro NSIS_HOOK_POSTINSTALL
  ; ---- 强制刷新 Windows 图标缓存（根治覆盖安装后桌面/任务栏仍显示旧图标） ----
  ; Windows 按"文件路径+图标索引"缓存图标且不校验文件内容是否已更新。
  ; 关键坑：iconcache 数据库被 explorer/ShellExperienceHost 等进程占用时，
  ; Delete 会静默失败（NSIS 不报错）；而被占用的文件依然可以 Rename。
  ; 因此采用「重命名法」：kill explorer → rename 缓存库为 .old → 重启 explorer
  ; → 删除 .old（此时旧库已无人引用，即使删除失败也不影响新缓存生成）。
  DetailPrint "刷新系统图标缓存..."
  ExecWait '"$SYSDIR\taskkill.exe" /F /IM explorer.exe'
  Sleep 800
  ; 根目录 IconCache.db（重命名，被锁也可成功）
  Rename "$LOCALAPPDATA\IconCache.db" "$LOCALAPPDATA\IconCache.db.old"
  ; Explorer 子目录 iconcache_*.db（Rename 不支持通配，需 FindFirst 循环）
  FindFirst $0 $1 "$LOCALAPPDATA\Microsoft\Windows\Explorer\iconcache_*.db"
  iconcache_loop:
    StrCmp $1 "" iconcache_done
    Rename "$LOCALAPPDATA\Microsoft\Windows\Explorer\$1" "$LOCALAPPDATA\Microsoft\Windows\Explorer\$1.old"
    FindNext $0 $1
    Goto iconcache_loop
  iconcache_done:
  FindClose $0
  ; 兜底删除（0.4.x 旧方案未被锁的残留）
  Delete "$LOCALAPPDATA\IconCache.db"
  Delete "$LOCALAPPDATA\Microsoft\Windows\Explorer\iconcache_*.db"
  Sleep 300
  Exec '"$WINDIR\explorer.exe"'
  Sleep 1500
  ; Explorer 已持有新缓存，旧 .old 库不再被引用，清理残留（失败无害）
  Delete "$LOCALAPPDATA\IconCache.db.old"
  Delete "$LOCALAPPDATA\Microsoft\Windows\Explorer\iconcache_*.db.old"

  ; ---- 清理 WebView2 页面缓存（防止前端 UI 被旧版缓存劫持） ----
  DetailPrint "清理界面缓存..."
  RMDir /r "$LOCALAPPDATA\com.gudashi.app\EBWebView\Default\Cache"
  RMDir /r "$LOCALAPPDATA\com.gudashi.app\EBWebView\Default\Code Cache"
  RMDir /r "$LOCALAPPDATA\com.gudashi.app\EBWebView\Default\Service Worker"

  ; ---- 写入 installer_flags.json 供后端读取 ----
  DetailPrint "写入安装配置..."
  FileOpen $0 "$INSTDIR\backend\installer_flags.json" w
  ${If} $AIEnabled == "1"
    FileWrite $0 '{"ai_enabled": true}'
  ${Else}
    FileWrite $0 '{"ai_enabled": false}'
  ${EndIf}
  FileClose $0

  ; ---- 如果启用 AI，安装 Ollama 并拉取模型 ----
  ${If} $AIEnabled == "1"
    Call InstallOllamaAndModel
  ${Else}
    DetailPrint "AI 对话功能未启用，跳过模型部署。"
  ${EndIf}
!macroend

; ============================================================
; Ollama 安装 + 模型拉取
; ============================================================
Function InstallOllamaAndModel
  DetailPrint "检查 Ollama 是否已安装..."

  ; 查找已有 Ollama 安装
  StrCpy $OllamaInstallPath ""
  IfFileExists "$PROGRAMFILES\Ollama\ollama.exe" 0 +3
    StrCpy $OllamaInstallPath "$PROGRAMFILES\Ollama\ollama.exe"
    Goto ollama_found
  IfFileExists "$PROGRAMFILES64\Ollama\ollama.exe" 0 +3
    StrCpy $OllamaInstallPath "$PROGRAMFILES64\Ollama\ollama.exe"
    Goto ollama_found
  IfFileExists "$LOCALAPPDATA\Programs\Ollama\ollama.exe" 0 ollama_not_found
    StrCpy $OllamaInstallPath "$LOCALAPPDATA\Programs\Ollama\ollama.exe"

  ollama_found:
  ${If} $OllamaInstallPath != ""
    DetailPrint "检测到已有 Ollama：$OllamaInstallPath"
    Goto pull_model
  ${EndIf}

  ollama_not_found:
  DetailPrint "未检测到 Ollama，开始下载安装..."
  DetailPrint "下载 Ollama 安装包（约 200MB）..."
  NSISdl::download "https://ollama.com/download/OllamaSetup.exe" "$TEMP\OllamaSetup.exe"
  Pop $0
  ${If} $0 != "success"
    DetailPrint "Ollama 下载失败，跳过模型部署（可稍后手动安装）。"
    Goto ollama_done
  ${EndIf}

  DetailPrint "安装 Ollama（静默模式）..."
  ExecWait '"$TEMP\OllamaSetup.exe" /SILENT' $0
  ${If} $0 != 0
    DetailPrint "Ollama 安装返回代码 $0，尝试继续..."
  ${EndIf}

  ; 定位安装后的 ollama.exe
  StrCpy $OllamaInstallPath "$PROGRAMFILES\Ollama\ollama.exe"
  IfFileExists $OllamaInstallPath 0 +2
    Goto pull_model
  StrCpy $OllamaInstallPath "$LOCALAPPDATA\Programs\Ollama\ollama.exe"

  pull_model:
  DetailPrint "等待 Ollama 服务启动..."
  ; 给 Ollama 服务一点启动时间
  Sleep 5000

  DetailPrint "拉取本地模型 qwen2.5:1.5b（约 1GB，首次较慢）..."
  nsExec::ExecToLog '"$OllamaInstallPath" pull qwen2.5:1.5b'
  Pop $0
  ${If} $0 == 0
    DetailPrint "模型拉取完成！"
  ${Else}
    DetailPrint "模型拉取失败（代码 $0），可在应用首次启动后手动执行：ollama pull qwen2.5:1.5b"
  ${EndIf}

  ollama_done:
  ; 清理临时安装包
  Delete "$TEMP\OllamaSetup.exe"
FunctionEnd

; ============================================================
; 卸载钩子
; ============================================================
!macro NSIS_HOOK_POSTUNINSTALL
  ; 仅清理股大师自身数据，不卸载 Ollama（可能被其他应用使用）
  ; 删除 installer_flags.json 已随安装目录整体删除
!macroend
