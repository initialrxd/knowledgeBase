# knowledgeBase · 本地 PDF 知识库

面向 Windows / macOS 的 Python 原生部署知识库。PDF 原件、分类副本、提取正文、切片和向量均可带走。
聊天、分类及 embedding 使用你自己的云 API；不需要部署本地 LLM 或 embedding 模型。

## 主要功能

- 导入单个 PDF 或持续监听文件夹，保留已有目录分类，自动整理未分类文档。
- 优先提取 PDF 文本层，按需 OCR，按页码和章节切片，保存原件与图片资源。
- 使用云端 embedding，结合 LanceDB 向量检索与 SQLite FTS5 / jieba 关键词检索。
- 本机管理台独立管理多个知识库、入库与检索参数，以及可关联多个库的 MCP 服务。
- 增量更新、内容去重、embedding 缓存和任务恢复；新版本完成后再替换旧版检索内容。
- 通过 HTTP / OpenAPI / MCP 提供查询，使用 Open WebUI 聊天并展示来源页码。
- 使用未保存的检索参数连续测试，查看平均耗时、服务端阶段计时及每次明细。
- 导出 PDF、正文、切片、元数据及向量，迁移后可继续使用或更换模型。

## 环境要求

- Windows x64 + PowerShell，或 macOS（Apple Silicon / Intel）。
- Python 3.11 / 3.12，推荐 3.11；Windows PowerShell 安装脚本使用 `py -3.11`。
- Git，用于克隆仓库；不需要 Docker 或 WSL。
- 可访问的 OpenAI 兼容聊天与 embedding API，分别配置地址、模型和密钥。
- 首次安装需要联网下载 Python 依赖和 tokenizer 词表；OCR 按需加载本机识别模型。

知识库服务与 Open WebUI 使用独立虚拟环境，避免依赖版本冲突。
项目包声明支持 Python `>=3.11,<3.13`。Windows 已本机回归；macOS 入口与两种架构依赖已适配，
实机验证范围及限制见 [平台兼容性与验证范围](docs/COMPATIBILITY.md)。本机 Windows 测试结果不能替代 macOS 验收。

## 快速启动

Windows：在 PowerShell 中克隆并安装：

```powershell
git clone https://github.com/initialrxd/knowledgeBase.git
Set-Location knowledgeBase
.\scripts\Install.ps1 -WithOpenWebUI
```

macOS：在终端中克隆并安装（先安装原生架构的 Python 3.11）：

```bash
git clone https://github.com/initialrxd/knowledgeBase.git
cd knowledgeBase
python3.11 scripts/manage.py install --with-openwebui
```

上面的 Open WebUI 安装命令适用于 Apple Silicon。Intel Mac 使用
`python3.11 scripts/manage.py install` 安装管理台及 HTTP / MCP 服务；当前 Open WebUI 版本
固定的原生依赖未提供 Intel macOS 安装包，暂不支持在 Intel Mac 上原生安装此聊天界面。

macOS 按本机平台解析依赖，不直接套用 Windows 的 `requirements*.lock.txt`。
Intel Mac 对 LanceDB / ONNX Runtime 使用独立版本约束；Apple Silicon 请使用原生 arm64 Python。
只需管理台和 HTTP / MCP 时省略 `--with-openwebui`；不需要 OCR 时添加 `--without-ocr`。
该选项在全新环境中省略 OCR 依赖，不会卸载已有环境中的 OCR 包。

安装脚本创建 `.venv` 和可选的 `.venv-webui`、安装对应平台依赖，并在 `.env` 不存在时根据
[配置示例](.env.example) 创建配置，自动生成查询与管理令牌。已有 `.env` 不会被覆盖。

编辑本机 `.env`，至少填写以下配置，再启动服务：

| 配置项 | 用途 |
|---|---|
| `KB_CHAT_BASE_URL` / `KB_CHAT_API_KEY` / `KB_CHAT_MODEL` | 回答模型的 API 地址、密钥和模型名 |
| `KB_EMBEDDING_BASE_URL` / `KB_EMBEDDING_API_KEY` / `KB_EMBEDDING_MODEL` | 文本向量 API 地址、密钥和模型名 |
| `KB_EMBEDDING_DIMENSIONS` | 预期向量维度；`0` 表示根据返回值确定 |
| `KB_CLASSIFY_BASE_URL` / `KB_CLASSIFY_API_KEY` / `KB_CLASSIFY_MODEL` | 可选独立分类模型，留空时沿用聊天配置 |
| `KB_DATA_DIR` | 本地知识库目录，默认 `./data` |

