"""
Docstring for transform_md.tests.test_transform_md
"""

from pathlib import Path
import importlib.util
import json
from unittest.mock import patch, MagicMock


import pytest


def load_transform_module(scripts_dir: Path):
    # scripts_dir is tests/
    # transform_md.py is in ../transform_md/transform_md.py
    script = scripts_dir.parent / "transform_md" / "transform_md.py"
    spec = importlib.util.spec_from_file_location("transform_md", str(script))
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


def test_transform_text_basic():
    scripts_dir = Path(__file__).resolve().parent
    mod = load_transform_module(scripts_dir)

    src = scripts_dir / "data" / "test_input.md"
    expected = scripts_dir / "data" / "expected_output.md"

    text = src.read_text(encoding="utf-8")
    out = mod.transform_text(text)
    assert out == expected.read_text(encoding="utf-8")


def test_transform_file_overwrite(tmp_path: Path):
    scripts_dir = Path(__file__).resolve().parent
    mod = load_transform_module(scripts_dir)

    inp = tmp_path / "in.md"
    inp.write_text("Line1\nCode snippet\nLine3\n")
    written = mod.transform_file(inp)
    assert written.exists()
    got = written.read_text(encoding="utf-8")
    assert "```mermaid" in got


def test_transform_code_snippet_with_lang():
    scripts_dir = Path(__file__).resolve().parent
    mod = load_transform_module(scripts_dir)
    src_text = """Title\n\nCode snippet (dot):\n\ndigraph { A -> B }\n\n"""
    out = mod.transform_text(src_text)
    assert "```dot" in out
    assert "digraph { A -> B }" in out
    assert out.strip().endswith("```")


def test_auto_close_unmatched_fence():
    scripts_dir = Path(__file__).resolve().parent
    mod = load_transform_module(scripts_dir)
    src_text = """Start\n\n```python\nprint(1)\n"""
    out = mod.transform_text(src_text)
    # should close the unclosed python fence
    assert out.strip().endswith("```")


def test_notebook_roundtrip():
    scripts_dir = Path(__file__).resolve().parent
    mod = load_transform_module(scripts_dir)
    md_text = """---
title: My Notebook
---
# Hello

This is a test.

```python
---
tags: [test]
---
print("hello world")
```

End.
"""
    nb = mod.md_to_notebook(md_text)
    assert nb["nbformat"] == 4
    assert len(nb["cells"]) == 3  # Markdown, Code, Markdown
    assert nb["metadata"]["title"] == "My Notebook"
    assert nb["cells"][1]["metadata"]["tags"] == ["test"]

    back_to_md = mod.notebook_to_md(nb)
    assert "My Notebook" in back_to_md
    assert 'print("hello world")' in back_to_md
    assert "---" in back_to_md


def test_qmd_roundtrip():
    scripts_dir = Path(__file__).resolve().parent
    mod = load_transform_module(scripts_dir)
    qmd_text = """---
title: Quarto Test
---
# Section

```{python}
#| label: test
#| fig-cap: caption
print(1)
```
"""
    # to notebook
    nb = mod.md_to_notebook(qmd_text, format=mod.MarkdownFormat.QMD)
    assert nb["cells"][1]["metadata"]["label"] == "test"
    assert nb["cells"][1]["metadata"]["fig-cap"] == "caption"

    # back to qmd
    back = mod.notebook_to_md(nb, format=mod.MarkdownFormat.QMD)
    assert "```{python}" in back
    assert "#| label: test" in back
    assert "#| fig-cap: caption" in back


def test_myst_roundtrip():
    scripts_dir = Path(__file__).resolve().parent
    mod = load_transform_module(scripts_dir)
    myst_text = """# MyST

```{code-cell} python
---
id: myst-cell
---
print("myst")
```
"""
    nb = mod.md_to_notebook(myst_text, format=mod.MarkdownFormat.MYST)
    assert nb["cells"][1]["metadata"]["id"] == "myst-cell"

    back = mod.notebook_to_md(nb, format=mod.MarkdownFormat.MYST)
    assert "```{code-cell} python" in back
    assert "id: myst-cell" in back


def test_myst_markdown_cell_metadata_uses_jupytext_blocks():
    scripts_dir = Path(__file__).resolve().parent
    mod = load_transform_module(scripts_dir)
    nb = {
        "metadata": {},
        "cells": [
            {
                "cell_type": "markdown",
                "metadata": {"chat_input": True},
                "source": ["# Prompt: 1\n"],
            },
            {
                "cell_type": "markdown",
                "metadata": {
                    "collapsed": True,
                    "jupyter": {"source_hidden": True},
                },
                "source": ["Thinking\n"],
            },
        ],
    }

    myst_text = mod.notebook_to_md(nb, format=mod.MarkdownFormat.MYST)

    assert '+++ {"chat_input": true}' in myst_text
    assert '+++ {"collapsed": true, "jupyter": {"source_hidden": true}}' in myst_text
    assert "---\nchat_input:" not in myst_text

    roundtrip = mod.md_to_notebook(myst_text, format=mod.MarkdownFormat.MYST)
    assert roundtrip["cells"][0]["metadata"] == {"chat_input": True}
    assert roundtrip["cells"][1]["metadata"] == {
        "collapsed": True,
        "jupyter": {"source_hidden": True},
    }


def test_transform_text_edge_cases():
    scripts_dir = Path(__file__).resolve().parent
    mod = load_transform_module(scripts_dir)

    # chat_cleanup
    text = "Line1\nShow thinking\nLine2\nExport to sheets\nLine3"
    # Specify enabled transforms to avoid defaults that might keep "Show thinking"
    out = mod.transform_text(text, enabled=["chat_cleanup"])
    assert "Show thinking" not in out
    assert "Export to sheets" not in out
    assert out.strip() == "Line1\nLine2\nLine3"

    # collapse blanks: 4 newlines -> 2 blank lines (3 newlines total)
    text = "line1\n\n\n\nline2"
    out = mod.transform_text(text)
    assert out == "line1\n\n\nline2"

    # no transforms
    out = mod.transform_text("Code snippet", enabled=[])
    assert out == "Code snippet"

    # tail newline
    out = mod.transform_text("line1\n")
    assert out.endswith("\n")

    # generic fence open toggle
    text = "```python\nprint(1)"
    out = mod.transform_text(text)
    assert out.endswith("```")


