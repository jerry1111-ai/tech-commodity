@echo off
chcp 65001 >nul
set KEY=C:\Users\28687\Downloads\12345678zzj.pem
set HOST=ubuntu@43.143.5.234
set SRCFILE=D:\桌面\ifind数据接口实验\宏观数据.xlsx

echo ================================================
echo   宏观数据同步到云端
echo ================================================
echo.
if not exist "%SRCFILE%" (
    echo [错误] 找不到文件：%SRCFILE%
    pause
    exit /b 1
)

echo [1/3] 上传宏观数据.xlsx ...
scp -i "%KEY%" -o StrictHostKeyChecking=no "%SRCFILE%" %HOST%:/opt/app/
if errorlevel 1 (
    echo [失败] 上传中断，请检查网络
    pause
    exit /b 1
)

echo [2/3] 服务器重新计算宏观评分 ...
ssh -i "%KEY%" -o StrictHostKeyChecking=no %HOST% "cd /opt/app/update_tool && /opt/app/.venv/bin/python build_macro.py 2>&1 | tail -4"

echo [3/3] 重新生成页面 ...
ssh -i "%KEY%" -o StrictHostKeyChecking=no %HOST% "cd /opt/app/update_tool && /opt/app/.venv/bin/python build_html.py 2>&1 | tail -2"

echo.
echo ================================================
echo   完成！刷新网页即可看到最新宏观数据
echo   http://43.143.5.234
echo ================================================
pause
