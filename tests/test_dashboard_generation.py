"""Tests for Grafana dashboard generation."""

import json
import tempfile
from pathlib import Path

import pytest


@pytest.mark.skip(
    reason="Legacy tests - use test_hybrid_dashboard_builder.py for current functionality"
)
class TestDashboardCommand:
    """Tests for generate-dashboard CLI command."""

    def test_generates_dashboard_file(self):
        """Test that command generates dashboard JSON file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)

            service_file = tmpdir / "test-api.yaml"
            service_file.write_text("""
service:
  name: test-api
  team: platform
  tier: standard
  type: api

resources:
  - kind: SLO
    name: availability
    spec:
      objective: 99.9
            """)

            output_file = tmpdir / "dashboard.json"

            from nthlayer_generate.cli.dashboard import generate_dashboard_command

            result = generate_dashboard_command(
                str(service_file), output=str(output_file), environment=None, dry_run=False
            )

            assert result == 0
            assert output_file.exists()

            # Verify JSON is valid
            dashboard_data = json.loads(output_file.read_text())
            assert "dashboard" in dashboard_data
            assert dashboard_data["dashboard"]["title"] == "test-api - Service Dashboard"

    def test_dry_run_doesnt_write_file(self):
        """Test that dry-run mode doesn't create files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)

            service_file = tmpdir / "test-api.yaml"
            service_file.write_text("""
service:
  name: test-api
  team: platform
  tier: standard
  type: api
            """)

            output_file = tmpdir / "dashboard.json"

            from nthlayer_generate.cli.dashboard import generate_dashboard_command

            result = generate_dashboard_command(
                str(service_file), output=str(output_file), environment=None, dry_run=True
            )

            assert result == 0
            assert not output_file.exists()  # No file in dry-run mode

    def test_environment_aware_dashboard(self):
        """Test that dashboards include environment in variables."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)

            service_file = tmpdir / "test-api.yaml"
            service_file.write_text("""
service:
  name: test-api
  team: platform
  tier: standard
  type: api

resources:
  - kind: SLO
    name: availability
    spec:
      objective: 99.9
            """)

            env_dir = tmpdir / "environments"
            env_dir.mkdir()
            (env_dir / "prod.yaml").write_text("""
environment: prod
service:
  tier: critical
            """)

            output_file = tmpdir / "dashboard.json"

            from nthlayer_generate.cli.dashboard import generate_dashboard_command

            result = generate_dashboard_command(
                str(service_file), output=str(output_file), environment="prod", dry_run=False
            )

            assert result == 0

            # Check environment variable is included
            dashboard_data = json.loads(output_file.read_text())
            variables = dashboard_data["dashboard"].get("templating", {}).get("list", [])

            env_var = next((v for v in variables if v["name"] == "environment"), None)
            assert env_var is not None
            assert env_var["current"]["value"] == "prod"


@pytest.mark.skip(
    reason="Legacy tests - use test_hybrid_dashboard_builder.py for current functionality"
)
class TestVariableSubstitution:
    """Tests for variable substitution in dashboards."""

    def test_substitutes_env_in_dashboard(self):
        """Test that ${env} is substituted in dashboard generation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)

            service_file = tmpdir / "test-api.yaml"
            service_file.write_text("""
service:
  name: test-api-${env}
  team: platform
  tier: standard
  type: api

resources:
  - kind: SLO
    name: availability-${env}
    spec:
      objective: 99.9
      description: "SLO for ${env} environment"
            """)

            env_dir = tmpdir / "environments"
            env_dir.mkdir()
            (env_dir / "staging.yaml").write_text("environment: staging")

            output_file = tmpdir / "dashboard.json"

            from nthlayer_generate.cli.dashboard import generate_dashboard_command

            result = generate_dashboard_command(
                str(service_file), output=str(output_file), environment="staging", dry_run=False
            )

            assert result == 0

            dashboard_data = json.loads(output_file.read_text())
            db = dashboard_data["dashboard"]

            # Service name should be substituted
            assert "test-api-staging" in db["title"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
