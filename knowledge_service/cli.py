from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

import httpx

from .config import Settings, initialize


def out(value):
    print(json.dumps(value, ensure_ascii=False, indent=2))


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="本地 PDF 知识库：Open WebUI / MCP / HTTP")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init", help="创建被 Git 忽略的本机配置")
    commands.add_parser("serve", help="启动本机管理和查询服务")
    commands.add_parser("mcp", help="启动 MCP stdio 代理（先启动服务）")
    commands.add_parser("status", help="任务和资料库状态")
    commands.add_parser("stop", help="保存检查点并停止知识库服务")
    commands.add_parser("documents", help="列出最近的文档")
    commands.add_parser("pause", help="当前任务完成后暂停队列")
    commands.add_parser("resume", help="恢复队列")
    reindex = commands.add_parser("reindex", help="为当前 embedding 配置建立新索引")
    reindex.add_argument("--wait", action="store_true")
    ingest = commands.add_parser("ingest", help="导入单个 PDF，或持续监听一个文件夹")
    ingest.add_argument("path")
    ingest.add_argument("--wait", action="store_true")
    scan = commands.add_parser("scan", help="扫描已注册来源目录")
    scan.add_argument("--verify", action="store_true", help="校验所有文件的 SHA-256")
    retry = commands.add_parser("retry", help="重试失败任务")
    retry.add_argument("job_id", nargs="?")
    classify = commands.add_parser("classify", help="手动分类并锁定")
    classify.add_argument("document_id")
    classify.add_argument("category")
    classify.add_argument("--unlock", action="store_true")
    delete = commands.add_parser("delete", help="从检索中移除文档，保留原始 PDF 和历史")
    delete.add_argument("document_id")
    export = commands.add_parser("export", help="导出到一个尚不存在的目录")
    export.add_argument("destination")
    export.add_argument("--no-vectors", action="store_true")
    export.add_argument("--wait", action="store_true")
    restore = commands.add_parser("import", help="将导出包恢复到空资料库")
    restore.add_argument("source")
    restore.add_argument("--wait", action="store_true")
    benchmark = commands.add_parser("benchmark", help="离线提取基准测试，不调用云 API")
    benchmark.add_argument("path")
    benchmark.add_argument("--max-files", type=int, default=20)
    benchmark.add_argument("--wait", action="store_true")
    search = commands.add_parser("search", help="检索知识库")
    search.add_argument("query")
    search.add_argument("--category")
    search.add_argument("--mode", choices=["hybrid", "keyword", "vector"])
    ask = commands.add_parser("ask", help="调用配置的聊天模型回答并引用来源")
    ask.add_argument("question")
    args = parser.parse_args()
    if args.command == "init":
        created = initialize()
        Path("inbox").mkdir(exist_ok=True)
        Settings().prepare()
        out({"created": created, "configuration": str(Path('.env').resolve()),
            "note": "凭据不回显。请在本机 .env 填写 API 参数。"})
        return
    settings = Settings()
    try:
        if args.command == "serve":
            from .api import serve
            from .service import KnowledgeService
            service = KnowledgeService(settings)
            try:
                asyncio.run(serve(service))
            finally:
                service.close()
            return
        if args.command == "mcp":
            from .api import run_stdio
            run_stdio(settings)
            return
        if args.command in ("search", "ask"):
            with httpx.Client(base_url=f"http://127.0.0.1:{settings.tools_port}",
                    headers={"Authorization": "Bearer " + settings.api_token.get_secret_value()}, timeout=180) as client:
                response = client.post("/v1/search" if args.command == "search" else "/v1/ask",
                    json={"query": args.query, "category": args.category, "mode": args.mode} if args.command == "search"
                    else {"question": args.question})
                response.raise_for_status()
                out(response.json())
            return
        with httpx.Client(base_url=f"http://127.0.0.1:{settings.port}",
                headers={"Authorization": "Bearer " + settings.admin_token.get_secret_value()}, timeout=180) as client:
            if args.command == "stop":
                response = client.post("/admin/shutdown")
            elif args.command in ("status", "documents"):
                response = client.get("/admin/" + args.command)
            else:
                action, payload = args.command, {}
                if action == "ingest":
                    source = Path(args.path).resolve()
                    action = "add_root" if source.is_dir() else "ingest"
                    payload = {"path": str(source)}
                elif action == "scan":
                    payload = {"verify": args.verify}
                elif action == "retry":
                    payload = {"job_id": args.job_id}
                elif action == "classify":
                    payload = {"document_id": args.document_id, "category": args.category, "locked": not args.unlock}
                elif action == "delete":
                    payload = {"document_id": args.document_id}
                elif action == "export":
                    payload = {"destination": str(Path(args.destination).resolve()), "include_vectors": not args.no_vectors}
                elif action == "import":
                    payload = {"source": str(Path(args.source).resolve())}
                elif action == "benchmark":
                    payload = {"path": str(Path(args.path).resolve()), "max_files": args.max_files}
                response = client.post("/admin/actions", json={"action": action, "args": payload})
            response.raise_for_status()
            result = response.json()
            if getattr(args, "wait", False):
                if "id" in result and "status" in result:
                    result = _wait_job(client, result["id"])
                elif args.command == "ingest" and Path(args.path).is_dir():
                    client.post("/admin/actions", json={"action": "scan", "args": {}}).raise_for_status()
                    while True:
                        state = client.get("/admin/status").json()
                        if not any(j["status"] in ("queued", "running") for j in state["jobs"]):
                            result = state
                            break
                        time.sleep(1)
            out(result)
    except httpx.ConnectError:
        print("无法连接本机服务。请先在另一个终端运行 scripts\\Start-Knowledge.ps1。", file=sys.stderr)
        sys.exit(1)
    except httpx.HTTPStatusError as error:
        try:
            detail = error.response.json().get("detail", "Request failed")
        except ValueError:
            detail = "Request failed"
        print(f"HTTP {error.response.status_code}: {detail}", file=sys.stderr)
        sys.exit(1)
    except (ValueError, RuntimeError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)


def _wait_job(client, identifier):
    while True:
        response = client.get("/admin/jobs/" + identifier)
        response.raise_for_status()
        row = response.json()
        if row["status"] in ("done", "failed", "cancelled"):
            return row
        time.sleep(1)


if __name__ == "__main__":
    main()
