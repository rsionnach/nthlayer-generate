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


AI_GATE_EXAMPLE = (
    Path(__file__).resolve().parents[1] / "examples" / "opensrm" / "ai-gate.reliability.yaml"
)


class TestAiGateJudgmentThresholds:
    """srm/v1 judgment magnitudes migrate to spec.judgment_threshold (opensrm-tnz3).

    Expected values are read from the example file, never hardcoded. The shapes
    asserted follow nthlayer-common 4.0 (docs/upgrading-4.0.md): calibration's
    target is `maximum_expected_calibration_error`; feedback_latency's is
    `maximum_p50` as a "<n>s" Duration string.
    """

    def test_example_calibration_and_feedback_latency_become_thresholds(self, tmp_path):
        """Relies on `nthlayer_common.manifest.v1_compat.convert_v1_to_v2`."""
        from nthlayer_generate.cli.migrate_manifest import migrate_manifest_command

        src = yaml.safe_load(AI_GATE_EXAMPLE.read_text())["spec"]["slos"]
        cal_target = src["calibration"]["target"]
        lat_target = src["feedback_latency"]["target"]

        out = tmp_path / "ai-gate.v2.yaml"
        rc = migrate_manifest_command(str(AI_GATE_EXAMPLE), output_path=str(out))
        assert rc == 0
        spec = yaml.safe_load(out.read_text())["spec"]

        thresholds = {t["type"]: t for t in spec["judgment_threshold"]}
        assert thresholds["calibration"]["bounds"] == {
            "maximum_expected_calibration_error": cal_target
        }
        # srm/v1 had no bins key and defaulted to 10; v2 calibration requires bins.
        assert thresholds["calibration"]["measurement"] == {
            "bins": 10,
            "window": src["calibration"]["window"],
        }
        assert thresholds["feedback_latency"]["bounds"] == {
            "maximum_p50": f"{int(lat_target)}s"
        }
        slo_types = {s["spec"]["judgment_type"] for s in spec["judgment_slo"]}
        # Non-vacuous: the other judgment SLOs are still there.
        assert {"reversal_rate", "high_confidence_failure"} <= slo_types
        assert not slo_types & {"calibration", "feedback_latency"}

    @pytest.mark.parametrize("section", ["segments", "stability", "audit_backlog"])
    def test_removed_srm_v1_threshold_is_rejected_cleanly(self, tmp_path, section):
        """Cleanly = returns exit code 1 (the command handles the error, so no
        exception/traceback escapes this direct call) and writes no output file.

        The 0.05 / 30d payload is a placeholder: the section type alone triggers
        the rejection in nthlayer-common 4.0.0.
        """
        from nthlayer_generate.cli.migrate_manifest import migrate_manifest_command

        payload = yaml.safe_load(AI_GATE_EXAMPLE.read_text())
        payload["spec"]["slos"][section] = {"target": 0.05, "window": "30d"}
        in_file = tmp_path / "ai-gate.yaml"
        in_file.write_text(yaml.safe_dump(payload))
        out = tmp_path / "ai-gate.v2.yaml"

        rc = migrate_manifest_command(str(in_file), output_path=str(out))
        assert rc == 1
        assert not out.exists()


