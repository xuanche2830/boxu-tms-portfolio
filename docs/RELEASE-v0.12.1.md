# Windows 演示程序

这次增加了一个可以双击启动的 Windows x64 演示程序。下载 `Boxu-Demo-Windows-x64.exe` 后运行，程序会在本机打开浏览器，载入六种运输阶段的合成订单。关闭程序窗口即可停止；练习数据留在当前 Windows 用户的 `%LOCALAPPDATA%\BoxuTMS\demo`，下次启动还能继续看。

此程序仅用于体验项目物流协同流程，不需要另装 Python，也不会连接飞书、UPS 或 FedEx。它没有代码签名，首次打开时 Windows 可能出现安全提示。本版尚未在其他人的电脑上验证。

下载页另附 `.sha256` 文件。可在 PowerShell 运行 `Get-FileHash .\Boxu-Demo-Windows-x64.exe -Algorithm SHA256`，将结果与文件中的哈希值核对。具体用法和已知限制见 [Windows EXE 说明](https://github.com/xuanche2830/boxu-tms-portfolio/blob/v0.12.1/docs/DESKTOP-EXE.md)。

当前仍是预发行原型，尚未用于正式业务。演示里的企业、人员和订单均为合成资料。
