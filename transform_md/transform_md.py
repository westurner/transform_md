"""Extensible Markdown and Jupyter Notebook Transformation Framework.

This module provides tools for normalizing AI-generated chat exports, syncing markdown
with Jupyter notebooks (.ipynb), and supporting multiple markdown dialects (MyST, Quarto).
It features a pluggable registry (REGISTRY) for custom format extensions and
configurable text transforms (such as 'code_snippet' and 'chat_split').
"""

from __future__ import annotations

import argparse
import json
import re
import hashlib
import mimetypes
import urllib.request
import urllib.parse
import logging
import sys
from enum import Enum
from pathlib import Path
from typing import Iterable

try:
    import yaml
except ImportError:
    yaml = None

logger = logging.getLogger("transform_md")


class ColorFormatter(logging.Formatter):
    """Formatter that adds ANSI red color to error and critical messages."""

    RED = "\033[31m"
    RESET = "\033[0m"

    def format(self, record):
        message = super().format(record)
        if record.levelno >= logging.ERROR:
            return f"{self.RED}{message}{self.RESET}"
        return message


def setup_logging(
    log_file: Path | str | None = "transform.log", verbose: bool = False
) -> None:
    """Configure logging to stdout (with color) and a file."""
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)

    # Clear existing handlers to avoid duplicates or stale streams in tests
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)

    # Stdout handler
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setFormatter(ColorFormatter("%(levelname)s: %(message)s"))
    logger.addHandler(stdout_handler)

    # File handler
    if log_file:
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(
            logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        )
        logger.addHandler(file_handler)


class MarkdownConfig:
    """Configuration for a specific markdown format."""

    def __init__(
        self,
        name: str,
        extensions: list[str] | None = None,
        default_transforms: list[str] | None = None,
        cell_fence_template: str = "```{lang}",
        cell_metadata_style: str = "yaml",
        chat_prompt_re: str | None = None,
        chat_response_re: str | None = None,
        chat_split_mode: str | None = None,
    ):
        self.name = name
        self.extensions = extensions or []
        self.default_transforms = default_transforms or [
            "close_fences",
            "collapse_blanks",
        ]
        self.cell_fence_template = cell_fence_template
        self.cell_metadata_style = cell_metadata_style
        self.chat_prompt_re = chat_prompt_re
        self.chat_response_re = chat_response_re
        self.chat_split_mode = chat_split_mode

    def is_transform_enabled(
        self, transform: str, explicitly_enabled: Iterable[str] | None = None
    ) -> bool:
        """Check if a transform is enabled for this format."""
        if explicitly_enabled is not None:
            return transform in explicitly_enabled
        return transform in self.default_transforms


class MarkdownFormat(Enum):
    """Legacy enum for markdown formats. Use REGISTRY for expansion."""

    CHATEXPORT_ABC1 = "chatexport_abc1"
    MYST = "myst"
    QMD = "qmd"
    STANDARD = "standard"


class MarkdownRegistry:
    """Registry for markdown formats."""

    def __init__(self):
        self._formats: dict[str, MarkdownConfig] = {}
        self._ext_map: dict[str, str] = {}

    def register(self, config: MarkdownConfig) -> None:
        """Register a new markdown format."""
        self._formats[config.name] = config
        for ext in config.extensions:
            self._ext_map[ext] = config.name

    def get(self, val: str | MarkdownFormat | MarkdownConfig | None) -> MarkdownConfig:
        """Get a format by name, enum, or config, defaulting to 'standard'."""
        if val is None:
            return self._formats.get("standard", MarkdownConfig(name="standard"))
        if isinstance(val, MarkdownConfig):
            return val

        # Try to handle MarkdownConfig if it's from a different module instance
        if hasattr(val, "name") and hasattr(val, "cell_fence_template"):
            return val  # type: ignore

        name = val.value if isinstance(val, MarkdownFormat) else val
        if name and name in self._formats:
            return self._formats[name]
        return self._formats.get("standard", MarkdownConfig(name="standard"))

    def infer(self, path: Path) -> MarkdownConfig:
        """Infer the format from a file path based on registered extensions."""
        # Sort by length descending to match '.myst.md' before '.md'
        sorted_exts = sorted(self._ext_map.keys(), key=len, reverse=True)
        filename = path.name.lower()
        for ext in sorted_exts:
            if filename.endswith(ext.lower()):
                return self.get(self._ext_map[ext])
        return self.get("standard")

    @property
    def format_names(self) -> list[str]:
        """List all registered format names."""
        return list(self._formats.keys())


# Global registry instance
REGISTRY = MarkdownRegistry()

# Register default formats
REGISTRY.register(
    MarkdownConfig(
        name="chatexport_abc1",
        extensions=[".md"],
        default_transforms=[
            "add_title",
            "chat_headings",
            "code_snippet",
            "close_fences",
            "collapse_blanks",
            "generate_toc",
            "chat_input_metadata",
            "chat_hide_thoughts",
            "chat_cleanup",
        ],
        chat_prompt_re=(
            r"(?im)^[ \t]*(?:#\s*)?You asked:?"
            r"[ \t]*(?:\n[ \t]*[-=]{3,}[ \t]*)?$"
        ),
        chat_response_re=(
            r"(?im)^(?:---[ \t]*\n)?[ \t]*(?:#\s*)?"
            r"(?:Gemini Replied|Gemini Response):?"
            r"[ \t]*(?:\n[ \t]*[-=]{3,}[ \t]*)?$"
        ),
    )
)
REGISTRY.register(
    MarkdownConfig(
        name="myst",
        extensions=[".myst.md"],
        default_transforms=["add_title"],
        cell_fence_template="```{{code-cell}} {lang}",
    )
)
REGISTRY.register(
    MarkdownConfig(
        name="qmd",
        extensions=[".qmd"],
        default_transforms=["add_title"],
        cell_fence_template="```{{{lang}}}",
        cell_metadata_style="quarto",
    )
)
REGISTRY.register(
    MarkdownConfig(
        name="copilot",
        extensions=[".copilot.json"],
        default_transforms=[
            "add_title",
            "chat_cleanup",
            "chat_headings",
            "code_snippet",
            "close_fences",
            "collapse_blanks",
            "generate_toc",
            "chat_input_metadata",
            "chat_hide_thoughts",
        ],
    )
)
REGISTRY.register(
    MarkdownConfig(name="standard", default_transforms=["add_title"], extensions=[])
)


