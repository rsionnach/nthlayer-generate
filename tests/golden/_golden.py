"""Golden comparison: normalise a value to JSON and compare it with data/.

A golden lives at ``data/<cell>/<manifest_id>.json``. ``check()`` compares;
with ``NTHLAYER_UPDATE_GOLDENS=1`` it writes the golden instead and still
fails, so a run that wrote goldens can never be mistaken for a passing run
(``test_golden_harness`` also asserts the variable is unset).

Goldens are never regenerated to make a test pass. A golden diff is the
output under review.

Updating goldens:

1. Run the golden tests with ``NTHLAYER_UPDATE_GOLDENS=1``. That run fails by
   design, so it can never be mistaken for a pass.
2. Rerun without the variable; it must pass.
3. Review ``git diff tests/golden/data`` as the change under review and get it
   approved before committing.

A test module that calls ``check()`` declares the goldens it produces as a
module-level ``GOLDEN_CELLS: dict[str, tuple[str, ...]]`` (cell -> manifest
ids), built from the same list it parametrises over. ``expected_goldens()``
collects them so the harness can find orphaned files in ``data/``.
"""

from __future__ import annotations

import dataclasses
import difflib
import enum
import importlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

import yaml

from ._corpus import OPENSRM, REPO

UPDATE_ENV = "NTHLAYER_UPDATE_GOLDENS"
DATA = Path(__file__).resolve().parent / "data"
MASKED = "<masked>"

# Dict keys whose values vary run to run and are replaced by "<masked>".
# Every key here must be found mechanically (run a cell twice, see what
# differs) and must occur in at least one stored golden — the harness
# asserts that, so the mask cannot silently cover nothing. Each entry names
# the cell it was found in.
MASK: frozenset[str] = frozenset(
    {
        # backstage: entity timestamp, datetime.now (generators/backstage.py:194).
        "generatedAt",
        # pipeline: AlertEvent.triggered_at, datetime.now.
        "triggered_at",
        # pipeline: AlertEvent.id is f"alert-<service>-<epoch seconds>"
        # (slos/alerts.py:142,191,258). The key is also the dashboard cell's
        # panels[].id, which this masks too: the mask is by key name only,
        # and "id" is the only stable name the alert id has. Every panel id
        # is the integer 0 today, so nothing is lost now; if panel ids ever
        # become meaningful, a per-cell mask is needed. Panel titles,
        # targets and order stay pinned.
        "id",
        # pipeline: ErrorBudget.period start/end, now minus/at now
        # (slos/pipeline.py:212).
        "start",
        "end",
        # pipeline: ErrorBudget.updated_at, datetime.now.
        "updated_at",
        # topology: TopologyGraph.exported_at, datetime.now.
        "exported_at",
    }
)


class GoldenPathError(ValueError):
    """A path in a golden value would make the golden checkout-specific."""


# (absolute root, replacement for the bare root, replacement for root + sep).
Root = tuple[str, str, str]


def _roots(tmp: Path | None) -> list[Root]:
    """Absolute roots to rewrite inside strings, longest first."""
    roots: list[Root] = []
    if tmp is not None:
        for t in {str(tmp), str(tmp.resolve())}:
            roots.append((t, "<tmp>", "<tmp>/"))
    roots.append((str(REPO), ".", ""))
    roots.append((str(OPENSRM), "<opensrm>", "<opensrm>/"))
    return sorted(roots, key=lambda r: len(r[0]), reverse=True)


def _path(value: Path, tmp: Path | None) -> str:
    resolved = value.resolve()
    if tmp is not None and resolved.is_relative_to(tmp.resolve()):
        rel = resolved.relative_to(tmp.resolve()).as_posix()
        return "<tmp>" if rel == "." else f"<tmp>/{rel}"
    if resolved.is_relative_to(REPO):
        return resolved.relative_to(REPO).as_posix()
    if resolved.is_relative_to(OPENSRM):
        rel = resolved.relative_to(OPENSRM).as_posix()
        return "<opensrm>" if rel == "." else f"<opensrm>/{rel}"
    if resolved.is_relative_to(Path(tempfile.gettempdir()).resolve()):
        raise GoldenPathError(f"temporary path {value} found; pass tmp= to check()")
    raise GoldenPathError(f"path {value} is outside the repo, opensrm and tmp")


def _continues_component(value: str, i: int) -> bool:
    """Whether ``value[i:]`` continues the path component before ``i``.

    ``<eco>/opensrm-x`` must not match the root ``<eco>/opensrm``. A ``.``
    continues a component (``opensrm.bak``) unless it ends the sentence.
    """
    if i >= len(value):
        return False
    c = value[i]
    if c.isalnum() or c in "-_":
        return True
    return c == "." and _continues_component(value, i + 1)