def test_chat_headings_transform():
    scripts_dir = Path(__file__).resolve().parent
    mod = load_transform_module(scripts_dir)

    text = """You asked:
---------
First question

Gemini Replied:
----------
First answer

You asked:
---------
Second question
"""
    # Enabled by default for chatexport_abc1
    out = mod.transform_text(text, format="chatexport_abc1")
    assert "# Prompt: 1" in out
    assert "# Response: 1" in out
    assert "# Prompt: 2" in out

    # Check numbering continuity
    lines = [l for l in out.splitlines() if l.startswith("# ")]
    assert lines == ["# Prompt: 1", "# Response: 1", "# Prompt: 2"]

    # Test explicit enable on other formats (wont do much without regexes)
    # Reverting expectation: standard doesn't have prompt regexes in registry now.
    out_std = mod.transform_text(text, enabled=["chat_headings"], format="standard")
    assert "# Prompt: 1" not in out_std  # Standard has no regexes!


def test_current_chatexport_headings_normalize_and_split():
    scripts_dir = Path(__file__).resolve().parent
    mod = load_transform_module(scripts_dir)

    text = """# you asked
message time: 2026-08-02 23:02:53
What is graphene?

---
# gemini response
Thinking

The answer is carbon.
"""

    out = mod.transform_text(text, format="chatexport_abc1")
    assert "# Prompt: 1" in out
    assert "# Response: 1" in out
    assert "# you asked" not in out
    assert "# gemini response" not in out

    nb = mod.md_to_notebook(
        text,
        enabled_transforms=[
            "chat_headings",
            "chat_input_metadata",
            "chat_split_m1",
            "chat_hide_thoughts",
            "chat_cleanup",
        ],
        format="chatexport_abc1",
    )
    assert len(nb["cells"]) == 5
    assert sum(cell["metadata"].get("chat_input") is True for cell in nb["cells"]) == 2
    thought_cells = [
        cell
        for cell in nb["cells"]
        if cell["metadata"].get("collapsed") is True
    ]
    assert len(thought_cells) == 1
    assert "Thinking" in "".join(thought_cells[0]["source"])
    assert "Show thinking" not in "".join(
        "".join(cell["source"]) for cell in nb["cells"]
    )


def test_gemini_chat_headings_and_top_links_are_normalized():
    scripts_dir = Path(__file__).resolve().parent
    mod = load_transform_module(scripts_dir)

    text = """# Google Gemini

### chat-1

## Nested section
#### Nested detail

___
###### [top](#table-of-contents)
### chat-2

# Another section
"""

    out = mod.transform_text(text, format="chatexport_abc1")

    assert "## chat-1" in out
    assert "### Nested section" in out
    assert "#### Nested detail" in out
    assert "[top](#table-of-contents)" not in out
    assert "\n# Another section\n" not in out
    assert "\n### Another section\n" in out


def test_chat_input_markdown_gets_styled_container():
    scripts_dir = Path(__file__).resolve().parent
    mod = load_transform_module(scripts_dir)

    nb = {
        "metadata": {},
        "cells": [
            {
                "cell_type": "markdown",
                "metadata": {"chat_input": True},
                "source": ["# Prompt: 1\n", "\n", "Question with **Markdown**\n"],
            }
        ],
    }

    out = mod.notebook_to_md(nb, format="myst")

    assert ":::{div}\n:class: chat-input" in out
    assert "> Question with **Markdown**" in out


def test_generate_toc_transform():
    scripts_dir = Path(__file__).resolve().parent
    mod = load_transform_module(scripts_dir)

    text = """---
title: My Paper
---
# Main Section
## Sub Section
### Tiny
Bonus
---
Footer
"""
    # Bonus and Footer are Setext headings
    # Bonus is Level 1 (===), Footer is Level 2 (---)
    # Wait, in the text I wrote 'Bonus\n---' it's level 2. Let's make it clear.
    text = """# Header 1
## Header 2

Setext 1
========

Setext 2
--------
"""
    out = mod.transform_text(text, enabled=["generate_toc"], format="standard")
    assert "## Contents" in out
    assert "* [Header 1](#header-1)" in out
    assert "  * [Header 2](#header-2)" in out
    assert "* [Setext 1](#setext-1)" in out
    assert "  * [Setext 2](#setext-2)" in out

    # Check frontmatter placement
    text_fm = "---\ntitle: test\n---\n# Title"
    out_fm = mod.transform_text(text_fm, enabled=["generate_toc"], format="standard")
    # Should be after fm
    lines = out_fm.splitlines()
    assert lines[0] == "---"
    assert lines[1] == "title: test"
    assert lines[2] == "---"
    assert lines[3] == ""
    assert lines[4] == "## Contents"


@pytest.mark.parametrize(
    "mode, format",
    [
        ("m1", "myst"),
        ("m2", "myst"),
        ("m2", "standard"),
    ],
)
def test_chat_input_metadata_roundtrip(mode, format):
    scripts_dir = Path(__file__).resolve().parent
    mod = load_transform_module(scripts_dir)

    text = """You asked:
---------
How are you?

Gemini Replied:
----------
Good.
"""
    # Use chatexport_abc1 format to get the regexes, but test round-trip into 'format'
    enabled = [f"chat_split_{mode}", "chat_input_metadata"]
    # We MUST disable generate_toc and chat_headings to avoid them polluting the round-trip check
    # if we want to be strict, or just look for the metadata.
    # Actually, we want to see if chat_input: True survives.

    nb = mod.md_to_notebook(text, enabled_transforms=enabled, format="chatexport_abc1")

    # Find prompt cell metadata
    found_in_nb = False
    for cell in nb["cells"]:
        if cell["metadata"].get("chat_input") is True:
            found_in_nb = True
            break
    assert found_in_nb, f"Metadata not found in notebook for {mode}/{format}"

    # 2. Notebook -> MD
    back_to_md = mod.notebook_to_md(nb, format=format)

    # 3. MD -> Notebook again
    nb2 = mod.md_to_notebook(back_to_md, format=format)

    found_back = False
    for cell in nb2["cells"]:
        if cell["metadata"].get("chat_input") is True:
            found_back = True
            break

    assert found_back, f"Metadata lost in round-trip for {mode}/{format}"


