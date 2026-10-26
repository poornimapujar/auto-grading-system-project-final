@echo off
cd /d "%~dp0"
echo ===== GradeAI start =====
echo Installing requirements (only needed the first time)...
py -m pip install -r requirements.txt
echo.
where ollama >nul 2>&1
if errorlevel 1 goto noollama
echo Found Ollama. Checking the FREE local model (the first time it downloads about 2 GB)...
ollama pull qwen2.5:3b
goto askkey
:noollama
echo Ollama is NOT installed. Install it from https://ollama.com for the free local AI model.
:askkey
echo.
set /p KEY=Press Enter to use the FREE local model, or paste a Claude API key (paid) instead: 
if not "%KEY%"=="" set ANTHROPIC_API_KEY=%KEY%
echo.
echo Opening the browser in a few seconds. KEEP THIS WINDOW OPEN.
start "" cmd /c "timeout /t 5 >nul & start http://127.0.0.1:5000"
py app.py
echo.
echo ===== The server stopped. Read the messages above. =====
pause
