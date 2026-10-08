"""A comment may narrate its own file; it may not assert a stale fact about another.

The ecosystem convention exists because prose rots silently. opensrm-ir5m
recorded six comments that asserted a checkable fact about a different file and
were wrong by the time anyone read them. During opensrm-t4rd's gate four more
were written, three of them inside the gate itself, and one was a pointer to
``test_quoted_scalar_is_always_one_line`` -- a test that had been renamed in the
same commit that added the pointer.

The general rule cannot be enforced mechanically. This narrow, high-frequency
case can: if a module under ``src/`` names a test or test class, that test must
exist. Nothing else in the suite notices when it stops existing, because a
docstring is not executed.
"""

import pathlib
import re

# ``test_foo`` or ``TestFoo`` inside reST double backticks, which is how this
# codebase cites a test from source.
_CITATION = re.compile(r"``(test_[A-Za-z0-9_]+|Test[A-Za-z0-9_]+)``")

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
_TESTS = pathlib.Path(__file__).resolve().parent


def _citations() -> dict[str, set[str]]:
    found: dict[str, set[str]] = {}
    for path in sorted(_SRC.rglob("*.py")):
        for match in _CITATION.finditer(path.read_text()):
            found.setdefault(match.group(1), set()).add(path.name)
    return found


def test_the_sweep_actually_reads_something() -> None:
    """Anti-vacuity: a moved ``src/`` tree would make this pass by finding nothing.

    The archetype test in nthlayer-common skipped its whole module for exactly
    this reason -- a path that stopped resolving -- and stayed green for weeks.
    """
    assert _SRC.is_dir(), f"source tree not found at {_SRC}"
    assert list(_SRC.rglob("*.py")), f"no modules under {_SRC}"
    assert list(_TESTS.rglob("test_*.py")), f"no test modules beside {_TESTS}"


def test_every_test_cited_from_src_exists() -> None:
    """The narrow half of the convention, enforced rather than reviewed."""
    haystack = "\n".join(
        path.read_text() for path in sorted(_TESTS.rglob("*.py"))
    )

    missing = {
        name: sorted(files)
        for name, files in _citations().items()
        if re.search(rf"(def|class)\s+{re.escape(name)}\b", haystack) is None
    }

    assert not missing, (
        "source cites tests that do not exist: "
        + "; ".join(f"{name} (in {', '.join(files)})" for name, files in missing.items())
        + ". Rename the citation to the real test, or delete the clause -- a "
        "pointer to a test that is gone is worse than no pointer, because it "
        "reads as coverage (opensrm-t4rd)."
    )