API 地址是端点根路径；供应商要求时需包含 `/v1`，不要填写完整的 `/embeddings` 或
`/chat/completions` 路径。回答模型需支持工具调用，才能在 Open WebUI 中调用知识库。

```powershell
.\scripts\Start-All.ps1
```

macOS 配置好 `.env` 后启动（同时适用于 Windows，将 `python3.11` 替换为 `py -3.11`）：

```bash
python3.11 scripts/manage.py start-all
# 只启动管理台：
python3.11 scripts/manage.py start-manager --background
# 保存检查点并请求停止：
python3.11 scripts/manage.py stop-all
```

管理台启动后会打开一次性登录链接；无桌面环境时加 `--no-browser`。
`start-all` 后台启动管理台及 Open WebUI；单独启动服务时加 `--background` 才会转入后台。
`start-knowledge` 可单独启动原 HTTP / MCP 服务，不要同时启动管理台和独立知识库服务。

- 知识库管理台：http://127.0.0.1:8767
- 聊天界面：http://127.0.0.1:8080
- Open WebUI 工具服务器：http://127.0.0.1:8766
- OpenAPI 描述：http://127.0.0.1:8766/openapi.json
- MCP Streamable HTTP：http://127.0.0.1:8766/mcp
- 本地管理 API：http://127.0.0.1:8765/docs

首次打开 Open WebUI 时创建自己的管理员账户，在工具菜单启用“本地 PDF 知识库”。
详见 [Open WebUI 接入](docs/OPENWEBUI.md)。

## 图形化管理

只启动知识库管理台，无需 Open WebUI：

```powershell
.\scripts\Start-Manager.ps1 -Background
```

启动脚本会打开一次性本机登录链接；也可以在登录页输入 `.env` 中的 `KB_ADMIN_TOKEN`。
首次启动将现有 `data` 原地接管为默认库，保留原索引、目录和原来的 8765/8766 接口。
运行中的旧服务会先正常停止并释放数据锁；不会强制结束正在保存数据的进程。

- **知识库**：独立存储与索引，选择 Embedding 配置，添加/停用/移除来源目录，查看完整队列统计、当前任务、可用状态，执行扫描、重试、暂停及重建。
- **Embedding 配置**：可复用的 OpenAI 兼容 API 配置，支持连接测试。连接测试发送一条短文本；运行中的配置每五分钟自动检查一次。
- **MCP 服务**：独立端口及令牌，可关联多个知识库；支持启停、真实 MCP 初始化测试、令牌更换及客户端配置复制。

“运行中”不等于 Ready。模型连接异常、索引待重建或部分库不可用时会显示降级原因；跨库检索返回可用结果和警告。
多库 MCP 返回 `knowledge_base_id`，读取片段或文档时须带上此字段；单库接入可继续使用原工具参数。
更换模型、地址、维度或 Revision 后手动重建索引，完成后再切换；只换 API Key 无需重建。

新建知识库时须填写数据源目录和独立的向量化存储目录；向量位于所选存储目录的 `vectors/`，切片及元数据保存在同一根目录。管理配置及凭据在 `manager-data/`，与知识库迁移包分开；`manager-data/` 和项目内 `knowledge-bases/` 均被 Git 忽略。
MCP 名称、端口、知识库范围和令牌都可以编辑；运行中保存会自动重启该 MCP，应用失败则恢复原配置。
移除来源目录或从管理台移除知识库只解除管理关系，不删除 PDF 和索引。
管理台仅监听本机，暂不提供局域网登录、多用户权限或通用第三方 MCP 程序管理。
任务记录以原文件名展示，悬停可查看完整来源路径，详情显示页数、切片进度与失败原因。
完整操作流程见 [多知识库管理台](docs/MANAGEMENT.md)。

前端已包含生产构建。修改前端后重新构建：

```powershell
cd frontend
npm ci
npm run build
```

生产静态文件在 `knowledge_service/static/`，正常使用不需要运行 Node.js 开发服务器。

