from __future__ import annotations

import os
from pathlib import Path

import pymupdf
import pytest

from knowledge_service.config import Settings
from knowledge_service.service import KnowledgeService


@pytest.fixture
def settings(tmp_path):
    # Reuse only the tokenizer dictionary; never copy local credentials into tests.
    os.environ["TIKTOKEN_CACHE_DIR"] = str(Path("data/cache/tiktoken").resolve())
    return Settings(_env_file=None, data_dir=tmp_path / "data", demo_mode=True, file_settle_seconds=0,
        api_token="test-read-token", admin_token="test-admin-token", tokenizer="cl100k_base",
        embedding_model="demo", chunk_tokens=128, chunk_overlap=16, requests_per_minute=1000)


@pytest.fixture
def service(settings):
    instance = KnowledgeService(settings)
    yield instance
    instance.close()


@pytest.fixture
def make_pdf(tmp_path):
    def create(name="sample.pdf", pages=None, scanned=False):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        doc = pymupdf.open()
        for text in pages or ["Radar sensor calibration uses a temperature correction table."]:
            page = doc.new_page()
            page.insert_text((72, 72), text, fontsize=11)
        if scanned:
            images = [p.get_pixmap().tobytes("png") for p in doc]
            doc.close()
            doc = pymupdf.open()
            for image in images:
                p = doc.new_page()
                p.insert_image(p.rect, stream=image)
        doc.save(path)
        doc.close()
        return path
    return create
