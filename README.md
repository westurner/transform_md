transform_md — README
======================

Purpose
-------

`transform_md` is an extensible utility to normalize and transform markdown files, specifically focused on cleaning up AI-generated chat exports and syncing them with Jupyter Notebooks. It supports multiple markdown dialects (Standard, MyST, Quarto) and provides a pluggable registry for user-defined formats.

Core Features
-------------
- **Clean Chat Exports**: Automatically converts "Code snippet" markers into mermaid blocks and handles turn-based conversational splitting.
- **Notebook Synchronization**: Two-way sync between `.md` and `.ipynb` files, preserving metadata, kernelspecs, and cell-types.
- **Multi-Format Support**:
    - **Standard**: Generic triple-backtick markdown.
    - **MyST**: Markdown for Sphinx/JupyterBook (using ` ```{code-cell} `).
    - **Quarto**: Data science publishing (`.qmd`) with support for `#|` directives.
    - **Chat Export**: Specialized handling for Gemini/AI chat exports with turn detection.
- **Extensible Architecture**: Register new file extensions (e.g., `.abc2.md`) with custom cell templates (e.g., ` ```abc2-{lang} `) and default transform sets.
- **Image Persistence**: Optional downloading of remote "Image of..." tags to local assets.

Transform Registry
------------------

Available transforms include:
- `code_snippet`: Converts `Code snippet` lines into mermaid fences (default for Chat Export).
- `close_fences`: Ensures all code blocks are correctly terminated (default on).
- `collapse_blanks`: Reduces excessive vertical whitespace (default on).
- `chat_split_m1`: Splits a chat conversation into individual markdown cells for each turn.
- `chat_split_m2`: Splits a chat into Python code cells using `promptstr("""...""")` with the response as a Markdown output.

Library API
-----------

- `transform_text(text: str, format=...) -> str`
  - Transform raw markdown text based on a specific format configuration.

- `md_to_notebook(text: str, enabled_transforms=None, format=...) -> dict`
  - Convert markdown text to a Jupyter Notebook dictionary. Supports chat-splitting modes.

- `notebook_to_md(nb: dict, format=...) -> str`
  - Convert a Jupyter Notebook dictionary back to markdown using format-specific templates.

- `REGISTRY.register(MarkdownConfig(...))`
  - Add support for a new markdown extension and behavior.

CLI
---

Usage examples:

Transform a single file in-place (detecting format by extension):

```bash
python3 transform_md.py example.md
```

Convert between dialects (e.g., MyST to Quarto):

```bash
python3 transform_md.py input.myst.md -o output.qmd --out-format qmd
```

Generate multiple output formats at once:

```bash
python3 transform_md.py input.md -o output --out-format myst,qmd,ipynb
```

Split a chat into a notebook using "Mode 1" (markdown cells) while keeping default transforms:

```bash
python3 transform_md.py chat.md --transform-cell-split m1 --sync
```

Split a chat into a notebook using "Mode 2" (code cells):

```bash
python3 transform_md.py chat.md --run-transforms chat_split_m2 --sync
```

Batch transform a directory of Quarto files:

```bash
python3 transform_md.py --indir science/ --outdir build/ --format qmd
```

Sync markdown to notebook (creates/updates `example.ipynb`):

```bash
python3 transform_md.py example.md --sync
```

Convert notebook to markdown using MyST syntax:

```bash
python3 transform_md.py example.ipynb --sync --out-format myst
```

Options:
- `--format`: Set both input and output markdown dialects.
- `--in-format`: Explicitly define how to parse the input file.
- `--out-format`: Explicitly define how to generate the output file.
- `--transform-cell-split`: Add `m1` or `m2` cell splitting to the enabled transforms.
- `--sync`: Enable two-way conversion between `.md` and `.ipynb`.

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
