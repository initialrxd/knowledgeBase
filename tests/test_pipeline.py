import pytest

from knowledge_service.extract import PDFExtractor
from knowledge_service.portable import _filesystem_path, export_bundle, import_bundle
from knowledge_service.service import KnowledgeService
from knowledge_service.text import split_pages


def test_native_pdf_never_calls_ocr(make_pdf, tmp_path, monkeypatch):
    extractor = PDFExtractor("auto")
    monkeypatch.setattr(extractor, "ocr", lambda *args: pytest.fail("Text PDF must not invoke OCR"))
    result = extractor.extract(make_pdf(), tmp_path / "extract")
    assert "calibration" in result["pages"][0]["text"]
    assert result["pages"][0]["method"] == "native"


def test_scan_ocr_is_conditional(make_pdf, tmp_path, monkeypatch):
    pdf = make_pdf(scanned=True)
    extractor = PDFExtractor("auto")
    calls = []
    monkeypatch.setattr(extractor, "ocr", lambda *args: calls.append(1) or "Recognized scan text")
    result = extractor.extract(pdf, tmp_path / "scan")
    assert calls == [1]
    assert result["pages"][0]["method"] == "ocr"
    disabled = PDFExtractor("off")
    monkeypatch.setattr(disabled, "ocr", lambda *args: pytest.fail("OCR disabled"))
    result = disabled.extract(pdf, tmp_path / "off")
    assert "no_extractable_text" in result["pages"][0]["warnings"]


def test_extraction_resumes_partial_checkpoint(make_pdf, tmp_path, monkeypatch):
    import threading
    pdf = make_pdf(pages=["Page one text", "Page two text", "Page three text"])
    destination = tmp_path / "checkpoint"
    extractor = PDFExtractor("off")
    stop = threading.Event()
    original = extractor._page
    def first_page(doc, index, target):
        result = original(doc, index, target)
        stop.set()
        return result
    monkeypatch.setattr(extractor, "_page", first_page)
    with pytest.raises(InterruptedError):
        extractor.extract(pdf, destination, stop=stop)
    assert len((destination / "pages.jsonl").read_text(encoding="utf-8").splitlines()) == 1
    # Simulate an interrupted write: a broken trailing JSON line must be discarded.
    with (destination / "pages.jsonl").open("ab") as stream:
        stream.write(b'{"page":2')
    called = []
    def remaining(doc, index, target):
        called.append(index)
        return original(doc, index, target)
    monkeypatch.setattr(extractor, "_page", remaining)
    result = extractor.extract(pdf, destination)
    assert called == [1, 2]
    assert len(result["pages"]) == 3


def test_mixed_pdf_uses_ocr_only_on_scanned_page(make_pdf, tmp_path, monkeypatch):
    import pymupdf
    native = make_pdf("text.pdf")
    scanned = make_pdf("scan.pdf", scanned=True)
    mixed = tmp_path / "mixed.pdf"
    with pymupdf.open(native) as doc, pymupdf.open(scanned) as scan:
        doc.insert_pdf(scan)
        doc.save(mixed)
    extractor = PDFExtractor()
    calls = []
    monkeypatch.setattr(extractor, "ocr", lambda page, *args: calls.append(page.number) or "Scanned appendix")
    result = extractor.extract(mixed, tmp_path / "mixed")
    assert calls == [1]
    assert [p["method"] for p in result["pages"]] == ["native", "ocr"]


def test_unicode_chunks_are_complete_and_keep_pages():
    text = "毫米波雷达传感器 calibration 温度补偿。" * 100
    chunks = split_pages([{"page": 7, "text": text, "method": "native"}], 64, 8)
    assert len(chunks) > 10
    assert all(c.page_start == c.page_end == 7 and c.token_count <= 64 for c in chunks)
    assert all("\ufffd" not in c.text for c in chunks)
    # No content gap when overlap is disabled, including token boundaries within Chinese characters.
    no_overlap = split_pages([{"page": 1, "text": text, "method": "native"}], 64, 0)
    assert "".join(c.text for c in no_overlap) == text


