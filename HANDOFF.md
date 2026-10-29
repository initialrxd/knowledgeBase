# 会话交接：本地 PDF 知识分享系统与 Open WebUI

## 2026-10-23：原生 PDF 上传的 Slim 限制已修复

- 用户开始使用 Open WebUI 原生知识库；Slim 模式的默认解析器拒绝 PDF 并返回 503。
- 启动器现在默认使用标准模式（`KB_WEBUI_SLIM=false`）和本地 Chroma；embedding、回答仍使用云 API。
- 隔离验证通过本地 PDF 读取和 Chroma 初始化；重启后 `/api/config` 确认 `features.slim=false`。
- 普通 `deepseek-v4.1-flash` 已重新启用原生知识库工具；外部服务专用 JSON 预设仍停用原生知识库工具。
- 测试账号通过真实文件 API 上传一个合成 PDF，状态 `completed`，向量检索命中唯一校验词；仅清理了本次合成文件。证据：`data/webui-native-validation.json`。
- 已有失败上传仍需重试/重新上传。原生知识库与原有独立 PDF 库分别存储，未迁移或清空原有资料。
- 此节更新此前关于 Slim 运行模式和普通 DeepSeek 原生工具开关的历史记录。

> 日期：2026-10-22（Asia/Shanghai）。本文不包含任何 API Key、访问令牌或管理员密码。
> 下一会话先读本文和 README，再查询实际运行状态；后台导入进度会继续变化。

## 1. 用户的原始需求

- 在本机 setup 基于 LLM 的知识分享系统，以 PDF 作为 Raw Data。
- 输入可以是已分类的目录，也可以是单独 PDF；未分类文件需要先整理分类。
- 新文件沿用既有分类，必要时允许新增类别；不要把每次新增变成全库重分类。
- 原始数据库变化后增量切片、增量向量化，避免不必要的重复 embedding。
- embedding 使用已有云 API，不要求本地部署 embedding 或 LLM。
- 知识库可以更换底层 LLM，并能迁移到其他电脑；原始 PDF 和切片都必须带走。

## 2. 对话中确认和修改的需求

| 事项 | 最终选择 |
|---|---|
| 调用方式 | 让 LLM 直接调用；同时提供 MCP 和 HTTP |
| 初始规模假设 | 大规模混合资料，百万页以上或暂不清楚；必须实际测量，不能承诺百万页性能 |
| 资料整理 | 生成分类副本，保留原始输入目录 |
| 部署 | Windows + Python，无 Docker/WSL2 |
| PDF 内容 | 文字、表格及扫描 OCR；不承诺纯图表/公式的语义理解 |
| 用户强调的提取规则 | 非图片型 PDF 直接读取原文本层，OCR 只按需使用 |
| 管理入口 | 命令行和 API；Open WebUI 作为聊天界面 |
| Open WebUI 集成 | 独立知识库服务通过 OpenAPI 接入，MCP 留给其他客户端 |
| 公网访问 | 最初接受自建 Agent + ngrok；后来明确改为“暂时仅本地使用，不需要公网登录” |
| 回答模型 | 用户指定 `deepseek-v4.1-flash` |
| embedding 模型 | 用户指定 `qwen3.7-text-embedding` |
| 分类模型 | 默认 `qwen3.7-flash`，可单独配置 |
| 凭据 | 用户已提供，本机 `.env` 已配置；不要复制到回复、代码或文档 |
| 测试资料 | `C:\Users\xdran\Desktop\Knowledge_DB` |
| 本文要求 | 完成后生成 Markdown，包含原始需求、对话变更、features、TODO，供下一会话继承 |
| 界面验收 | 用户已自行创建管理员及专用测试账户，并授权登录测试；凭据仅在会话中提供，不写入本文 |

## 3. 环境和接入配置

