# 日常操作与迁移指南

以下默认示例在 PowerShell 中执行，启动和停止另提供 CMD 示例。本机已经安装并配置完成，不需要每天重新运行安装脚本。

## 1. 启动

```powershell
Set-Location -LiteralPath 'C:\Users\xdran\Documents\ChatGPT\Knowledge_Sharing_System 2'
.\scripts\Start-Manager.ps1 -Background
```

使用 CMD（命令提示符）时：

```bat
cd /d "C:\Users\xdran\Documents\ChatGPT\Knowledge_Sharing_System 2"
scripts\Start-Manager.cmd --background
```

后台启动管理台、受管知识库和 MCP；启动后可关闭命令行窗口。电脑重启后需要重新启动，目前没有配置开机自启。
不自动打开管理页面时加 `--no-browser`。

也可单独启动：

```powershell
.\scripts\Start-Knowledge.ps1 -Background
```

CMD 对应为 `scripts\Start-Knowledge.cmd --background`。
独立知识库服务与管理台不要同时管理同一个数据目录。

Open WebUI 仅作可选验证客户端，按 [独立接入文档](OPENWEBUI.md) 另行安装、启动和停止。

查询状态和资料：

```powershell
.\.venv\Scripts\python.exe -m knowledge_service.cli status
.\.venv\Scripts\python.exe -m knowledge_service.cli documents
```

任务状态 `queued` 是排队，`running` 是处理，`done` 是完成，`failed` 是失败。命令返回任务 ID 或入队数量不等于向量化完成；请再查询状态。当前状态列表只显示最近 50 个任务。

## 2. 停止和重启

停止管理台、受管知识库和 MCP：

```powershell
.\scripts\Stop-Manager.ps1
```

CMD 使用 `scripts\Stop-Manager.cmd`。如启动时设置了管理台端口，停止时也需附加相同的 `--port 端口号`。

停止独立单库服务：

```powershell
.\scripts\Stop-Knowledge.ps1
```

知识库会保存提取/向量化检查点并退出，可能需要等待当前处理步骤结束。不要用关闭网页代替停止服务。重启时先停止、等待退出，再运行启动命令；服务重启不会删除已入库数据。

## 3. PDF 新增和更新

本机已经注册并持续监听的来源目录是：

```text
C:\Users\xdran\Desktop\Knowledge_DB
```

在知识库服务运行期间，把新 PDF 放入这个目录或它的子目录，或覆盖更新原路径的 PDF。系统通过文件监听触发处理，并默认每 300 秒补充扫描；文件需写入稳定后才处理。服务停机期间的变化在下次启动后通过扫描发现。

希望立即检查更新时，执行：

```powershell
.\.venv\Scripts\python.exe -m knowledge_service.cli scan --verify
.\.venv\Scripts\python.exe -m knowledge_service.cli status
```

`scan --verify` 对已经注册的来源做内容哈希校验并将变化入队，不是同步等待所有向量生成。它不会把未变化文件全部重新 embedding；对更新文档重新提取和切片后，相同片段复用 embedding 缓存，新片段才调用 API。新版本全部完成后才替换检索中的旧版本。

加入另一个持续监听的文件夹：

```powershell
.\.venv\Scripts\python.exe -m knowledge_service.cli ingest 'D:\My_PDFs' --wait
```

加入单个 PDF：

```powershell
.\.venv\Scripts\python.exe -m knowledge_service.cli ingest 'D:\new.pdf' --wait
```

这里的 D 盘路径是示例，请替换为实际路径。已导入的单文件也会监听和定期扫描更新。

已有分类子目录会保留为分类；未分类 PDF 调用分类模型，优先复用已有类别。原始输入文件不会被移动；分类副本存放在独立 library 中。请修改来源 PDF，不要直接修改 data 下的托管副本、切片或数据库。

失败后查看 `status` 的 error，再按需重试失败任务：

```powershell
.\.venv\Scripts\python.exe -m knowledge_service.cli retry
```

从来源目录删除 PDF 只标记来源缺失，已入库知识仍保留；需要从检索中移除时使用 `delete <document_id>`，这也会保留原件和历史版本。

## 4. 文件和向量保存位置

下面路径均相对于工程根目录：

