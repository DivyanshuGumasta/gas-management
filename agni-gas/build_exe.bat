@echo off
REM Builds dist\AgniGas\AgniGas.exe  (run on Windows, Python 3.11+ installed)
python -m pip install -r requirements.txt pyinstaller
pyinstaller --noconfirm --windowed --name AgniGas ^
  --add-data "templates;templates" ^
  --add-data "static;static" ^
  --add-data "schema.sql;." ^
  desktop.py
echo.
echo Done. Copy the dist\AgniGas folder to the client's laptop.
echo Data is stored in %%APPDATA%%\AgniGas (database + daily backups).
pause
