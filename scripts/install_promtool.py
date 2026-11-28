#!/usr/bin/env python3
"""Install the pinned promtool (opensrm-r0bx).

    uv run python scripts/install_promtool.py [--dest DIR]

Downloads the official Prometheus release for this platform, checks it
against the release's sha256sums.txt, and copies ``promtool`` into DIR
(default ``~/.local/bin``). The version is not written here: it is
``PROMTOOL_VERSION`` in ``nthlayer_generate.validation.promtool``, the same
constant the runner checks, so CI, a developer's machine and the tests
cannot drift apart.
"""

from __future__ import annotations

import argparse
import hashlib
import platform
import shutil
import stat
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

from nthlayer_generate.validation.promtool import PROMTOOL_VERSION

_RELEASES = "https://github.com/prometheus/prometheus/releases/download"
# platform.system() / platform.machine() -> the names in the release assets.
_OS_NAMES = {"Linux": "linux", "Darwin": "darwin"}
_ARCH_NAMES = {"x86_64": "amd64", "amd64": "amd64", "aarch64": "arm64", "arm64": "arm64"}


def _asset_stem() -> str:
    system, machine = platform.system(), platform.machine()
    if system not in _OS_NAMES or machine not in _ARCH_NAMES:
        raise SystemExit(f"install_promtool: no release asset known for {system}/{machine}")
    return f"prometheus-{PROMTOOL_VERSION}.{_OS_NAMES[system]}-{_ARCH_NAMES[machine]}"


def _download(url: str, dest: Path) -> None:
    with urllib.request.urlopen(url, timeout=120) as response:  # noqa: S310 (fixed https host)
        dest.write_bytes(response.read())


def _expected_sha256(sums: Path, archive_name: str) -> str:
    for line in sums.read_text(encoding="utf-8").splitlines():
        fields = line.split()
        if len(fields) == 2 and fields[1] == archive_name:
            return fields[0]
    raise SystemExit(f"install_promtool: {archive_name} is not listed in sha256sums.txt")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dest", type=Path, default=Path.home() / ".local" / "bin")
    args = parser.parse_args()

    stem = _asset_stem()
    archive_name = f"{stem}.tar.gz"
    base = f"{_RELEASES}/v{PROMTOOL_VERSION}"

    with tempfile.TemporaryDirectory(prefix="install-promtool-") as tmp:
        work = Path(tmp)
        archive, sums = work / archive_name, work / "sha256sums.txt"
        _download(f"{base}/{archive_name}", archive)
        _download(f"{base}/sha256sums.txt", sums)

        expected = _expected_sha256(sums, archive_name)
        actual = hashlib.sha256(archive.read_bytes()).hexdigest()
        if actual != expected:
            raise SystemExit(
                f"install_promtool: checksum mismatch for {archive_name}: "
                f"expected {expected}, got {actual}"
            )

        member_name = f"{stem}/promtool"
        with tarfile.open(archive) as tar:
            member = tar.extractfile(member_name)
            if member is None:
                raise SystemExit(f"install_promtool: {member_name} is not in the archive")
            binary = member.read()

    args.dest.mkdir(parents=True, exist_ok=True)
    target = args.dest / "promtool"
    target.write_bytes(binary)
    target.chmod(target.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    sys.stderr.write(f"promtool {PROMTOOL_VERSION} installed at {target}\n")
    sys.stderr.write(path_warning(target, shutil.which("promtool")))
    return 0


def path_warning(target: Path, on_path: str | None) -> str:
    """What to tell the user when PATH does not lead to ``target``, else "".

    The runner takes promtool from PATH. If another promtool comes first, or
    the install directory is not on PATH, the runner keeps reporting
    promtool as unavailable and pointing back at this script.
    """
    if on_path is None:
        return (
            f"WARNING: {target.parent} is not on PATH, so the tests will not find "
            f"promtool. Add it to PATH.\n"
        )
    if Path(on_path).resolve() != target.resolve():
        return (
            f"WARNING: PATH finds another promtool first, at {on_path}. Put "
            f"{target.parent} earlier on PATH.\n"
        )
    return ""


if __name__ == "__main__":
    sys.exit(main())
