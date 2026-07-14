[CmdletBinding()]
param(
    [string]$ServerName = "gmail",
    [switch]$SkipSync
)

$isWindowsPlatform = if (Get-Variable IsWindows -ErrorAction SilentlyContinue) {
    $IsWindows
} else {
    $env:OS -eq "Windows_NT"
}
if (-not $isWindowsPlatform) {
    throw "Gmail MCP currently supports Windows Credential Manager only."
}

foreach ($command in @("uv", "copilot")) {
    if (-not (Get-Command $command -ErrorAction SilentlyContinue)) {
        throw "Required command is not installed or not on PATH: $command"
    }
}

$repo = Split-Path $PSScriptRoot -Parent
Push-Location $repo
try {
    if (-not $SkipSync) {
        uv sync --locked
        if ($LASTEXITCODE -ne 0) {
            throw "uv sync failed."
        }
    }

    $executable = Join-Path $repo ".venv\Scripts\gmail-mcp.exe"
    if (-not (Test-Path $executable)) {
        throw "Gmail MCP executable was not created: $executable"
    }

    $tools = @(
        "gmail_search",
        "gmail_get_message",
        "gmail_get_thread",
        "gmail_list_labels",
        "gmail_create_label",
        "gmail_list_filters",
        "gmail_create_filter",
        "gmail_delete_filter",
        "gmail_list_attachments",
        "gmail_download_attachment",
        "gmail_modify_labels",
        "gmail_archive",
        "gmail_create_draft",
        "gmail_send_draft",
        "gmail_trash",
        "gmail_untrash"
    ) -join ","

    copilot mcp get $ServerName --json *> $null
    if ($LASTEXITCODE -eq 0) {
        copilot mcp remove $ServerName
        if ($LASTEXITCODE -ne 0) {
            throw "Unable to remove existing Copilot MCP registration."
        }
    }

    copilot mcp add $ServerName --tools $tools -- $executable serve
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to register Gmail MCP with Copilot CLI."
    }

    copilot mcp get $ServerName --json
    & (Join-Path $repo "scripts\install-user-skill.ps1")
    Write-Output ""
    Write-Output "Next:"
    Write-Output "  1. Install a Desktop OAuth JSON with scripts\install-oauth-client.ps1."
    Write-Output "  2. Run .\.venv\Scripts\gmail-mcp.exe auth."
    Write-Output "  3. Run .\.venv\Scripts\gmail-mcp.exe status."
} finally {
    Pop-Location
}
