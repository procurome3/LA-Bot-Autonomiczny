$ErrorActionPreference = "Stop"

$BotDir = (Resolve-Path $PSScriptRoot).Path
$ProfilesDir = Join-Path $BotDir "draft_profiles"
$Runner = Join-Path $BotDir "profile_start.py"
$Raid = Join-Path $BotDir "raid.py"

if (-not (Test-Path $Runner)) {
    throw "Brak profile_start.py w folderze bota."
}

if (-not (Test-Path $ProfilesDir)) {
    throw "Brak folderu draft_profiles."
}

if (-not (Test-Path $Raid)) {
    Write-Host ""
    Write-Host "UWAGA: w tym folderze nie ma jeszcze raid.py." -ForegroundColor Yellow
    Write-Host "Komendy zostaną utworzone, ale zaczną działać dopiero gdy raid.py"
    Write-Host "będzie znajdował się w tym samym folderze co profile_start.py."
    Write-Host ""
}

$profiles = Get-ChildItem -Path $ProfilesDir -Filter "*.json" -File
if (-not $profiles) {
    throw "Brak plików JSON w draft_profiles."
}

$created = @()

foreach ($file in $profiles) {
    $name = $file.BaseName.ToLowerInvariant()

    if ($name -notmatch '^[a-z0-9_-]+$') {
        Write-Host "Pomijam profil o niebezpiecznej nazwie: $($file.Name)" -ForegroundColor Yellow
        continue
    }

    $cmdPath = Join-Path $BotDir ($name + ".cmd")
    $content = @"
@echo off
setlocal
cd /d "%~dp0"
py profile_start.py $name %*
"@
    [System.IO.File]::WriteAllText($cmdPath, $content, [System.Text.Encoding]::ASCII)
    $created += $name
}

# Add the bot directory to the user's PATH, without SETX truncation.
$UserPath = [Environment]::GetEnvironmentVariable("Path", "User")
$parts = @()
if ($UserPath) {
    $parts = $UserPath.Split(";") | Where-Object { $_ -and $_.Trim() -ne "" }
}

$alreadyThere = $false
foreach ($p in $parts) {
    try {
        if ([System.IO.Path]::GetFullPath($p.Trim()) -ieq [System.IO.Path]::GetFullPath($BotDir)) {
            $alreadyThere = $true
            break
        }
    } catch {}
}

if (-not $alreadyThere) {
    $newPath = ((@($parts) + @($BotDir)) | Select-Object -Unique) -join ";"
    [Environment]::SetEnvironmentVariable("Path", $newPath, "User")
}

Write-Host ""
Write-Host "Utworzono komendy profili:" -ForegroundColor Green
foreach ($name in $created) {
    Write-Host ("  " + $name) -ForegroundColor Cyan
}

Write-Host ""
Write-Host "Każda z tych komend uruchamia teraz RAID.PY OD POCZĄTKU:" -ForegroundColor Yellow
Write-Host "  Fresh start -> closeadds -> unfinishedBattleCheck -> dalsze aktywne moduły -> Live Arena"
Write-Host ""
Write-Host "Po dodaniu nowego pliku draft_profiles\nazwa.json uruchom ten instalator ponownie."
Write-Host "Zamknij obecny PowerShell/CMD i otwórz nowe okno, jeśli PATH został zmieniony."
Write-Host ""
Read-Host "Naciśnij Enter, aby zamknąć"
