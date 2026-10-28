"""Tests for CLI dashboard generation command."""

import json
from unittest.mock import patch

import pytest

from nthlayer_generate.cli.dashboard import generate_dashboard_command
from nthlayer_generate.dashboards.manifest_builder import build_dashboard_from_manifest

BUILDER = "nthlayer_generate.cli.dashboard.build_dashboard_from_manifest"

MINIMAL_SERVICE_YAML = """
service:
  name: test-api
  team: platform
  tier: standard
  type: api
"""

FULL_SERVICE_YAML = """
service:
  name: payment-api
  team: payments
  tier: critical
  type: api

resources:
  - kind: SLO
    name: availability
    spec:
      objective: 99.9
      window: 30d
  - kind: Dependencies
    name: databases
    spec:
      databases:
        - type: postgres
          instance: payments-db
"""


class TestGenerateDashboardCommand:
    """Tests for generate_dashboard_command."""

    def test_basic_dashboard_generation(self, tmp_path):
        """Test successful dashboard generation."""
        service_file = tmp_path / "service.yaml"
        service_file.write_text(MINIMAL_SERVICE_YAML)
        output_file = tmp_path / "dashboard.json"

        result = generate_dashboard_command(
            service_file=str(service_file),
            output=str(output_file),
        )

        assert result == 0
        assert output_file.exists()
        data = json.loads(output_file.read_text())
        assert "dashboard" in data

    def test_dry_run_mode(self, tmp_path, capsys):
        """Test dry run mode prints JSON and doesn't write file."""
        service_file = tmp_path / "service.yaml"
        service_file.write_text(MINIMAL_SERVICE_YAML)
        output_file = tmp_path / "dashboard.json"

        result = generate_dashboard_command(
            service_file=str(service_file),
            output=str(output_file),
            dry_run=True,
        )

        assert result == 0
        assert not output_file.exists()  # Dry run doesn't write file

        # Check output contains dashboard JSON
        captured = capsys.readouterr()
        assert "Dashboard JSON (dry run):" in captured.out
        # The JSON is printed to stdout
        assert '"dashboard"' in captured.out or "dashboard" in captured.out

    def test_full_panels_mode(self, tmp_path):
        """Test full panels mode includes all template panels."""
        service_file = tmp_path / "service.yaml"
        service_file.write_text(FULL_SERVICE_YAML)
        output_file = tmp_path / "dashboard.json"

        result = generate_dashboard_command(
            service_file=str(service_file),
            output=str(output_file),
            full_panels=True,
        )

        assert result == 0
        assert output_file.exists()

    def test_default_output_path(self, tmp_path, monkeypatch):
        """Test default output path when output not specified."""
        service_file = tmp_path / "service.yaml"
        service_file.write_text(MINIMAL_SERVICE_YAML)

        # Change to tmp_path so generated/ is created there
        monkeypatch.chdir(tmp_path)

        result = generate_dashboard_command(
            service_file=str(service_file),
            output=None,  # Use default
        )

        assert result == 0
        # Default path is generated/dashboards/{service}.json
        default_output = tmp_path / "generated" / "dashboards" / "test-api.json"
        assert default_output.exists()

    def test_quiet_mode(self, tmp_path, capsys):
        """Test quiet mode suppresses output."""
        service_file = tmp_path / "service.yaml"
        service_file.write_text(MINIMAL_SERVICE_YAML)
        output_file = tmp_path / "dashboard.json"

        result = generate_dashboard_command(
            service_file=str(service_file),
            output=str(output_file),
            quiet=True,
        )

        assert result == 0
        captured = capsys.readouterr()
        # Quiet mode should have minimal/no output
        assert "Generate Grafana Dashboard" not in captured.out

    def test_with_environment(self, tmp_path):
        """Test dashboard generation with environment parameter."""
        service_file = tmp_path / "service.yaml"
        service_file.write_text(MINIMAL_SERVICE_YAML)

        # Create environments directory
        env_dir = tmp_path / "environments"
        env_dir.mkdir()
        (env_dir / "prod.yaml").write_text("""
environment: prod
service:
  tier: critical
""")

        output_file = tmp_path / "dashboard.json"

        with patch(BUILDER, wraps=build_dashboard_from_manifest) as spy:
            result = generate_dashboard_command(
                service_file=str(service_file),
                output=str(output_file),
                environment="prod",
            )

        assert result == 0
        manifest = spy.call_args[0][0]
        # The environments/prod.yaml overlay was applied by load_manifest
        assert manifest.environment == "prod"
        assert manifest.tier == "critical"
        assert output_file.exists()

    def test_file_not_found_error(self, tmp_path):
        """Test error handling when service file doesn't exist."""
        service_file = tmp_path / "service.yaml"
        service_file.write_text(MINIMAL_SERVICE_YAML)

        with patch(
            BUILDER,
            side_effect=FileNotFoundError("Template file not found"),
        ):
            result = generate_dashboard_command(
                service_file=str(service_file),
                output=str(tmp_path / "dashboard.json"),
            )

        assert result == 1

    def test_yaml_error_during_build(self, tmp_path, capsys):
        """Test error handling for YAML error during build."""
        import yaml

        service_file = tmp_path / "service.yaml"
        service_file.write_text(MINIMAL_SERVICE_YAML)

        with patch(
            BUILDER,
            side_effect=yaml.YAMLError("Invalid YAML in template"),
        ):
            result = generate_dashboard_command(
                service_file=str(service_file),
                output=str(tmp_path / "dashboard.json"),
            )

        assert result == 1

    def test_missing_required_fields_error(self, tmp_path, capsys):
        """Test error handling for missing required fields during build."""
        service_file = tmp_path / "service.yaml"
        service_file.write_text(MINIMAL_SERVICE_YAML)

        with patch(
            BUILDER,
            side_effect=KeyError("required_field"),
        ):
            result = generate_dashboard_command(
                service_file=str(service_file),
                output=str(tmp_path / "dashboard.json"),
            )

        assert result == 1

    def test_oserror_handling(self, tmp_path):
        """Test handling of OSError during file operations."""
        service_file = tmp_path / "service.yaml"
        service_file.write_text(MINIMAL_SERVICE_YAML)

        # Use a directory that doesn't exist and can't be created
        with patch("pathlib.Path.mkdir", side_effect=OSError("Permission denied")):
            result = generate_dashboard_command(
                service_file=str(service_file),
                output="/root/forbidden/dashboard.json",
            )

        assert result == 1

    def test_value_error_handling(self, tmp_path):
        """Test handling of ValueError during processing."""
        service_file = tmp_path / "service.yaml"
        service_file.write_text(MINIMAL_SERVICE_YAML)

        with patch(
            BUILDER,
            side_effect=ValueError("Invalid service type"),
        ):
            result = generate_dashboard_command(
                service_file=str(service_file),
                output=str(tmp_path / "dashboard.json"),
            )

        assert result == 1

    def test_type_error_handling(self, tmp_path):
        """Test handling of TypeError during processing."""
        service_file = tmp_path / "service.yaml"
        service_file.write_text(MINIMAL_SERVICE_YAML)

        with patch(
            BUILDER,
            side_effect=TypeError("Invalid type"),
        ):
            result = generate_dashboard_command(
                service_file=str(service_file),
                output=str(tmp_path / "dashboard.json"),
            )

        assert result == 1

    def test_with_slos_and_dependencies(self, tmp_path):
        """Test dashboard generation with SLOs and dependencies."""
        service_file = tmp_path / "service.yaml"
        service_file.write_text(FULL_SERVICE_YAML)
        output_file = tmp_path / "dashboard.json"

        result = generate_dashboard_command(
            service_file=str(service_file),
            output=str(output_file),
        )

        assert result == 0
        data = json.loads(output_file.read_text())
        assert "dashboard" in data

    def test_builder_receives_loaded_manifest(self, tmp_path):
        """The command hands the loaded manifest and flags to the builder."""
        service_file = tmp_path / "service.yaml"
        service_file.write_text(FULL_SERVICE_YAML)
        output_file = tmp_path / "dashboard.json"

        with patch(BUILDER, wraps=build_dashboard_from_manifest) as spy:
            result = generate_dashboard_command(
                service_file=str(service_file),
                output=str(output_file),
                full_panels=True,
                prometheus_url="http://prom:9090",
            )

        assert result == 0
        spy.assert_called_once()
        manifest = spy.call_args[0][0]
        assert manifest.name == "payment-api"
        assert manifest.team == "payments"
        assert manifest.tier == "critical"
        assert [s.name for s in manifest.slos] == ["availability"]
        assert manifest.slos[0].target == 99.9
        assert [d.database_type for d in manifest.dependencies] == ["postgres"]
        assert spy.call_args[1] == {"full_panels": True, "prometheus_url": "http://prom:9090"}

    def test_written_file_is_builder_output(self, tmp_path):
        """The builder's dict is written verbatim as the dashboard JSON."""
        service_file = tmp_path / "service.yaml"
        service_file.write_text(MINIMAL_SERVICE_YAML)
        output_file = tmp_path / "dashboard.json"
        payload = {"dashboard": {"title": "T", "uid": "u", "panels": []}, "overwrite": True}

        with patch(BUILDER, return_value=payload):
            result = generate_dashboard_command(
                service_file=str(service_file),
                output=str(output_file),
            )

        assert result == 0
        assert json.loads(output_file.read_text()) == payload

    def test_manifest_load_error_handling(self, tmp_path):
        """A manifest the loader rejects (no team) exits 1 before building."""
        service_file = tmp_path / "service.yaml"
        # service.team is required by the legacy parser
        service_file.write_text("service:\n  name: test-api\n  tier: standard\n  type: api\n")
        output_file = tmp_path / "dashboard.json"

        with patch(BUILDER) as mock_build:
            result = generate_dashboard_command(
                service_file=str(service_file),
                output=str(output_file),
            )

        assert result == 1
        mock_build.assert_not_called()
        assert not output_file.exists()

    def test_invalid_tier_error_handling(self, tmp_path):
        """A tier outside critical/high/standard/low exits 1 before building."""
        service_file = tmp_path / "service.yaml"
        service_file.write_text(MINIMAL_SERVICE_YAML.replace("tier: standard", "tier: tier-1"))

        with patch(BUILDER) as mock_build:
            result = generate_dashboard_command(
                service_file=str(service_file),
                output=str(tmp_path / "dashboard.json"),
            )

        assert result == 1
        mock_build.assert_not_called()

    def test_output_directory_creation(self, tmp_path):
        """Test that output directory is created if it doesn't exist."""
        service_file = tmp_path / "service.yaml"
        service_file.write_text(MINIMAL_SERVICE_YAML)

        # Nested output path
        output_file = tmp_path / "deep" / "nested" / "path" / "dashboard.json"

        result = generate_dashboard_command(
            service_file=str(service_file),
            output=str(output_file),
        )

        assert result == 0
        assert output_file.exists()