- 项目：`C:\Users\xdran\Documents\ChatGPT\Knowledge_Sharing_System 2`。
- 系统已有 Python 3.11.9；知识库 `.venv` 与 Open WebUI `.venv-webui` 隔离。
- 聊天与 embedding 的 Base URL：`https://dmzaiapi.calterah.com/v1`。
- 实测 `/embedding` 返回 404，标准 **`/embeddings`** 可用，返回 **1024 维**。
- embedding 请求只发送 `model` 和 `input`；本地配置的 dimensions 用于校验结果，不发送维度缩减参数。
- 当前配置批量 8；遇到 400/413 批量错误会拆小请求，并在进程内记住较小批量。
- 本机不支持最新版 NumPy 2.4 的 CPU baseline：知识库锁定 NumPy 1.26.4、OpenCV 4.11；Open WebUI 使用 NumPy 2.2.6。
- LanceDB 0.40.0 和 ONNX Runtime 已在本机加载验证。
- tokenizer `cl100k_base` 字典已下载到 `data/cache/tiktoken/`。曾误拒下载，用户随后明确允许；当前默认正常使用 tokenizer。
- Open WebUI 0.12.3 已安装并运行，健康检查及 `/api/config` 返回 200。
- Open WebUI 启动器启用 slim 运行分支，避免加载本地推理后端；不需要 Docker，不下载本地 LLM/embedding 权重。

## 4. 已实现的功能

### 数据处理

- 递归目录和单个 PDF 接入；保留已有相对目录分类。
- 未分类文档调用分类模型，优先复用类别；置信度不足或分类 API 失败进入“待分类”，保留警告。
- 人工修正并锁定分类，避免后续自动覆盖。
- 原件按 SHA-256 留存，分类副本保存在独立 library，原文件名加文档 ID 避免同名覆盖。
- 默认直接读取原生文本并按位置排序；表格默认保留原生文本。
- `KB_PDF_LAYOUT=structured` 可启用 Markdown 表格/版面提取，耗时更高。
- `KB_OCR_MODE=auto/off/force`；默认只对无有效文本或乱码页按需 OCR。
- 文字页插图默认保存资源，不自动做图片区域 OCR；需要时设置 `KB_OCR_IMAGE_REGIONS=true`。
- OCR 使用本机 RapidOCR/ONNX CPU，线程数受限。图片/纯图形内容不自动获得语义理解。
- 按页、段落和章节切片；长表格分段重复表头；保留章节、PDF 物理页码、文本哈希和提取方式。
- UTF-8 边界安全，避免切片损坏中文字符。

### 增量和恢复

- 文件内容哈希去重，重复导入跳过；内容相同的切片复用 embedding 缓存。
- 文本提取逐页检查点，可恢复损坏的最后一行 JSONL。
- 持久化任务队列，支持状态查询、暂停、恢复、重试和优雅停止。
- 首次导入的 pending document ID 持久化，失败重试能使用同一解析目录。
- 新版全部向量完成后才原子发布；失败更新继续提供旧版本。
- 文件系统监听 + 默认 300 秒补充扫描；支持完整 SHA-256 校验扫描。
- 来源文件消失只标记缺失；显式删除从检索中移除，原件和历史保留。
- embedding 模型/维度/处理配置分别建表，重建完成后才切换，不混用不同模型向量。

### 查询与接入

- SQLite FTS5 + jieba 的 BM25 与向量检索融合排序。
- 分类（包含子类别）和文档过滤；只返回当前版本、未删除文档。
- HTTP 查询工具：`search_knowledge`、`get_chunk`、`get_document`、`list_categories`。
- 应用接口 `/v1/ask` 调用 DeepSeek，并校验引用片段 ID。
- MCP Streamable HTTP `/mcp`；stdio 是访问主服务的代理，避免多进程直接争用索引。
- 查询和管理使用不同 Bearer Token；管理只绑定 loopback；远程查询描述不包含管理接口。
- 限流、返回页数/片段数限制；不在日志记录 API Key 或文档请求正文。
- Open WebUI 后台已预置启用的 OpenAPI 连接，默认模型已保存为 DeepSeek。
- 提供专用模型预设 `config/openwebui-model.json`，可在 Workspace > Models 导入。

