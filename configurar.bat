@echo off
rem ===========================================================================
rem  Baixador-Mp3 - instalacao no Windows (execute UMA vez, com internet)
rem
rem  O que este script faz:
rem   1. verifica o Python (e orienta a instalar se faltar);
rem   2. instala as dependencias Python (yt-dlp, mutagen, Pillow);
rem   3. baixa yt-dlp.exe e ffmpeg.exe para a pasta "ferramentas";
rem   4. cria as pastas Musicas\ Videos\ e Capas\;
rem   5. confere tudo rodando "python -m baixador.app.musica check".
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
rem  Regras desta etapa:
rem   - se a ferramenta ja existe e responde, NAO baixa de novo (economiza
rem     muito tempo quando o configurar.bat roda de novo);
rem   - usa curl.exe (nativo no Windows 10/11, rapido e com barra de
rem     progresso) e so cai para o PowerShell se o curl falhar;
rem   - o FFmpeg (~85 MB) vem em ZIP: o download e feito pelo curl e a
rem     extracao pelo Expand-Archive, que e local e instantaneo.
if not exist "ferramentas" mkdir "ferramentas"

echo.
set "TEM_YTDLP="
if exist "ferramentas\yt-dlp.exe" (
  "ferramentas\yt-dlp.exe" --version >nul 2>&1 && set "TEM_YTDLP=1"
)
if defined TEM_YTDLP (
  echo [OK] yt-dlp.exe ja esta em ferramentas\ ^(nao precisa baixar de novo^).
) else (
  echo [..] Baixando yt-dlp.exe ^(~17 MB^)...
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
    echo [AVISO] Nao foi possivel baixar o yt-dlp.exe automaticamente.
    echo         Baixe em https://github.com/yt-dlp/yt-dlp/releases
    echo         e coloque o arquivo yt-dlp.exe em ferramentas\
  )
)

set "TEM_FFMPEG="
if exist "ferramentas\ffmpeg.exe" (
  "ferramentas\ffmpeg.exe" -version >nul 2>&1 && set "TEM_FFMPEG=1"
)
if defined TEM_FFMPEG (
  echo [OK] ffmpeg.exe ja esta em ferramentas\ ^(nao precisa baixar de novo^).
) else (
  echo [..] Baixando FFmpeg ^(~85 MB, o arquivo demora alguns minutos^)...
  echo      Dica: deixe esta janela aberta; o progresso aparece abaixo.
  if exist "ferramentas\ffmpeg.zip" del /q "ferramentas\ffmpeg.zip"
  where curl >nul 2>nul
  if not errorlevel 1 (
    curl.exe -L --fail --retry 3 --progress-bar -o "ferramentas\ffmpeg.zip" ^
      "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
  ) else (
    powershell -NoProfile -ExecutionPolicy Bypass -Command ^
      "$ErrorActionPreference='Stop'; try { Invoke-WebRequest -Uri 'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip' -OutFile 'ferramentas\ffmpeg.zip' -UseBasicParsing } catch { exit 1 }"
  )
  if exist "ferramentas\ffmpeg.zip" (
    echo [..] Extraindo os executaveis do ZIP...
    powershell -NoProfile -ExecutionPolicy Bypass -Command ^
      "$ErrorActionPreference='Stop';" ^
      "$dir = Join-Path $env:TEMP ('ffmpeg-baixador-' + [guid]::NewGuid());" ^
      "try {" ^
      "  Expand-Archive -Path 'ferramentas\ffmpeg.zip' -DestinationPath $dir -Force;" ^
      "  $exe = Get-ChildItem -Path $dir -Recurse -Filter 'ffmpeg.exe' | Select-Object -First 1;" ^
      "  $probe = Get-ChildItem -Path $dir -Recurse -Filter 'ffprobe.exe' | Select-Object -First 1;" ^
      "  if ($exe) { Copy-Item $exe.FullName 'ferramentas\ffmpeg.exe' -Force };" ^
      "  if ($probe) { Copy-Item $probe.FullName 'ferramentas\ffprobe.exe' -Force }" ^
      "} finally { Remove-Item $dir -Recurse -Force -ErrorAction SilentlyContinue }"
    del /q "ferramentas\ffmpeg.zip"
  )
  if exist "ferramentas\ffmpeg.exe" (
    echo [OK] ffmpeg.exe
  ) else (
    echo [AVISO] Nao foi possivel baixar o FFmpeg automaticamente.
    echo         Baixe em https://www.gyan.dev/ffmpeg/builds/
    echo         ^(arquivo ffmpeg-release-essentials.zip^), extraia e coloque
    echo         ffmpeg.exe dentro da pasta ferramentas\
  )
)

rem ---------- 4) Pastas ----------------------------------------------------
for %%p in (Musicas Videos Capas) do if not exist "%%p" mkdir "%%p"
echo [OK] Pastas Musicas\, Videos\ e Capas\ prontas.

rem ---------- 5) Verificacao ----------------------------------------------
echo.
echo [..] Verificando instalacao...
%PY% -m baixador.app.musica check
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