需要停止管理台、受管知识库及 Open WebUI 时，运行 `.\scripts\Stop-All.ps1`；
跨平台入口为 `python3.11 scripts/manage.py stop-all`。

只使用 HTTP / MCP 时，可运行 `.\scripts\Install.ps1`，然后运行
`.\scripts\Start-Knowledge.ps1 -Background`，无需安装 Open WebUI。

Open WebUI 原生 Workspace > Knowledge 与本项目的独立知识库分别保存数据。
网页上传不会自动导入本服务；通过下面的命令导入后，在聊天中启用外部知识库工具。

## 入库与检索配置

在管理台选择「知识库 → 详情 → 入库与检索」，可独立调整每个库的参数：

| 配置组 | 可调整内容 | 生效范围 |
|---|---|---|
| 向量化配置 | 切片长度、重叠、OCR、图片区域 OCR、PDF 版面提取、API 并发 | 切片/OCR 用于后续导入和更新；并发上限作用于该库的模型请求 |
| 检索配置 | 默认检索模式、返回片段数、分类和文档范围 | HTTP、MCP、CLI 和内置问答中未显式指定的参数 |
| 共享 Embedding 配置 | API 地址、模型、维度、Revision、密钥、批大小 | 关联该配置的知识库 |

入库与检索分别保存，只更新各自的参数；运行中的库会等待当前批次完成后重启。
管理模式使用每个库保存的配置，应在管理台修改；独立服务从 `.env` 读取配置。
已有且未变化的资料需重新导入才会按新的切片/OCR 参数重新处理，普通扫描和向量重建不会重新切片。
API 并发上限不代表单个入库任务会并行处理多个 Embedding 批次。

请求中的显式参数可覆盖检索默认值，分类或文档范围传空字符串可清除对应默认过滤。
单独启动服务时，也可通过 `.env` 的 `KB_SEARCH_MODE`、`KB_SEARCH_LIMIT`、
`KB_SEARCH_CATEGORY` 和 `KB_SEARCH_DOCUMENT_ID` 配置默认值；默认模式为 `hybrid`，返回 10 条。
多库 MCP 未指定 `limit` 时，各库使用自己的默认数量，合并结果上限取关联库默认数量的最大值。

## 检索测试与耗时

在「检索配置」下输入问题，使用当前表单中尚未保存的参数测试当前知识库。
默认顺序执行 5 次，可选 2–10 次；每次使用相同参数，全部成功后显示算术平均值、每次明细及最后一次结果。
测试不会保存配置；点击「保存检索配置」后才更新系统默认值。任一次失败时，本轮不显示平均值。
混合或向量模式的每次测试都会调用 Embedding API。

| 耗时项 | 含义 |
|---|---|
| 总耗时 | 浏览器发送请求至完成响应解析 |
| 服务端处理（汇总） | 服务内部阶段之和，仅作汇总，不重复相加 |
| 问题向量化 | Embedding 调用，包含等待、重试和响应校验 |
| 关键词检索 | 问题分词、全文查询和关键词排名 |
| 向量检索 | 分类候选过滤、向量查询及数据库锁等待 |
| 结果整理 | 有效片段读取、融合排序、去重和引用生成 |
| 服务端其他处理 | 参数准备、配置读取和资源清理等剩余处理 |
| 请求额外开销 | 总耗时减服务端处理，最小为零；包含管理台转发、传输、序列化和浏览器解析 |

平均值按原始精度计算，以毫秒显示一位小数。未执行的阶段显示“未执行”；部分请求跳过时，
该次按零计入整轮平均，并标明跳过次数。旧服务未返回的计时显示“不可用”，不推算缺失值。
混合检索在向量化失败后成功降级为关键词检索时，仍保留失败尝试的耗时及警告。
请求额外开销不等于纯网络延迟；手机端可横向滚动每次耗时表格。

## 接入资料

先启动知识库服务，再执行：