# Malformed legacy resource specs: common's loader raises a bare AttributeError
# on each (opensrm-wo62.4.10), which must not escape as a traceback. What the
# legacy path did at 88057bb, probed:
# - dependencies-spec-str: ignored the spec and exited 0. Exit 1 is now
#   stricter, from common's loader, not from any rule of the legacy format.
# - databases-not-a-list, database-entry-str: rejected, exit 1.
# - slo-spec-int: crashed with AttributeError.
_MALFORMED = {
    "dependencies-spec-str": "  - kind: Dependencies\n    name: upstream\n    spec: oops\n",
    "databases-not-a-list": (
        "  - kind: Dependencies\n    name: upstream\n    spec:\n      databases: notalist\n"
    ),
    "database-entry-str": (
        "  - kind: Dependencies\n    name: upstream\n    spec:\n      databases: [pg]\n"
    ),
    "slo-spec-int": "  - kind: SLO\n    name: availability\n    spec: 5\n",
}


@pytest.mark.parametrize("resources", _MALFORMED.values(), ids=_MALFORMED.keys())
def test_malformed_legacy_spec_exits_1(resources, tmp_path):
    path = tmp_path / "bad-service.yaml"
    path.write_text(
        "service:\n  name: bad-service\n  team: platform\n  tier: standard\n  type: api\n"
        "resources:\n" + resources
    )

    assert generate_dashboard_command(str(path), output=str(tmp_path / "d.json")) == 1