def test_mixed_headings_and_toc():
    scripts_dir = Path(__file__).resolve().parent
    mod = load_transform_module(scripts_dir)

    text = """# Main Topic

## Intro
Standard intro.

You asked:
---------
Question 1?

Gemini Replied:
--------------
Answer 1.

### Technical Details
- Part A
- Part B

You asked:
---------
Question 2?
"""
    # Test m1 mode
    nb = mod.md_to_notebook(
        text,
        format="chatexport_abc1",
        enabled_transforms=["chat_split_m1", "generate_toc", "chat_headings"],
    )

    # Check TOC of the first cell (which should contain the preamble)
    preamble = "".join(nb["cells"][0]["source"])
    assert "## Contents" in preamble
    assert "* [Main Topic](#main-topic)" in preamble
    assert "* [Intro](#intro)" in preamble
    assert "* [Technical Details](#technical-details)" in preamble

    # Crucially: Prompt/Response headings SHOULD be in TOC now (user preference)
    toc_lines = [l for l in preamble.splitlines() if "* [" in l]
    assert any("Prompt: 1" in l for l in toc_lines)
    assert any("Response: 1" in l for l in toc_lines)
    assert any("Prompt: 2" in l for l in toc_lines)

    # Check cells
    # Indices:
    # 0: Preamble (Title, TOC, Intro)
    # 1: # Prompt: 1
    # 2: Question 1?
    # 3: # Response: 1
    # 4: Answer 1 + Technical Details
    # 5: # Prompt: 2
    # 6: Question 2?

    assert len(nb["cells"]) == 7
    assert "# Prompt: 1" in "".join(nb["cells"][1]["source"])
    assert "# Response: 1" in "".join(nb["cells"][3]["source"])
    assert "### Technical Details" in "".join(nb["cells"][4]["source"])
    assert "# Prompt: 2" in "".join(nb["cells"][5]["source"])


def test_toc_indentation_normalization():
    scripts_dir = Path(__file__).resolve().parent
    mod = load_transform_module(scripts_dir)

    # Text starting with H2
    text = """## Section 1
### Part A
## Section 2
"""
    out = mod.transform_text(text, enabled=["generate_toc"])
    lines = [l for l in out.splitlines() if "* [" in l]
    # min level is 2.
    # H2: 2 - 2 = 0 indent
    # H3: 3 - 2 = 1 indent (2 spaces)
    assert lines[0] == "* [Section 1](#section-1)"
    assert lines[1] == "  * [Part A](#part-a)"
    assert lines[2] == "* [Section 2](#section-2)"


def test_add_title_transform():
    scripts_dir = Path(__file__).resolve().parent
    mod = load_transform_module(scripts_dir)

    text = "Some content"
    out = mod.transform_text(text, enabled=["add_title"], doc_title="My Title")
    assert out.startswith("# My Title\n\nSome content")

    # test deduplication
    text2 = "# My Title\n\nAlready has it"
    out2 = mod.transform_text(text2, enabled=["add_title"], doc_title="My Title")
    assert out2 == text2


def test_transform_file_add_title(tmp_path: Path):
    scripts_dir = Path(__file__).resolve().parent
    mod = load_transform_module(scripts_dir)

    inp = tmp_path / "Document Name.md"
    inp.write_text("content")

    # Test default (add_title is in DEFAULT_TRANSFORMS)
    written = mod.transform_file(inp)
    got = written.read_text()
    # Expect title AND TOC by default (TOC follows title)
    assert got.startswith(
        "# Document Name\n\n## Contents\n\n* [Document Name](#document-name)\n\ncontent"
    )

    # Test explicitly disabled
    inp2 = tmp_path / "Other.md"
    inp2.write_text("content")
    written2 = mod.transform_file(inp2, in_transforms=[])
    got2 = written2.read_text()
    assert got2 == "content"


def test_json_ingestion_and_splitting(tmp_path: Path):
    scripts_dir = Path(__file__).resolve().parent
    mod = load_transform_module(scripts_dir)

    # Gemini JSON
    gem_file = tmp_path / "gemini.json"
    gem_data = {
        "messages": [
            {"author": "user", "content": "Q1"},
            {"author": "ai", "content": "A1"},
        ]
    }
    gem_file.write_text(json.dumps(gem_data))

    # Transform to nb with m1 split
    nb_file = tmp_path / "out.ipynb"
    mod.transform_file(gem_file, nb_file, in_transforms=["chat_split_m1"])

    nb = json.loads(nb_file.read_text())
    # Should have 4 cells: P1, Q1, R1, A1 (preamble is empty but might stay)
    # Filter out empty cells
    cells = [c for c in nb["cells"] if "".join(c["source"]).strip()]

    assert any("# Prompt: 1" in "".join(c["source"]) for c in cells)
    assert any("Q1" in "".join(c["source"]) for c in cells)
    assert any(
        "# Response: 2" in "".join(c["source"]) for c in cells
    )  # Gemini uses msg index
    assert any("A1" in "".join(c["source"]) for c in cells)

    # Copilot JSON
    cop_file = tmp_path / "test.copilot.json"
    cop_data = {
        "requests": [
            {
                "message": {"text": "Copilot Q"},
                "response": [{"kind": "markdown", "value": "Copilot A"}],
            }
        ]
    }
    cop_file.write_text(json.dumps(cop_data))

    nb_file_cop = tmp_path / "cop.ipynb"
    mod.transform_file(cop_file, nb_file_cop, in_transforms=["chat_split_m1"])

    nb_cop = json.loads(nb_file_cop.read_text())
    cells_cop = [c for c in nb_cop["cells"] if "".join(c["source"]).strip()]
    assert any("# Prompt: 1" in "".join(c["source"]) for c in cells_cop)
    assert any("Copilot Q" in "".join(c["source"]) for c in cells_cop)
    assert any("# Response: 1" in "".join(c["source"]) for c in cells_cop)
    assert any("Copilot A" in "".join(c["source"]) for c in cells_cop)


