@echo off
rem Baixador-Mp3 - abre o programa (interface grafica) com dois cliques.
rem Na primeira vez, rode configurar.bat.
cd /d "%~dp0"
title Baixador-Mp3
set "PY="
set "PYW="
where py >nul 2>nul && set "PY=py -3"
if not defined PY (
  where python >nul 2>nul && set "PY=python"
)
if not defined PY (
  echo [ERRO] Python nao encontrado. Rode configurar.bat primeiro.
  pause
  exit /b 1
)
rem pythonw = sem janela de console; se nao existir, usa python normal.
set "PYW="
where pythonw >nul 2>nul && set "PYW=pythonw"
if defined PYW (
  start "" %PYW% interface.py
) else (
  %PY% interface.py
  if errorlevel 1 (
    echo.
    echo O programa encontrou um erro. Rode configurar.bat e tente de novo.
    pause
  )
)
