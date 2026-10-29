"""A real local OCR smoke test, using generated test text and no cloud API."""
import json
import sys
from pathlib import Path

import pymupdf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from knowledge_service.extract import PDFExtractor  # noqa: E402

folder = Path("tmp/ocr-check")
folder.mkdir(parents=True, exist_ok=True)
with pymupdf.open() as document:
    page = document.new_page()
    page.insert_text((72, 120), "RADAR CALIBRATION\nTEST DOCUMENT", fontsize=24)
    image = page.get_pixmap(matrix=pymupdf.Matrix(2, 2)).tobytes("png")
with pymupdf.open() as scanned:
    page = scanned.new_page()
    page.insert_image(page.rect, stream=image)
    scanned.save(folder / "scan.pdf")
result = PDFExtractor("auto").extract(folder / "scan.pdf", folder / "result")
text = result["pages"][0]["text"]
report = {"passed": result["pages"][0]["method"] == "ocr" and "RADAR" in text.upper(),
    "recognized_characters": len(text), "warnings": result["warnings"], "api_calls": 0}
(folder / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
print(json.dumps(report))
if not report["passed"]:
    raise SystemExit(1)