DEFAULT_TRANSFORMS = [
    "add_title",
    "chat_input_metadata",
    "chat_headings",
    "generate_toc",
    "code_snippet",
    "close_fences",
    "collapse_blanks",
    "chat_hide_thoughts",
    "chat_cleanup",
]


def _slugify(text: str) -> str:
    """Generate a GitHub-style anchor slug from heading text."""
    text = text.lower().strip()
    # Remove everything except alphanumeric, spaces, hyphens, underscores
    text = re.sub(r"[^\w\s-]", "", text)
    # Replace spaces and multiple hyphens with single hyphen
    text = re.sub(r"[-\s]+", "-", text)
    return text


def transform_text(
    text: str,
    enabled: Iterable[str] | None = None,
    format: str | MarkdownFormat | MarkdownConfig = "chatexport_abc1",
    doc_title: str | None = None,
) -> str:
    """Transform the input markdown text.

    If format is CHATEXPORT_ABC1 (Gemini):
    - Lines matching `Code snippet` optionally with `(lang)` become code-fence openers
      like ```lang (defaults to `mermaid`). Case-insensitive and allows an optional
      trailing colon.
    - Auto-closes a mermaid block started from `Code snippet` when a blank line
      follows content, inserting a blank line before and after the closing fence.
      Trailing newline is simplified.
    - Auto-closes any unclosed triple-backtick fence at EOF.
    - Collapse runs of more than two consecutive blank lines into two.
    """
    config = REGISTRY.get(format)

    code_snip_re = re.compile(
        r"^\s*Code snippet(?:\s*\((?P<lang>[^)]+)\))?\s*:?$", re.I
    )
    cleanup_re = re.compile(r"^\s*(Show thinking|Export to sheets)\s*$", re.I)

    prompt_re = (
        re.compile(config.chat_prompt_re, re.M) if config.chat_prompt_re else None
    )
    response_re = (
        re.compile(config.chat_response_re, re.M) if config.chat_response_re else None
    )

    # Track prompt numbers for chat_headings
    prompt_n = 0
    response_n = 0

    out_lines: list[str] = []

    mermaid_open = False
    mermaid_has_content = False
    generic_fence_open = False

    blank_run = 0
    skip_lines = 0

    lines = text.splitlines()

    # Prepend title if requested and not already present as first heading
    # We'll do this later to handle frontmatter correctly
    added_title = False

    for i, line in enumerate(lines):
        if skip_lines > 0:
            skip_lines -= 1
            continue

        if config.is_transform_enabled("chat_headings", explicitly_enabled=enabled):
            remaining = "\n".join(lines[i:])
            if prompt_re and (m := prompt_re.match(remaining)):
                prompt_n += 1
                match_text = m.group(0)
                out_lines.append(f"# Prompt: {prompt_n}")
                out_lines.append("")
                skip_lines = match_text.count("\n")
                continue
            elif response_re and (m := response_re.match(remaining)):
                response_n += 1
                match_text = m.group(0)
                out_lines.append(f"# Response: {response_n}")
                out_lines.append("")
                skip_lines = match_text.count("\n")
                continue

        if config.is_transform_enabled("chat_cleanup", explicitly_enabled=enabled):
            # If hiding thoughts is enabled, we keep "Show thinking" for the splitting phase
            is_thinking = line.strip().lower() == "show thinking"
            if cleanup_re.fullmatch(line) and not (
                is_thinking
                and config.is_transform_enabled(
                    "chat_hide_thoughts", explicitly_enabled=enabled
                )
            ):
                continue

        m = code_snip_re.fullmatch(line.strip())
        if m and config.is_transform_enabled(
            "code_snippet", explicitly_enabled=enabled
        ):
            lang = (m.group("lang") or "mermaid").strip()
            out_lines.append(f"```{lang}")
            if lang.lower() == "mermaid":
                mermaid_open = True
                mermaid_has_content = False
            else:
                generic_fence_open = True
            blank_run = 0
            continue

        # Toggle generic fence state on explicit ``` lines
        if line.strip().startswith("```"):
            out_lines.append(line)
            if config.is_transform_enabled("close_fences", explicitly_enabled=enabled):
                generic_fence_open = not generic_fence_open
                if mermaid_open:
                    mermaid_open = False
                    mermaid_has_content = False
            blank_run = 0
            continue

        if mermaid_open:
            if (
                config.is_transform_enabled("close_fences", explicitly_enabled=enabled)
                and line.strip() == ""
                and mermaid_has_content
            ):
                out_lines.append("")
                out_lines.append("```")
                out_lines.append("")
                mermaid_open = False
                mermaid_has_content = False
                blank_run = 1
                continue
            if line.strip() != "":
                mermaid_has_content = True
            out_lines.append(line)
            blank_run = 0 if line.strip() != "" else blank_run + 1
            continue

        # Normal line handling: collapse excessive blank runs
        if line.strip() == "":
            blank_run += 1
            if (
                not config.is_transform_enabled(
                    "collapse_blanks", explicitly_enabled=enabled
                )
                or blank_run <= 2
            ):
                out_lines.append("")
            continue

        blank_run = 0
        out_lines.append(line)

    # close any open fences at EOF (if enabled)
    if config.is_transform_enabled("close_fences", explicitly_enabled=enabled):
        if mermaid_open and mermaid_has_content:
            out_lines.append("")
            out_lines.append("```")
            mermaid_open = False

        if generic_fence_open:
            out_lines.append("```")
            generic_fence_open = False

    # Post-processing: Add title and TOC
    insert_pos = 0
    if out_lines and out_lines[0].startswith("---"):
        try:
            # simplistic toggle check for second ---
            for idx in range(1, len(out_lines)):
                if out_lines[idx].startswith("---"):
                    insert_pos = idx + 1
                    break
        except Exception:
            pass

    # 1. Add Title
    if doc_title and config.is_transform_enabled(
        "add_title", explicitly_enabled=enabled
    ):
        title_heading = f"# {doc_title}"
        # Check if already present at the top (after frontmatter)
        already_has_title = False
        for idx in range(insert_pos, min(insert_pos + 3, len(out_lines))):
            if out_lines[idx].strip() == title_heading:
                already_has_title = True
                break

        if not already_has_title:
            title_lines = [title_heading, ""]
            out_lines = out_lines[:insert_pos] + title_lines + out_lines[insert_pos:]
            insert_pos += 2

    # 2. Add TOC
    if config.is_transform_enabled("generate_toc", explicitly_enabled=enabled):
        # Skip if already exists
        if not any(re.match(r"^##\s+Contents\s*$", l, re.I) for l in out_lines):
            toc_entries = []
            i = 0
            while i < len(out_lines):
                line = out_lines[i]

                # Skip if it matches a chat delimiter
                line_stripped = line.strip()
                if line_stripped.lower().startswith(("you asked", "gemini replied")):
                    remaining = "\n".join(out_lines[i:])
                    m_p = prompt_re.match(remaining) if prompt_re else None
                    m_r = response_re.match(remaining) if response_re else None
                    m = m_p or m_r
                    if m:
                        i += m.group(0).count("\n") + 1
                        continue

                # ATX: # Heading
                m_atx = re.match(r"^(#+)\s+(.+)$", line_stripped)
                if m_atx:
                    level = len(m_atx.group(1))
                    title = m_atx.group(2).strip()
                    if title.lower() != "contents":
                        toc_entries.append((level, title))
                # Setext: Line\n=== or Line\n---
                elif i + 1 < len(out_lines):
                    next_line = out_lines[i + 1].strip()
                    if (
                        line_stripped
                        and next_line
                        and len(next_line) >= 3
                        and all(c == next_line[0] for c in next_line)
                        and next_line[0] in "=-"
                    ):
                        title = line_stripped
                        level = 1 if next_line[0] == "=" else 2
                        if title.lower() != "contents":
                            toc_entries.append((level, title))
                i += 1

            if toc_entries:
                min_lvl = min(lvl for lvl, _ in toc_entries)
                toc_lines = ["## Contents", ""]
                for level, title in toc_entries:
                    slug = _slugify(title)
                    indent = "  " * (level - min_lvl)
                    toc_lines.append(f"{indent}* [{title}](#{slug})")
                toc_lines.append("")

                final_toc = []
                if insert_pos > 0 and out_lines[insert_pos - 1].strip():
                    final_toc.append("")
                final_toc.extend(toc_lines)

                out_lines = out_lines[:insert_pos] + final_toc + out_lines[insert_pos:]

    if text.endswith("\n"):
        return "\n".join(out_lines) + "\n"
    return "\n".join(out_lines)

    if text.endswith("\n"):
        return "\n".join(out_lines) + "\n"
    return "\n".join(out_lines)


