@echo off
rem Abre a interface antiga por abas (a Central Musical e a entrada padrao).
cd /d "%~dp0"
where py >nul 2>nul && (
  py -3 main.py --classica
) || (
  python main.py --classica
)
if errorlevel 1 pause
