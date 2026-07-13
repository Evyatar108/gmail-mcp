[CmdletBinding()]
param(
    [string]$SkillsHome = (Join-Path $HOME ".copilot\skills")
)

$repo = Split-Path $PSScriptRoot -Parent
$skills = Get-ChildItem (Join-Path $repo "skills") -Directory
foreach ($skill in $skills) {
    $source = Join-Path $skill.FullName "SKILL.md"
    if (-not (Test-Path $source)) {
        continue
    }
    $destination = Join-Path $SkillsHome $skill.Name
    New-Item -ItemType Directory -Force $destination | Out-Null
    Copy-Item -Force $source (Join-Path $destination "SKILL.md")
    Write-Output "Installed $($skill.Name) at $destination"
}
