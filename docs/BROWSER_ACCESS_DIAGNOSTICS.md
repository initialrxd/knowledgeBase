# 浏览器授权不一致诊断记录

日期：2026-10-23，Asia/Shanghai。没有包含账户密码、API Key、登录 Token 或浏览历史。本次没有自动提交反馈或上传日志。

## 当前结果

Open WebUI 的界面登录测试仍未执行。Codex Browser Use 在读取页面、填写账号之前就拒绝访问 `http://127.0.0.1:8080`。

工具返回：

> A saved permission or managed policy denies access.

这不能证明用户设置仍为拒绝；下面的检查表明允许设置与运行结果不一致。实际根因尚未确认，不能声称已经修复。

## 已确认的证据

1. 用户提供的设置截图：默认浏览和该 HTTP origin 的浏览均为“始终允许”。
2. 只读解析用户的 `C:\Users\xdran\.codex\config.toml`：`browser_use.origins["http://127.0.0.1:8080"].access` 是 `allow`。
3. 用户已完全重启桌面应用；重启后同一 origin 仍被拒绝。不要再次把重复重启/重新设置允许当作已验证的修复。
4. 使用桌面应用实际选择的 bundled Codex executable，通过官方 app-server 的 `initialize`、`config/read`、`configRequirements/read` 做了只读诊断，没有启动聊天或模型任务，没有调用配置写入方法：
   - 诊断进程报告 `Codex Desktop/0.163.0-alpha.11`。
   - 从工程目录读取的生效配置中，该 HTTP origin 的 access 仍为 `allow`。
   - 配置层显示用户 config 和系统 config；系统层没有浏览器覆盖。
   - `configRequirements/read` 没有返回管理 requirements。
   - **范围限制：这是新诊断进程，不是已运行聊天内部的配置快照，不能据此排除聊天覆盖、桌面授权桥接或其他运行时规则。**
5. 桌面应用日志显示本聊天的 `node_repl` MCP startup 为 `ready`、没有启动错误；浏览器标签页宿主也能建立，随后仍在 origin 授权环节失败。
6. `codex doctor --json` 的桌面 app-server handshake 和 config load 正常。它还给出 MCP 授权环境变量在 CLI 环境缺失的警告，但桌面会话与 CLI 环境不同，**不能将此警告当成已证实的根因，也不应手工伪造这些授权变量**。
7. PATH 中的 npm CLI 与桌面 bundled CLI 版本不同；它们是不同安装，不足以单独证明不兼容。后续配置诊断已使用桌面 bundled executable。

脱敏的机器可读结果在 `tmp/browser-policy-diagnostic.json`；复现读取脚本在 `tmp/read_browser_policy.py`。tmp 为本机诊断材料，不属于正式知识库导出。

## 已尝试及边界

- 新建同一 IAB origin 的标签页、读取用户打开的标签页都被拒绝。
- 没有改动 Codex 安全配置、管理 requirements、授权缓存或验证身份。
- 没有改用 localhost、其他端口、代理、其他浏览器、CDP 或脚本登录来绕过拒绝。
- 没有因通用 doctor 警告去关闭 Defender、修改沙箱或添加排除项。
- 用户两次发送 `/debug-config`，当前聊天中只收到命令文本，没有得到配置面板或诊断输出。该命令来自官方 CLI/开发配置说明，不能保证本桌面聊天支持；不要反复要求用户发送同一命令。

## 可提交给产品支持的问题描述

```text
Windows 桌面应用 Browser Use 的站点允许规则与执行结果不一致。
目标 origin：http://127.0.0.1:8080。
设置 UI 显示该站点浏览“始终允许”，config.toml 的 access=allow。
重启后，读取页面和导航仍报 A saved permission or managed policy denies access。
使用桌面 bundled Codex 的 config/read 确认新诊断进程生效规则为 allow；
configRequirements/read 未返回管理 requirements，MCP startup 日志为 ready。
请排查当前聊天授权上下文、origin gate 的实际规则来源和拒绝原因。
尚未提交任何站点登录信息。
```

当前需要产品支持或具备授权诊断能力的管理员提供实际拒绝来源；工程本身不能修复宿主应用的 origin gate。知识库后台先前已独立通过 HTTP/MCP/真实模型验证，但这不等于 Open WebUI 界面测试通过。

官方参考：

- https://learn.chatgpt.com/docs/app/settings
- https://learn.chatgpt.com/docs/app-server
- https://learn.chatgpt.com/docs/developer-settings
