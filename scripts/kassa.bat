@echo off
rem Kassa oynasi: chek chop etish oynasi chiqmasdan togridan-togri standart printerga boradi.
rem Windows sozlamalarida termoprinterni "standart printer" qilib qoying.
set URL=http://127.0.0.1:8000/savdo/kassa/
set CHROME=%ProgramFiles%\Google\Chrome\Application\chrome.exe
if not exist "%CHROME%" set CHROME=%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe
if not exist "%CHROME%" set CHROME=%LocalAppData%\Google\Chrome\Application\chrome.exe
if exist "%CHROME%" (
  start "" "%CHROME%" --kiosk-printing --user-data-dir="%LocalAppData%\DokonKassa" --app=%URL%
) else (
  start "" "%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe" --kiosk-printing --user-data-dir="%LocalAppData%\DokonKassa" --app=%URL%
)
