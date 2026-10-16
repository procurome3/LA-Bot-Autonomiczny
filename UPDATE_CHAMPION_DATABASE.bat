@echo off
setlocal
cd /d "%~dp0"
echo =====================================================
echo  Live Arena V16.5 - Champion Kit DB Live Forms Updater
echo  FACTS ONLY - tier/ranking/rating data are discarded
echo  Primary: HellHades current form and game skill identifiers
echo  All Mythical forms fetched separately; legacy preview fallback
echo =====================================================
py -m pip install -r requirements_livearena.txt
if errorlevel 1 goto :error

echo.
echo Building/updating Legendary + Mythical database...
py tools\update_champion_database_api.py --resume --rarity legendary mythical --workers 4
if errorlevel 1 goto :partial
py tools\validate_champion_database.py --report data\champion_database_validation_report.json
if errorlevel 1 goto :partial

echo.
echo Database update complete and validation passed.
echo See data\champion_database_update_report.json for coverage/status.
pause
exit /b 0

:partial
echo.
echo Update finished, but some records are still partial/failed/unmatched.
echo Run this BAT again. --resume keeps completed champions and retries gaps.
echo See data\champion_database_update_report.json for exact coverage.
pause
exit /b 1

:error
echo.
echo Dependency installation failed.
pause
exit /b 2
