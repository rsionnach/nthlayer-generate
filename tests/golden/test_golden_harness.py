"""Tests that keep the golden corpus and the stored goldens honest.

None of these skip: a missing opensrm sibling, an unclassified example, a
vacuous mask or an orphaned golden is a failure, because each is a way for
the golden suite to stay green while testing less than it claims.
"""

from __future__ import annotations

import json
import os
from collections import Counter
from pathlib import Path

import pytest

from ._corpus import (
    ALL,
    EX,
    LEGACY,
    NON_MANIFESTS,
    NOT_MANIFESTS_BY_DESIGN,
    OPENSRM,
    REPO,
    SRM_V1,
    V2,
    manifest_id,
)
from ._golden import (
    DATA,
    MASK,
    MASKED,
    UPDATE_ENV,
    GoldenPathError,
    expected_goldens,
    normalise,
    stored_files,
    update_mode,
)


def _example_yaml() -> list[Path]:
    return sorted(p for pattern in ("*.yaml", "*.yml") for p in EX.rglob(pattern))


def _by_design(path: Path) -> bool:
    rel = path.relative_to(EX)
    return any(
        rel == Path(entry) or Path(entry) in rel.parents for entry, _ in NOT_MANIFESTS_BY_DESIGN
    )


def test_every_example_is_classified_exactly_once() -> None:
    groups = {
        "SRM_V1": set(SRM_V1),
        "LEGACY": set(LEGACY),
        "NON_MANIFESTS": set(NON_MANIFESTS),
    }
    problems = []
    for path in _example_yaml():
        homes = [name for name, members in groups.items() if path in members]
        if _by_design(path):
            homes.append("NOT_MANIFESTS_BY_DESIGN")
        if len(homes) != 1:
            problems.append(f"{path.relative_to(EX)}: {homes or 'unclassified'}")
    assert problems == []


def test_every_corpus_entry_exists_and_is_listed_once() -> None:
    corpus = SRM_V1 + LEGACY + NON_MANIFESTS
    assert [p for p in corpus if not p.is_file()] == []
    assert [p for p, n in Counter(corpus).items() if n > 1] == []
    for entry, reason in NOT_MANIFESTS_BY_DESIGN:
        assert (EX / entry).exists(), entry
        assert reason


def test_corpus_counts() -> None:
    assert (len(SRM_V1), len(LEGACY), len(NON_MANIFESTS)) == (7, 20, 12)


def test_opensrm_sibling_is_present_and_has_v2_manifests() -> None:
    # Never a skip: CI checks the sibling out (.github/workflows/ci.yml),
    # and a missing checkout would otherwise drop every v2 golden silently.
    assert OPENSRM.is_dir(), f"opensrm sibling not found at {OPENSRM}"
    assert len(V2) >= 1


def test_manifest_ids_are_unique() -> None:
    ids = [manifest_id(p) for p in ALL]
    assert [i for i, n in Counter(ids).items() if n > 1] == []


def test_update_mode_is_off() -> None:
    # A run that wrote goldens must not be able to pass.
    assert os.environ.get(UPDATE_ENV) is None


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("1", True),
        ("true", True),
        ("TRUE", True),
        ("Yes", True),
        ("0", False),
        ("false", False),
        ("", False),
        ("no", False),
    ],
)
def test_update_mode_is_truthy_values_only(
    monkeypatch: pytest.MonkeyPatch, value: str, expected: bool
) -> None:
    monkeypatch.setenv(UPDATE_ENV, value)
    assert update_mode() is expected


def test_update_mode_unset_is_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(UPDATE_ENV, raising=False)
    assert update_mode() is False


def _has_masked_key(node: object, key: str) -> bool:
    if isinstance(node, dict):
        return any((k == key and v == MASKED) or _has_masked_key(v, key) for k, v in node.items())
    if isinstance(node, list):
        return any(_has_masked_key(v, key) for v in node)
    return False


def test_every_mask_key_masks_something() -> None:
    goldens = [json.loads(p.read_text(encoding="utf-8")) for p in stored_files()]
    assert [k for k in sorted(MASK) if not any(_has_masked_key(g, k) for g in goldens)] == []


def test_no_orphaned_goldens() -> None:
    expected = expected_goldens()
    orphans = []
    for path in stored_files():
        rel = path.relative_to(DATA)
        if len(rel.parts) != 2 or rel.suffix != ".json" or (rel.parts[0], rel.stem) not in expected:
            orphans.append(rel.as_posix())
    assert orphans == []


# Path rewriting: a root is rewritten only at a path-component boundary.
_ECO = OPENSRM.parent


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (f"in {REPO}/examples/x.yaml", "in examples/x.yaml"),
        (f"in {REPO}", "in ."),
        (f"in {REPO}: bad", "in .: bad"),
        (f"in {REPO}.", "in .."),
        (f"in {OPENSRM}/spec/v2", "in <opensrm>/spec/v2"),
        (f"in {OPENSRM}", "in <opensrm>"),
        (f"'{OPENSRM}'", "'<opensrm>'"),
        (f"in {_ECO}/opensrm-x/spec", f"in {_ECO}/opensrm-x/spec"),
        (f"in {_ECO}/opensrm.bak", f"in {_ECO}/opensrm.bak"),
        (f"in {REPO}-old/x", f"in {REPO}-old/x"),
    ],
)
def test_string_paths_are_rewritten_at_component_boundaries(raw: str, expected: str) -> None:
    assert json.loads(normalise([raw])) == [expected]


def test_path_objects_are_rewritten_at_component_boundaries() -> None:
    assert json.loads(normalise([REPO, REPO / "examples", OPENSRM, OPENSRM / "spec"])) == [
        ".",
        "examples",
        "<opensrm>",
        "<opensrm>/spec",
    ]
    with pytest.raises(GoldenPathError):
        normalise(_ECO / "opensrm-x")


def test_tmp_paths_are_rewritten(tmp_path: Path) -> None:
    value = [tmp_path / "a.yaml", f"wrote {tmp_path}/a.yaml", str(tmp_path)]
    assert json.loads(normalise(value, tmp=tmp_path)) == [
        "<tmp>/a.yaml",
        "wrote <tmp>/a.yaml",
        "<tmp>",
    ]
