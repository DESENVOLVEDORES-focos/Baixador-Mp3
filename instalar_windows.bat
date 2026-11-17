@echo off
rem Baixador-Mp3 - instalacao no Windows (execute uma unica vez).
cd /d "%~dp0"
where py >nul 2>nul && set PY=py -3 || set PY=python
%PY% --version || (echo Python nao encontrado. Instale em https://www.python.org/downloads/ marcando "Add python.exe to PATH". & pause & exit /b 1)
%PY% -m pip install --upgrade pip
%PY% -m pip install -r requirements.txt
echo.
echo Instalacao concluida. Garanta que o FFmpeg esta instalado e no PATH
echo (https://ffmpeg.org/download.html) e de dois cliques em iniciar_interface.bat
pause
