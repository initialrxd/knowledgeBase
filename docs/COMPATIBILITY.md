# Windows / macOS 兼容性

检查日期：2026-10-29。代码适配与实际运行验收分别记录，尚未运行的 CI 不算通过证据。

## 支持目标与当前证据

| 平台 | 管理台、PDF、检索、HTTP / MCP、迁移 | 可选 Open WebUI 0.12.3 | 本轮实际验证 |
|---|---|---|---|
| Windows x64，Python 3.11 | 已有支持，新增统一入口 | 保留独立环境及 Windows 快捷脚本 | 本机测试、依赖检查；详见下方 |
| Windows x64，Python 3.12 | 包声明及 CI 目标 | Python 范围允许，待验收 | 未实机执行 |
| macOS 14+，Apple Silicon，Python 3.11 / 3.12 | 已适配入口及原生依赖解析，待实机验收 | 已适配路径与进程退出，待原生安装及运行验收 | 平台分支测试；CI 待执行 |
| macOS 14+，Intel，Python 3.11 / 3.12 | 配置独立 LanceDB / OCR 依赖版本，待实机验收 | 当前版本不支持原生安装 | 平台分支测试；CI 待执行 |

不将 Windows ARM64、32 位 Python、Rosetta 环境、旧版 macOS 或任意 Linux 发行版列入本轮验收范围。
macOS 14+ 是当前部署目标，不表示已验证所有小版本的最低系统需求。
Windows 本轮环境为 Windows x64 / CPython 3.11，不能据此宣称全部 Windows 版本均已测试。

## 本次排除的障碍

- 旧脚本依赖 `py -3.11`、PowerShell、`Scripts/python.exe` 和 `open-webui.exe`。
  新的 `scripts/manage.py` 用本机 Python 创建环境，区分 Windows `Scripts/` 与 macOS `bin/`，
  提供 install、start-manager、start-knowledge、start-openwebui、start-all、stop-all。
- Windows 安装入口调用同一安装逻辑，子命令失败立即停止；`--without-ocr` 不再被完整锁定文件忽略。
- Windows 保留现有依赖快照；macOS 按 `pyproject.toml` 原生解析，使用
  `config/constraints-macos.txt`。这是一份兼容性约束，不是完整的 macOS 依赖锁。
- 当前 [LanceDB 0.40.0](https://pypi.org/project/lancedb/0.40.0/#files) 不发布 Intel macOS wheel；
  Intel 核心服务使用仍发布该 wheel 的 [LanceDB 0.25.3](https://pypi.org/project/lancedb/0.25.3/#files)。
- 当前 [ONNX Runtime 1.31.0](https://pypi.org/project/onnxruntime/1.31.0/#files) 的 macOS wheel 为 arm64；
  Intel OCR 使用 [1.23.2](https://pypi.org/project/onnxruntime/1.23.2/#files)。
  这些约束也写入包元数据，使直接安装核心包时同样生效。
- Open WebUI 0.12.3 的本机已安装包元数据固定要求 `onnxruntime==1.26.0`；
  [该版本](https://pypi.org/project/onnxruntime/1.26.0/#files) 未发布 Intel macOS wheel。
  Intel 下请求安装 Open WebUI 会先给出明确错误；不会用 `--no-deps` 绕过上游约束。
- macOS 的 Open WebUI 启动器使用 exec 替换包装进程，停止信号可直接送达服务器。
  停止前验证 PID 对应的命令行；核心服务仍通过认证 API 保存检查点并退出。
- 从 macOS 导出依赖快照时写入独立的 `*.darwin.lock.txt`，保留 Windows 快照。
- 迁移包的恢复说明已更新为跨平台入口。跨系统迁移应使用导出/导入包，
  不复用 `.venv`、`manager-data/` 中的绝对路径或直接降级打开现有 LanceDB 目录。
  新电脑需重新配置 API 凭据和来源目录；Open WebUI 聊天与账户单独备份。

## 使用

Windows 的 PowerShell 命令继续可用。统一入口在 Windows 使用 `py -3.11`，在 macOS 使用 `python3.11`：

```bash
python3.11 scripts/manage.py install
# Apple Silicon / Windows 可选择安装聊天界面：
python3.11 scripts/manage.py install --with-openwebui
# 编辑 .env 中的模型配置后：
python3.11 scripts/manage.py start-manager --background
# 安装了 Open WebUI 时，可改为 start-all。
python3.11 scripts/manage.py stop-all
```

`start-manager` 默认端口为 8767，`--port` 可更改；停止时须传入同一端口。
无浏览器环境加 `--no-browser`。前台启动按 Ctrl+C 退出，后台启动使用 stop-all。
stop-all 返回表示已请求正常退出，正在处理的知识库批次仍可能需要时间保存。
仅使用原服务时运行 `start-knowledge --background`。不要与管理台同时启动同一知识库。

首次安装需要网络下载依赖和 tokenizer；测试中的 demo 模式不代表生产环境可以离线调用云 API。
macOS 目录访问受系统权限约束，需向终端/Python 授予实际来源目录的访问权限。

## 验证

本轮 Windows 完整回归 49 项通过（182.35 秒）；补充 Intel Open WebUI 安装前检查后，
13 项启动脚本专项测试全部通过，合计 50 项独立用例具有通过证据。
ruff 检查、核心 / Open WebUI 两个环境的 `pip check`、前端 TypeScript / Vite 构建通过。
前端构建在沙箱内遇到 esbuild `spawn EPERM`，允许启动编译子进程后通过。
原测试保留 Starlette TestClient 与 MCP 客户端接口弃用警告。
新增测试覆盖：平台路径、安装依赖选择、失败即停、
中文与空格路径下真实后台进程及健康检查、端口冲突、macOS exec、PID 身份不符时拒绝停止。
原回归包含真实 worker / MCP 子进程、PDF 处理、检索、导出恢复及多库管理。
OCR 测试使用替身验证触发条件，不代表已完成 Mac 上真实扫描页识别验收。

`.github/workflows/compatibility.yml` 为 Windows x64、macOS Apple Silicon、macOS Intel
分别配置 Python 3.11 / 3.12：通过统一入口安装，运行 pytest、ruff、原生 OCR 库导入及前端构建。
Mac runner 选择依据 [GitHub 官方 runner 文档](https://docs.github.com/en/actions/reference/runners/github-hosted-runners)。
本轮未提交或推送代码，未触发远程 CI；Open WebUI 的 macOS 原生安装和浏览器会话仍需独立验收。

本机验证命令：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check knowledge_service tests scripts
.\.venv\Scripts\python.exe -m pip check
.\.venv-webui\Scripts\python.exe -m pip check
```

macOS 对应解释器为 `.venv/bin/python` / `.venv-webui/bin/python`。