### 迁移

- 流式导出带完成标记、格式版本和 SHA-256 清单的文件夹。
- 包含原件、分类副本、Markdown、逐页 JSONL、切片 JSONL、资源、分类、版本、Parquet 向量和 tokenizer 字典。
- 同时包含 application 源码、安装脚本、配置示例、本文和依赖锁定文件；不依赖原电脑 Git remote。
- 从空库恢复，先校验完整性；重建关键词索引和 embedding 缓存；不恢复原电脑来源目录监听。
- 可省略向量导出，恢复后重建；更换回答模型不需要重建向量。
- Open WebUI 账号和聊天记录单独备份，不放进知识库导出包。

## 5. 运行与常用命令

所有命令在项目根目录执行，先确保服务已启动。

```powershell
.\scripts\Start-All.ps1
# 或分别启动
.\scripts\Start-Knowledge.ps1 -Background
.\scripts\Start-OpenWebUI.ps1 -Background

.\.venv\Scripts\python.exe -m knowledge_service.cli status
.\.venv\Scripts\python.exe -m knowledge_service.cli documents
.\.venv\Scripts\python.exe -m knowledge_service.cli ingest 'C:\Users\xdran\Desktop\Knowledge_DB'
.\.venv\Scripts\python.exe -m knowledge_service.cli search '毫米波雷达如何校准'
.\.venv\Scripts\python.exe -m knowledge_service.cli ask '毫米波雷达为什么需要校准'
.\.venv\Scripts\python.exe -m knowledge_service.cli retry
.\.venv\Scripts\python.exe -m knowledge_service.cli scan --verify
.\.venv\Scripts\python.exe -m knowledge_service.cli stop
```

| 地址 | 用途 |
|---|---|
| http://127.0.0.1:8080 | Open WebUI，用户已自行配置管理员和测试账户 |
| http://127.0.0.1:8766/openapi.json | OpenAPI 查询工具描述 |
| http://127.0.0.1:8766/mcp | MCP HTTP |
| http://127.0.0.1:8765/docs | 仅本机管理 API，使用 ADMIN Token |

- `.env` 保存凭据和模型配置，已被 Git 忽略；改动后重启对应服务。
- `data/` 保存知识库；`openwebui-data/` 保存 Open WebUI 数据；`logs/` 保存后台日志。
- 登录 Open WebUI 后启用“本地 PDF 知识库”工具或导入专用模型预设。
- 用户已自行创建账户；没有修改管理员账户或保存测试密码。
- 浏览器访问 `http://127.0.0.1:8080` 先被用户拒绝，用户随后授权测试。用户再回复“已允许访问”后，重试仍被保存的拒绝规则/管理策略阻止，尚未提交登录。该限制尚未实际解除；不要通过其他浏览器、接口登录或底层自动化绕过访问策略。服务端 API 验证另有证据。

## 6. 已有验证证据

