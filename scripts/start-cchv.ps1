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

function Resolve-CchvRepoDir {
    param([string]$Hint)

    $candidates = @(
        $Hint
        $env:CCHV_REPO_DIR
        "E:\web\tools\Codex-Claude-History-Viewer"
        (Join-Path $env:USERPROFILE "web\tools\Codex-Claude-History-Viewer")
    ) | Where-Object { $_ -and $_.Trim() }

    foreach ($candidate in $candidates) {
        $full = [System.IO.Path]::GetFullPath($candidate)
        if (
            (Test-Path -LiteralPath $full) -and
            (Test-Path -LiteralPath (Join-Path $full "app.py")) -and
            (Test-Path -LiteralPath (Join-Path $full "static"))
        ) {
            return $full
        }
    }

    throw "CCHV repo not found. Set -RepoDir or CCHV_REPO_DIR."
}

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    throw "python not found in PATH"
}

if (-not (Test-Path -LiteralPath $DataDir)) {
    New-Item -ItemType Directory -Path $DataDir | Out-Null
}

$RepoDir = Resolve-CchvRepoDir -Hint $RepoDir

Set-Location -LiteralPath $RepoDir

python .\app.py `
  --codex-dir $CodexDir `
  --claude-dir $ClaudeDir `
  --openclaw-dir $OpenClawDir `
  --data-dir $DataDir `
  --host $BindHost `
  --port $Port
