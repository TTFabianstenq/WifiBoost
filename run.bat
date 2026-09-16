@echo off
py -3 -m pip install -r "%~dp0requirements.txt"
py -3 "%~dp0src\wifiboost.py"
