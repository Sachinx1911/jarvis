"""Only jarvis/providers/ may import vendor AI SDKs (PLAN.md 5.5)."""

import ast
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent.parent / "jarvis"
VENDOR_MODULES = {"anthropic", "openai", "ollama", "llama_cpp", "mlx_lm", "google.generativeai", "mistralai", "cohere"}


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module)
    return names


def _is_vendor(module: str) -> bool:
    return any(module == v or module.startswith(v + ".") for v in VENDOR_MODULES)


def test_vendor_sdks_only_in_providers():
    offenders = []
    for path in PACKAGE.rglob("*.py"):
        rel = path.relative_to(PACKAGE)
        if rel.parts[0] == "providers" and rel.name != "base.py":
            continue
        bad = sorted(m for m in _imports(path) if _is_vendor(m))
        if bad:
            offenders.append(f"{rel}: {bad}")
    assert not offenders, "vendor imports outside providers/: " + "; ".join(offenders)


def test_base_types_are_vendor_free():
    assert not any(_is_vendor(m) for m in _imports(PACKAGE / "providers" / "base.py"))


def test_checker_catches_a_violation(tmp_path):
    bad = tmp_path / "bad.py"
    bad.write_text("import anthropic\nfrom openai import OpenAI\n", encoding="utf-8")
    assert {m for m in _imports(bad) if _is_vendor(m)} == {"anthropic", "openai"}
