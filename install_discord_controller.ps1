# install_discord_controller.ps1
# Instaluje discord_controller.py jako ukryte zadanie Harmonogramu zadań Windows.
# Zadanie uruchamia się automatycznie po zalogowaniu użytkownika.

$ErrorActionPreference = "Stop"

$TaskName = "RaidDiscordController"
$ProjectDir = "C:\Users\procu\OneDrive\Pulpit\LA R\raid-scripts"
$ControllerPath = Join-Path $ProjectDir "discord_controller.py"

Write-Host ""
Write-Host "=== Instalacja Raid Discord Controller ===" -ForegroundColor Cyan
Write-Host ""

# 1. Sprawdź plik kontrolera.
if (-not (Test-Path $ControllerPath)) {
    throw "Nie znaleziono: $ControllerPath"
}

# 2. Sprawdź wymagane zmienne środowiskowe użytkownika.
$BotToken = [Environment]::GetEnvironmentVariable("DISCORD_BOT_TOKEN", "User")
$AllowedUserId = [Environment]::GetEnvironmentVariable("DISCORD_ALLOWED_USER_ID", "User")

if ([string]::IsNullOrWhiteSpace($BotToken)) {
    throw "Brak zmiennej DISCORD_BOT_TOKEN. Najpierw ustaw ją poleceniem setx DISCORD_BOT_TOKEN `"TOKEN`"."
}

if ([string]::IsNullOrWhiteSpace($AllowedUserId)) {
    throw "Brak zmiennej DISCORD_ALLOWED_USER_ID. Najpierw ustaw ją poleceniem setx DISCORD_ALLOWED_USER_ID `"TWOJE_ID`"."
}

# 3. Znajdź interpreter Pythona używany przez launcher 'py'.
try {
    $PythonExe = (& py -c "import sys; print(sys.executable)" 2>$null).Trim()
} catch {
    throw "Nie udało się znaleźć Pythona przez polecenie 'py'."
}

if ([string]::IsNullOrWhiteSpace($PythonExe) -or -not (Test-Path $PythonExe)) {
    throw "Nie znaleziono interpretera Python."
}

# pythonw.exe działa bez widocznego okna konsoli.
$PythonDir = Split-Path $PythonExe -Parent
$PythonwExe = Join-Path $PythonDir "pythonw.exe"

if (-not (Test-Path $PythonwExe)) {
    Write-Host "Nie znaleziono pythonw.exe. Użyję python.exe z ukrytym oknem." -ForegroundColor Yellow
    $PythonwExe = $PythonExe
}

Write-Host "Python:      $PythonwExe"
Write-Host "Controller:  $ControllerPath"
Write-Host "Task:        $TaskName"
Write-Host ""

# 4. Usuń starą wersję zadania, jeśli istnieje.
$ExistingTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($ExistingTask) {
    Write-Host "Usuwam poprzednią wersję zadania..." -ForegroundColor Yellow
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

# 5. Akcja: uruchom discord_controller.py.
$Action = New-ScheduledTaskAction `
    -Execute $PythonwExe `
    -Argument "`"$ControllerPath`"" `
    -WorkingDirectory $ProjectDir

# 6. Trigger: po zalogowaniu bieżącego użytkownika.
$Trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME

# 7. Ustawienia:
# - nie uruchamiaj drugiej kopii,
# - pozwól działać bez limitu czasu,
# - uruchom ponownie po awarii.
$Settings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -RestartCount 5 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -StartWhenAvailable

# Ważne dla pyautogui: zadanie działa w interaktywnej sesji zalogowanego użytkownika.
$Principal = New-ScheduledTaskPrincipal `
    -UserId "$env:USERDOMAIN\$env:USERNAME" `
    -LogonType Interactive `
    -RunLevel Limited

# 8. Zarejestruj zadanie.
Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Settings $Settings `
    -Principal $Principal `
    -Description "Discord controller do zdalnego uruchamiania RAID i raid.py." `
    -Force | Out-Null

Write-Host "Zadanie zostało utworzone." -ForegroundColor Green

# 9. Uruchom od razu.
Start-ScheduledTask -TaskName $TaskName
Start-Sleep -Seconds 2

$Task = Get-ScheduledTask -TaskName $TaskName
$Info = Get-ScheduledTaskInfo -TaskName $TaskName

Write-Host ""
Write-Host "Stan zadania: $($Task.State)" -ForegroundColor Green
Write-Host "Ostatni wynik: $($Info.LastTaskResult)"
Write-Host ""
Write-Host "Gotowe." -ForegroundColor Green
Write-Host "Możesz zamknąć PowerShell. Kontroler Discord będzie działał w tle."
Write-Host "Po następnym zalogowaniu do Windows uruchomi się automatycznie."
Write-Host ""
Write-Host "Test na Discordzie: !raid status" -ForegroundColor Cyan
Write-Host ""
Write-Host "Aby zatrzymać kontroler ręcznie:"
Write-Host "  Stop-ScheduledTask -TaskName `"$TaskName`""
Write-Host ""
Write-Host "Aby uruchomić ponownie:"
Write-Host "  Start-ScheduledTask -TaskName `"$TaskName`""
Write-Host ""
