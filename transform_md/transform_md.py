"""Transform exported Gemini chat markdown into improved markdown.

This module provides a simple `transform_text` function which currently
replaces lines that equal "Code snippet" with a mermaid code-fence
starter (```mermaid). It also exposes a small CLI to transform files.
"""
from __future__ import annotations

import argparse
import re
import hashlib
import mimetypes
import urllib.request
import urllib.parse
from pathlib import Path
from typing import Iterable


DEFAULT_TRANSFORMS = [
    "code_snippet",
    "close_fences",
    "collapse_blanks",
]


def transform_text(text: str, enabled: Iterable[str] | None = None) -> str:
    """Transform the input markdown text.

    New transforms:
    - Lines matching `Code snippet` optionally with `(lang)` become code-fence openers
      like ```lang (defaults to `mermaid`). Case-insensitive and allows an optional
      trailing colon.
    - Auto-closes a mermaid block started from `Code snippet` when a blank line
      follows content, inserting a blank line before and after the closing fence.
    - Auto-closes any unclosed triple-backtick fence at EOF.
    - Collapse runs of more than two consecutive blank lines into two.
    """
    code_snip_re = re.compile(r"^\s*Code snippet(?:\s*\((?P<lang>[^)]+)\))?\s*:?$", re.I)

    enabled_set = set(enabled) if enabled is not None else set(DEFAULT_TRANSFORMS)

    out_lines: list[str] = []

    mermaid_open = False
    mermaid_has_content = False
    generic_fence_open = False

    blank_run = 0

    lines = text.splitlines()
    for line in lines:
        m = code_snip_re.fullmatch(line.strip())
        if m and 'code_snippet' in enabled_set:
            lang = (m.group('lang') or 'mermaid').strip()
            out_lines.append(f"```{lang}")
            if lang.lower() == 'mermaid':
                mermaid_open = True
                mermaid_has_content = False
            else:
                generic_fence_open = True
            blank_run = 0
            continue

        # Toggle generic fence state on explicit ``` lines
        if line.strip().startswith('```'):
            out_lines.append(line)
            if 'close_fences' in enabled_set:
                generic_fence_open = not generic_fence_open
                if mermaid_open:
                    mermaid_open = False
                    mermaid_has_content = False
            blank_run = 0
            continue

        if mermaid_open:
            if 'close_fences' in enabled_set and line.strip() == '' and mermaid_has_content:
                out_lines.append('')
                out_lines.append('```')
                out_lines.append('')
                mermaid_open = False
                mermaid_has_content = False
                blank_run = 1
                continue
            if line.strip() != '':
                mermaid_has_content = True
            out_lines.append(line)
            blank_run = 0 if line.strip() != '' else blank_run + 1
            continue

        # Normal line handling: collapse excessive blank runs
        if line.strip() == '':
            blank_run += 1
            if 'collapse_blanks' not in enabled_set or blank_run <= 2:
                out_lines.append('')
            continue

        blank_run = 0
        out_lines.append(line)

    # close any open fences at EOF (if enabled)
    if 'close_fences' in enabled_set:
        if mermaid_open and mermaid_has_content:
            out_lines.append('')
            out_lines.append('```')
            mermaid_open = False

        if generic_fence_open:
            out_lines.append('```')
            generic_fence_open = False

    if text.endswith('\n'):
        return '\n'.join(out_lines) + '\n'
    return '\n'.join(out_lines)
    
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
            req = urllib.request.Request(url, headers={"User-Agent": "transform-md/1.0"})
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


def transform_file(in_path: Path, out_path: Path | None = None, enabled: Iterable[str] | None = None, download_images: bool = False) -> Path:
    """Read `in_path`, transform its contents, and write to `out_path`.

    If `out_path` is not provided the input file is overwritten.
    Returns the path written.
    """
    text = in_path.read_text(encoding="utf-8")
    new_text = transform_text(text, enabled=enabled)
    if download_images:
        target_dir = (out_path or in_path).parent
        new_text = _download_and_replace_images(new_text, target_dir)
    if out_path is None:
        out_path = in_path
    out_path.write_text(new_text, encoding="utf-8")
    return out_path

def _cli() -> None:
    parser = argparse.ArgumentParser(description="Transform exported Gemini chat markdown to improved markdown.")
    parser.add_argument("input", type=Path, help="Input markdown file")
    parser.add_argument("-o", "--output", type=Path, help="Output file (default: overwrite input)")
    parser.add_argument("--indir", type=Path, help="Input directory to transform all .md files (overrides input file)")
    parser.add_argument("--outdir", type=Path, help="Output directory for transformed files (required with --indir)")
    parser.add_argument("--list-transforms", action="store_true", help="List available transforms and exit")
    parser.add_argument("--run-transforms", type=str, help="Comma-separated transforms to run (overrides defaults)")
    parser.add_argument("--skip-transforms", type=str, help="Comma-separated transforms to skip")
    parser.add_argument("--download-images", action="store_true", help="Download remote images referenced as 'Image of' and replace with local files")
    args = parser.parse_args()

    available = {
        "code_snippet": "Convert 'Code snippet' lines into fences (default on)",
        "close_fences": "Auto-close fences started by transforms and unclosed triple-backticks (default on)",
        "collapse_blanks": "Collapse long blank runs to two blank lines (default on)",
    }

    if args.list_transforms:
        print("Available transforms:")
        for k, v in available.items():
            print(f"- {k}: {v}")
        return

    # build enabled set
    if args.run_transforms:
        enabled = [t.strip() for t in args.run_transforms.split(",") if t.strip()]
    else:
        enabled = list(DEFAULT_TRANSFORMS)
        if args.skip_transforms:
            skip = {t.strip() for t in args.skip_transforms.split(",") if t.strip()}
            enabled = [t for t in enabled if t not in skip]
    if args.indir:
        if not args.outdir:
            parser.error("--outdir is required when --indir is used")
        in_dir: Path = args.indir
        out_dir: Path = args.outdir
        out_dir.mkdir(parents=True, exist_ok=True)
        written = []
        for p in sorted(in_dir.glob("*.md")):
            target = out_dir / p.name
            transform_file(p, target, enabled=enabled, download_images=args.download_images)
            written.append(str(target))
        print("Wrote:")
        for w in written:
            print(w)
    else:
        output = transform_file(args.input, args.output, enabled=enabled, download_images=args.download_images)
        print(f"Wrote: {output}")


if __name__ == "__main__":
    _cli()