- 最终完整 pytest：**23 passed**，另有一条 Starlette TestClient 弃用警告；耗时约 79 秒。
- 随后优化长手册的关键词发布：每个版本只清理一次 FTS，避免每个切片扫描整张 FTS；增加 publishing 阶段进度。该修改后的处理流程定向测试 **16 passed**（约 80 秒）。测试前设置 `$env:TIKTOKEN_CACHE_DIR = Join-Path (Get-Location) 'data\cache\tiktoken'`，否则单独运行纯 tokenizer 测试可能尝试联网下载并被沙箱代理阻止；服务运行本身会设置缓存路径。
- 全库首次导出暴露 Windows MAX_PATH 问题：分类目录和长文件名叠加后复制失败。现已为导出/恢复的数据复制启用 Windows extended path；扩展现有迁移测试覆盖超过 260 字符的资源路径，迁移及篡改检测 **2 passed**，ruff 通过。失败导出的 `.partial-*` 不可用于迁移，暂保留供核查。
- ruff 检查通过；两个环境 `pip check` 无依赖冲突。
- 真实 HTTP 与 MCP 协议验证通过：4 个公开查询工具、10 个混合检索结果、DeepSeek 回答含 4 个有效片段引用；证据 `data/validation.json`。
- 真实分类 API 验证通过：复用 `TI/AWR2944/Application_note`，没有警告；证据 `tmp/classifier-check/report.json`。
- 真实本机 OCR 验证通过：合成扫描页识别 31 个字符，没有警告、未调用云 API；证据 `tmp/ocr-check/report.json`。OCR 模型随 RapidOCR 包提供，不额外下载。
- Open WebUI 启动日志确认初始化了 1 个工具服务器，健康及配置接口均为 200；这不等同于已登录或界面问答通过。
- 真实 20 页校准 PDF 已走通：提取、26 个切片、Qwen embedding、DeepSeek 引用回答、重复导入跳过、导出后恢复并检索。
- 该早期 smoke 的参数是 OCR off/早期解析器；最终默认 native/auto 的全库结果以运行快照为准。
- 测试来源共有 **31 份 PDF、7,382 页、95,562,321 字节**。
- 其中《AWR294x Technical Reference Manual (Rev. D)》为 **6,913 页、8,692 个切片**，已全部生成向量并发布。
- 中途实测 DeepSeek 可能将多数输出预算用于 reasoning；回答输出预算已调整到 8,192，并检测空文本/截断，不发布不完整答案。
- `/v1/ask` 会拒绝缺失/编造的片段 ID；这只是引用有效性校验，不代表对所有语义陈述的正确性做了证明。

## 7. TODO 与明确边界

### 本轮收尾/下一会话优先核对

1. 本轮全量导入已完成；接手时仍需查询实时状态，检查后续新增文件和任务。
2. 同配置 reindex 已完成索引整理，未重复调用 embedding API。当前 9,564 条向量未达到自动训练 IVF_FLAT 的 10,000 行阈值，使用精确向量扫描；不能宣称 ANN 已训练或百万页性能已验证。
3. `scripts/verify_running.py` 的 HTTP、DeepSeek 引用及 MCP 验证已通过；最新复验结果见文末。
4. 完整 pytest 23 项已通过；仅在代码变动、失败或新风险出现时重跑相关测试。
5. 用户已创建 Open WebUI 账户。待 Codex 浏览器访问限制解除后，验证测试账户的工具可见性、实际检索和来源引用；不能将服务端验证当作界面验收。

### 后续能力（不冒充已完成）

- 大规模压测：百万页容量、峰值 RSS、向量索引 recall、延迟与云 API 费用。现有小样本不能证明百万页可用性。
- 更完整的中文/复杂版面/扫描件质量评估；合成扫描页及回归测试不等于真实资料识别准确率保证。
- Open WebUI 原生引用卡片与 PDF 点击预览。
- Open WebUI 上传文件同步进入外部知识库、分类浏览、任务进度管理网页。
- 必须先检索再回答的固定 RAG 适配层；目前 Open WebUI 工具由模型自主调用，系统提示词不能强制。
- 对接 Dify/AnythingLLM 等具体产品的导入适配；当前只提供开放格式导出。
- 多用户/逐文档 ACL、多租户、企业权限尚未实现；读取令牌可访问整个知识库。
- 图表/公式语义、多模态解析未实现。
- 类别数量非常多时，需要分类体系候选检索；当前仅向分类模型传入有限数量的已有类别。
- 历史版本、过期向量/缓存与孤立资源的保留/清理策略需按长期使用情况完善；不要直接删除用户数据。
- 公网接入/OAuth：用户已明确暂不需要。ngrok 脚本保留，不启用、不索取账户。

## 8. 接手注意