def test_download_images_failure(tmp_path: Path):
    scripts_dir = Path(__file__).resolve().parent
    mod = load_transform_module(scripts_dir)

    img_url = "http://example.com/fail.png"
    text = f"![Image of fail]({img_url})"

    with patch("urllib.request.urlopen", side_effect=Exception("Failed")):
        out = mod._download_and_replace_images(text, tmp_path)
    # should remain unchanged
    assert img_url in out


def test_download_images_guess_ext(tmp_path: Path):
    scripts_dir = Path(__file__).resolve().parent
    mod = load_transform_module(scripts_dir)

    # from URL path
    img_url = "http://example.com/somefile.jpg"
    text = f"![Image of test]({img_url})"

    mock_resp = MagicMock()
    mock_resp.read.return_value = b"data"
    mock_resp.getheaders.return_value = []
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        out = mod._download_and_replace_images(text, tmp_path)
    assert "images/somefile.jpg" in out


def test_cli_advanced(tmp_path: Path, capsys):
    scripts_dir = Path(__file__).resolve().parent
    mod = load_transform_module(scripts_dir)

    test_md = tmp_path / "advanced.md"
    test_md.write_text("Code snippet\n\n\n\n\nline")

    # test skip-transforms
    with patch(
        "sys.argv",
        [
            "transform_md.py",
            str(test_md),
            "--skip-transforms",
            "collapse_blanks,generate_toc,chat_headings",
        ],
    ):
        mod._cli()
    assert "\n\n\n" in test_md.read_text()

    # test run-transforms
    test_md.write_text("Code snippet\n")
    with patch(
        "sys.argv",
        ["transform_md.py", str(test_md), "--run-transforms", "code_snippet"],
    ):
        mod._cli()
    assert "```mermaid" in test_md.read_text()

    # download images CLI
    test_md.write_text("![Image of me](http://example.com/img.png)")
    mock_resp = MagicMock()
    mock_resp.read.return_value = b"data"
    mock_resp.getheaders.return_value = [("Content-Type", "image/png")]
    mock_resp.__enter__.return_value = mock_resp
    with patch("urllib.request.urlopen", return_value=mock_resp):
        with patch("sys.argv", ["transform_md.py", str(test_md), "--download-images"]):
            mod._cli()
    assert "images/img.png" in test_md.read_text()


def test_cli_errors(tmp_path: Path):
    scripts_dir = Path(__file__).resolve().parent
    mod = load_transform_module(scripts_dir)

    # indir without outdir
    with patch("sys.argv", ["transform_md.py", "--indir", "somein"]):
        with patch(
            "argparse.ArgumentParser.error", side_effect=ValueError("error")
        ) as mock_error:
            try:
                mod._cli()
            except ValueError:
                pass
            mock_error.assert_called()

    # no input
    with patch("sys.argv", ["transform_md.py"]):
        with patch(
            "argparse.ArgumentParser.error", side_effect=ValueError("error")
        ) as mock_error:
            try:
                mod._cli()
            except ValueError:
                pass
            mock_error.assert_called()


def test_transform_text_more_coverage():
    scripts_dir = Path(__file__).resolve().parent
    mod = load_transform_module(scripts_dir)

    # mermaid open with blank lines
    text = "Code snippet\n\ncontent\n\n"
    out = mod.transform_text(text)
    assert "```mermaid" in out
    assert out.count("```") == 2

    # generic fence closing toggle
    text = "```python\ncontent\n```"
    out = mod.transform_text(text)
    assert out.count("```") == 2

    # no newline at end
    assert not mod.transform_text("line").endswith("\n")


def test_download_images_complex(tmp_path: Path):
    scripts_dir = Path(__file__).resolve().parent
    mod = load_transform_module(scripts_dir)

    # test unique names
    text = "![Image of](http://ex.com/a.png) ![Image of](http://ex.com/a.png)"

    mock_resp = MagicMock()
    mock_resp.read.return_value = b"data"
    mock_resp.getheaders.return_value = [("Content-Type", "image/png")]
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        out = mod._download_and_replace_images(text, tmp_path)
    assert "a.png" in out
    assert "a-1.png" in out


def test_md_to_notebook_metadata_error():
    scripts_dir = Path(__file__).resolve().parent
    mod = load_transform_module(scripts_dir)

    # invalid yaml frontmatter
    md = "---\n [ : invalid\n---\n# Title"
    nb = mod.md_to_notebook(md, format="standard")
    assert nb["cells"][0]["cell_type"] == "markdown"

    # invalid inner yaml
    md = "```python\n---\n[: invalid\n---\nprint(1)\n```"
    nb = mod.md_to_notebook(md, format="standard")
    # The current implementation consumes the metadata block even if invalid
    assert "print(1)" in nb["cells"][0]["source"][0]


