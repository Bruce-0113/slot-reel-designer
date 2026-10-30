"""File output shared by the command-line tools."""

from __future__ import annotations

from pathlib import Path


def save(text: str, path: Path) -> str:
    """Write ``text`` to ``path``; return 'created', 'updated' or 'unchanged'."""
    if path.exists():
        state = "unchanged" if path.read_text() == text else "updated"
    else:
        state = "created"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return state
