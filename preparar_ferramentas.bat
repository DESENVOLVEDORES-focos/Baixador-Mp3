@echo off
rem ===========================================================================
rem  Baixador-Mp3 - preparar ferramentas (FFmpeg e yt-dlp)
rem
rem  Este pacote pode trazer o FFmpeg ja incluido (ferramentas\ffmpeg.zip).
rem  Este script:
rem    1. extrai o ffmpeg.exe incluido, se existir (instantaneo, sem internet);
rem    2. baixa o yt-dlp.exe se ele ainda nao estiver na pasta;
rem    3. cria a pasta ferramentas\ quando falta;
rem    4. diz o que ficou pronto e o que faltou.
rem
rem  Nada aqui mexe em pastas do sistema: tudo fica dentro desta pasta.
rem ===========================================================================
setlocal enabledelayedexpansion
cd /d "%~dp0"
title Baixador-Mp3 - preparar ferramentas
echo.
echo ============================================
echo   BAIXADOR-MP3 - PREPARAR FERRAMENTAS
echo ============================================
echo.

if not exist "ferramentas" mkdir "ferramentas"

rem ---------- 1) FFmpeg incluido no pacote --------------------------------
if exist "ferramentas\ffmpeg.exe" (
  echo [OK] ffmpeg.exe ja esta em ferramentas\.
  goto ffmpeg_pronto
)
if exist "ferramentas\ffmpeg.zip" (
  echo [..] Extraindo o FFmpeg que vem no pacote...
  powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$ErrorActionPreference='Stop';" ^
    "$dir = Join-Path $env:TEMP ('ffmpeg-pacote-' + [guid]::NewGuid());" ^
    "try {" ^
    "  Expand-Archive -Path 'ferramentas\ffmpeg.zip' -DestinationPath $dir -Force;" ^
    "  $exe = Get-ChildItem -Path $dir -Recurse -Filter 'ffmpeg.exe' | Select-Object -First 1;" ^
    "  $probe = Get-ChildItem -Path $dir -Recurse -Filter 'ffprobe.exe' | Select-Object -First 1;" ^
    "  if ($exe) { Copy-Item $exe.FullName 'ferramentas\ffmpeg.exe' -Force };" ^
    "  if ($probe) { Copy-Item $probe.FullName 'ferramentas\ffprobe.exe' -Force }" ^
    "} finally { Remove-Item $dir -Recurse -Force -ErrorAction SilentlyContinue }"
  if exist "ferramentas\ffmpeg.exe" (
    echo [OK] ffmpeg.exe extraido do pacote.
    del /q "ferramentas\ffmpeg.zip" >nul 2>&1
  ) else (
    echo [AVISO] Nao consegui extrair ferramentas\ffmpeg.zip.
    echo         Rode configurar.bat para baixar o FFmpeg da internet.
  )
) else (
  echo [AVISO] O FFmpeg nao veio neste pacote ^(ferramentas\ffmpeg.zip ausente^).
  echo         Rode configurar.bat, que baixa o FFmpeg da internet.
)
:ffmpeg_pronto

rem ---------- 2) yt-dlp ----------------------------------------------------
set "TEM_YTDLP="
if exist "ferramentas\yt-dlp.exe" (
  "ferramentas\yt-dlp.exe" --version >nul 2>&1 && set "TEM_YTDLP=1"
)
if defined TEM_YTDLP (
  echo [OK] yt-dlp.exe ja esta em ferramentas\.
  goto ytdlp_pronto
)

echo [..] Baixando yt-dlp.exe ^(~24 MB^)...
if exist "ferramentas\yt-dlp.zip" del /q "ferramentas\yt-dlp.zip" >nul 2>&1
where curl >nul 2>nul
if not errorlevel 1 (
  curl.exe -L --fail --retry 3 --progress-bar -o "ferramentas\yt-dlp.exe" ^
    "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe"
) else (
  powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$ErrorActionPreference='Stop'; try { Invoke-WebRequest -Uri 'https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe' -OutFile 'ferramentas\yt-dlp.exe' -UseBasicParsing } catch { exit 1 }"
)
if exist "ferramentas\yt-dlp.exe" (
  echo [OK] yt-dlp.exe
) else (
  echo [AVISO] Nao consegui baixar o yt-dlp.exe.
  echo         Alternativa sem baixar nada: rode configurar.bat, que instala o
  echo         yt-dlp pelo pip ^(o programa usa "python -m yt_dlp" sozinho^).
)
:ytdlp_pronto

rem ---------- 3) Pastas ----------------------------------------------------
for %%p in (Musicas Videos Capas) do if not exist "%%p" mkdir "%%p"

echo.
echo ---------- Resumo ----------
if exist "ferramentas\ffmpeg.exe" (echo  FFmpeg : OK) else (echo  FFmpeg : FALTANDO)
if exist "ferramentas\yt-dlp.exe" (echo  yt-dlp : OK em ferramentas\) else (echo  yt-dlp : nao esta em ferramentas\ [pode vir do pip])
echo.
echo Proximo passo: iniciar.bat
echo.
pause
