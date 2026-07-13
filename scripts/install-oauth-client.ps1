[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string]$Path,

    [string]$Destination = (Join-Path $env:APPDATA "gmail-mcp\credentials.json")
)

$isWindowsPlatform = if (Get-Variable IsWindows -ErrorAction SilentlyContinue) {
    $IsWindows
} else {
    $env:OS -eq "Windows_NT"
}
if (-not $isWindowsPlatform) {
    throw "Gmail MCP currently supports Windows Credential Manager only."
}

$source = (Resolve-Path -LiteralPath $Path).Path
$content = Get-Content -LiteralPath $source -Raw
try {
    $document = $content | ConvertFrom-Json
} catch {
    throw "OAuth client file is not valid JSON."
}

if ($document.web) {
    throw "Web OAuth clients are not supported. Create a Desktop app client."
}
if (-not $document.installed) {
    throw "OAuth JSON must contain an 'installed' Desktop client."
}

$client = $document.installed
foreach ($field in @("client_id", "auth_uri", "token_uri", "redirect_uris")) {
    if (-not $client.$field) {
        throw "Desktop OAuth JSON is missing '$field'."
    }
}
if ($client.client_id -notmatch "\.apps\.googleusercontent\.com$") {
    throw "Desktop OAuth client_id is invalid."
}
if ($client.token_uri -ne "https://oauth2.googleapis.com/token") {
    throw "Unexpected OAuth token URI."
}
if (-not ($client.redirect_uris | Where-Object { $_ -match "^http://localhost(?::\d+)?/?$" })) {
    throw "Desktop OAuth JSON must include a localhost redirect URI."
}

$destinationDirectory = Split-Path $Destination -Parent
New-Item -ItemType Directory -Force $destinationDirectory | Out-Null
Copy-Item -LiteralPath $source -Destination $Destination -Force

$identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$acl = New-Object System.Security.AccessControl.FileSecurity
$acl.SetAccessRuleProtection($true, $false)
$acl.SetOwner([System.Security.Principal.NTAccount]$identity)
$rule = New-Object System.Security.AccessControl.FileSystemAccessRule(
    $identity,
    "FullControl",
    "Allow"
)
$acl.AddAccessRule($rule)
Set-Acl -LiteralPath $Destination -AclObject $acl

Write-Output "Installed Desktop OAuth client at $Destination"
