@echo off
echo Criando tarefa agendada para iniciar arbitragem com o Windows...

schtasks /create /tn "Arbitragem ETH" /tr "cmd /c start \"\" /MIN C:\arbitragem\iniciar.bat" /sc onlogon /delay 0001:00 /rl highest /f

echo.
echo Tarefa criada com sucesso!
echo A arbitragem vai iniciar automaticamente 1 minuto apos o login.
echo.
pause
