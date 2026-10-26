$nodeBin = "C:\Users\keert\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin"
if (Test-Path "$nodeBin\node.exe") {
    $env:PATH = "$nodeBin;$env:PATH"
}
node scripts/chain.mjs
