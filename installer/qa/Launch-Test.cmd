@echo off
setlocal
set "ROOT=%~dp0"
if exist "%ROOT%fail.flag" (
  >"%ROOT%outcome.txt" echo FAIL:7
  exit /b 7
)
>"%ROOT%outcome.txt" echo PASS:0
exit /b 0
