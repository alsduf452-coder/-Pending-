@echo off
setlocal
pushd "%~dp0"
echo App version: REV-03
echo App folder: %CD%
if exist ".venv312\Scripts\python.exe" (
  ".venv312\Scripts\python.exe" -m streamlit run app.py
) else if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -m streamlit run app.py
) else (
  echo No local Python environment found.
  echo Install first: py -3.12 -m venv .venv312
  echo Then: .venv312\Scripts\python.exe -m pip install -r requirements.txt
)
popd
pause
