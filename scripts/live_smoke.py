"""Run a real PDF -> cloud embedding -> DeepSeek answer -> portable restore check.

Uses local .env. Prints status and counts only; never prints credentials or document contents.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from knowledge_service.config import Settings
from knowledge_service.portable import export_bundle, import_bundle
from knowledge_service.service import KnowledgeService


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source")
    parser.add_argument("--destination", default="tmp/live-smoke")
    args = parser.parse_args()
    base = Path(args.destination).resolve()
    base.mkdir(parents=True, exist_ok=True)
    settings = Settings(data_dir=base / "data", ocr_mode="off", file_settle_seconds=0)
    service = KnowledgeService(settings)
    started = time.perf_counter()
    try:
        source = Path(args.source).resolve()
        root = service.add_root(source.parents[3])
        result = service.ingest(source, root["id"])
        calls = service.providers.embedding_calls
        repeated = service.ingest(source, root["id"])
        assert repeated["status"] == "unchanged" and service.providers.embedding_calls == calls
        found = service.search("How do TI mmWave radar devices perform self-calibration?")
        assert found["results"] and not found["warnings"], found["warnings"]
        answer = service.ask("根据文档，TI mmWave 雷达器件为什么需要校准？请引用片段ID。")
        assert answer["citations"] and "citation_validation_failed" not in answer["warnings"]
        bundle = base / ("export-" + str(int(time.time())))
        export_bundle(service, bundle)
        restored = KnowledgeService(settings.model_copy(update={"data_dir": base / ("restored-" + str(int(time.time())))}))
        try:
            import_bundle(restored, bundle)
            assert restored.providers.embedding_calls == 0
            assert restored.get_document(result["document_id"])["current_version"] == result["version_id"]
            recovered = restored.search("self calibration")
            assert recovered["results"] and not recovered["warnings"]
        finally:
            restored.close()
        report = {"passed": True, "pages": result.get("pages"), "chunks": result.get("chunks"),
            "citations": len(answer["citations"]), "answer_model": settings.chat_model,
            "embedding_model": settings.embedding_model, "seconds": round(time.perf_counter() - started, 2),
            "bundle": str(bundle)}
        (base / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=True))
    finally:
        service.close()


if __name__ == "__main__":
    main()
