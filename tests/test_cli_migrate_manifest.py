"""Tests for the `nthlayer migrate-manifest` CLI command (opensrm-b22.2)."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml


def _v1_payload() -> dict:
    return {
        "apiVersion": "srm/v1",
        "kind": "ServiceReliabilityManifest",
        "metadata": {"name": "svc", "team": "team-a", "tier": "critical"},
        "spec": {
            "type": "api",
            "slos": {
                "availability": {
                    "target": 99.9,
                    "window": "30d",
                    "indicator": {"query": "rate(http[5m])"},
                },
            },
        },
    }


class TestMigrateManifestCommand:
    def test_writes_v2_file_alongside_input(self, tmp_path):
        from nthlayer_generate.cli.migrate_manifest import migrate_manifest_command

        in_file = tmp_path / "svc.yaml"
        in_file.write_text(yaml.safe_dump(_v1_payload()))

        rc = migrate_manifest_command(str(in_file))
        assert rc == 0
        out_file = tmp_path / "svc.v2.yaml"
        assert out_file.exists()
        out_data = yaml.safe_load(out_file.read_text())
        assert out_data["apiVersion"] == "opensrm.nthlayer.io/v2"

    def test_explicit_output_path(self, tmp_path):
        from nthlayer_generate.cli.migrate_manifest import migrate_manifest_command

        in_file = tmp_path / "svc.yaml"
        in_file.write_text(yaml.safe_dump(_v1_payload()))
        out_file = tmp_path / "subdir" / "v2.yaml"

        rc = migrate_manifest_command(str(in_file), output_path=str(out_file))
        assert rc == 0
        assert out_file.exists()

    def test_dry_run_does_not_write(self, tmp_path, capsys):
        from nthlayer_generate.cli.migrate_manifest import migrate_manifest_command

        in_file = tmp_path / "svc.yaml"
        in_file.write_text(yaml.safe_dump(_v1_payload()))

        rc = migrate_manifest_command(str(in_file), dry_run=True)
        assert rc == 0
        # No .v2.yaml file should be created.
        assert not (tmp_path / "svc.v2.yaml").exists()
        captured = capsys.readouterr()
        assert "opensrm.nthlayer.io/v2" in captured.out

    def test_existing_output_without_force_fails(self, tmp_path):
        from nthlayer_generate.cli.migrate_manifest import migrate_manifest_command

        in_file = tmp_path / "svc.yaml"
        in_file.write_text(yaml.safe_dump(_v1_payload()))
        out_file = tmp_path / "svc.v2.yaml"
        out_file.write_text("# pre-existing")

        rc = migrate_manifest_command(str(in_file), output_path=str(out_file))
        assert rc == 1
        # Pre-existing file unchanged.
        assert out_file.read_text() == "# pre-existing"

    def test_force_overwrites(self, tmp_path):
        from nthlayer_generate.cli.migrate_manifest import migrate_manifest_command

        in_file = tmp_path / "svc.yaml"
        in_file.write_text(yaml.safe_dump(_v1_payload()))
        out_file = tmp_path / "svc.v2.yaml"
        out_file.write_text("# pre-existing")

        rc = migrate_manifest_command(
            str(in_file), output_path=str(out_file), force=True
        )
        assert rc == 0
        assert "opensrm.nthlayer.io/v2" in out_file.read_text()

    def test_already_v2_input_is_noop(self, tmp_path):
        from nthlayer_generate.cli.migrate_manifest import migrate_manifest_command

        in_file = tmp_path / "svc.yaml"
        in_file.write_text(yaml.safe_dump({
            "apiVersion": "opensrm.nthlayer.io/v2",
            "kind": "ServiceManifest",
            "metadata": {"name": "svc", "labels": {"tier": "critical", "type": "api"}},
            "spec": {"owner": {"group": "group:default/team-a"}, "service": {"name": "svc"}},
        }))

        rc = migrate_manifest_command(str(in_file))
        assert rc == 0
        # No .v2.yaml side-output created (already-v2 input is a no-op).
        assert not (tmp_path / "svc.v2.yaml").exists()

    def test_missing_input_returns_1(self, tmp_path):
        from nthlayer_generate.cli.migrate_manifest import migrate_manifest_command
        rc = migrate_manifest_command(str(tmp_path / "nonexistent.yaml"))
        assert rc == 1

    def test_invalid_yaml_returns_1(self, tmp_path):
        from nthlayer_generate.cli.migrate_manifest import migrate_manifest_command
        in_file = tmp_path / "bad.yaml"
        in_file.write_text("apiVersion: srm/v1\n  bad indent: oops:")
        rc = migrate_manifest_command(str(in_file))
        assert rc == 1

    def test_unsupported_input_apiversion_returns_1(self, tmp_path):
        from nthlayer_generate.cli.migrate_manifest import migrate_manifest_command
        in_file = tmp_path / "weird.yaml"
        in_file.write_text(yaml.safe_dump({"apiVersion": "something/else"}))
        rc = migrate_manifest_command(str(in_file))
        assert rc == 1


class TestDemoSpecsViaCLI:
    """End-to-end: every demo spec converts via the CLI command + writes a parseable v2 file."""

    DEMO_FILES = ["payment-api.yaml", "fraud-detect.yaml", "order-service.yaml", "checkout-svc.yaml"]

    @pytest.fixture
    def demo_dir(self) -> Path:
        # nthlayer-generate is at ecosystem/nthlayer-generate; demo specs at
        # ecosystem/nthlayer/demo/specs.
        candidate = Path(__file__).resolve().parents[2] / "nthlayer" / "demo" / "specs"
        if not candidate.exists():
            pytest.skip(f"Demo specs directory not found at {candidate}")
        return candidate

    @pytest.mark.parametrize("filename", DEMO_FILES)
    def test_demo_spec_migrates_via_cli(self, tmp_path, demo_dir: Path, filename: str):
        from nthlayer_common.manifest.parser.v2 import parse_opensrm_v2

        from nthlayer_generate.cli.migrate_manifest import migrate_manifest_command

        src = demo_dir / filename
        if not src.exists():
            pytest.skip(f"{filename} not present")

        out = tmp_path / f"{src.stem}.v2.yaml"
        rc = migrate_manifest_command(str(src), output_path=str(out))
        assert rc == 0, f"CLI returned {rc} for {filename}"
        assert out.exists()

        # Parse the written file end-to-end through the v2 parser.
        v2_data = yaml.safe_load(out.read_text())
        manifest = parse_opensrm_v2(v2_data)
        assert manifest.name == src.stem
