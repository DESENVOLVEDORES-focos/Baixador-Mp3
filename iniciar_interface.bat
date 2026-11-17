@echo off
rem Baixador-Mp3 - abre a interface grafica sem precisar de terminal.
cd /d "%~dp0"
where py >nul 2>nul && (py -3 interface.py & goto :fim)
python interface.py
:fim
if errorlevel 1 (
  echo.
  echo O programa encontrou um erro. Confira se o Python esta instalado
  echo e execute instalar_windows.bat uma vez.
  pause
)
