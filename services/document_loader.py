"""Loads the project document and serves *small, targeted* slices of it to agents."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

from services.errors import DocumentError

_HEADING = re.compile(r"^(#{1,3})\s+(.*\S)\s*$")
_NUMBERING = re.compile(r"^\d+[\.\)]?\s*")


def _norm_heading(title: str) -> str:
    return _NUMBERING.sub("", title.strip()).lower()


def _compact(text: str) -> str:
    text = text.replace("**", "")
    lines = [ln.rstrip() for ln in text.splitlines()]
    return "\n".join(ln for ln in lines if ln.strip())


class ProjectDocument:
    def __init__(self, path: Path, raw: str):
        self.path = path
        self.raw = raw
        self.sha256 = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
        self.title = ""
        self.sections: dict[str, str] = {}
        self._parse()

    def _parse(self) -> None:
        current, buf = None, []
        for line in self.raw.splitlines():
            m = _HEADING.match(line)
            if m and len(m.group(1)) == 1 and not self.title:
                self.title = m.group(2).strip()
                continue
            if m and len(m.group(1)) >= 2:
                if current is not None:
                    self.sections[current] = "\n".join(buf)
                current, buf = _norm_heading(m.group(2)), []
            elif current is not None:
                buf.append(line)
        if current is not None:
            self.sections[current] = "\n".join(buf)
        if not self.sections:
            raise DocumentError(f"{self.path}: no '## ' sections found; expected a structured markdown document")

    def get(self, *names: str, max_chars: int = 3500) -> str:
        """Concatenate sections matching `names` (exact heading first, else substring), truncated evenly."""
        picked: list[str] = []
        for name in names:
            name = name.lower()
            hits = [h for h in self.sections if h == name] or [h for h in self.sections if name in h]
            for h in hits:
                if h not in picked:
                    picked.append(h)
        if not picked:
            return ""
        per = max(300, max_chars // len(picked))
        parts = []
        for h in picked:
            body = _compact(self.sections[h])
            if len(body) > per:
                body = body[:per].rsplit("\n", 1)[0]
            parts.append(f"## {h.title()}\n{body}")
        return "\n".join(parts)

    def detect_duration_weeks(self):
        """Deterministic duration detection ('4 weeks', 'one month')."""
        text = self.raw.lower()
        m = re.search(r"(\d+)\s*[- ]?\s*weeks?", text)
        if m:
            return int(m.group(1))
        if re.search(r"\b(one|1)\s*[- ]?\s*month", text):
            return 4
        return None


def load_document(path: Path) -> ProjectDocument:
    path = Path(path)
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise DocumentError(f"Cannot read project document {path}: {exc}") from exc
    if len(raw.strip()) < 200:
        raise DocumentError(f"{path} is too short to be a project document")
    return ProjectDocument(path, raw)
