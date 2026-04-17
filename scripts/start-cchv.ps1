param(
    [string]$RepoDir = "",
    [string]$CodexDir = "$env:USERPROFILE\.codex",
    [string]$ClaudeDir = "$env:USERPROFILE\.claude",
    [string]$OpenClawDir = "$env:USERPROFILE\.openclaw",
    [string]$DataDir = "E:\cchv-data",
    [string]$BindHost = "127.0.0.1",
    [int]$Port = 8787
)

$ErrorActionPreference = "Stop"

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    throw "python not found in PATH"
}

if (-not (Test-Path -LiteralPath $DataDir)) {
    New-Item -ItemType Directory -Path $DataDir | Out-Null
}

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Resolver = Join-Path $ScriptDir "resolve_cchv_repo.py"
$RepoDir = (& python $Resolver --hint $RepoDir --script-dir $ScriptDir --cwd (Get-Location).Path).Trim()
if (-not $RepoDir) {
    throw "CCHV repo not found. Set -RepoDir or CCHV_REPO_DIR."
}

Set-Location -LiteralPath $RepoDir

python .\app.py `
  --codex-dir $CodexDir `
  --claude-dir $ClaudeDir `
  --openclaw-dir $OpenClawDir `
  --data-dir $DataDir `
  --host $BindHost `
  --port $Port
