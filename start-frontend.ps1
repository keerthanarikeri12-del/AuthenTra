$nodeBin = "C:\Users\keert\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin"
$pnpmBin = "C:\Users\keert\.cache\codex-runtimes\codex-primary-runtime\dependencies\bin\fallback"
if (Test-Path "$nodeBin\node.exe") {
    $env:PATH = "$nodeBin;$pnpmBin;$env:PATH"
}
node ./node_modules/vite/bin/vite.js
