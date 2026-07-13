[CmdletBinding()]
param(
    [string]$ServerName = "gmail"
)

if (-not (Get-Command copilot -ErrorAction SilentlyContinue)) {
    throw "GitHub Copilot CLI is not installed or not on PATH."
}

copilot mcp get $ServerName --json *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Output "No Copilot MCP server named '$ServerName' is registered."
    exit 0
}

copilot mcp remove $ServerName
if ($LASTEXITCODE -ne 0) {
    throw "Unable to remove Copilot MCP registration '$ServerName'."
}

Write-Output "Removed Copilot MCP registration '$ServerName'."
Write-Output "OAuth credentials were not revoked or deleted."