def _get_chat_segments(
    text: str, prompt_re_str: str | None, response_re_str: str | None
) -> list[dict]:
    """Split text into a list of {'type': 'prompt'|'response'|'other', 'content': str}."""
    BOUNDARIES = []
    if prompt_re_str:
        for m in re.finditer(prompt_re_str, text, re.M):
            BOUNDARIES.append(("prompt", m.start(), m.end()))
    if response_re_str:
        for m in re.finditer(response_re_str, text, re.M):
            BOUNDARIES.append(("response", m.start(), m.end()))

    BOUNDARIES.sort(key=lambda x: x[1])

    segments = []
    last_pos = 0
    current_type = "other"

    for btype, start, end in BOUNDARIES:
        # segment before this header
        content = text[last_pos:start].strip("\r\n")
        if content or segments:
            segments.append({"type": current_type, "content": content})
        last_pos = end  # Start next segment AFTER the header (delimiter)
        current_type = btype

    # last segment
    content = text[last_pos:].strip("\r\n")
    if content or (not segments and last_pos > 0):
        segments.append({"type": current_type, "content": content})

    return segments


def _md_to_notebook_chat(
    text: str,
    config: MarkdownConfig,
    mode: str,
    metadata: dict,
    enabled: Iterable[str] | None = None,
) -> dict:
    """Specialized notebook converter for chat turn splitting (m1, m2)."""
    segments = _get_chat_segments(text, config.chat_prompt_re, config.chat_response_re)

    # Always split by structural headings if we are in a chat-splitting mode.
    # We do this even if 'chat_headings' isn't explicitly enabled because the headings
    # might have been added by a previous transformation or be present in the source.
    h_segments = []
    for seg in segments:
        section_type = seg["type"]
        # Split content by chat headings, keeping the headings in the result
        # Note: We use capturing group to keep the delimiter
        parts = re.split(
            r"(^# (?:Prompt|Response): \d+\s*$)", seg["content"], flags=re.MULTILINE
        )
        for p in parts:
            if not p.strip("\r\n"):
                continue
            is_h = re.match(r"^# (?:Prompt|Response): \d+\s*$", p.strip())
            if is_h:
                section_type = (
                    "prompt"
                    if p.strip().lower().startswith("# prompt:")
                    else "response"
                )
            h_segments.append(
                {
                    "type": "heading" if is_h else section_type,
                    "content": p.strip("\r\n"),
                }
            )
    segments = h_segments

    # If chat_hide_thoughts is enabled, split out thoughts from response segments
    if config.is_transform_enabled("chat_hide_thoughts", explicitly_enabled=enabled):
        t_segments = []
        # Keywords based on Lignolux and standard Gemini thought patterns
        thought_keywords = r"\b(Thinking|Thought|I'm|I am|I’ve|I’m|I've|I have|I'll|I will|I shall|I aim|My focus|My research|My analysis|I'm now|I'm currently|Beginning query|Summarizing|Verifying|Considering|Examining|Initiating|Analyzing|Refining|Adjusting|Defining)\b"

        for seg in segments:
            if seg["type"] == "response":
                content = seg["content"]
                sub_parts = re.split(
                    r"(^Show thinking\s*$)", content, flags=re.MULTILINE | re.I
                )
                for part in sub_parts:
                    if re.match(r"^Show thinking\s*$", part, re.I):
                        continue
                    else:
                        blocks = re.split(r"\n\n+", part)
                        thought_blocks = []
                        response_blocks = []
                        in_thoughts = True
                        for b in blocks:
                            if not b.strip("\r\n"):
                                continue
                            is_b_thought = False
                            b_check = b.strip()
                            if b_check.startswith("**") and re.search(
                                thought_keywords, b_check, re.I
                            ):
                                is_b_thought = True
                            elif re.match(
                                r"^(?:I'm|I am|I’m)\s+(?:currently|now|focused|exploring|investigating)\b",
                                b_check,
                                re.I,
                            ):
                                is_b_thought = True
                            elif b_check.lower() in {"thinking", "thought", "thinking..."}:
                                is_b_thought = True

                            if is_b_thought and in_thoughts:
                                thought_blocks.append(b.strip("\r\n"))
                            else:
                                in_thoughts = False
                                response_blocks.append(b.strip("\r\n"))

                        if thought_blocks:
                            t_segments.append(
                                {
                                    "type": "thought",
                                    "content": "\n\n".join(thought_blocks),
                                }
                            )
                        if response_blocks:
                            t_segments.append(
                                {
                                    "type": "response",
                                    "content": "\n\n".join(response_blocks),
                                }
                            )
            else:
                t_segments.append(seg)
        segments = t_segments

    cells = []

    if mode == "m1":
        for seg in segments:
            if not seg["content"]:
                continue

            cell_meta = {}
            is_prompt = seg["type"] == "prompt" or (
                seg["type"] == "heading" and "# Prompt:" in seg["content"]
            )
            if is_prompt and config.is_transform_enabled(
                "chat_input_metadata", explicitly_enabled=enabled
            ):
                cell_meta["chat_input"] = True

            if seg["type"] == "thought":
                cell_meta.update(
                    {"collapsed": True, "jupyter": {"source_hidden": True}}
                )

            cells.append(
                {
                    "cell_type": "markdown",
                    "metadata": cell_meta,
                    "source": [line + "\n" for line in seg["content"].splitlines()],
                }
            )
    elif mode == "m2":
        i = 0
        while i < len(segments):
            seg = segments[i]
            if seg["type"] == "prompt":
                prompt_content = seg["content"]
                response_content = ""
                # group any following 'response' segments (and skip 'thought' which are handled separately)
                if i + 1 < len(segments) and segments[i + 1]["type"] == "response":
                    response_content = segments[i + 1]["content"]
                    i += 1

                # escape triple quotes for the python string
                escaped_prompt = prompt_content.replace('"""', '\\"\\"\\"')

                cell_meta = {}
                if config.is_transform_enabled(
                    "chat_input_metadata", explicitly_enabled=enabled
                ):
                    cell_meta["chat_input"] = True

                cells.append(
                    {
                        "cell_type": "code",
                        "execution_count": None,
                        "metadata": cell_meta,
                        "outputs": [
                            {
                                "output_type": "display_data",
                                "data": {
                                    "text/markdown": [
                                        line + "\n"
                                        for line in response_content.splitlines()
                                    ]
                                },
                                "metadata": {},
                            }
                        ]
                        if response_content
                        else [],
                        "source": [
                            'promptstr("""\n',
                            *[line + "\n" for line in escaped_prompt.splitlines()],
                            '""")\n',
                        ],
                    }
                )
            else:
                # 'other' or stray 'response' or 'thought' or 'heading'
                if seg["content"]:
                    cell_meta = {}
                    if seg["type"] == "thought":
                        cell_meta.update(
                            {"collapsed": True, "jupyter": {"source_hidden": True}}
                        )
                    cells.append(
                        {
                            "cell_type": "markdown",
                            "metadata": cell_meta,
                            "source": [
                                line + "\n" for line in seg["content"].splitlines()
                            ],
                        }
                    )
            i += 1

    if "kernelspec" not in metadata:
        metadata["kernelspec"] = {
            "display_name": "Python 3",
            "language": "python",
            "name": "python3",
        }

    return {"cells": cells, "metadata": metadata, "nbformat": 4, "nbformat_minor": 5}


