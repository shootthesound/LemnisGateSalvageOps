@echo off
cd /d "%~dp0"
python -c "import PIL" 2>nul || python -m pip install --user pillow
python studio.py
if errorlevel 1 pause