```powershell
# 文件夹：保留既有分类，持续扫描和监听新增/修改文件。
.\.venv\Scripts\python.exe -m knowledge_service.cli ingest 'C:\path\to\Knowledge_DB'
# 单个未分类 PDF：自动分类，不改变源文件。
.\.venv\Scripts\python.exe -m knowledge_service.cli ingest 'C:\path\new.pdf' --wait
.\.venv\Scripts\python.exe -m knowledge_service.cli status
.\.venv\Scripts\python.exe -m knowledge_service.cli documents
.\.venv\Scripts\python.exe -m knowledge_service.cli search '毫米波雷达如何校准'
.\.venv\Scripts\python.exe -m knowledge_service.cli ask '毫米波雷达为什么需要校准'
```

以上命令在项目根目录执行；macOS 将 `.\.venv\Scripts\python.exe` 替换为 `.venv/bin/python`。

普通 PDF 直接读取文本层；扫描页或无可读文本的图片区域才按需 OCR。
默认 `KB_PDF_LAYOUT=native` 直接读取并按位置排序正文，表格以原生文本形式保留。
需要 Markdown 表格和更细的版面处理时设置 `KB_PDF_LAYOUT=structured`，这会增加解析耗时。
文字页中的插图默认只保存资源；仅在显式设置 `KB_OCR_IMAGE_REGIONS=true` 时尝试图片区域 OCR。
`KB_OCR_MODE=auto/off/force`，默认 `auto`。OCR 在本机 CPU 执行，不理解纯图形/公式语义。
当前向量来自提取后的文本，保存图片资源不代表对图片生成向量；架构图中的箭头、连接关系和数据流不会自动转成可检索语义。
只关闭 OCR 不会跳过普通文本 PDF。加密、损坏、识别失败页面会报告，不会默默当作成功识别。
标题和章节优先使用 PDF 元数据、书签；所有引用页码是从 1 开始的 PDF 物理页码。

## 增量处理与故障恢复

- SHA-256 去重；未变化文件跳过；相同片段复用当前 embedding 配置的缓存。
- 新版本所有向量就绪后再切换。失败更新继续提供旧版内容。
- 逐页解析检查点、持久化任务队列、API 超时重试及批量自适应拆分。
- 默认每 5 分钟补充扫描，可用 `scan --verify` 强制校验所有来源文件内容。
- 来源消失仅标记“来源缺失”；`delete <document_id>` 才从当前检索中移除，原件仍保留。
- 对可正常扫描的来源目录，已删除文件对应的排队或失败导入任务会取消；目录离线或扫描不完整时保留任务，避免误判删除。
- `pause` 在当前任务完成后暂停后续任务；`resume` 恢复前先扫描来源；`retry [job_id]` 刷新来源并重试仍有效的失败任务。
- `classify <document_id> '分类/路径'` 修改并锁定分类，`--unlock` 允许后续内容更新时重新分类。
- `stop` 保存检查点并关闭服务；较早启动的进程需要重启到包含此命令的版本后才能使用。

## 导出与迁移

```powershell
# 目标文件夹必须不存在；默认包含向量，不导出任何 .env 或访问令牌。
.\.venv\Scripts\python.exe -m knowledge_service.cli export 'C:\backup\knowledge-20261022' --wait
# 在另一台电脑配置并启动一个空资料库，然后导入。
.\.venv\Scripts\python.exe -m knowledge_service.cli import 'C:\backup\knowledge-20261022' --wait
```

导出是一个带 `COMPLETE` 标记和 SHA-256 校验清单的文件夹，可另行压缩。
包含 PDF、分类副本、Markdown、逐页 JSONL、切片 JSONL、元数据、Parquet 向量、tokenizer 缓存及依赖锁定文件。
不导出源电脑目录监听配置；在新电脑另行注册来源目录。
`--no-vectors` 导出纯资料包，恢复后运行 `reindex --wait`。

更换回答/分类模型不重建向量；更换 embedding 配置后重启服务并执行 `reindex --wait`。
新索引完成后才切换；不同模型的向量绝不混用。若新旧 embedding 地址不同，重建期间检索会明确降级为关键词检索。

Open WebUI 的聊天、账号和设置在 `openwebui-data/`，需要停机后单独备份。

## API 与权限

