"""Local Binary Ninja guide documentation queries.

Searches the HTML docs shipped with Binary Ninja (D:/BN/docs/ on Windows,
/Applications/Binary Ninja.app/Contents/Resources/docs on macOS, etc.).
No bridge call — everything is done from the on-disk HTML tree.
"""

from __future__ import annotations

import os
import platform
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path

DOCS_DIR_ENV = "BN_DOCS_DIR"


def find_docs_dir(explicit: str | None = None) -> Path:
    """Resolve the Binary Ninja guide docs directory."""
    if explicit:
        p = Path(explicit).expanduser()
        if p.is_dir():
            return p

    env = os.environ.get(DOCS_DIR_ENV)
    if env:
        p = Path(env).expanduser()
        if p.is_dir():
            return p

    system = platform.system()
    if system == "Darwin":
        p = Path("/Applications/Binary Ninja.app/Contents/Resources/docs")
        if p.is_dir():
            return p

    candidates = []
    if system == "Windows":
        local = os.environ.get("LOCALAPPDATA")
        if local:
            candidates.append(Path(local) / "Vector35" / "BinaryNinja" / "docs")
        program_files = os.environ.get("PROGRAMFILES", "C:\\Program Files")
        candidates.append(Path(program_files) / "Vector35" / "BinaryNinja" / "docs")
        # Common alternative install locations
        candidates.append(Path("D:/BN/docs"))
        candidates.append(Path("C:/BN/docs"))

    candidates.append(Path.home() / "binaryninja" / "docs")
    candidates.append(Path("/opt/binaryninja/docs"))
    candidates.append(Path("/opt/binaryninja/docs"))

    for c in candidates:
        if c.is_dir():
            return c

    raise FileNotFoundError(
        f"Could not locate Binary Ninja docs. Set {DOCS_DIR_ENV} "
        f"or pass --docs-dir. Searched: " + ", ".join(str(c) for c in candidates)
    )


class _TextExtractor(HTMLParser):
    """Extract readable text and title from HTML, skipping CSS/JS/nav."""

    def __init__(self):
        super().__init__()
        self.text: list[str] = []
        self.title: str = ""
        self.in_title = False
        self.in_skip = 0  # nest level for style/script/nav/header

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "nav", "header", "footer"):
            self.in_skip += 1
        elif tag == "title":
            self.in_title = True

    def handle_endtag(self, tag):
        if tag in ("script", "style", "nav", "header", "footer"):
            self.in_skip = max(0, self.in_skip - 1)
        elif tag == "title":
            self.in_title = False

    def handle_data(self, data):
        if self.in_skip > 0:
            return
        text = data.strip()
        if not text:
            return
        if self.in_title:
            self.title = text
        else:
            self.text.append(text)


def _extract_text(html_path: Path) -> tuple[str, str]:
    """Extract title and body text from an HTML file. Returns (title, text)."""
    extractor = _TextExtractor()
    try:
        extractor.feed(html_path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return (html_path.stem, "")
    return (extractor.title or html_path.stem, " ".join(extractor.text))


@dataclass
class PageEntry:
    relpath: str
    title: str
    text: str


def build_index(docs_dir: Path) -> list[PageEntry]:
    """Build an index of all HTML pages in the docs directory."""
    entries = []
    for html_path in sorted(docs_dir.rglob("*.html")):
        rel = str(html_path.relative_to(docs_dir))
        # Skip search index files and assets
        if "search/" in rel or "assets/" in rel or "fonts/" in rel:
            continue
        title, text = _extract_text(html_path)
        entries.append(PageEntry(relpath=rel, title=title, text=text))
    return entries


def search(entries: list[PageEntry], pattern: str, max_results: int = 20) -> list[tuple[PageEntry, list[str]]]:
    """Full-text search across indexed pages. Returns matching entries with context lines."""
    try:
        regex = re.compile(pattern, re.IGNORECASE)
    except re.error:
        return []

    results = []
    for entry in entries:
        matches = []
        # Search title
        if regex.search(entry.title):
            matches.append(f"TITLE: {entry.title}")
        # Search body text
        for m in regex.finditer(entry.text):
            start = max(0, m.start() - 40)
            end = min(len(entry.text), m.end() + 40)
            ctx = entry.text[start:end]
            matches.append(f"...{ctx}...")
            if len(matches) >= 5:
                break

        if matches:
            results.append((entry, matches))

    return results[:max_results]


def format_search_results(results: list[tuple[PageEntry, list[str]]]) -> str:
    """Format search results as readable text."""
    if not results:
        return "No matches found."

    lines = []
    for entry, matches in results:
        lines.append(f"  {entry.title}")
        lines.append(f"    {entry.relpath}")
        for m in matches[:3]:
            # Truncate long lines
            if len(m) > 120:
                m = m[:117] + "..."
            lines.append(f"      {m}")
        lines.append("")
    return "\n".join(lines)


def show_page(docs_dir: Path, name: str) -> str | None:
    """Show the full text content of a page by name (partial match)."""
    matches = []
    for html_path in sorted(docs_dir.rglob("*.html")):
        rel = str(html_path.relative_to(docs_dir))
        stem = html_path.stem
        if name.lower() in rel.lower() or name.lower() in stem.lower():
            matches.append(html_path)

    if not matches:
        return None

    # Use the best match (shortest path)
    html_path = min(matches, key=lambda p: len(str(p)))
    title, text = _extract_text(html_path)
    rel = str(html_path.relative_to(docs_dir))

    return f"{title}\n  {rel}\n\n{text}"


def list_pages(entries: list[PageEntry], filter_term: str = "") -> str:
    """List all indexed pages, optionally filtered."""
    filtered = entries
    if filter_term:
        fl = filter_term.lower()
        filtered = [e for e in entries if fl in e.relpath.lower() or fl in e.title.lower()]

    lines = [f"  {e.title:<50} {e.relpath}" for e in filtered]
    return "\n".join(lines)
