@echo off
cd /d "%~dp0"
python -m pip install -r requirements.txt
python hxv4_gui.py
pause
