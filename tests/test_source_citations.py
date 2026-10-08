"""When source cites a test, that test must exist.

The ecosystem convention is that a comment may narrate its own file but must
not assert a checkable fact about another; such a claim becomes an assertion or
gets deleted. The general rule cannot be enforced mechanically. This narrow,
high-frequency case can, and it is the one that actually keeps rotting:
opensrm-ir5m recorded six stale cross-file comments, and opensrm-t4rd's gate
produced five more, three of them written during the gate itself.

One of those five was a pointer to ``test_quoted_scalar_is_always_one_line``,
a test renamed in the same commit that added the pointer. Another was the first
version of THIS file, whose docstring claimed it covered any test named from
``src/`` while its pattern matched only the double-backtick spelling -- so the
two citations added alongside it, in ``specs/manifest.py``, were invisible to
it. A guard that overstates its own reach is worse than no guard, so the
patterns below are deliberately broad and ``test_the_known_citations_are_seen``
pins the count.

Nothing else in the suite notices a dead citation, because a comment is never
executed.
"""

import pathlib
import re

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
_TESTS = pathlib.Path(__file__).resolve().parent

# The three spellings this codebase actually uses, in rough order of frequency.
#   ``test_foo`` / ``TestFoo``      -- a bare name in reST double backticks
#   `test_foo` / `TestFoo`          -- the same in single backticks
#   test_mod.py::TestFoo            -- pytest node id, with or without backticks
#   test_mod.py                     -- a whole module
_NAME = r"(?:test_[A-Za-z0-9_]+|Test[A-Za-z0-9_]+)"
_NODE_ID = re.compile(r"(test_[A-Za-z0-9_]*\.py)::(" + _NAME + r")")
_MODULE = re.compile(r"\b(test_[a-z0-9_]+\.py)\b(?!::)")
_BACKTICKED = re.compile(r"`{1,2}(" + _NAME + r")`{1,2}")


def _test_sources() -> dict[str, str]:
    return {path.name: path.read_text() for path in sorted(_TESTS.rglob("*.py"))}


def _citations() -> list[tuple[str, str, str]]:
    """Every citation in ``src/`` as (source file, kind, cited thing)."""
    found: list[tuple[str, str, str]] = []
    for path in sorted(_SRC.rglob("*.py")):
        text = path.read_text()
        for module, name in _NODE_ID.findall(text):
            found.append((path.name, "node", f"{module}::{name}"))
        for module in _MODULE.findall(text):
            found.append((path.name, "module", module))
        for name in _BACKTICKED.findall(text):
            found.append((path.name, "name", name))
    return found


def test_the_sweep_actually_reads_something() -> None:
    """Anti-vacuity: a moved tree would make every assertion below pass.

    ``test_manifest_v2_archetypes.py`` in nthlayer-common skipped its entire
    module for exactly this reason -- a path that quietly stopped resolving --
    and stayed green while it tested nothing.
    """
    assert _SRC.is_dir(), f"source tree not found at {_SRC}"
    assert list(_SRC.rglob("*.py")), f"no modules under {_SRC}"
    assert _test_sources(), f"no test modules beside {_TESTS}"


def test_the_known_citations_are_seen() -> None:
    """Pins the guard's reach, because the first version overstated it.

    A floor, not an exact count: adding a citation should not fail here, but a
    pattern that stops matching should. Raise it deliberately if citations are
    added, and never lower it to make a failure go away -- widen the patterns
    instead.
    """
    citations = _citations()
    kinds = {kind for _, kind, _ in citations}
    assert len(citations) >= 3, (
        f"found only {len(citations)} citations in src/ ({citations}); the "
        f"patterns have probably stopped matching, so this guard is inspecting "
        f"almost nothing. Widen _NODE_ID / _MODULE / _BACKTICKED rather than "
        f"lowering this floor."
    )
    assert {"node", "module", "name"} <= kinds, (
        f"only these citation kinds were found: {sorted(kinds)}. All three "
        f"spellings existed when this was written, so a missing kind means a "
        f"pattern broke, not that the codebase changed style."
    )


def test_every_cited_test_exists() -> None:
    sources = _test_sources()
    haystack = "\n".join(sources.values())
    missing: list[str] = []

    for source_file, kind, cited in _citations():
        if kind == "module":
            ok = cited in sources
        elif kind == "node":
            module, name = cited.split("::")
            ok = module in sources and (
                re.search(rf"(def|class)\s+{re.escape(name)}\b", sources[module]) is not None
            )
        else:
            ok = re.search(rf"(def|class)\s+{re.escape(cited)}\b", haystack) is not None
        if not ok:
            missing.append(f"{cited} (cited in {source_file})")

    assert not missing, (
        "source cites tests that do not exist: "
        + "; ".join(missing)
        + ". Rename the citation to the real test, or delete the clause -- a "
        "pointer to a test that is gone is worse than no pointer, because it "
        "reads as coverage (opensrm-t4rd)."
    )
