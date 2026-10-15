@echo off
REM BLNG 单对话批量生成启动器（供计划任务调用，脱离工具会话）
cd /d "C:\Users\Administrator\WorkBuddy\2026-10-09-10-02-25\blng-agent"
set NO_PROXY=localhost,127.0.0.1,::1,0.0.0.0
set no_proxy=localhost,127.0.0.1,::1,0.0.0.0
set HTTP_PROXY=
set HTTPS_PROXY=
"C:\Users\Administrator\.workbuddy\binaries\python\envs\default\Scripts\python.exe" blng_conversation.py --file basketball_prompts.json --name basketball >> "runlog\basketball_run.log" 2>> "runlog\basketball_run.err.log"
echo EXIT_CODE=%ERRORLEVEL% >> "runlog\basketball_run.log"
