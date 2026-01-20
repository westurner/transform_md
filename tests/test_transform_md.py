from pathlib import Path
import importlib.util


def load_transform_module(scripts_dir: Path):
    script = scripts_dir / "transform_md.py"
    spec = importlib.util.spec_from_file_location("transform_md", str(script))
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


def test_transform_text_basic():
    scripts_dir = Path(__file__).resolve().parent
    mod = load_transform_module(scripts_dir)

    src = scripts_dir / "tests" / "data" / "test_input.md"
    expected = scripts_dir / "tests" / "data" / "expected_output.md"

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
    assert out.strip().endswith('```')


def test_auto_close_unmatched_fence():
    scripts_dir = Path(__file__).resolve().parent
    mod = load_transform_module(scripts_dir)
    src_text = """Start\n\n```python\nprint(1)\n"""
    out = mod.transform_text(src_text)
    # should close the unclosed python fence
    assert out.strip().endswith('```')