def _string(value: str, roots: list[Root]) -> str:
    """Rewrite each absolute root in ``value`` at a path-component boundary."""
    for root, bare, prefix in roots:
        out: list[str] = []
        start = 0
        while (i := value.find(root, start)) != -1:
            end = i + len(root)
            out.append(value[start:i])
            if value.startswith(os.sep, end):
                out.append(prefix)
                end += len(os.sep)
            elif _continues_component(value, end):
                out.append(root)
            else:
                out.append(bare)
            start = end
        out.append(value[start:])
        value = "".join(out)
    return value


def _key(key: Any) -> str:
    if isinstance(key, enum.Enum):
        key = key.value
    return key if isinstance(key, str) else str(key)


def _plain(value: Any, roots: list[Root], tmp: Path | None) -> Any:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        value = dataclasses.asdict(value)
    if isinstance(value, enum.Enum):
        value = value.value
    if isinstance(value, Path):
        return _path(value, tmp)
    if isinstance(value, str):
        return _string(value, roots)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, dict):
        return {
            _key(k): (MASKED if _key(k) in MASK else _plain(v, roots, tmp))
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_plain(v, roots, tmp) for v in value]
    if isinstance(value, (set, frozenset)):
        return sorted((_plain(v, roots, tmp) for v in value), key=json.dumps)
    raise TypeError(f"cannot normalise {type(value).__name__} for a golden")


def _parse_document(value: str) -> Any:
    """A top-level string holding a JSON or YAML document, as structure.

    Only a mapping or sequence counts: every string is a valid YAML scalar,
    and parsing prose would turn ``"a: b"`` into a dict.
    """
    for parse in (json.loads, yaml.safe_load):
        try:
            parsed = parse(value)
        except (ValueError, yaml.YAMLError):
            continue
        if isinstance(parsed, (dict, list)):
            return parsed
    return value


def normalise(value: object, *, tmp: Path | None = None) -> str:
    """``value`` as sorted, indented JSON text with paths and MASK applied.

    Dataclasses become dicts, enums their values, paths become relative to
    the repo (``<opensrm>/...`` for the spec sibling, ``<tmp>/...`` under
    ``tmp``), absolute prefixes inside strings are rewritten the same way,
    and a top-level JSON/YAML document string is parsed. Anything that has
    no faithful JSON form raises rather than being stringified.
    """
    if isinstance(value, str):
        value = _parse_document(value)
    plain = _plain(value, _roots(tmp), tmp)
    return json.dumps(plain, sort_keys=True, indent=2, ensure_ascii=False)


def golden_path(cell: str, manifest_id: str) -> Path:
    for part in (cell, manifest_id):
        if not part or "/" in part or os.sep in part or part.startswith("."):
            raise ValueError(f"unsafe golden name component: {part!r}")
    return DATA / cell / f"{manifest_id}.json"


def update_mode() -> bool:
    return os.environ.get(UPDATE_ENV) is not None


def check(cell: str, manifest_id: str, value: object, *, tmp: Path | None = None) -> None:
    """Compare ``value`` with its stored golden; in update mode, write it and fail."""
    path = golden_path(cell, manifest_id)
    actual = normalise(value, tmp=tmp) + "\n"
    if update_mode():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(actual, encoding="utf-8")
        raise AssertionError(
            f"{UPDATE_ENV} is set: wrote {path.relative_to(REPO)}; rerun without it"
        )
    if not path.is_file():
        raise AssertionError(
            f"missing golden {path.relative_to(REPO)}; write it with {UPDATE_ENV}=1 "
            "from code whose output you intend to pin"
        )
    expected = path.read_text(encoding="utf-8")
    if actual != expected:
        diff = "".join(
            difflib.unified_diff(
                expected.splitlines(keepends=True),
                actual.splitlines(keepends=True),
                fromfile=f"golden/{cell}/{manifest_id}.json",
                tofile="actual",
            )
        )
        raise AssertionError(f"golden mismatch for {cell}/{manifest_id}:\n{diff}")


def expected_goldens() -> set[tuple[str, str]]:
    """Every (cell, manifest_id) some golden test module declares it produces."""
    expected: set[tuple[str, str]] = set()
    for module_path in sorted(Path(__file__).resolve().parent.glob("test_golden_*.py")):
        module = importlib.import_module(f"{__package__}.{module_path.stem}")
        for cell, ids in getattr(module, "GOLDEN_CELLS", {}).items():
            expected.update((cell, i) for i in ids)
    return expected


def stored_files() -> list[Path]:
    """Every file under data/, golden-shaped or not."""
    return sorted(p for p in DATA.rglob("*") if p.is_file()) if DATA.is_dir() else []
