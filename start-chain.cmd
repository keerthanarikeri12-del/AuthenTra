@echo off
set "NODE_BIN=C:\Users\keert\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin"
if exist "%NODE_BIN%\node.exe" (
    set "PATH=%NODE_BIN%;%PATH%"
)
node scripts/chain.mjs
