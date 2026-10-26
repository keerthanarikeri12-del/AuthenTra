@echo off
set "NODE_BIN=C:\Users\keert\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin"
set "PNPM_BIN=C:\Users\keert\.cache\codex-runtimes\codex-primary-runtime\dependencies\bin\fallback"
if exist "%NODE_BIN%\node.exe" (
    set "PATH=%NODE_BIN%;%PNPM_BIN%;%PATH%"
)
node ./node_modules/vite/bin/vite.js
