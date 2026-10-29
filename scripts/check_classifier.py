"""Exercise actual cloud classification with a short sample, without indexing duplicates."""
import json
import sys
from pathlib import Path

import pymupdf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from knowledge_service.config import Settings  # noqa: E402
from knowledge_service.service import KnowledgeService  # noqa: E402

source = Path(sys.argv[1]).resolve()
service = KnowledgeService(Settings(data_dir=Path("tmp/classifier-check")))
try:
    service.category("TI/AWR2944/Application_note")
    with pymupdf.open(source) as document:
        pages = [{"text": document[i].get_text()} for i in range(min(3, len(document)))]
        title = document.metadata.get("title") or source.stem
    identifier, warnings = service.classify(title, pages)
    category = service.db.one("SELECT path FROM categories WHERE id=?", (identifier,))["path"]
    report = {"passed": not warnings and category != "待分类", "category": category,
        "warnings": warnings, "model": service.s.classify_model or service.s.chat_model}
    print(json.dumps(report, ensure_ascii=True))
    Path("tmp/classifier-check/report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if not report["passed"]:
        raise SystemExit(1)
finally:
    service.close()
