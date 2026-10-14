@echo off
echo ===============================================================
echo Starting Google Chrome with Remote Debugging (Port 9222)
echo ===============================================================
echo.
echo Closing existing Chrome processes to allow Remote Debugging port 9222 binding...
taskkill /F /IM chrome.exe >nul 2>&1
timeout /t 1 /nobreak >nul

set "CHROME_EXE=C:\Program Files\Google\Chrome\Application\chrome.exe"
if not exist "%CHROME_EXE%" set "CHROME_EXE=C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"

echo Launching Chrome with your active tabs restored on port 9222...
set "USER_DATA_DIR=%LOCALAPPDATA%\Google\Chrome\User Data"
start "" "%CHROME_EXE%" --remote-debugging-port=9222 "--user-data-dir=%USER_DATA_DIR%" --remote-allow-origins=* --restore-last-session --disable-session-crashed-bubble --hide-crash-restore-bubble --start-maximized "http://localhost:8080"

echo.
echo [SUCCESS] Chrome is now running with Remote Debugging on port 9222!
echo All your active tabs, accounts, and logins are preserved.
echo The scraper will now open new tabs directly inside this Chrome window.
echo ===============================================================
