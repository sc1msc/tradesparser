@echo off
rem HonestLot: daily pipeline run from Windows Task Scheduler (task "HonestLot\Pipeline").
rem See automation.py and "run_pipeline.py --auto".
cd /d "%~dp0"
".venv\Scripts\python.exe" -X utf8 run_pipeline.py --auto
