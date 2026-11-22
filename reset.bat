@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul

echo ====================================================================
echo   RESET DE DADOS LOCAIS - PORTFOLIO TECNICO
echo ====================================================================
echo.
echo ATENCAO: Este script vai apagar TODOS os dados dentro da pasta "dados\":
echo   - Banco de dados SQLite (dados\banco\*)
echo   - Imagens, avatar, curriculo e PDFs (dados\midias\*)
echo   - Logs (dados\logs\*)
echo   - Snapshots pre-restore (dados\backups_pre_restore\*)
echo.
echo O arquivo ".env" e os ".gitkeep" serao PRESERVADOS.
echo.
set /p CONFIRMA=Digite RESET em maiusculas para confirmar: 
if not "%CONFIRMA%"=="RESET" (
    echo.
    echo Operacao cancelada. Nenhum arquivo foi apagado.
    pause
    exit /b 0
)

echo.
echo [1/3] Parando container Docker (se estiver rodando)...
docker compose down >nul 2>&1

echo [2/3] Limpando arquivos persistentes em dados\...
for %%D in ("dados\banco" "dados\midias" "dados\logs" "dados\backups_pre_restore") do (
    if exist "%%~D" (
        for /d %%S in ("%%~D\*") do rd /s /q "%%~S" 2>nul
        for %%F in ("%%~D\*") do (
            if /i not "%%~nxF"==".gitkeep" del /f /q "%%~F" 2>nul
        )
    )
)

echo [3/3] Garantindo estrutura base com .gitkeep...
if not exist "dados\banco" mkdir "dados\banco"
if not exist "dados\midias" mkdir "dados\midias"
if not exist "dados\logs" mkdir "dados\logs"
if not exist "dados\.gitkeep" type nul > "dados\.gitkeep"
if not exist "dados\banco\.gitkeep" type nul > "dados\banco\.gitkeep"
if not exist "dados\midias\.gitkeep" type nul > "dados\midias\.gitkeep"
if not exist "dados\logs\.gitkeep" type nul > "dados\logs\.gitkeep"

echo.
echo Concluido! A pasta "dados\" foi zerada mantendo o ".env".
echo Para subir a aplicacao limpa e testar a restauracao do backup:
echo     docker compose up --build
echo.
pause

