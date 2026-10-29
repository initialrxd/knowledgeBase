from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pymupdf


class PDFExtractor:
    """Read native text first. OCR is a fallback, with per-page checkpoints."""
    VERSION = 3

    def __init__(self, mode="auto", ocr=None, layout="native", image_regions=False):
        self.mode, self._ocr = mode, ocr
        self.layout, self.image_regions = layout, image_regions

    def ocr(self, page, clip=None):
        if self._ocr is None:
            from rapidocr import RapidOCR
            self._ocr = RapidOCR(params={
                "EngineConfig.onnxruntime.intra_op_num_threads": 2,
                "EngineConfig.onnxruntime.inter_op_num_threads": 1,
            })
        import numpy as np
        pix = page.get_pixmap(matrix=pymupdf.Matrix(2, 2), colorspace=pymupdf.csRGB, clip=clip)
        image = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
        output = self._ocr(image)
        return "\n".join(getattr(output, "txts", None) or [])

    @staticmethod
    def _save(path, value):
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        temp.replace(path)

    def extract(self, path: Path, destination: Path, stop=None, fallback_title=None, progress=None) -> dict:
        destination.mkdir(parents=True, exist_ok=True)
        (destination / "assets").mkdir(exist_ok=True)
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for block in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(block)
        signature = {"sha256": digest.hexdigest(), "mode": self.mode, "parser": self.VERSION,
            "layout": self.layout, "image_regions": self.image_regions}
        state_path, page_path = destination / "extraction_state.json", destination / "pages.jsonl"
        previous = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
        pages = []
        if previous.get("signature") == signature and page_path.exists():
            with page_path.open("rb+") as cached:
                good = 0
                while line := cached.readline():
                    try:
                        row = json.loads(line)
                        if row["page"] != len(pages) + 1:
                            break
                        pages.append(row)
                        good = cached.tell()
                    except (ValueError, KeyError, UnicodeDecodeError):
                        break
                cached.truncate(good)
        else:
            page_path.write_text("", encoding="utf-8")
        warnings = [f"page {p['page']}: {w}" for p in pages for w in p["warnings"]]
        with pymupdf.open(path) as doc:
            if doc.needs_pass:
                raise ValueError("PDF is password-protected; provide an unlocked copy")
            if not len(doc):
                raise ValueError("PDF contains no pages")
            title = (doc.metadata or {}).get("title") or fallback_title or path.stem
            info = {"signature": signature, "title": title, "total_pages": len(doc), "completed_pages": len(pages), "complete": False}
            self._save(state_path, info)
            toc = {}
            for level, heading, page_no in doc.get_toc(simple=True):
                if page_no >= 1:
                    toc.setdefault(page_no, []).append("#" * min(level, 6) + " " + heading)
            with page_path.open("a", encoding="utf-8") as output:
                for index in range(len(pages), len(doc)):
                    if stop is not None and stop.is_set():
                        raise InterruptedError("Extraction checkpoint saved; resume on next service start")
                    item = self._page(doc, index, destination)
                    if index + 1 in toc:
                        item["text"] = "\n\n".join(toc[index + 1]) + "\n\n" + item["text"]
                    pages.append(item)
                    warnings.extend(f"page {index+1}: {w}" for w in item["warnings"])
                    output.write(json.dumps(item, ensure_ascii=False) + "\n")
                    output.flush()
                    if (index + 1) % 25 == 0:
                        info["completed_pages"] = index + 1
                        self._save(state_path, info)
                        if progress:
                            progress({"stage": "extracting", "completed_pages": index + 1, "total_pages": len(doc)})
            info.update(completed_pages=len(pages), complete=True)
            self._save(state_path, info)
        with (destination / "document.md").open("w", encoding="utf-8") as markdown:
            for p in pages:
                markdown.write(f"<!-- PDF page {p['page']} -->\n\n{p['text']}\n\n")
        return {"title": re.sub(r"\s+", " ", title).strip(), "pages": pages, "warnings": warnings}

    def _page(self, doc, index, destination):
        page = doc[index]
        native = page.get_text("text", sort=True).strip()
        garbled = bool(native) and native.count("\ufffd") / max(len(native), 1) > 0.05
        text, method, warnings = native, "native", []
        images = []
        for n, info in enumerate(page.get_image_info(xrefs=True)):
            rect = pymupdf.Rect(info["bbox"]) & page.rect
            if rect.is_empty:
                continue
            xref = info.get("xref", 0)
            if xref:
                try:
                    image = doc.extract_image(xref)
                    (destination / "assets" / f"p{index+1}-{n}.{image['ext']}").write_bytes(image["image"])
                except (ValueError, RuntimeError):
                    warnings.append("image_extraction_failed")
            if rect.get_area() >= page.rect.get_area() * 0.08:
                images.append(rect)
        if self.mode == "force" or (self.mode == "auto" and (not native or garbled)):
            try:
                recovered = self.ocr(page)
                if recovered.strip():
                    text, method = recovered, "ocr"
                else:
                    warnings.append("ocr_no_text")
            except Exception:
                warnings.append("ocr_failed_or_unavailable")
        elif native:
            if self.layout == "structured":
                try:
                    from pymupdf4llm.helpers.pymupdf_rag import to_markdown
                    markdown = to_markdown(doc, pages=[index], hdr_info=False, show_progress=False, write_images=False)
                    if isinstance(markdown, str) and markdown.strip():
                        text = markdown.strip()
                except Exception:
                    warnings.append("layout_fallback_to_native_text")
            if self.mode == "auto" and self.image_regions and images:
                blocks, additions = page.get_text("blocks"), []
                for rect in images:
                    if any(len(b) > 6 and b[6] == 0 and (pymupdf.Rect(b[:4]) & rect).get_area() > 1 for b in blocks):
                        continue
                    try:
                        recovered = self.ocr(page, rect).strip()
                        if recovered:
                            additions.append(recovered)
                    except Exception:
                        warnings.append("image_region_ocr_failed_or_unavailable")
                if additions:
                    text += "\n\n" + "\n\n".join(additions)
                    method = "native+ocr"
        if not text.strip():
            warnings.append("no_extractable_text")
        if garbled and method == "native":
            warnings.append("garbled_text")
        return {"page": index + 1, "text": text, "method": method, "warnings": warnings}
