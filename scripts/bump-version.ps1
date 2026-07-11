param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidatePattern('^\d+\.\d+\.\d+$')]
    [string]$Version
)

$ErrorActionPreference = 'Stop'

uv version $Version --no-sync

Write-Host "Version updated to $Version in pyproject.toml and uv.lock."
Write-Host "After reviewing CHANGELOG.md, create the release tag: git tag $Version"
