param(
    [string]$RepoDir = "E:\web\tools\Codex-Claude-History-Viewer",
    [string]$CodexDir = "$env:USERPROFILE\.codex",
    [string]$ClaudeDir = "$env:USERPROFILE\.claude",
    [string]$DataDir = "E:\cchv-data",
    [string]$BindHost = "127.0.0.1",
    [int]$Port = 8787
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath $RepoDir)) {
    throw "RepoDir not found: $RepoDir"
}

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    throw "python not found in PATH"
}

if (-not (Test-Path -LiteralPath $DataDir)) {
    New-Item -ItemType Directory -Path $DataDir | Out-Null
}

Set-Location -LiteralPath $RepoDir

python .\app.py `
  --codex-dir $CodexDir `
  --claude-dir $ClaudeDir `
  --data-dir $DataDir `
  --host $BindHost `
  --port $Port
