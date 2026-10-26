"""Load records: what today's loader makes of every corpus file (cell ``load``).

One golden per file: whether it loads, the exception if not, every warning
emitted, and the manifest fields the later cells depend on. Failures are
pinned as data, not skipped — a file that starts or stops loading is a
golden diff.
"""

from __future__ import annotations

import warnings
from pathlib import Path

import pytest
from nthlayer_common.manifest import load_manifest

from ._corpus import ALL, manifest_id
from ._golden import check

CASES = tuple((manifest_id(p), p) for p in ALL)
GOLDEN_CELLS = {"load": tuple(i for i, _ in CASES)}


def load_record(path: Path) -> dict[str, object]:
    record: dict[str, object] = {
        "ok": False,
        "error": None,
        "warnings": [],
        "source_format": None,
        "type": None,
        "authored_type": None,
        "slos": None,
        "dependencies": None,
    }
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            manifest = load_manifest(path, suppress_deprecation_warning=True)
        except Exception as e:  # noqa: BLE001 — every failure is the record
            record["error"] = [type(e).__name__, str(e)]
            manifest = None
    record["warnings"] = [[w.category.__name__, str(w.message)] for w in caught]
    if manifest is None:
        return record
    record["ok"] = True
    record["source_format"] = manifest.source_format
    record["type"] = manifest.type
    # The spelling the file used, before alias resolution (common 5.4.0).
    record["authored_type"] = getattr(manifest, "authored_type", None)
    record["slos"] = [
        [s.name, s.slo_type, s.target, s.window, bool(s.indicator_query)] for s in manifest.slos
    ]
    # Generate's model has no judgment_thresholds today; common's does.
    # Recorded only when non-empty, so the switch to common adds the key only
    # to the manifests that declare thresholds, not to every loadable golden.
    thresholds = getattr(manifest, "judgment_thresholds", ())
    if thresholds:
        record["judgment_thresholds"] = list(thresholds)
    record["dependencies"] = [[d.name, d.type, d.critical] for d in manifest.dependencies]
    return record


@pytest.mark.parametrize(("mid", "path"), CASES, ids=[i for i, _ in CASES])
def test_load_record(mid: str, path: Path) -> None:
    check("load", mid, load_record(path))