查询端口使用 `KB_API_TOKEN`，本地管理端口使用不同的 `KB_ADMIN_TOKEN`。
OpenAPI 只公开 `search_knowledge`、`get_chunk`、`get_document`、`list_categories`。
应用还可调用未纳入工具描述的 `/v1/ask`。返回的回答会校验片段 ID 是否来自检索，不能据此保证每个陈述的语义正确性。
支持 MCP HTTP 和 stdio 代理；stdio 代理也必须先启动主服务。
单库 `/v1/search` 成功响应包含 `timings_ms`：`total_ms`、`embedding_ms`、`keyword_ms`、
`vector_ms`、`results_ms` 和 `other_ms`，单位为毫秒；未执行的阶段为 `null`。
管理台检索测试直接透传该字段，多库聚合检索不汇总各库计时。
远程自建 Agent 接入详见 [远程连接](docs/REMOTE.md)。

## 测试与规模验证

```powershell
$env:TIKTOKEN_CACHE_DIR = Join-Path (Get-Location) 'data\cache\tiktoken'
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check knowledge_service tests scripts
.\.venv\Scripts\python.exe -m knowledge_service.cli benchmark 'C:\path\samples' --max-files 20 --wait
```

离线 benchmark 不调用 API，不发布测试文档；报告提取时间、切片数、token 数和 Python 分配峰值（不含原生库内存）。
真实 API 的延迟、成本和大规模索引容量需要用真实导入测量。百万页容量尚不能由小样本测试保证。

## 项目结构

```text
knowledge_service/           Python 服务与命令行
  api.py                    HTTP、OpenAPI 与 MCP 接口
  cli.py                    导入、检索、任务管理和迁移命令
  config.py                 配置读取与本机初始化
  extract.py / text.py       PDF 提取、OCR 与文本切片
  service.py                增量处理、任务队列与检索编排
  providers.py              云端聊天、分类和 embedding 调用
  db.py / vectors.py        SQLite 元数据与 LanceDB 向量存储
  portable.py / benchmark.py 导出导入与离线基准测试
  manager*.py / worker.py   多库管理、受管进程及 MCP 网关
  static/                   管理台生产静态文件
frontend/                   React / TypeScript 管理台源码
scripts/                    跨平台管理入口、Windows 快捷脚本和诊断工具
config/                     Open WebUI 模型预设
tests/                      API、处理流水线与模型客户端测试
docs/                       操作、Open WebUI 和远程接入说明
.env.example                无密钥的配置模板
requirements*.lock.txt      知识库与 Open WebUI 依赖锁定文件
pyproject.toml              Python 包、命令行入口与开发工具配置
.github/workflows/          Windows / macOS 兼容性 CI
```

## 更多文档

- [日常操作与迁移](docs/OPERATIONS.md)：启动、停止、PDF 更新、备份与迁移。文中的本机路径和历史快照记录需要按实际部署替换。
- [多知识库管理台](docs/MANAGEMENT.md)：多库配置、MCP 服务、状态解释和检索阶段计时。
- [平台兼容性](docs/COMPATIBILITY.md)：Windows / macOS 安装范围、CI 配置及验证限制。
- [Open WebUI 接入](docs/OPENWEBUI.md)：工具服务器、模型预设和原生知识库的使用区别。
- [远程 Agent 接入](docs/REMOTE.md)：通过自己的 HTTPS 隧道提供查询服务。
- [开发交接记录](HANDOFF.md)：实现状态、历史验证和后续工作；历史记录不代表当前运行状态。

## 数据目录

- `.env`：本机敏感配置，已被 Git 忽略。
- `data/originals/`：按内容哈希保存的 PDF 原件。
- `data/library/`：分类副本，文件名包含原名和文档 ID。
- `data/extracted/<version>/`：逐页正文、Markdown、切片、资源及解析检查点。
- `data/metadata.sqlite3`：分类、版本、任务、来源、BM25 和 embedding 缓存。
- `data/vectors/`：独立 embedding 配置的 LanceDB 数据表。
- 新建知识库使用创建时选择的存储根目录，包含同样的 `originals/`、`extracted/`、`vectors/` 等数据。
- `manager-data/`：管理定义、每库配置及凭据，需作为敏感数据单独备份。
- `openwebui-data/`：Open WebUI 账号、对话、设置及服务密钥。
- `logs/`：启动日志；不记录 API 请求正文或凭据。
- `HANDOFF.md`：当前需求、实现状态、验证证据和下一会话 TODO。

不要把 `.env`、数据目录或日志提交到 Git。更改 `.env` 后重启对应服务。
