@echo off
setlocal
chcp 65001 >nul
title RUSHBOT :: Statlockle Rush solver
color 0B
mode con: cols=92 lines=40 >nul 2>nul

set "HERE=%~dp0"
cd /d "%HERE%"

:home
cls
echo.
type banner.txt
echo.
echo   statlockle rush solver  .  humanized  .  ranked
echo   ------------------------------------------------------------
echo.

where python >nul 2>nul
if errorlevel 1 goto nopython

python -c "import cryptography" >nul 2>nul
if errorlevel 1 (
  echo   [~] installing dependencies ^(cryptography^)...
  python -m pip install -q -r requirements.txt
  if errorlevel 1 goto pipfail
)

echo   [ok] python + deps ready
echo.
echo   [1]  setup cookie      (grab session from a browser)
echo   [2]  play a run        (humanized, max score)
echo   [3]  run x3            (storm the leaderboard)
echo   [4]  refresh datasets  (public stats drift)
echo   [5]  leaderboard       (top entries)
echo   [q]  quit
echo.
set /p "opt=  : "

if /i "%opt%"=="1" goto setup
if /i "%opt%"=="2" goto play
if /i "%opt%"=="3" goto run3
if /i "%opt%"=="4" goto fetch
if /i "%opt%"=="5" goto board
if /i "%opt%"=="q" exit /b 0
goto home

:nopython
echo   [x] python not found - install python 3.10+ from https://python.org
pause
exit /b 1

:pipfail
echo   [x] pip install failed - run: python -m pip install -r requirements.txt
pause
goto home

:setup
cls
echo.
echo   setup cookie - read the statlocker session from a local browser
echo.
echo   browser:  [1] brave   [2] chrome   [3] edge
set /p "br=  : "
set "BROWSER=brave"
if "%br%"=="2" set "BROWSER=chrome"
if "%br%"=="3" set "BROWSER=edge"
echo.
echo   profile (enter = Default, or e.g. "Profile 1")
set /p "prof=  : "
if "%prof%"=="" set "prof=Default"
echo.
echo   extracting from %BROWSER%/%prof% ...
python -m rushbot brave --browser %BROWSER% --profile %prof%
if errorlevel 1 (
  echo   [x] could not read cookies - are you logged into statlocker.gg in that profile?
) else (
  echo   [ok] cookie written to data/cookie.txt
)
echo.
pause
goto home

:play
cls
echo.
echo   play a run - humanized pacing, slow-reader speed bonus
echo.
python -m rushbot play --latency --read-speed slow
echo.
pause
goto home

:run3
cls
echo.
echo   run x3 - three attempts, best valid run wins
echo.
for /l %%i in (1,1,3) do (
  echo   --- attempt %%i/3
  python -m rushbot play --latency --read-speed slow
  echo.
)
pause
goto home

:fetch
cls
echo.
echo   refresh datasets - re-download heroes / items / usage stats
echo.
python -m rushbot fetch
echo.
echo   [ok] datasets refreshed
echo.
pause
goto home

:board
cls
echo.
echo   leaderboard
echo.
python -m rushbot board
echo.
pause
goto home