def test_incremental_duplicate_rename_update_and_lock(service, make_pdf):
    source = make_pdf(pages=["Radar calibration procedure for sensor A.", "Keep supply voltage at five volts."])
    first = service.ingest(source)
    calls = service.providers.embedding_calls
    assert first["status"] == "indexed"
    assert service.ingest(source)["status"] == "unchanged"
    assert service.providers.embedding_calls == calls
    renamed = source.with_name("renamed.pdf")
    source.rename(renamed)
    assert service.ingest(renamed)["status"] == "duplicate"
    assert service.providers.embedding_calls == calls
    service.set_category(first["document_id"], "Radar/Calibration")
    assert service.search("calibration", category="Radar", mode="keyword")["results"]
    # A changed second page reuses the exact first-page embedding.
    renamed.unlink()
    make_pdf("renamed.pdf", pages=["Radar calibration procedure for sensor A.", "Keep supply voltage at six volts."])
    second = service.ingest(renamed)
    assert second["document_id"] == first["document_id"]
    assert second["version_id"] != first["version_id"]
    assert service.providers.embedding_calls == calls + 1
    doc = service.get_document(first["document_id"])
    assert doc["category"] == "Radar/Calibration"
    assert doc["category_locked"]
    assert not service.search("five", mode="keyword")["results"]
    assert service.search("six", mode="keyword")["results"]


def test_failed_update_keeps_current_version(service, make_pdf, monkeypatch):
    source = make_pdf()
    first = service.ingest(source)
    source.unlink()
    make_pdf(pages=["New content that cannot be embedded."])
    def fail(*args):
        raise ValueError("Injected embedding outage")
    monkeypatch.setattr(service.providers, "embed", fail)
    with pytest.raises(ValueError, match="outage"):
        service.ingest(source)
    assert service.get_document(first["document_id"])["current_version"] == first["version_id"]
    assert service.search("calibration", mode="keyword")["results"]


def test_first_import_failure_reuses_extraction_checkpoint(service, make_pdf, monkeypatch):
    source = make_pdf()
    embed = service.providers.embed
    monkeypatch.setattr(service.providers, "embed", lambda texts: (_ for _ in ()).throw(ValueError("outage")))
    with pytest.raises(ValueError, match="outage"):
        service.ingest(source)
    folders = list((service.s.root / "extracted").iterdir())
    monkeypatch.setattr(service.providers, "embed", embed)
    monkeypatch.setattr(service.extractor, "_page", lambda *args: pytest.fail("Already extracted page must be reused"))
    assert service.ingest(source)["status"] == "indexed"
    assert list((service.s.root / "extracted").iterdir()) == folders


def test_directory_classification_and_missing_retention(service, make_pdf):
    pdf = make_pdf("source/Radar/Datasheet/sensor.pdf")
    root = service.add_root(pdf.parents[2])
    result = service.ingest(pdf, root["id"])
    assert service.get_document(result["document_id"])["category"] == "Radar/Datasheet"
    pdf.unlink()
    service.scan()
    assert service.status()["missing_sources"]
    assert service.get_document(result["document_id"])


def test_single_file_updates_are_queued_by_scan(service, make_pdf):
    source = make_pdf()
    initial = service.ingest(source)
    source.unlink()
    make_pdf(pages=["A changed single-file source with new calibration data."])
    assert service.scan()["enqueued"] == 1
    job = service.db.one("SELECT id FROM jobs WHERE status='queued'")
    service.run_job(job["id"])
    assert service.get_document(initial["document_id"])["current_version"] != initial["version_id"]


def test_delete_removes_retrieval_but_retains_pdf(service, make_pdf):
    result = service.ingest(make_pdf())
    original = list((service.s.root / "originals").glob("*.pdf"))[0]
    service.delete_document(result["document_id"])
    assert not service.search("calibration", mode="keyword")["results"]
    assert original.exists()
    with pytest.raises(KeyError):
        service.get_document(result["document_id"])


