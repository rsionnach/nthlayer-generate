"""Guard: the command named in common's opensrm/v1 rejection runs in generate.

nthlayer-common's loader rejects opensrm/v1 manifests with a message that ends
in a copy-pasteable ``nthlayer-generate migrate-manifest <path>``. Generate is
the authority for whether that command works, so this derives the command from
the real error and checks it against generate's real entry points and parser
(opensrm-dww5). Only the delimiter before the command is hardcoded (COMMAND_FOLLOWS).
"""

from __future__ import annotations

import shlex
import shutil
import tomllib
from pathlib import Path

import pytest
from nthlayer_common.manifest import ManifestLoadError, load_manifest

from nthlayer_generate.demo import build_parser

REPO_ROOT = Path(__file__).resolve().parents[1]
SPEC_EXAMPLE = REPO_ROOT.parent / "opensrm" / "examples" / "api-minimal.yaml"
# Text that precedes the command in nthlayer-common's rejection message
# (src/nthlayer_common/manifest/opensrm_v1.py: "...package: <command>").
COMMAND_FOLLOWS = "package: "
ENTRY_TARGET = "nthlayer_generate.demo:main"


@pytest.fixture(scope="module")
def scripts() -> dict[str, str]:
    with (REPO_ROOT / "pyproject.toml").open("rb") as f:
        return tomllib.load(f)["project"]["scripts"]


@pytest.fixture
def rejection(tmp_path: Path) -> tuple[Path, str]:
    """(manifest path, real error text) from loading an opensrm/v1 manifest."""
    assert SPEC_EXAMPLE.exists(), f"spec example missing: {SPEC_EXAMPLE}"
    path = tmp_path / "my dir" / "svc.yaml"  # space forces shlex quoting
    path.parent.mkdir()
    shutil.copy(SPEC_EXAMPLE, path)
    assert "apiVersion: opensrm/v1" in path.read_text()
    with pytest.raises(ManifestLoadError) as exc:
        load_manifest(path)
    return path, str(exc.value)


@pytest.fixture
def argv(rejection: tuple[Path, str]) -> list[str]:
    _, text = rejection
    assert text.count(COMMAND_FOLLOWS) == 1, text
    return shlex.split(text.split(COMMAND_FOLLOWS)[1])


def test_command_script_is_declared_and_points_at_generate(argv, scripts):
    assert argv[0] in scripts, f"{argv[0]!r} is not a [project.scripts] entry"
    assert scripts[argv[0]] == ENTRY_TARGET


def test_command_parses_with_generate_parser(argv, rejection):
    path, _ = rejection
    args = build_parser().parse_args(argv[1:])
    assert args.command == "migrate-manifest"
    assert args.manifest == str(path)


def test_generate_owns_bare_nthlayer_name(scripts):
    assert scripts.get("nthlayer") == ENTRY_TARGET
