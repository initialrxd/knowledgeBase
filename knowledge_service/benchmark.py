from __future__ import annotations

import json
import statistics
import time
import tracemalloc
from pathlib import Path

from .extract import PDFExtractor
from .text import split_pages


def benchmark(service, path: Path, max_files=20):
    """Offline extraction benchmark: no cloud spending or publishing into the real corpus."""
    if not path.is_dir() or max_files < 1 or max_files > 1000:
        raise ValueError("Provide an existing sample folder and max_files between 1 and 1000")
    target = service.s.root / "staging" / ("benchmark-" + str(int(time.time())))
    target.mkdir()
    start, pages, chunks, tokens, files = time.perf_counter(), 0, 0, 0, 0
    failures, times = [], []
    tracemalloc.start()
    for pdf in path.rglob("*"):
        if pdf.suffix.lower() != ".pdf" or not pdf.is_file() or pdf.resolve().is_relative_to(service.s.root):
            continue
        begin = time.perf_counter()
        try:
            result = PDFExtractor(service.s.ocr_mode, layout=service.s.pdf_layout,
                image_regions=service.s.ocr_image_regions).extract(pdf, target / str(files))
            pieces = split_pages(result["pages"], service.s.chunk_tokens, service.s.chunk_overlap, service.s.tokenizer)
            pages += len(result["pages"])
            chunks += len(pieces)
            tokens += sum(c.token_count for c in pieces)
            times.append(time.perf_counter() - begin)
        except Exception as error:
            failures.append({"file": pdf.name, "error_type": type(error).__name__})
        files += 1
        if files >= max_files:
            break
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    elapsed = time.perf_counter() - start
    report = {"files": files, "pages": pages, "chunks": chunks, "estimated_embedding_tokens": tokens,
        "elapsed_seconds": round(elapsed, 3), "seconds_per_1000_pages": round(elapsed / pages * 1000, 2) if pages else None,
        "median_seconds_per_file": round(statistics.median(times), 3) if times else None,
        "python_peak_allocated_bytes": peak, "native_library_memory_included": False,
        "extracted_bytes": sum(p.stat().st_size for p in target.rglob("*") if p.is_file()),
        "api_calls": 0, "failures": failures, "performance_sla": "not established",
        "note": "Extraction only. Run a small real import to measure API latency, index size, and query latency."}
    (target / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report