def md_to_notebook(
    text: str,
    enabled_transforms: Iterable[str] | None = None,
    format: str | MarkdownFormat | MarkdownConfig = "standard",
    doc_title: str | None = None,
) -> dict:
    """Convert markdown text to an .ipynb-compatible dictionary.

    Runs transform_text first.
    Supports YAML front-matter and MyST/Quarto-style code cells.
    Also supports chat splitting modes (m1, m2) if configured or enabled via transforms.
    """
    config = REGISTRY.get(format)

    cleaned = transform_text(
        text, enabled=enabled_transforms, format=config, doc_title=doc_title
    )

    metadata = {}
    content = cleaned

    # Extract front-matter
    fm_match = re.match(r"^---\s*\n(.*?)\n---\s*\n", content, re.DOTALL)
    if fm_match:
        if yaml:
            try:
                metadata = yaml.safe_load(fm_match.group(1)) or {}
            except Exception:
                pass
        content = content[fm_match.end() :]

    mode = config.chat_split_mode
    if enabled_transforms:
        if "chat_split_m1" in enabled_transforms:
            mode = "m1"
        elif "chat_split_m2" in enabled_transforms:
            mode = "m2"

    if mode in ["m1", "m2"]:
        return _md_to_notebook_chat(
            content, config, mode, metadata, enabled=enabled_transforms
        )

    if "kernelspec" not in metadata:
        metadata["kernelspec"] = {
            "display_name": "Python 3",
            "language": "python",
            "name": "python3",
        }

    cells = []

    myst_cell_break_re = re.compile(
        r"^\+\++(?:[ \t]+(?P<metadata>\{.*\}))?[ \t]*$",
        re.MULTILINE,
    )

    def append_markdown_cells(markdown_text: str) -> None:
        """Append MyST markdown cells, including Jupytext metadata breaks."""
        if config.name != "myst":
            markdown_parts = [(markdown_text, {})]
        else:
            markdown_parts = []
            last_break = 0
            pending_metadata = {}
            for cell_break in myst_cell_break_re.finditer(markdown_text):
                cell_source = markdown_text[last_break : cell_break.start()].strip()
                if cell_source:
                    markdown_parts.append((cell_source, pending_metadata))
                pending_metadata = {}
                if cell_break.group("metadata"):
                    try:
                        parsed_metadata = json.loads(cell_break.group("metadata"))
                        if isinstance(parsed_metadata, dict):
                            pending_metadata = parsed_metadata
                    except json.JSONDecodeError:
                        pass
                last_break = cell_break.end()

            cell_source = markdown_text[last_break:].strip()
            if cell_source:
                markdown_parts.append((cell_source, pending_metadata))

        for cell_source, cell_metadata in markdown_parts:
            if not cell_source:
                continue
            cells.append(
                {
                    "cell_type": "markdown",
                    "metadata": cell_metadata,
                    "source": [line + "\n" for line in cell_source.splitlines()],
                }
            )

    # Match code fences: ```[ { ]lang[ } ]
    # Also handles MyST {code-cell} format and Quarto {lang}
    fence_re = re.compile(
        r"^```(?:\{)?([^\s\}]+)(?:\})?.*?\n(.*?)\n```", re.MULTILINE | re.DOTALL
    )

    last_pos = 0
    for match in fence_re.finditer(content):
        # markdown before
        md_part = content[last_pos : match.start()].strip()
        if md_part:
            append_markdown_cells(md_part)

        lang_input = match.group(1).strip().lower()
        code_content = match.group(2)
        cell_metadata = {}

        is_code = True
        lang = lang_input
        if "code-cell" in lang_input:
            lang = "python"  # default for code-cell
        elif lang_input in ["markdown", "md", "text"]:
            is_code = False

        # Parse internal metadata
        # 1. MyST style: --- YAML ---
        inner_fm = re.match(r"^---\s*\n(.*?)\n---\s*\n", code_content, re.DOTALL)
        if inner_fm:
            if yaml:
                try:
                    cell_metadata.update(yaml.safe_load(inner_fm.group(1)) or {})
                except Exception:
                    pass
            code_content = code_content[inner_fm.end() :]

        # 2. Quarto style: #| key: value
        if is_code:
            q_lines = []
            for line in code_content.splitlines():
                if line.startswith("#|"):
                    if yaml:
                        try:
                            # Parse Quarto directive
                            part = line[2:].strip()
                            if ":" in part:
                                k, v = part.split(":", 1)
                                cell_metadata[k.strip()] = yaml.safe_load(v.strip())
                        except Exception:
                            pass
                else:
                    q_lines.append(line)
            if cell_metadata:  # If we found any #| metadata, update code_content
                code_content = "\n".join(q_lines)

        if is_code:
            cell_metadata["language"] = lang
            cells.append(
                {
                    "cell_type": "code",
                    "execution_count": None,
                    "metadata": cell_metadata,
                    "outputs": [],
                    "source": [line + "\n" for line in code_content.splitlines()],
                }
            )
        else:
            cells.append(
                {
                    "cell_type": "markdown",
                    "metadata": cell_metadata,
                    "source": [line + "\n" for line in code_content.splitlines()],
                }
            )

        last_pos = match.end()

    # tail
    md_tail = content[last_pos:].strip()
    if md_tail:
        append_markdown_cells(md_tail)

    return {"cells": cells, "metadata": metadata, "nbformat": 4, "nbformat_minor": 5}


