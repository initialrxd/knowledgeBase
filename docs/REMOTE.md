# 远程 Agent 接入

服务只在本机监听；通过你自己的 ngrok 账户提供 HTTPS 通道。
云端 Agent 必须支持自行设置 Authorization 请求头。本版不提供面向第三方云助手的 OAuth 登录。

1. 从 ngrok 官方渠道安装 Windows agent，并按官方说明配置账户 authtoken。
2. 在 `.env` 设置 `KB_PUBLIC_BASE_URL=https://你的域名.ngrok.app`。
3. 重启知识库服务。
4. 运行 `scripts\Start-Remote.ps1 -Url https://你的域名.ngrok.app`。
5. 云端 Agent 调用 `/v1/search` 等接口，携带 `Authorization: Bearer <KB_API_TOKEN>`。
6. MCP 客户端连接同一域名的 `/mcp`，使用相同的读取令牌。

只转发查询端口 **8766**。管理端口 **8765** 始终仅供本机使用，不要建立公网隧道。
远程工具没有导入、删除、分类修改、文件系统读取或导出能力。
`/v1/ask` 会使用你的聊天 API 额度，请仅向可信调用方分发读取令牌。

账户域名和令牌由你在本机填写。未提供 ngrok 账户时，代码可以完成本机验收，但无法建立真实公网通道。
本机、知识库进程和 ngrok 进程都需要保持运行。

官方安装说明：https://ngrok.com/docs/start
