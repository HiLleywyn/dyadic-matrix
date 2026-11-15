param([string]$InstallRoot = (Join-Path $env:LOCALAPPDATA 'DyadicMatrix'))
$ErrorActionPreference = 'Stop'
$sourceRoot = [IO.Path]::GetFullPath($PSScriptRoot)
$manifest = Get-Content -LiteralPath (Join-Path $sourceRoot 'release.json') -Raw | ConvertFrom-Json
if ($manifest.platform -ne 'windows' -or $manifest.architecture -ne 'x86_64' -or $manifest.version -notmatch '^\d+\.\d+\.\d+-alpha\.\d+$') { throw 'Unexpected package identity' }
foreach ($property in $manifest.files.PSObject.Properties) {
    $candidate = [IO.Path]::GetFullPath((Join-Path $sourceRoot $property.Name))
    if (-not $candidate.StartsWith($sourceRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { throw 'Unsafe package path' }
    if ((Get-FileHash -LiteralPath $candidate -Algorithm SHA256).Hash.ToLowerInvariant() -ne $property.Value) { throw "Integrity check failed: $($property.Name)" }
}
$destination = Join-Path ([IO.Path]::GetFullPath($InstallRoot)) $manifest.version
if ($destination.StartsWith($sourceRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { throw 'InstallRoot must be outside the extracted package' }
if (Test-Path -LiteralPath $destination) { throw 'This version already exists; choose another InstallRoot or use the existing installation.' }
$reparse = Get-ChildItem -LiteralPath $sourceRoot -Recurse -Force | Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint }
if ($reparse) { throw 'Package must contain ordinary files and directories' }
New-Item -ItemType Directory -Path $destination -Force | Out-Null
Get-ChildItem -LiteralPath $sourceRoot -Force | Copy-Item -Destination $destination -Recurse
$executable = Join-Path $destination 'bin/dm/dm.exe'
& $executable --version
if ($LASTEXITCODE -ne 0) { throw 'Installed executable failed its version check' }
Write-Output "Installed: $executable"
Write-Output "Add this directory to your user PATH: $(Split-Path -Parent $executable)"
