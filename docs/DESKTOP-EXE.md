# Windows 本地使用版

普通使用者下载 `Boxu-Windows-x64.zip`，全部解压后双击 `Boxu-Windows-x64.exe`。图形启动窗口提供合成演示、自己的工作空间、资料目录、使用说明和完整备份恢复入口。页面通过 `127.0.0.1` 在本机访问，不需要安装 Python、Node.js 或数据库。详细操作见包内“先读我.html”或 [第一次使用](QUICK-START.html)。

演示首次创建六阶段合成订单，仍使用 v0.12.1 的 `%LOCALAPPDATA%\BoxuTMS\demo`。独立工作空间使用 `%LOCALAPPDATA%\BoxuTMS\work`，首次设置自己的负责人；不会复制作者的源码工作库或账号。资料在升级与重启后保留。源代码启动的 `data/work` 与 EXE 工作空间不是同一份资料；需要迁移时先制作完整备份，再用启动窗口恢复到空白空间。

默认演示端口 8769、工作端口 8768 被占用时，桌面程序选另一个本机端口并显示实际地址。已启动的同一空间可以重复打开页面，不能启动第二个写入服务。切换空间请使用启动窗口，防止跳到另一套本机服务。关闭窗口会停止该窗口启动的服务；如果页面正在保存，先等保存完成再退出。

恢复仅面向空白工作空间，已有资料会被拒绝覆盖。备份包含账号验证资料和附件，恢复后仍使用原账号密码，旧登录会话不恢复。运行日志位于对应空间的 `logs/application.log`，启动与恢复失败的简短原因位于 `startup-error.log`。这两个文件可能含本机信息，公开反馈前应脱敏。

发行页同时提供一个 `.sha256` 文件。下载后可以在 PowerShell 里核对：

```powershell
Get-FileHash .\Boxu-Windows-x64.zip -Algorithm SHA256
```

显示的哈希值应与 `.sha256` 文件一致。此 EXE 尚未进行代码签名；部分 Windows 设备可能显示安全提示。不要从不明来源下载同名文件。

## 从源码重建

在 Windows x64 上安装 Python 3.12，克隆仓库，在根目录运行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install PyInstaller==6.22.3
.\scripts\build_exe.ps1
```

先按 README 安装前端依赖并运行 `pnpm build`。生成的 EXE、使用包 ZIP 和 SHA-256 文件位于仓库同级的 `release-build/`。构建内容包括前端页面、迁移文件、公开规则、用户说明、Python/Tk 运行时与依赖；本机数据库、账号、附件、备份和日志都不进入资源清单。包内收集第三方依赖许可。

最终使用包必须运行 `python scripts/check_desktop.py --executable <EXE路径>`，在源码目录以外检查图形入口初始化、两种空间、账号创建、数据持久化、重复启动、端口避让及空库备份恢复。发布前还需通过 `python scripts/check.py all` 和前端构建；具体结果见 [验证记录](VALIDATION.md)。自动检查不代表已在其他人的 Windows 设备或所有杀毒软件环境验证。