def notebook_to_md(
    nb: dict, format: str | MarkdownFormat | MarkdownConfig = "standard"
) -> str:
    """Convert an .ipynb dictionary back to markdown."""
    config = REGISTRY.get(format)
    lines = []
    metadata = nb.get("metadata", {})
    if metadata and yaml:
        lines.append("---")
        lines.append(yaml.dump(metadata).strip())
        lines.append("---")
        lines.append("")

    last_cell_was_markdown = False
    for cell in nb.get("cells", []):
        ctype = cell.get("cell_type", "markdown")
        source = cell.get("source", [])
        if isinstance(source, list):
            source_text = "".join(source)
        else:
            source_text = str(source)

        cmeta = cell.get("metadata", {})

        if ctype == "markdown":
            if config.name == "myst" and (cmeta or last_cell_was_markdown):
                # Jupytext uses +++ to preserve markdown cell boundaries and metadata.
                lines.append(
                    f"+++ {json.dumps(cmeta)}" if cmeta else "+++"
                )
            elif cmeta and yaml and config.cell_metadata_style == "yaml":
                lines.append("---")
                lines.append(yaml.dump(cmeta).strip())
                lines.append("---")
            lines.append(source_text.strip())
            lines.append("")
            last_cell_was_markdown = True
        else:
            # code cell
            lang = cmeta.get("language")
            if not lang:
                if "kernelspec" in metadata:
                    lang = metadata["kernelspec"].get("language", "python")
                else:
                    lang = "python"

            lines.append(config.cell_fence_template.format(lang=lang))

            if cmeta and yaml:
                display_meta = {k: v for k, v in cmeta.items() if k != "language"}
                if display_meta:
                    if config.cell_metadata_style == "quarto":
                        # Quarto prefer #|
                        for k, v in display_meta.items():
                            val_str = yaml.dump(v).strip()
                            lines.append(f"#| {k}: {val_str}")
                    else:
                        lines.append("---")
                        lines.append(yaml.dump(display_meta).strip())
                        lines.append("---")
            lines.append(source_text.rstrip())
            lines.append("```")
            lines.append("")
            last_cell_was_markdown = False

    return "\n".join(lines).strip() + "\n"