class TestOpensrmV1:
    """opensrm/v1 -> v2 (opensrm-pnmv).

    Fixtures follow opensrm/spec/v1/schema.json and the spec's
    opensrm/examples/*.yaml (api-minimal, ai-gate-minimal), not the converter.
    """

    @staticmethod
    def _doc(**spec) -> dict:
        return {
            "apiVersion": "opensrm/v1",
            "kind": "ServiceReliabilityManifest",
            "metadata": {"name": "my-service", "team": "platform", "tier": "standard"},
            "spec": {
                "type": "api",
                "slos": {"availability": {"target": 0.999, "window": "30d"}},
                **spec,
            },
        }

    def _write(self, tmp_path, doc=None, **spec) -> Path:
        p = tmp_path / "svc.yaml"
        p.write_text(yaml.safe_dump(doc if doc is not None else self._doc(**spec)))
        return p

    @staticmethod
    def _run(*args, **kwargs) -> int:
        from nthlayer_generate.cli.migrate_manifest import migrate_manifest_command

        return migrate_manifest_command(*args, **kwargs)

    @staticmethod
    def _capture_warnings(monkeypatch) -> list[str]:
        from nthlayer_generate.cli import migrate_manifest

        calls: list[str] = []
        monkeypatch.setattr(migrate_manifest, "warning", calls.append)
        return calls

    def test_lossless_converts(self, tmp_path):
        p = self._write(tmp_path)
        assert self._run(str(p)) == 0
        out = yaml.safe_load((tmp_path / "svc.v2.yaml").read_text())
        assert out["apiVersion"] == "opensrm.nthlayer.io/v2"

    def test_lossy_refuses_without_the_flag(self, tmp_path):
        p = self._write(tmp_path, deployment={"gates": {}})
        assert self._run(str(p)) == 1
        assert not (tmp_path / "svc.v2.yaml").exists()

    def test_lossy_writes_with_the_flag(self, tmp_path):
        p = self._write(tmp_path, deployment={"gates": {}})
        assert self._run(str(p), allow_lossy=True) == 0
        out = yaml.safe_load((tmp_path / "svc.v2.yaml").read_text())
        assert "deployment" not in out["spec"]

    def test_dropped_field_is_warned_with_path(self, tmp_path, monkeypatch):
        calls = self._capture_warnings(monkeypatch)
        p = self._write(tmp_path, deployment={"gates": {}})
        assert self._run(str(p), allow_lossy=True) == 0
        assert any(c.startswith("Not migrated: spec.deployment") for c in calls)

    def test_missing_type_needs_service_type(self, tmp_path):
        doc = self._doc()
        del doc["spec"]["type"]
        p = self._write(tmp_path, doc)
        assert self._run(str(p)) == 1
        assert self._run(str(p), service_type="api") == 0

    def test_unconvertible_document_returns_1(self, tmp_path):
        doc = self._doc()
        doc["metadata"]["tier"] = "gold"
        p = self._write(tmp_path, doc)
        assert self._run(str(p), allow_lossy=True) == 1
        assert not (tmp_path / "svc.v2.yaml").exists()

    def test_assumed_only_field_does_not_refuse(self, tmp_path, monkeypatch):
        """ai-gate calibration declares no bins in v1; the assumption is
        reported but is not loss, so no --allow-lossy is needed."""
        calls = self._capture_warnings(monkeypatch)
        doc = self._doc(
            type="ai-gate",
            slos={
                "availability": {"target": 0.999, "window": "30d"},
                "judgment": {"calibration": {"target": 0.10, "window": "30d"}},
            },
        )
        p = self._write(tmp_path, doc)
        assert self._run(str(p)) == 0
        out = yaml.safe_load((tmp_path / "svc.v2.yaml").read_text())
        assert out["spec"]["judgment_threshold"][0]["type"] == "calibration"
        assumed = [c for c in calls if c.startswith("Converted with an assumption:")]
        assert len(assumed) == 1
        assert "spec.slos.judgment.calibration" in assumed[0]
        assert not any(c.startswith("Not migrated:") for c in calls)

    def _with_openslo_ref(self, tmp_path) -> Path:
        # An OpenSLO document of the shape the converter's own v2 output uses
        # for inline SLOs (apiVersion openslo/v1, kind SLO).
        (tmp_path / "extra-slo.yaml").write_text(
            yaml.safe_dump(
                {
                    "apiVersion": "openslo/v1",
                    "kind": "SLO",
                    "metadata": {"name": "my-service-availability"},
                    "spec": {
                        "service": "my-service",
                        "timeWindow": [{"duration": "30d", "isRolling": True}],
                        "objectives": [{"displayName": "99.9% availability", "target": 0.999}],
                    },
                }
            )
        )
        doc = self._doc(slos={"openslo": [{"path": "extra-slo.yaml"}]})
        return self._write(tmp_path, doc)

    def test_relative_ref_warns_when_output_moves(self, tmp_path, monkeypatch):
        calls = self._capture_warnings(monkeypatch)
        p = self._with_openslo_ref(tmp_path)
        out = tmp_path / "elsewhere" / "svc.v2.yaml"
        assert self._run(str(p), output_path=str(out)) == 0
        assert out.exists()
        refs = [c for c in calls if "extra-slo.yaml" in c]
        assert len(refs) == 1

    def test_relative_ref_silent_when_output_beside_input(self, tmp_path, monkeypatch):
        calls = self._capture_warnings(monkeypatch)
        p = self._with_openslo_ref(tmp_path)
        assert self._run(str(p)) == 0
        assert (tmp_path / "svc.v2.yaml").exists()
        assert not [c for c in calls if "extra-slo.yaml" in c]

    def test_openslo_path_that_is_a_directory_returns_1(self, tmp_path):
        (tmp_path / "sub").mkdir()
        p = self._write(tmp_path, self._doc(slos={"openslo": [{"path": "sub"}]}))
        assert self._run(str(p)) == 1
        assert not (tmp_path / "svc.v2.yaml").exists()

    def test_openslo_path_with_invalid_utf8_returns_1(self, tmp_path):
        (tmp_path / "bad.yaml").write_bytes(b"\xff\xfe\x00")
        p = self._write(tmp_path, self._doc(slos={"openslo": [{"path": "bad.yaml"}]}))
        assert self._run(str(p)) == 1
        assert not (tmp_path / "svc.v2.yaml").exists()

    def test_openslo_path_to_missing_file_returns_1(self, tmp_path):
        p = self._write(tmp_path, self._doc(slos={"openslo": [{"path": "nope.yaml"}]}))
        assert self._run(str(p)) == 1
        assert not (tmp_path / "svc.v2.yaml").exists()

    def test_srm_v1_warns_that_opensrm_flags_are_ignored(self, tmp_path, monkeypatch):
        src = tmp_path / "old.yaml"
        src.write_text(yaml.safe_dump(_v1_payload()))
        calls = self._capture_warnings(monkeypatch)
        baseline = self._run(str(src), dry_run=True)
        assert not [c for c in calls if "--service-type" in c]
        rc = self._run(str(src), dry_run=True, service_type="api")
        assert rc == baseline
        assert [c for c in calls if "--service-type" in c]

    def test_flags_are_wired(self):
        from nthlayer_generate.demo import build_parser

        args = build_parser().parse_args(
            ["migrate-manifest", "x.yaml", "--allow-lossy", "--service-type", "api"]
        )
        assert (args.allow_lossy, args.service_type) == (True, "api")