def test_export_restore_without_api_calls(service, make_pdf, tmp_path):
    result = service.ingest(make_pdf())
    # Classification/asset names plus an export prefix can exceed Windows MAX_PATH.
    asset = "long-" + "a" * 150 + ".txt"
    relative = "extracted/" + result["version_id"] + "/" + asset
    _filesystem_path(service.s.root / relative).write_text("portable asset", encoding="utf-8")
    bundle = tmp_path / ("portable-" + "b" * 70)
    export_bundle(service, bundle)
    assert (bundle / "COMPLETE").exists()
    assert not (bundle / ".env").exists()
    assert not (bundle / "requirements-webui.lock.txt").exists()
    assert not (bundle / "application" / "scripts" / "openwebui.py").exists()
    assert not (bundle / "application" / "docs" / "OPENWEBUI.md").exists()
    assert _filesystem_path(bundle / relative).read_text(encoding="utf-8") == "portable asset"
    restored = KnowledgeService(service.s.model_copy(update={"data_dir": tmp_path / "restored"}))
    try:
        import_bundle(restored, bundle)
        assert restored.providers.embedding_calls == 0
        assert restored.get_document(result["document_id"])["title"]
        assert restored.search("calibration")["results"]
        assert restored.db.rows("SELECT * FROM roots") == []
        assert restored.db.rows("SELECT * FROM sources") == []
        assert _filesystem_path(restored.s.root / relative).read_text(encoding="utf-8") == "portable asset"
    finally:
        restored.close()


def test_export_tamper_is_rejected_before_import(service, make_pdf, tmp_path):
    service.ingest(make_pdf())
    bundle = tmp_path / "tampered"
    export_bundle(service, bundle, include_vectors=False)
    original = next((bundle / "originals").glob("*.pdf"))
    original.write_bytes(b"tampered")
    restored = KnowledgeService(service.s.model_copy(update={"data_dir": tmp_path / "empty"}))
    try:
        with pytest.raises(ValueError, match="checksum"):
            import_bundle(restored, bundle)
        assert restored.status()["counts"]["documents"] == 0
    finally:
        restored.close()


def test_reindex_keeps_text_and_separates_models(service, make_pdf):
    result = service.ingest(make_pdf())
    previous = service.db.get_meta("active_profile")
    updated = service.s.model_copy(update={"embedding_revision": "new-model"})
    service.s = updated
    service.providers.settings = updated
    reindexed = service.reindex()
    assert reindexed["profile"] != previous
    assert service.get_document(result["document_id"])["current_version"] == result["version_id"]
    assert len(service.db.rows("SELECT * FROM profiles")) == 2


def test_persistent_jobs_recover_and_do_not_duplicate(service, make_pdf):
    path = make_pdf()
    one = service.enqueue("ingest", {"path": str(path)})
    two = service.enqueue("ingest", {"path": str(path)})
    assert one["id"] == two["id"]
    service.db.execute("UPDATE jobs SET status='running' WHERE id=?", (one["id"],))
    service.db.recover_jobs()
    assert service.db.one("SELECT status FROM jobs WHERE id=?", (one["id"],))["status"] == "queued"
    service.run_job(one["id"])
    assert service.db.one("SELECT status FROM jobs WHERE id=?", (one["id"],))["status"] == "done"


def test_classifier_reuses_and_adds_categories(service, monkeypatch):
    service.category("Radar/Calibration")
    monkeypatch.setattr(service.providers, "chat", lambda *args, **kwargs:
        '{"category":"Radar/Calibration","confidence":0.95,"reason":"existing topic"}')
    identifier, warnings = service.classify("Calibration", [{"text": "Radar calibration"}])
    assert service.db.one("SELECT path FROM categories WHERE id=?", (identifier,))["path"] == "Radar/Calibration"
    assert not warnings
    monkeypatch.setattr(service.providers, "chat", lambda *args, **kwargs:
        '{"category":"Radar/Interference","confidence":0.9,"reason":"new topic"}')
    identifier, warnings = service.classify("Interference", [{"text": "Interference cancellation"}])
    assert service.db.one("SELECT path FROM categories WHERE id=?", (identifier,))["path"] == "Radar/Interference"
    monkeypatch.setattr(service.providers, "chat", lambda *args, **kwargs:
        '{"category":"Unsure","confidence":0.1,"reason":"uncertain"}')
    identifier, warnings = service.classify("Unknown", [{"text": "Unknown"}])
    assert service.db.one("SELECT path FROM categories WHERE id=?", (identifier,))["path"] == "待分类"
    assert "classification_uncertain" in warnings
