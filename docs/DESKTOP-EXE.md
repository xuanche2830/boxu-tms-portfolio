# Windows 演示程序

`Boxu-Demo-Windows-x64.exe` 是本机合成演示入口。双击后会出现一个程序窗口，随后在默认浏览器打开泊序。页面只通过 `127.0.0.1` 在这台电脑上访问；关闭程序窗口即停止服务。它不需要另装 Python，也不会连接飞书或承运商。

首次运行会创建六种阶段的合成订单。之后的练习内容保存在 `%LOCALAPPDATA%\BoxuTMS\demo`，重新启动仍可看到。请不要把这个目录当成正式业务数据库；本发行物只用于演示。若默认端口 8769 已被占用，程序会选另一个本机端口，并在窗口里显示实际地址。

发行页同时提供一个 `.sha256` 文件。下载后可以在 PowerShell 里核对：

```powershell
Get-FileHash .\Boxu-Demo-Windows-x64.exe -Algorithm SHA256
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

生成的 EXE 和 SHA-256 文件位于仓库同级的 `release-build/`。构建内容包括前端页面、迁移文件、演示所需的公开规则资料、Python 代码、解释器与依赖；本机 `data/`、账号、数据库、附件与日志都不进入 EXE。

发行页上的 EXE 在 GitHub 托管的 Windows 环境完成打包，并通过启动、演示库初始化和页面响应检查。随后下载同一个发行文件到本地 Windows 11 x64，再次核对 SHA-256、启动和演示页。尚未在其他人的 Windows 设备、不同杀毒软件环境或代码签名后验证。也可直接按 [README](../README.md) 用 Python 运行源码。
