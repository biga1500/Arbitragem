@echo off
cd /d C:\arbitragem

:loop
echo [%date% %time%] Iniciando arbitragem... >> logs\run.log
python run.py >> logs\run.log 2>> logs\run_err.log
echo [%date% %time%] Processo encerrado. Reiniciando em 10s... >> logs\run.log
timeout /t 10 /nobreak > nul
goto loop
