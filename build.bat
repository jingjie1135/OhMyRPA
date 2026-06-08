@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul

set SOURCE_DIR=%~dp0
set BUILD_DIR=G:\MirrorAutomationBuild
set OUTPUT_DIR=%SOURCE_DIR%dist

echo ==========================================
echo 镜界自动化 - Nuitka 自动打包脚本
echo ==========================================
echo.

echo 1. 清理并准备纯英文编译目录: %BUILD_DIR%
if exist "%BUILD_DIR%" rmdir /s /q "%BUILD_DIR%"
mkdir "%BUILD_DIR%"

echo 2. 复制源码到编译目录 (规避中文路径问题)...
robocopy "%SOURCE_DIR:~0,-1%" "%BUILD_DIR%" /E /XD ".git" "__pycache__" "dist" "Daily" "Scripts" "Workflows" "targets" "popups" "*.build" /XF "nuitka-crash-report.xml" "build.bat" >nul
if %errorlevel% GEQ 8 (
    echo [错误] 复制文件失败
    pause
    exit /b %errorlevel%
)

echo 3. 开始 Nuitka 编译...
echo [注意] 此过程需要完整编译 C 代码，取决于 CPU 性能，通常需要 15~30 分钟。
echo [提示] 期间如果看似卡住请耐心等待。
cd /d "%BUILD_DIR%"

python -m nuitka --onefile --enable-plugin=pyqt6 --windows-console-mode=disable --windows-icon-from-ico=icon.png --include-data-file=scrcpy-server=scrcpy-server --include-data-file=icon.png=icon.png --include-package-data=av --include-module=av.sidedata.encparams --include-module=av.sidedata.motionvectors --onefile-tempdir-spec="{TEMP}/MirrorAutomation" --output-dir=dist --output-filename=MirrorAutomation.exe --assume-yes-for-downloads gui.py

if %errorlevel% neq 0 (
    echo.
    echo [错误] Nuitka 编译失败！请向上传递上方报错信息。
    pause
    exit /b %errorlevel%
)

echo.
echo 4. 复制编译产物回原项目目录...
if not exist "%OUTPUT_DIR%" mkdir "%OUTPUT_DIR%"
copy /y "%BUILD_DIR%\dist\MirrorAutomation.exe" "%OUTPUT_DIR%\MirrorAutomation.exe" >nul

echo 5. 清理临时编译目录...
cd /d "%SOURCE_DIR%"
rmdir /s /q "%BUILD_DIR%"

echo.
echo ========================================================
echo 🎉 编译成功！
echo ✅ 可执行文件位置: %OUTPUT_DIR%\MirrorAutomation.exe
echo. 
echo [运行说明]
echo - 单文件版本在首次双击时，会解压到临时目录，大概有 3~5 秒无反应，属于正常现象。
echo - 程序会在 exe 同级目录下自动读取/生成 Scripts 文件夹。
echo ========================================================
pause
