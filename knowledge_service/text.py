from __future__ import annotations

import hashlib
import re
import threading
from dataclasses import asdict, dataclass

import jieba
import tiktoken

_lock = threading.Lock()
_encodings = {}
jieba.setLogLevel(40)


class ByteEncoding:
    """Offline conservative input budget: one unit per UTF-8 byte, not model tokens."""
    n_vocab = 256

    def encode(self, text, disallowed_special=()):
        return list(text.encode("utf-8"))

    def decode_bytes(self, ids):
        return bytes(ids)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def terms(text: str) -> str:
    # Tokenize Chinese before SQLite's unicode61 tokenizer. Never expose FTS query syntax to users.
    return " ".join(t.lower() for t in jieba.cut_for_search(text)
                    if re.search(r"[\w]", t, re.UNICODE))


def fts_query(text: str) -> str:
    return " OR ".join('"' + t.replace('"', '""') + '"' for t in dict.fromkeys(terms(text).split()))


def encoding(name="cl100k_base"):
    if name == "utf8_bytes":
        return ByteEncoding()
    with _lock:
        if name not in _encodings:
            _encodings[name] = tiktoken.get_encoding(name)
        return _encodings[name]


@dataclass
class Chunk:
    text: str
    content_hash: str
    token_count: int
    page_start: int
    page_end: int
    section: str
    method: str

    def to_dict(self):
        return asdict(self)


def split_pages(pages: list[dict], target=800, overlap=100, tokenizer="cl100k_base") -> list[Chunk]:
    """Respect page/paragraph boundaries; long tables repeat their header. Never cut UTF-8 bytes."""
    enc = encoding(tokenizer)
    result = []
    section = ""
    for page in pages:
        pending = ""

        def emit(text: str):
            if text.strip():
                result.append(Chunk(text, sha256_text(text),
                    len(enc.encode(text, disallowed_special=())), page["page"], page["page"],
                    section, page["method"]))

        def length(text):
            return len(enc.encode(text, disallowed_special=()))

        blocks = re.split(r"\n\s*\n", page["text"].strip())
        for block in blocks:
            if not block.strip():
                continue
            heading = re.match(r"^(#{1,6})\s+(.+)", block)
            if heading:
                emit(pending)
                pending = ""
                section = heading.group(2).strip()
            if length(block) > target:
                emit(pending)
                pending = ""
                lines = block.splitlines()
                header = "\n".join(lines[:2]) if len(lines) > 2 and "|" in lines[0] and re.search(r"\|\s*:?-", lines[1]) else ""
                if header and length(header) < target // 2:
                    buffer = header
                    for line in lines[2:]:
                        if length(line) + length(header) >= target:
                            emit(buffer)
                            _split_long(line, enc, target - length(header) - 2, 0,
                                        lambda part: emit(header + "\n" + part))
                            buffer = header
                        elif length(buffer + "\n" + line) > target:
                            emit(buffer)
                            buffer = header + "\n" + line
                        else:
                            buffer += "\n" + line
                    if buffer != header:
                        emit(buffer)
                else:
                    _split_long(block, enc, target, overlap, emit)
            elif length(pending + "\n\n" + block) > target:
                emit(pending)
                tail = _tail(pending, enc, overlap)
                pending = tail + "\n\n" + block if length(tail + "\n\n" + block) <= target else block
            else:
                pending = (pending + "\n\n" + block).strip()
        emit(pending)
    return result


def _tail(text, enc, count):
    if not count:
        return ""
    ids = enc.encode(text, disallowed_special=())
    start = max(0, len(ids) - count)
    # decode_single_token_bytes can split a multi-byte Chinese character at token boundaries.
    while start < len(ids):
        try:
            return enc.decode_bytes(ids[start:]).decode("utf-8")
        except UnicodeDecodeError:
            start += 1
    return ""


def _split_long(text, enc, target, overlap, emit):
    ids = enc.encode(text, disallowed_special=())
    start = 0
    while start < len(ids):
        end = min(start + target, len(ids))
        while end > start:
            try:
                part = enc.decode_bytes(ids[start:end]).decode("utf-8")
                break
            except UnicodeDecodeError:
                end -= 1
        if end <= start:
            raise ValueError("Chunk token budget too small for a Unicode character")
        emit(part)
        if end == len(ids):
            break
        next_start = max(start + 1, end - overlap)
        while next_start < end:
            try:
                enc.decode_bytes(ids[next_start:end]).decode("utf-8")
                break
            except UnicodeDecodeError:
                next_start += 1
        start = next_start
