@echo off
rem ===========================================================================
rem  Baixador-Mp3 - instalacao no Windows (execute UMA vez, com internet)
rem
rem  O que este script faz:
rem   1. verifica o Python (e orienta a instalar se faltar);
rem   2. instala as dependencias Python (yt-dlp, mutagen, Pillow);
rem   3. baixa yt-dlp.exe e ffmpeg.exe para a pasta "ferramentas";
rem   4. cria as pastas Musicas\ Videos\ e Capas\;
rem   5. confere tudo rodando "python musica.py check".
rem
rem  Nada aqui mexe em pastas do sistema: tudo fica dentro desta pasta.
rem ===========================================================================
setlocal enabledelayedexpansion
cd /d "%~dp0"
title Baixador-Mp3 - instalacao
echo.
echo ============================================
echo   BAIXADOR-MP3 - INSTALACAO
echo ============================================
echo.

rem ---------- 1) Python -----------------------------------------------------
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY (
  where python >nul 2>nul && set "PY=python"
)
if not defined PY (
  echo [ERRO] Python nao encontrado.
  echo.
  echo   1^) Baixe em https://www.python.org/downloads/windows/
  echo   2^) Na primeira tela do instalador marque "Add python.exe to PATH"
  echo   3^) Rode este arquivo novamente.
  echo.
  pause
  exit /b 1
)
for /f "delims=" %%v in ('%PY% -c "import sys;print(sys.version.split()[0])"') do set "VER=%%v"
echo [OK] Python !VER! encontrado.

rem ---------- 2) Dependencias Python ---------------------------------------
echo.
echo [..] Instalando dependencias Python (yt-dlp, mutagen, Pillow)...
%PY% -m pip install --upgrade pip >nul 2>&1
%PY% -m pip install -r requirements.txt
if errorlevel 1 (
  echo [ERRO] Falha ao instalar as dependencias. Verifique sua internet.
  pause
  exit /b 1
)
echo [OK] Dependencias instaladas.

rem ---------- 3) Ferramentas (yt-dlp.exe e ffmpeg.exe) ---------------------
if not exist "ferramentas" mkdir "ferramentas"
echo.
echo [..] Baixando yt-dlp.exe...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ErrorActionPreference='Stop';" ^
  "try { Invoke-WebRequest -Uri 'https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe' -OutFile 'ferramentas\yt-dlp.exe' -UseBasicParsing; Write-Host '[OK] yt-dlp.exe' } catch { Write-Host '[AVISO] Nao foi possivel baixar o yt-dlp.exe:' $_.Exception.Message }"

echo [..] Baixando FFmpeg (build oficial gyan.dev)...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ErrorActionPreference='Stop';" ^
  "try {" ^
  "  $zip = Join-Path $env:TEMP 'ffmpeg-baixador.zip';" ^
  "  Invoke-WebRequest -Uri 'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip' -OutFile $zip -UseBasicParsing;" ^
  "  $dir = Join-Path $env:TEMP ('ffmpeg-baixador-' + [guid]::NewGuid());" ^
  "  Expand-Archive -Path $zip -DestinationPath $dir -Force;" ^
  "  $exe = Get-ChildItem -Path $dir -Recurse -Filter 'ffmpeg.exe' | Select-Object -First 1;" ^
  "  $probe = Get-ChildItem -Path $dir -Recurse -Filter 'ffprobe.exe' | Select-Object -First 1;" ^
  "  if ($exe) { Copy-Item $exe.FullName 'ferramentas\ffmpeg.exe' -Force; Write-Host '[OK] ffmpeg.exe' };" ^
  "  if ($probe) { Copy-Item $probe.FullName 'ferramentas\ffprobe.exe' -Force };" ^
  "  Remove-Item $zip,$dir -Recurse -Force -ErrorAction SilentlyContinue" ^
  "} catch { Write-Host '[AVISO] Nao foi possivel baixar o FFmpeg automaticamente.'; Write-Host '        Baixe em https://ffmpeg.org/download.html e coloque ffmpeg.exe em ferramentas\' }"

rem ---------- 4) Pastas ----------------------------------------------------
for %%p in (Musicas Videos Capas) do if not exist "%%p" mkdir "%%p"
echo [OK] Pastas Musicas\, Videos\ e Capas\ prontas.

rem ---------- 5) Verificacao ----------------------------------------------
echo.
echo [..] Verificando instalacao...
%PY% musica.py check
if errorlevel 1 (
  echo.
  echo [AVISO] Falta alguma ferramenta. O programa abre, mas downloads
  echo         de MP3 precisam do FFmpeg. Rode este instalador de novo com
  echo         internet ou coloque ffmpeg.exe em ferramentas\.
) else (
  echo.
  echo ============================================
  echo   TUDO PRONTO!
  echo ============================================
  echo   Abra o programa com:  iniciar.bat
  echo.
)
echo.
pause