| 路径 | 内容 |
|---|---|
| `data/originals/` | 按内容哈希保存的原始 PDF |
| `data/library/` | 按分类整理的 PDF 副本 |
| `data/extracted/<version_id>/document.md` | 提取后的可读正文 |
| `data/extracted/<version_id>/pages.jsonl` | 逐页正文、页码和提取方式 |
| `data/extracted/<version_id>/chunks.jsonl` | 切片正文、片段 ID、页码等元数据 |
| `data/extracted/<version_id>/assets/` | 提取的图片等资源 |
| `data/vectors/` | LanceDB 数值向量，按 embedding 配置隔离 |
| `data/metadata.sqlite3` | 文档、分类、版本、任务、来源、关键词索引和 embedding 缓存 |
| `data/cache/tiktoken/` | tokenizer 词表缓存 |
| `openwebui-data/` | Open WebUI 账号、对话、设置及服务密钥 |
| `.env` | 云 API 凭据和运行配置 |
| `logs/` | 服务日志 |

切片是可读文本，向量是用于相似度检索的数值。只拷贝 `data/vectors/` 无法恢复完整知识库；使用下面的导出命令统一带走。

## 5. 导出和迁移到另一台 Windows 电脑

已生成并校验的初始快照：`exports/knowledge-20261022/`，包含 31 份 PDF、9,564 个切片及向量，约 364 MB。它不会跟随后续更新自动刷新。

生成新快照时先启动知识库服务，等待更新任务完成，再导出到一个不存在的目标目录：

```powershell
.\.venv\Scripts\python.exe -m knowledge_service.cli export '.\exports\knowledge-backup-02' --wait
```

确认任务为 `done`、目标中有 `COMPLETE`，再复制整个目录到新电脑，也可以压缩传输。`.partial-*` 是未完成目录，不能作为恢复包。

导出包包含原件、分类副本、正文、逐页数据、切片、分类和版本、Parquet 向量、词表缓存，以及 application 下的源码、安装脚本和依赖锁定文件。不包含 `.env`、源电脑目录监听和 Open WebUI 的账户/聊天数据。

新电脑需要 Python 3.11。将导出包的 `application` 复制为新的工程目录，保留导出包本身完整。以下新电脑路径均为示例：

```powershell
Set-Location -LiteralPath 'D:\Knowledge_Sharing_System'
.\scripts\Install.ps1
# 安装后编辑本机 .env，填写云 API 配置。
# 复用导出向量时，embedding 的地址、模型、维度和处理配置应与原库一致。
.\scripts\Start-Knowledge.ps1 -Background
.\.venv\Scripts\python.exe -m knowledge_service.cli import 'D:\KB_Backup\knowledge-backup-02' --wait
.\.venv\Scripts\python.exe -m knowledge_service.cli status
```

导入必须面向空知识库，不能覆盖现有文档；导入会校验文件完整性。带向量且 embedding 配置一致时，不需重新调用 embedding API。

如果还要持续接收源 PDF 的更新，把原始来源目录也复制到新电脑，并重新注册新路径：

```powershell
.\.venv\Scripts\python.exe -m knowledge_service.cli ingest 'D:\Knowledge_DB' --wait
```

资料内容相同会被去重，不应重复生成 embedding；旧电脑的来源绝对路径不会自动恢复。

Open WebUI 不属于知识库迁移包。如仍需迁移这个验证客户端，应按其独立生命周期停止后，
单独备份 `openwebui-data/`；只迁移知识库时无需安装或恢复 Open WebUI。

## 6. 更换底层模型

- 更换回答 LLM：修改 `.env` 的聊天地址、模型和密钥，重启服务；原 PDF、切片和向量可以继续使用。Open WebUI 已保存的模型连接配置需在管理界面同步核对。
- 更换 embedding 模型/维度/处理配置：修改 `.env`、重启知识库后执行下列命令，等待新配置的向量就绪：

```powershell
.\.venv\Scripts\python.exe -m knowledge_service.cli reindex --wait
```

普通 PDF 更新使用 ingest/scan，不需要每次手动 reindex。改用其他知识库产品时，开放格式的 PDF、Markdown、JSONL、Parquet 可以带走，但目标产品可能需要自己的导入适配；不能保证直接读取 LanceDB 或 Parquet 就可运行。