- 未经用户要求，不创建新聊天、不委派子 agent、不提交或推送代码。
- API Key 已存在 `.env`；需要检查时只报告是否配置，不回显内容。
- 原始测试目录是用户数据，禁止移动、重命名或删除其中的文件。
- 后台进程来自本项目；正常使用 `knowledge stop` 停止主服务，避免强杀而丢失当前批次进度。
- 更换模型和迁移先验证 profile、维度、处理规则，不能因为维度相同就复用另一模型向量。
- 不将“服务健康检查成功”等同于“用户已登录”或“Open WebUI 聊天端到端已验收”。

## 9. 最终运行快照

- 全部测试来源已发布：**31 份 PDF / 7,382 页 / 9,564 个切片**，来源 31，失败导入任务 0。
- 主服务已优雅停止并重新启动，已加载最终的 FTS 写入优化、索引整理和单文件监听修正；Open WebUI 保持运行，未改动用户账户。
- 同 embedding profile 的 reindex 已完成，整理 31 份资料的向量，无需重新生成已完成的 embedding。
- 最终重启及全库发布后的 `scripts/verify_running.py` 再次通过：4 个 HTTP 工具、10 条真实混合检索结果、DeepSeek 回答 3 个有效片段引用、MCP 初始化/工具列表/调用成功。最终报告 `data/validation.json`。
- 长手册 PDF 第 2 页报告 `ocr_no_text` 和 `no_extractable_text` 两条警告，其余页面完成。已用原 PDF 核查该页：0 文本字符、0 图片、0 绘图对象，是空白页；原始警告仍保留。
- 界面验收仍被 Codex 浏览器 origin 权限策略阻止：用户已再次明确允许，但读取已打开的登录页仍返回保存的拒绝规则/管理策略；尚未提交测试账号登录。
- 2026-10-23 追加核查：用户截图显示默认及 `http://127.0.0.1:8080` 的浏览权限均为“始终允许”；只读检查 `C:\Users\xdran\.codex\config.toml`，该 origin 的 `access` 也确为 `allow`。浏览器工具仍返回 saved permission/managed policy deny。因此不能继续认定是用户未开启该网站权限；实际原因尚未确认，可能涉及运行中的权限状态未刷新或其他管理策略。建议完全重启桌面应用后在同一会话复测；仍失败则提交权限显示与执行结果不一致的问题。没有修改用户安全配置，没有通过其他方式绕过 origin 拒绝。
- 用户随后确认已重启 Codex；重启后对已打开登录页的 `cua.getTab` 复测仍被相同 origin gate 拒绝，尚未提交任何登录信息。重启未解决，不能再将重启作为已知有效修复；下一步需由产品支持/管理员排查权限执行结果与 UI/配置不一致的原因。
- 2026-10-23 深入诊断见 `docs/BROWSER_ACCESS_DIAGNOSTICS.md`：通过桌面 bundled Codex 的只读 app-server 方法检查，新诊断进程的生效 origin 规则仍为 allow、未加载管理 requirements；但当前聊天 Browser Use 仍拒绝。MCP 在桌面日志中为 ready；CLI doctor 的授权环境变量警告不能证明桌面缺变量。`/debug-config` 在当前聊天没有返回诊断结果，不要反复要求用户发送。未修复宿主授权问题，未修改安全策略或绕过拒绝。
- 全库迁移包：`exports/knowledge-20261022/`，已包含 `COMPLETE`；**1,821 个校验文件、364,103,766 字节、31 份原件、9,564 个切片、9,564 条向量**。逐文件大小及 SHA-256、清单完整性、向量/切片数量一致性均通过；应用源码未包含当前 API Key。证据 `data/export-validation.json`。该次全库包没有再完整恢复一遍；恢复功能有真实小库 smoke 和含 Windows 长路径的回归测试证据。
- 导出任务首次失败后已成功重试，最终任务为 done、无 error。失败遗留目录 `exports/knowledge-20261022.partial-d98046ac/` 没有完成标记，不可用于恢复；它只是失败导出的副本，可在确认完整迁移包后清理，不涉及源 PDF。
- 导出包的 `application/HANDOFF.md` 是打包时的快照；本项目根目录本文还包含包完成后的校验结果，以这里为最新交接记录。
