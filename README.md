# knowledgeBase · 本地 PDF 知识库

Windows / Python 原生部署的可迁移知识库。PDF 原件、分类副本、提取正文、切片和向量均可带走。
聊天、分类及 embedding 使用你自己的云 API；不需要部署本地 LLM 或 embedding 模型。

## 主要功能

- 导入单个 PDF 或持续监听文件夹，保留已有目录分类，自动整理未分类文档。
- 优先提取 PDF 文本层，按需 OCR，按页码和章节切片，保存原件与图片资源。
- 使用云端 embedding，结合 LanceDB 向量检索与 SQLite FTS5 / jieba 关键词检索。
- 增量更新、内容去重、embedding 缓存和任务恢复；新版本完成后再替换旧版检索内容。
- 通过 HTTP / OpenAPI / MCP 提供查询，使用 Open WebUI 聊天并展示来源页码。
- 导出 PDF、正文、切片、元数据及向量，迁移后可继续使用或更换模型。

## 环境要求

- Windows + PowerShell；安装脚本使用 Python 3.11 和 `py` 启动器。
- Git，用于克隆仓库；不需要 Docker 或 WSL。
- 可访问的 OpenAI 兼容聊天与 embedding API，分别配置地址、模型和密钥。
- 首次安装需要联网下载 Python 依赖和 tokenizer 词表；OCR 按需加载本机识别模型。

知识库服务与 Open WebUI 使用独立虚拟环境，避免依赖版本冲突。
项目包声明支持 Python `>=3.11,<3.13`，仓库的 Windows 安装流程使用 Python 3.11。

## 快速启动

在 PowerShell 中克隆并安装：

```powershell
git clone https://github.com/initialrxd/knowledgeBase.git
Set-Location knowledgeBase
.\scripts\Install.ps1 -WithOpenWebUI
```

安装脚本创建 `.venv` 和 `.venv-webui`、安装锁定依赖，并在 `.env` 不存在时根据
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

- 聊天界面：http://127.0.0.1:8080
- Open WebUI 工具服务器：http://127.0.0.1:8766
- OpenAPI 描述：http://127.0.0.1:8766/openapi.json
- MCP Streamable HTTP：http://127.0.0.1:8766/mcp
- 本地管理 API：http://127.0.0.1:8765/docs

首次打开 Open WebUI 时创建自己的管理员账户，在工具菜单启用“本地 PDF 知识库”。
详见 [Open WebUI 接入](docs/OPENWEBUI.md)。

需要停止两个服务时，运行 `.\scripts\Stop-All.ps1`。

只使用 HTTP / MCP 时，可运行 `.\scripts\Install.ps1`，然后运行
`.\scripts\Start-Knowledge.ps1 -Background`，无需安装 Open WebUI。

Open WebUI 原生 Workspace > Knowledge 与本项目的独立知识库分别保存数据。
网页上传不会自动导入本服务；通过下面的命令导入后，在聊天中启用外部知识库工具。

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
- `pause` 在当前任务完成后暂停后续任务；`resume` 恢复；`retry [job_id]` 重试失败任务。
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
scripts/                    Windows 安装、启动、停止和诊断脚本
config/                     Open WebUI 模型预设
tests/                      API、处理流水线与模型客户端测试
docs/                       操作、Open WebUI 和远程接入说明
.env.example                无密钥的配置模板
requirements*.lock.txt      知识库与 Open WebUI 依赖锁定文件
pyproject.toml              Python 包、命令行入口与开发工具配置
```

## 更多文档

- [日常操作与迁移](docs/OPERATIONS.md)：启动、停止、PDF 更新、备份与迁移。文中的本机路径和历史快照记录需要按实际部署替换。
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
- `logs/`：启动日志；不记录 API 请求正文或凭据。
- `HANDOFF.md`：当前需求、实现状态、验证证据和下一会话 TODO。

不要把 `.env`、数据目录或日志提交到 Git。更改 `.env` 后重启对应服务。