def _download_and_replace_images(text: str, out_dir: Path) -> str:
    """Find `![Image of ...](http...)` tags, download images to out_dir/images and replace URLs.

    Returns updated text. If download fails for an image the original URL is left in place.
    """
    images_dir = out_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    # match alt text starting with 'Image of' (case-insensitive)
    img_re = re.compile(r"!\[Image of[^\]]*\]\((?P<url>https?://[^)\s]+)\)", re.I)

    def _guess_ext(url: str, headers) -> str:
        # try from URL path
        path = urllib.parse.urlparse(url).path
        base = Path(urllib.parse.unquote(path)).name
        if "." in base:
            ext = Path(base).suffix
            if ext:
                return ext
        # fallback to content-type header
        ctype = headers.get("content-type") if headers else None
        if ctype:
            ext = mimetypes.guess_extension(ctype.split(";")[0].strip())
            if ext:
                return ext
        return ".img"

    seen_names: dict[str, int] = {}

    def _download(m: re.Match) -> str:
        url = m.group("url")
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "transform-md/1.0"}
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = resp.read()
                headers = {k.lower(): v for k, v in resp.getheaders()}
                ext = _guess_ext(url, headers)
        except Exception:
            return m.group(0)  # leave unchanged on failure

        # derive filename
        parsed = urllib.parse.urlparse(url)
        name = Path(urllib.parse.unquote(parsed.path)).stem
        if not name:
            name = hashlib.sha1(url.encode("utf-8")).hexdigest()[:10]
        # ensure unique
        count = seen_names.get(name, 0)
        seen_names[name] = count + 1
        if count:
            name = f"{name}-{count}"
        fname = f"{name}{ext}"
        target = images_dir / fname
        try:
            target.write_bytes(data)
        except Exception:
            return m.group(0)

        rel = Path("images") / fname
        return f"![Image of]({rel.as_posix()})"

    new_text = img_re.sub(lambda mm: _download(mm), text)
    return new_text


def infer_format(path: Path) -> MarkdownConfig:
    """Infer the markdown format from the file extension."""
    return REGISTRY.infer(path)


