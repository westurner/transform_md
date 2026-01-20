transform_md — README
======================

Purpose
-------

Small utility to normalize Gemini/Chat export markdown into cleaner markdown.

Current behavior
----------------
- Replaces lines that equal `Code snippet` (ignoring surrounding whitespace) with a mermaid fence opener: ```````mermaid``````
- Automatically inserts a closing fence (```````) after the mermaid block. The transformer attempts to preserve blank-line structure.
- CLI supports single-file transform and directory batch mode (`--indir`/`--outdir`).

Library API
-----------

- `transform_text(text: str) -> str`
  - Transform raw markdown and return transformed text.

- `transform_file(in_path: Path, out_path: Optional[Path]) -> Path`
  - Read `in_path`, write transformed content to `out_path` (overwrites if omitted), and return the written path.

CLI
---

Usage examples:

Transform a single file in-place:

```bash
python3 transform_md.py example.md
```

Transform a single file to a new path:

```bash
python3 transform_md.py example.md -o out/cleaned.md
```

Batch transform a directory (write to `out/cleaned_chats`):

```bash
python3 transform_md.py --indir chats/ --outdir out/cleaned_chats
```

Notes
-----

- The transformer is intentionally conservative: it only converts full lines matching `Code snippet` to open a mermaid block and attempts to insert a closing fence when it detects content following that marker.
- If you want additional rules (other labels to fenced blocks, heading normalizations, trimming), extend `transform_text()` and add tests in `tests/`.

Development
-----------

Run tests (preferred via the prefixed Makefile in `src/sustainablefactory/scripts`):

```bash
# from repo root
make -C src/sustainablefactory/scripts md-test
```

Run the transform via `make` (batch mode):

```bash
# from repo root
make -C src/sustainablefactory/scripts md-transform INDIR=chats/ OUTDIR=out/cleaned_chats
```

You can still run the script directly if needed (see examples above).