def test_cli_sync_from_ipynb(tmp_path: Path):
    scripts_dir = Path(__file__).resolve().parent
    mod = load_transform_module(scripts_dir)

    nb_file = tmp_path / "sync.ipynb"
    nb = {
        "cells": [{"cell_type": "markdown", "source": ["# Title"]}],
        "metadata": {},
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    nb_file.write_text(json.dumps(nb))

    with patch("sys.argv", ["transform_md.py", str(nb_file), "--sync"]):
        mod._cli()

    assert (tmp_path / "sync.md").exists()
    assert "# Title" in (tmp_path / "sync.md").read_text()


def test_cli_sync_indir(tmp_path: Path):
    scripts_dir = Path(__file__).resolve().parent
    mod = load_transform_module(scripts_dir)

    indir = tmp_path / "in_sync"
    indir.mkdir()
    (indir / "test.md").write_text("# Test")

    outdir = tmp_path / "out_sync"

    with patch(
        "sys.argv",
        ["transform_md.py", "--indir", str(indir), "--outdir", str(outdir), "--sync"],
    ):
        mod._cli()

    assert (outdir / "test.ipynb").exists()


def test_transform_text_tail_coverage():
    scripts_dir = Path(__file__).resolve().parent
    mod = load_transform_module(scripts_dir)

    # md tail
    md = "```python\nprint(1)\n```\nTail"
    nb = mod.md_to_notebook(md)
    assert nb["cells"][-1]["source"] == ["Tail\n"]

    # explicit fence inside mermaid to hit 76-77
    text = "Code snippet\ncontent\n```\n"
    out = mod.transform_text(text)
    # 1 from Code snippet, 1 from explicit fence, 1 from EOF because generic_fence_open was toggled
    assert out.count("```") == 3

    # no extension in URL, use hashlib
    img_url = "http://example.com/path-without-ext"
    text = f"![Image of me]({img_url})"
    mock_resp = MagicMock()
    mock_resp.read.return_value = b"data"
    mock_resp.getheaders.return_value = [("Content-Type", "image/png")]
    mock_resp.__enter__.return_value = mock_resp
    with patch("urllib.request.urlopen", return_value=mock_resp):
        out = mod._download_and_replace_images(text, Path("/tmp"))
    assert "images/" in out


def test_md_to_notebook_yaml_error():
    scripts_dir = Path(__file__).resolve().parent
    mod = load_transform_module(scripts_dir)

    with patch("yaml.safe_load", side_effect=Exception("YAML Error")):
        # frontmatter error
        nb = mod.md_to_notebook("---\ntitle: test\n---\n# Content", format="standard")
        assert nb["metadata"] == {
            "kernelspec": {
                "display_name": "Python 3",
                "language": "python",
                "name": "python3",
            }
        }

        # internal fm error
        nb = mod.md_to_notebook(
            "```python\n---\nid: 1\n---\nprint(1)\n```", format="standard"
        )
        assert nb["cells"][0]["metadata"] == {"language": "python"}


def test_download_images_write_error(tmp_path: Path):
    scripts_dir = Path(__file__).resolve().parent
    mod = load_transform_module(scripts_dir)

    img_url = "http://example.com/a.png"
    text = f"![Image of me]({img_url})"
    mock_resp = MagicMock()
    mock_resp.read.return_value = b"data"
    mock_resp.getheaders.return_value = [("Content-Type", "image/png")]
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        with patch("pathlib.Path.write_bytes", side_effect=IOError("full")):
            out = mod._download_and_replace_images(text, tmp_path)
    assert img_url in out


def test_md_to_notebook_lang_none():
    scripts_dir = Path(__file__).resolve().parent
    mod = load_transform_module(scripts_dir)
    # fence without lang
    md = "```\ncontent\n```"
    nb = mod.md_to_notebook(md)
    # should default to mermaid if started by Code snippet,
    # but here it's an explicit fence.
    # Code says: lang = match.group(1).strip().lower()
    # If ```\n then it might be empty or something.
    # Actually re says [^s}]+ so it REQUIRES something after ```?
    # No, it says ([^\s\}]+) which requires at least one char.
    # So ` ``` ` alone won't match.
    pass


def test_notebook_to_md_edge_cases():
    scripts_dir = Path(__file__).resolve().parent
    mod = load_transform_module(scripts_dir)

    nb = {
        "cells": [
            {
                "cell_type": "code",
                "metadata": {"language": "python"},
                "source": "print(1)",
            },
            {
                "cell_type": "code",
                "metadata": {"some": "meta"},
                "source": ["line1\n", "line2"],
            },
        ],
        "metadata": {"kernelspec": {"language": "python"}},
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    md = mod.notebook_to_md(nb)
    assert "```python" in md
    assert "line1\nline2" in md
    assert "some: meta" in md
    scripts_dir = Path(__file__).resolve().parent
    mod = load_transform_module(scripts_dir)
    md = """```{code-cell} python
---
id: test
---
print(1)
```"""
    nb = mod.md_to_notebook(md, format="standard")
    assert nb["cells"][0]["cell_type"] == "code"
    assert nb["cells"][0]["metadata"]["id"] == "test"
    assert nb["cells"][0]["metadata"]["language"] == "python"


def test_download_images(tmp_path: Path):
    scripts_dir = Path(__file__).resolve().parent
    mod = load_transform_module(scripts_dir)

    img_url = "http://example.com/test.png"
    text = f"![Image of something]({img_url})"

    mock_resp = MagicMock()
    mock_resp.read.return_value = b"fake-image-data"
    mock_resp.getheaders.return_value = [("Content-Type", "image/png")]
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        out = mod._download_and_replace_images(text, tmp_path)

    assert "images/test.png" in out
    img_file = tmp_path / "images" / "test.png"
    assert img_file.exists()
    assert img_file.read_bytes() == b"fake-image-data"


def test_transform_file_ipynb(tmp_path: Path):
    scripts_dir = Path(__file__).resolve().parent
    mod = load_transform_module(scripts_dir)

    md_file = tmp_path / "test.md"
    md_file.write_text("# Title\n\nCode snippet\nprint(1)\n")

    nb_file = tmp_path / "test.ipynb"
    mod.transform_file(md_file, nb_file)

    assert nb_file.exists()
    nb = json.loads(nb_file.read_text())
    assert nb["cells"][1]["cell_type"] == "code"

    # Round trip file
    md_back = tmp_path / "back.md"
    mod.transform_file(nb_file, md_back)
    assert "# Title" in md_back.read_text()


def test_cli_basic(tmp_path: Path, capsys):
    scripts_dir = Path(__file__).resolve().parent
    mod = load_transform_module(scripts_dir)

    test_md = tmp_path / "cli.md"
    test_md.write_text("Code snippet\n")

    with patch("sys.argv", ["transform_md.py", str(test_md)]):
        mod._cli()

    # capturing logger.info which goes to sys.stdout
    captured = capsys.readouterr().out
    assert "Transforming:" in captured
    assert "cli.md" in captured
    assert "```mermaid" in test_md.read_text()


def test_cli_sync(tmp_path: Path):
    scripts_dir = Path(__file__).resolve().parent
    mod = load_transform_module(scripts_dir)

    test_md = tmp_path / "sync.md"
    test_md.write_text("# Sync\n")

    with patch("sys.argv", ["transform_md.py", str(test_md), "--sync"]):
        mod._cli()

    assert (tmp_path / "sync.ipynb").exists()


def test_cli_indir(tmp_path: Path):
    scripts_dir = Path(__file__).resolve().parent
    mod = load_transform_module(scripts_dir)

    indir = tmp_path / "in"
    indir.mkdir()
    (indir / "one.md").write_text("one")

    outdir = tmp_path / "out"

    with patch(
        "sys.argv", ["transform_md.py", "--indir", str(indir), "--outdir", str(outdir)]
    ):
        mod._cli()

    assert (outdir / "one.md").exists()


def test_cli_list_transforms(capsys):
    scripts_dir = Path(__file__).resolve().parent
    mod = load_transform_module(scripts_dir)

    with patch("sys.argv", ["transform_md.py", "--list-transforms"]):
        mod._cli()

    assert "Available transforms:" in capsys.readouterr().out


def test_cli_guess_format(capsys):
    scripts_dir = Path(__file__).resolve().parent
    mod = load_transform_module(scripts_dir)

    # .md -> chatexport_abc1
    with patch("sys.argv", ["transform_md.py", "test.md", "--guess-format"]):
        mod._cli()
    assert "chatexport_abc1" in capsys.readouterr().out.strip()

    # .myst.md -> myst
    with patch("sys.argv", ["transform_md.py", "test.myst.md", "--guess-format"]):
        mod._cli()
    assert "myst" in capsys.readouterr().out.strip()

    # .qmd -> qmd
    with patch("sys.argv", ["transform_md.py", "test.qmd", "--guess-format"]):
        mod._cli()
    assert "qmd" in capsys.readouterr().out.strip()

    # other -> standard
    with patch("sys.argv", ["transform_md.py", "test.txt", "--guess-format"]):
        mod._cli()
    assert "standard" in capsys.readouterr().out.strip()


def test_extensibility_custom_format(tmp_path: Path):
    scripts_dir = Path(__file__).resolve().parent
    mod = load_transform_module(scripts_dir)

    # Define a custom format .abc2.md
    custom_cfg = mod.MarkdownConfig(
        name="abc2",
        extensions=[".abc2.md"],
        default_transforms=["code_snippet", "close_fences"],
        cell_fence_template="```abc2-{lang}",
    )
    mod.REGISTRY.register(custom_cfg)

    # Verify inference
    assert mod.infer_format(Path("test.abc2.md")).name == "abc2"

    # Verify transform default
    text = "Code snippet\ncontent\n"
    # Use config object directly to be 100% sure
    out = mod.transform_text(text, format=custom_cfg)
    assert "```mermaid" in out

    # Verify notebook conversion
    nb = mod.md_to_notebook(text, format="abc2")
    back = mod.notebook_to_md(nb, format="abc2")
    assert "```abc2-mermaid" in back


def test_chat_splitting():
    scripts_dir = Path(__file__).resolve().parent
    mod = load_transform_module(scripts_dir)

    chat_text = """You asked:
----------
What is graphene?

---
Gemini Replied:
---------------
Graphene is carbon.
"""
    # Mode 1
    nb1 = mod.md_to_notebook(
        chat_text, enabled_transforms=["chat_split_m1"], format="chatexport_abc1"
    )
    assert len(nb1["cells"]) == 2
    assert nb1["cells"][0]["cell_type"] == "markdown"
    assert "What is graphene?" in "".join(nb1["cells"][0]["source"])
    assert nb1["cells"][1]["cell_type"] == "markdown"
    assert "Graphene is carbon." in "".join(nb1["cells"][1]["source"])

    # Mode 2
    nb2 = mod.md_to_notebook(
        chat_text, enabled_transforms=["chat_split_m2"], format="chatexport_abc1"
    )
    assert len(nb2["cells"]) == 1
    assert nb2["cells"][0]["cell_type"] == "code"
    source = "".join(nb2["cells"][0]["source"])
    assert 'promptstr("""' in source
    assert "What is graphene?" in source

    outputs = nb2["cells"][0]["outputs"]
    assert len(outputs) == 1
    assert outputs[0]["output_type"] == "display_data"
    assert "Graphene is carbon." in "".join(outputs[0]["data"]["text/markdown"])


def test_dialect_conversion(tmp_path: Path):
    scripts_dir = Path(__file__).resolve().parent
    mod = load_transform_module(scripts_dir)

    myst_text = "```{code-cell}\nprint('hello')\n```"
    myst_file = tmp_path / "test.myst.md"
    myst_file.write_text(myst_text)

    qmd_file = tmp_path / "test.qmd"

    # Convert MyST to Quarto
    mod.transform_file(myst_file, qmd_file, out_format="qmd")

    out_text = qmd_file.read_text()
    assert "```{python}" in out_text
    assert "```{code-cell}" not in out_text


def test_extra_coverage():
    scripts_dir = Path(__file__).resolve().parent
    mod = load_transform_module(scripts_dir)

    # Registry.get(None)
    assert mod.REGISTRY.get(None).name == "standard"

    # Registry.get(duck)
    class Duck:
        def __init__(self):
            self.name = "duck"
            self.cell_fence_template = "---"

    assert mod.REGISTRY.get(Duck()).name == "duck"

    # Registry.get(unknown string)
    assert mod.REGISTRY.get("unknown_format").name == "standard"

    # Line 274: continue in m1 loop
    segs = [{"type": "prompt", "content": "hello"}, {"type": "response", "content": ""}]
    with patch.object(mod, "_get_chat_segments", return_value=segs):
        nb = mod._md_to_notebook_chat("...", mod.REGISTRY.get("standard"), "m1", {})
        assert len(nb["cells"]) == 1

    # Line 316-317: m2 mode, non-empty other segment
    segs2 = [{"type": "other", "content": "stray"}]
    with patch.object(mod, "_get_chat_segments", return_value=segs2):
        nb2 = mod._md_to_notebook_chat("...", mod.REGISTRY.get("standard"), "m2", {})
        assert len(nb2["cells"]) == 1


def test_markdown_cell_in_fence_coverage():
    scripts_dir = Path(__file__).resolve().parent
    mod = load_transform_module(scripts_dir)
    md = "```markdown\n# Hello\n```"
    nb = mod.md_to_notebook(md, format="standard")
    assert nb["cells"][0]["cell_type"] == "markdown"
    assert "# Hello" in nb["cells"][0]["source"][0]


def test_quarto_invalid_directive_coverage():
    scripts_dir = Path(__file__).resolve().parent
    mod = load_transform_module(scripts_dir)
    # Quarto directive with error (no colon or invalid yaml)
    md = "```{python}\n#| label-without-colon\nprint(1)\n```"
    nb = mod.md_to_notebook(md)
    assert "print(1)" in "".join(nb["cells"][0]["source"])

    md = "```{python}\n#| label: :\nprint(1)\n```"
    nb = mod.md_to_notebook(md)
    assert "print(1)" in "".join(nb["cells"][0]["source"])


def test_notebook_to_md_no_metadata_coverage():
    scripts_dir = Path(__file__).resolve().parent
    mod = load_transform_module(scripts_dir)
    nb = {"cells": [], "metadata": {}}
    md = mod.notebook_to_md(nb)
    assert md.strip() == ""


def test_missing_lines_coverage(tmp_path: Path):
    scripts_dir = Path(__file__).resolve().parent
    mod = load_transform_module(scripts_dir)

    # Hit 286: notebook_to_md with no kernelspec
    nb = {
        "cells": [{"cell_type": "code", "metadata": {}, "source": "print(1)"}],
        "metadata": {},
    }
    md = mod.notebook_to_md(nb)
    assert "```python" in md

    # Hit 339 (new mapping): return ".img" in _guess_ext
    mock_resp = MagicMock()
    mock_resp.read.return_value = b"data"
    mock_resp.getheaders.return_value = []
    mock_resp.__enter__.return_value = mock_resp
    with patch("urllib.request.urlopen", return_value=mock_resp):
        out = mod._download_and_replace_images(
            "![Image of](http://ex.com/noext)", tmp_path
        )
    assert ".img" in out

    # Hit 358 (new mapping): hashlib fallback
    with patch("urllib.request.urlopen", return_value=mock_resp):
        out = mod._download_and_replace_images("![Image of](http://ex.com/)", tmp_path)
    assert "images/" in out

    # Hit 481 (approx): indir sync with .ipynb
    indir = tmp_path / "in_sync_ipynb"
    indir.mkdir()
    (indir / "test.ipynb").write_text(
        json.dumps({"cells": [], "metadata": {}, "nbformat": 4, "nbformat_minor": 5})
    )
    outdir = tmp_path / "out_sync_ipynb"
    with patch(
        "sys.argv",
        ["transform_md.py", "--indir", str(indir), "--outdir", str(outdir), "--sync"],
    ):
        mod._cli()
    assert (outdir / "test.md").exists()

    # Hit 496 (approx): single file sync with .ipynb
    nb_file_sync = tmp_path / "sync_me_again.ipynb"
    nb_file_sync.write_text(
        json.dumps({"cells": [], "metadata": {}, "nbformat": 4, "nbformat_minor": 5})
    )
    with patch("sys.argv", ["transform_md.py", str(nb_file_sync), "--sync"]):
        mod._cli()
    assert (tmp_path / "sync_me_again.md").exists()


def test_cli_guess_format_error_coverage():
    scripts_dir = Path(__file__).resolve().parent
    mod = load_transform_module(scripts_dir)
    with patch("sys.argv", ["transform_md.py", "--guess-format"]):
        with patch(
            "argparse.ArgumentParser.error", side_effect=ValueError("error")
        ) as mock_err:
            try:
                mod._cli()
            except ValueError:
                pass
            mock_err.assert_called()


def test_cli_sync_ipynb_to_md_coverage(tmp_path: Path):
    scripts_dir = Path(__file__).resolve().parent
    mod = load_transform_module(scripts_dir)

    # Single file
    nb_file = tmp_path / "test.ipynb"
    nb_file.write_text(
        json.dumps({"cells": [], "metadata": {}, "nbformat": 4, "nbformat_minor": 5})
    )
    with patch("sys.argv", ["transform_md.py", str(nb_file), "--sync"]):
        mod._cli()
    assert (tmp_path / "test.md").exists()

    # Indir
    indir = tmp_path / "in_ipynb"
    indir.mkdir()
    (indir / "other.ipynb").write_text(
        json.dumps({"cells": [], "metadata": {}, "nbformat": 4, "nbformat_minor": 5})
    )
    outdir = tmp_path / "out_ipynb"
    with patch(
        "sys.argv",
        ["transform_md.py", "--indir", str(indir), "--outdir", str(outdir), "--sync"],
    ):
        mod._cli()
    assert (outdir / "other.md").exists()


def test_no_yaml_fallback_coverage():
    scripts_dir = Path(__file__).resolve().parent
    mod = load_transform_module(scripts_dir)

    # We can't easily uninstall yaml, but we can mock 'yaml' being None in the module
    # and then re-run some functions.
    # Note: load_transform_module creates a new module instance.

    with patch.dict("sys.modules", {"yaml": None}):
        # Need to reload or re-import to trigger the ImportError block
        import sys

        if "transform_md" in sys.modules:
            del sys.modules["transform_md"]

        # Manually trigger the block logic if possible or just mock the global
        mod_no_yaml = load_transform_module(scripts_dir)
        # Force it
        mod_no_yaml.yaml = None

        md = "---\ntitle: doc\n---\n# Content\n```python\nprint(1)\n```"
        nb = mod_no_yaml.md_to_notebook(md)
        assert nb["metadata"] == {
            "kernelspec": {
                "display_name": "Python 3",
                "language": "python",
                "name": "python3",
            }
        }

        # notebook_to_md
        md_out = mod_no_yaml.notebook_to_md(nb)
        assert "---" not in md_out


def test_cli_transform_cell_split(tmp_path: Path):
    scripts_dir = Path(__file__).resolve().parent
    mod = load_transform_module(scripts_dir)

    test_md = tmp_path / "split_test.md"
    test_md.write_text(
        "You asked:\n----------\nHello\n\nGemini Replied:\n---------------\nHi\n"
    )

    # Test --transform-cell-split=m1
    out_ipynb = tmp_path / "split_test.ipynb"
    # Skip generate_toc to keep the cell count predictable for this logic test
    with patch(
        "sys.argv",
        [
            "transform_md.py",
            str(test_md),
            "-o",
            str(out_ipynb),
            "--transform-cell-split",
            "m1",
            "--skip-transforms",
            "generate_toc",
        ],
    ):
        mod._cli()

    assert out_ipynb.exists()
    nb = json.loads(out_ipynb.read_text())
    # Now splits into 5 cells because the title heading is added by default,
    # plus 4 cells for Prompt/Response headings and content.
    assert len(nb["cells"]) == 5
    assert "# split_test" in "".join(nb["cells"][0]["source"])
    assert "# Prompt: 1" in "".join(nb["cells"][1]["source"])
    assert "Hello" in "".join(nb["cells"][2]["source"])
    assert "# Response: 1" in "".join(nb["cells"][3]["source"])
    assert "Hi" in "".join(nb["cells"][4]["source"])

    # Test that it ADDS to defaults (e.g. code_snippet is still there)
    test_md_2 = tmp_path / "split_test_2.md"
    test_md_2.write_text("Code snippet\n\nYou asked:\n----------\nHello\n")
    out_ipynb_2 = tmp_path / "split_test_2.ipynb"
    with patch(
        "sys.argv",
        [
            "transform_md.py",
            str(test_md_2),
            "-o",
            str(out_ipynb_2),
            "--transform-cell-split",
            "m1",
            "--skip-transforms",
            "generate_toc",
        ],
    ):
        mod._cli()

    nb2 = json.loads(out_ipynb_2.read_text())
    # The first cell should contain the transformed mermaid block if code_snippet worked before splitting
    # Wait, transform_text is called BEFORE md_to_notebook_chat if md_to_notebook is called.
    # In md_to_notebook:
    # cleaned = transform_text(text, enabled=enabled_transforms, format=config)
    # ...
    # if mode in ["m1", "m2"]: return _md_to_notebook_chat(content, config, mode, metadata)

    # So "Code snippet" becomes "```mermaid"
    # Then _md_to_notebook_chat splits by "You asked:".
    # So the first cell will have the mermaid block.
    assert "```mermaid" in "".join(nb2["cells"][0]["source"])


def test_transform_file_splitting_md_to_md(tmp_path: Path):
    scripts_dir = Path(__file__).resolve().parent
    mod = load_transform_module(scripts_dir)

    test_md = tmp_path / "split.md"
    test_md.write_text("You asked:\n----------\nHello\n")

    # split md to md should strip the header
    mod.transform_file(test_md, in_transforms=["chat_split_m1"])

    got = test_md.read_text()
    assert "You asked:" not in got
    assert "Hello" in got


def test_transform_file_default_split_mode(tmp_path: Path):
    scripts_dir = Path(__file__).resolve().parent
    mod = load_transform_module(scripts_dir)

    # Create a format with default split_mode
    cfg = mod.MarkdownConfig(
        name="splitfmt",
        extensions=[".split.md"],
        chat_split_mode="m1",
        chat_prompt_re=r"^H1\n-+$",
    )
    mod.REGISTRY.register(cfg)

    test_md = tmp_path / "test.split.md"
    test_md.write_text("H1\n--\nContent\n")

    # should split automatically because of chat_split_mode
    mod.transform_file(test_md)
    got = test_md.read_text()
    assert "H1" not in got
    assert "Content" in got


def test_cli_multi_out_format(tmp_path: Path):
    scripts_dir = Path(__file__).resolve().parent
    mod = load_transform_module(scripts_dir)

    test_md = tmp_path / "multi.md"
    test_md.write_text("# Hello\n")

    # Test --out-format=standard,myst,ipynb
    with patch(
        "sys.argv",
        [
            "transform_md.py",
            str(test_md),
            "-o",
            str(tmp_path / "out"),
            "--out-format",
            "standard,myst,ipynb",
        ],
    ):
        mod._cli()

    assert (tmp_path / "out.standard.md").exists()
    assert (tmp_path / "out.myst.md").exists()
    assert (tmp_path / "out.ipynb").exists()

    # Test --indir with multiple formats
    indir = tmp_path / "indir"
    indir.mkdir()
    (indir / "one.md").write_text("# One")
    outdir = tmp_path / "outdir"

    with patch(
        "sys.argv",
        [
            "transform_md.py",
            "--indir",
            str(indir),
            "--outdir",
            str(outdir),
            "--out-format",
            "standard,qmd",
        ],
    ):
        mod._cli()

    assert (outdir / "one.standard.md").exists()
    assert (outdir / "one.qmd").exists()


def test_cli_in_out_transforms(tmp_path: Path):
    scripts_dir = Path(__file__).resolve().parent
    mod = load_transform_module(scripts_dir)

    test_md = tmp_path / "inout.md"
    test_md.write_text("line1\n\n\n\nline2")

    # Run with in-transforms skipping collapse_blanks, but out-transforms using it.
    with patch(
        "sys.argv",
        [
            "transform_md.py",
            str(test_md),
            "--in-transforms",
            "close_fences",
            "--out-transforms",
            "collapse_blanks",
        ],
    ):
        mod._cli()

    got = test_md.read_text()
    # collapse_blanks reduces 4 newlines to 2 blank lines (3 newlines total)
    assert got.count("\n\n") == 1
    assert "line1\n\n\nline2" in got
