"""CLI: python -m truthguard.ingest <path> [<path> ...]"""
from __future__ import annotations

import sys
from pathlib import Path

from truthguard.config import ensure_dirs
from truthguard.ingest import run


def main() -> None:
    ensure_dirs()
    args = sys.argv[1:]
    if not args:
        print("Usage: python -m truthguard.ingest <dir-or-file> ...")
        sys.exit(1)

    paths: list[str] = []
    for arg in args:
        p = Path(arg)
        if p.is_dir():
            # Recursively collect all supported files
            for ext in ("*.txt", "*.pdf", "*.docx", "*.eml"):
                paths.extend(str(f) for f in p.rglob(ext))
        elif p.is_file():
            paths.append(str(p))

    if not paths:
        print(f"No files found in: {args}")
        sys.exit(0)

    doc_ids = run(paths)
    print(f"Ingested {len(doc_ids)} document(s): {doc_ids}")


if __name__ == "__main__":
    main()