def transform_file(
    in_path: Path,
    out_path: Path | None = None,
    in_transforms: Iterable[str] | None = None,
    out_transforms: Iterable[str] | None = None,
    download_images: bool = False,
    in_format: str | MarkdownFormat | MarkdownConfig | None = None,
    out_format: str | MarkdownFormat | MarkdownConfig | None = None,
) -> Path:
    """Read `in_path`, transform its contents, and write to `out_path`.

    Supports registered extensions (e.g. .md, .myst.md, .qmd) and .ipynb.

    If `out_path` is not provided the input file is overwritten.
    If input is markdown and output is markdown and different formats are specified,
    it will perform a conversion via a notebook round-trip.

    Returns the path written.
    """
    # Target path determines out_format if not provided
    target_path = out_path or in_path

    # Try to detect Gemini/Copilot JSON formats early to use better default configs
    if in_format is None:
        if in_path.suffix.lower() == ".json" and not in_path.name.lower().endswith(
            ".copilot.json"
        ):
            # Peek to see if it's Gemini
            try:
                data = json.loads(in_path.read_text(encoding="utf-8"))
                if isinstance(data, dict) and "messages" in data:
                    in_format = "chatexport_abc1"
            except:
                pass
        elif in_path.name.lower().endswith(".copilot.json"):
            in_format = "copilot"

    in_config = (
        REGISTRY.get(in_format) if in_format is not None else REGISTRY.infer(in_path)
    )
    out_config = (
        REGISTRY.get(out_format)
        if out_format is not None
        else (REGISTRY.infer(target_path) if out_path else in_config)
    )

    if in_path.suffix.lower() == ".ipynb":
        nb = json.loads(in_path.read_text(encoding="utf-8"))
        text = notebook_to_md(nb, format=in_config)
    elif in_config.name == "copilot" or in_path.name.lower().endswith(".copilot.json"):
        # Handle Copilot export JSON
        try:
            data = json.loads(in_path.read_text(encoding="utf-8"))
            text = ""
            for i, req in enumerate(data.get("requests", [])):
                prompt = req.get("message", {}).get("text", "")
                text += f"# Prompt: {i + 1}\n\n{prompt}\n\n"

                response_text = ""
                for part in req.get("response", []):
                    if part.get("kind") == "markdown":
                        response_text += part.get("value", "") + "\n"
                    elif part.get("kind") == "textEditGroup" and "edits" in part:
                        # Extract text from edits
                        for edit_group in part["edits"]:
                            for edit in edit_group:
                                response_text += edit.get("text", "")
                        response_text += "\n"

                if response_text:
                    text += f"# Response: {i + 1}\n\n{response_text}\n\n"

            if not text:
                text = in_path.read_text(encoding="utf-8")
        except:
            text = in_path.read_text(encoding="utf-8")
    elif in_path.suffix.lower() == ".json":
        # Handle Gemini export JSON
        try:
            data = json.loads(in_path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and "messages" in data:
                text = ""
                for i, msg in enumerate(data["messages"]):
                    raw_author = msg.get("author", "unknown").lower()
                    if raw_author == "ai":
                        author = "Response"
                    elif raw_author == "user":
                        author = "Prompt"
                    else:
                        author = raw_author.capitalize()
                    text += f"# {author}: {i + 1}\n\n"
                    text += msg.get("content", "") + "\n\n"
            else:
                text = in_path.read_text(encoding="utf-8")
        except:
            text = in_path.read_text(encoding="utf-8")
    else:
        text = in_path.read_text(encoding="utf-8")

    if target_path.suffix.lower() == ".ipynb":
        nb = md_to_notebook(
            text,
            enabled_transforms=in_transforms,
            format=in_config,
            doc_title=in_path.stem,
        )
        target_path.write_text(json.dumps(nb, indent=1), encoding="utf-8")
    else:
        # Markdown output
        is_splitting = False
        if in_transforms and (
            "chat_split_m1" in in_transforms or "chat_split_m2" in in_transforms
        ):
            is_splitting = True
        elif in_config.chat_split_mode:
            is_splitting = True

        if in_path.suffix.lower() != ".ipynb" and (
            in_config.name != out_config.name or is_splitting
        ):
            # Dialect conversion or Chat Splitting: md -> nb -> md
            nb = md_to_notebook(
                text,
                enabled_transforms=in_transforms,
                format=in_config,
                doc_title=in_path.stem,
            )
            new_text = notebook_to_md(nb, format=out_config)
        else:
            # Normal transformation
            new_text = transform_text(
                text, enabled=in_transforms, format=in_config, doc_title=in_path.stem
            )

        # Apply output transforms
        new_text = transform_text(new_text, enabled=out_transforms, format=out_config)

        if download_images:
            target_dir = target_path.parent
            new_text = _download_and_replace_images(new_text, target_dir)
        target_path.write_text(new_text, encoding="utf-8")
    return target_path


def _cli() -> None:
    parser = argparse.ArgumentParser(
        description="Transform and sync Markdown and Jupyter Notebooks with support for MyST, Quarto, and Chat splitting.",
        epilog="Use --list-transforms to see available text modifications.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "input", type=Path, nargs="?", help="Input markdown or .ipynb file"
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Output file (default: overwrite input, or sync suffix if --sync)",
    )
    parser.add_argument(
        "--indir", type=Path, help="Batch process a directory (all .md/.ipynb/.qmd)"
    )
    parser.add_argument(
        "--outdir", type=Path, help="Output directory (required with --indir)"
    )
    parser.add_argument(
        "--list-transforms",
        action="store_true",
        help="List available transforms and exit",
    )
    parser.add_argument(
        "--run-transforms",
        type=str,
        help="Comma-separated transforms to run (applied to input stage)",
    )
    parser.add_argument(
        "--in-transforms",
        type=str,
        help="Comma-separated transforms for input (overrides --run-transforms)",
    )
    parser.add_argument(
        "--out-transforms", type=str, help="Comma-separated transforms for output"
    )
    parser.add_argument(
        "--transform-cell-split",
        type=str,
        choices=["m1", "m2"],
        help="Add chat splitting transform (m1 or m2) to input transforms",
    )
    parser.add_argument(
        "--skip-transforms", type=str, help="Comma-separated transforms to skip"
    )
    parser.add_argument(
        "--download-images",
        action="store_true",
        help="Download remote images referenced as 'Image of' and replace with local files",
    )
    parser.add_argument(
        "--sync",
        action="store_true",
        help="Two-way sync: create .ipynb from .md or vice-versa",
    )
    parser.add_argument(
        "--format",
        type=str,
        help="Markdown format for both input and output (e.g. myst, qmd, standard, ipynb)",
    )
    parser.add_argument(
        "--in-format", type=str, help="Markdown format for input (overrides --format)"
    )
    parser.add_argument(
        "--out-format", type=str, help="Markdown format for output (overrides --format)"
    )
    parser.add_argument(
        "--guess-format",
        action="store_true",
        help="Print the detected format for the input file and exit",
    )
    parser.add_argument(
        "--log-file", type=Path, default=Path("transform.log"), help="Path to log file"
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Enable verbose (DEBUG) logging"
    )
    args = parser.parse_args()

    setup_logging(log_file=args.log_file, verbose=args.verbose)

    if args.guess_format:
        if not args.input:
            parser.error("input file is required for --guess-format")
        print(infer_format(args.input).name)
        return

    fmt_in = args.in_format or args.format
    fmt_outs = []
    if args.out_format:
        fmt_outs = [f.strip() for f in args.out_format.split(",") if f.strip()]
    elif args.format:
        fmt_outs = [args.format]

    # Validate formats (allowing 'ipynb' as a special pseudo-format for file-type conversion)
    valid = set(REGISTRY.format_names) | {"ipynb"}
    if fmt_in and fmt_in not in valid:
        parser.error(
            f"invalid in-format: '{fmt_in}' (choose from {', '.join(sorted(REGISTRY.format_names))}, ipynb)"
        )

    for f in fmt_outs:
        if f not in valid:
            parser.error(
                f"invalid out-format: '{f}' (choose from {', '.join(sorted(REGISTRY.format_names))}, ipynb)"
            )

    available = {
        "add_title": "Add the filename as a # {title} heading",
        "code_snippet": "Convert 'Code snippet' lines into fences (default on for chatexport_abc1)",
        "close_fences": "Auto-close fences started by transforms and unclosed triple-backticks (default on)",
        "collapse_blanks": "Collapse long blank runs to two blank lines (default on)",
        "chat_cleanup": "Remove 'Show thinking' and 'Export to sheets' boilerplate (default on)",
        "chat_headings": "Add markdown headings before each chat turn",
        "generate_toc": "Generate a static Table of Contents under a '## Contents' heading",
        "chat_split_m1": "Split chat into markdown cells per turn",
        "chat_split_m2": "Split chat into code cells with promptstr() and markdown outputs",
    }

    if args.list_transforms:
        print("Available transforms:")
        for k, v in available.items():
            print(f"- {k}: {v}")
        return

    if not args.input and not args.indir:
        parser.error("input file or --indir is required")

    # build transform sets
    raw_in = args.in_transforms or args.run_transforms
    if raw_in:
        in_enabled = [t.strip() for t in raw_in.split(",") if t.strip()]
    else:
        in_enabled = list(DEFAULT_TRANSFORMS)
        if args.skip_transforms:
            skip = {t.strip() for t in args.skip_transforms.split(",") if t.strip()}
            in_enabled = [t for t in in_enabled if t not in skip]

    if args.transform_cell_split:
        tsplit = f"chat_split_{args.transform_cell_split}"
        if tsplit not in in_enabled:
            in_enabled.append(tsplit)

    if args.out_transforms:
        out_enabled = [t.strip() for t in args.out_transforms.split(",") if t.strip()]
    else:
        out_enabled = None

    if args.indir:
        if not args.outdir:
            parser.error("--outdir is required when --indir is used")
        in_dir: Path = args.indir
        out_dir: Path = args.outdir
        out_dir.mkdir(parents=True, exist_ok=True)
        written = []
        files = sorted(
            list(in_dir.glob("*.md"))
            + list(in_dir.glob("*.ipynb"))
            + list(in_dir.glob("*.qmd"))
        )
        for p in files:
            for f_out in fmt_outs or [None]:
                target = out_dir / p.name
                if f_out == "ipynb":
                    target = target.with_suffix(".ipynb")
                elif f_out:
                    cfg = REGISTRY.get(f_out)
                    ext = cfg.extensions[0] if cfg.extensions else ".md"
                    if len(fmt_outs) > 1:
                        if not ext.startswith(f".{f_out}"):
                            target = target.with_suffix(f".{f_out}{ext}")
                        else:
                            target = target.with_suffix(ext)
                    else:
                        target = target.with_suffix(ext)
                elif args.sync:
                    if p.suffix.lower() == ".ipynb":
                        target = target.with_suffix(".md")
                    else:
                        target = target.with_suffix(".ipynb")

                actual_f_out = "standard" if f_out == "ipynb" else f_out
                logger.info(
                    "Transforming: %r -> %r", p.name, target.name
                )  # TODO: escape or print tuple
                transform_file(
                    p,
                    target,
                    in_transforms=in_enabled,
                    out_transforms=out_enabled,
                    download_images=args.download_images,
                    in_format=fmt_in,
                    out_format=actual_f_out,
                )
                written.append(str(target))
        # Final summary
        if len(written) > 0:
            logger.info("Successfully wrote %d files.", len(written))
    else:
        inp = args.input
        out_base = args.output
        written = []

        for f_out in fmt_outs or [None]:
            out = out_base
            if f_out == "ipynb":
                if not out:
                    out = inp.with_suffix(".ipynb")
                elif out.suffix.lower() != ".ipynb":
                    # If user provided -o out.md but f_out is ipynb, override or append?
                    # Let's override suffix if it's explicitly requested as ipynb
                    out = out.with_suffix(".ipynb")
            elif f_out:
                cfg = REGISTRY.get(f_out)
                ext = cfg.extensions[0] if cfg.extensions else ".md"
                if not out:
                    if len(fmt_outs) > 1:
                        if not ext.startswith(f".{f_out}"):
                            out = inp.with_suffix(f".{f_out}{ext}")
                        else:
                            out = inp.with_suffix(ext)
                    else:
                        out = inp.with_suffix(ext)
                elif out_base and len(fmt_outs) > 1:
                    # Use stem to avoid double extension if possible
                    if not ext.startswith(f".{f_out}"):
                        out = out_base.parent / f"{out_base.stem}.{f_out}{ext}"
                    else:
                        out = out_base.parent / f"{out_base.stem}{ext}"
            elif args.sync and not out:
                if inp.suffix.lower() == ".ipynb":
                    out = inp.with_suffix(".md")
                else:
                    out = inp.with_suffix(".ipynb")

            actual_f_out = "standard" if f_out == "ipynb" else f_out
            target_name = (out or inp).name
            logger.info("Transforming: %s -> %s", inp.name, target_name)
            output = transform_file(
                inp,
                out,
                in_transforms=in_enabled,
                out_transforms=out_enabled,
                download_images=args.download_images,
                in_format=fmt_in,
                out_format=actual_f_out,
            )
            written.append(str(output))

        if len(written) > 1:
            logger.info("Successfully wrote %d files.", len(written))
        elif written:
            # We already logged Transforming... above
            pass


if __name__ == "__main__":
    _cli()  # pragma: no cover
