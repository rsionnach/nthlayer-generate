"""Tests for cli/generate_loki.py.

Tests for Loki LogQL alert generation CLI command.
"""

import argparse
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from nthlayer_generate.cli.generate_loki import (
    generate_loki_command,
    handle_loki_command,
    register_loki_parser,
)

# generate_loki_command imports these inside the function body, so they are
# looked up on their source modules at call time -- patch them there.
GENERATOR_CLASS = "nthlayer_generate.loki.LokiAlertGenerator"
LOAD_MANIFEST = "nthlayer_common.manifest.load_manifest"


@pytest.fixture
def service_with_dependencies():
    """Create legacy-format service YAML with database dependencies.

    Tier must be one of nthlayer-common's TIER_NAMES (critical, high,
    standard, low); Dependencies.spec.databases entries carry name + type.
    """
    return """
service:
  name: payment-api
  team: payments-team
  tier: critical
  type: api
resources:
  - kind: Dependencies
    name: upstream
    spec:
      databases:
        - name: payments-db
          type: postgres
        - name: payments-cache
          type: redis
"""


@pytest.fixture
def simple_service():
    """Create simple service YAML without dependencies."""
    return """
service:
  name: simple-api
  team: simple-team
  tier: standard
  type: api
"""


def _mock_generator(alerts, ruler_yaml="groups: []"):
    generator = MagicMock()
    generator.generate_from_manifest.return_value = alerts
    generator.to_ruler_yaml.return_value = ruler_yaml
    return generator


def _alerts(service=0, dependency=0):
    alerts = []
    for _ in range(service):
        alert = MagicMock()
        alert.category = "service"
        alerts.append(alert)
    for _ in range(dependency):
        alert = MagicMock()
        alert.category = "dependency"
        alerts.append(alert)
    return alerts


class TestGenerateLokiCommand:
    """Tests for generate_loki_command function."""

    def test_missing_service_file(self):
        """Test with non-existent service file."""
        result = generate_loki_command("/nonexistent/service.yaml")

        assert result == 1

    def test_invalid_yaml(self):
        """Test with invalid YAML file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            bad_file = Path(tmpdir) / "bad.yaml"
            bad_file.write_text("not: valid: yaml: {{")

            with patch(GENERATOR_CLASS) as mock_generator_class:
                result = generate_loki_command(str(bad_file))

        assert result == 1
        mock_generator_class.return_value.generate_from_manifest.assert_not_called()

    def test_invalid_tier(self, service_with_dependencies):
        """A tier outside critical/high/standard/low exits 1 before generating."""
        with tempfile.TemporaryDirectory() as tmpdir:
            service_file = Path(tmpdir) / "service.yaml"
            service_file.write_text(service_with_dependencies.replace("critical", "tier-1"))

            with patch(GENERATOR_CLASS) as mock_generator_class:
                result = generate_loki_command(str(service_file), dry_run=True)

        assert result == 1
        mock_generator_class.return_value.generate_from_manifest.assert_not_called()

    def test_dry_run(self, service_with_dependencies, tmp_path, monkeypatch):
        """Dry run renders ruler YAML from the loaded manifest and writes nothing."""
        monkeypatch.chdir(tmp_path)
        mock_generator = _mock_generator(_alerts(service=1, dependency=1))
        service_file = tmp_path / "service.yaml"
        service_file.write_text(service_with_dependencies)

        with patch(GENERATOR_CLASS, return_value=mock_generator):
            result = generate_loki_command(str(service_file), dry_run=True)

        assert result == 0
        mock_generator.generate_from_manifest.assert_called_once()
        manifest = mock_generator.generate_from_manifest.call_args[0][0]
        assert manifest.name == "payment-api"
        assert manifest.tier == "critical"
        assert manifest.team == "payments-team"
        assert [d.database_type for d in manifest.dependencies] == ["postgres", "redis"]
        mock_generator.to_ruler_yaml.assert_called_once()
        assert mock_generator.to_ruler_yaml.call_args[1] == {"group_name": "payment-api"}
        mock_generator.write_ruler_file.assert_not_called()
        assert not (tmp_path / "generated").exists()

    def test_generate_with_output(self, service_with_dependencies, tmp_path):
        """Real generator writes a parseable Loki ruler file at --output."""
        service_file = tmp_path / "service.yaml"
        service_file.write_text(service_with_dependencies)
        output_file = tmp_path / "alerts.yaml"

        result = generate_loki_command(str(service_file), output=str(output_file))

        assert result == 0
        data = yaml.safe_load(output_file.read_text())
        assert [g["name"] for g in data["groups"]] == ["payment-api"]
        rules = data["groups"][0]["rules"]
        sources = {r["labels"]["source"] for r in rules}
        assert sources == {"service", "dependency"}
        technologies = {r["labels"]["technology"] for r in rules}
        assert {"postgres", "redis"} <= technologies
        for rule in rules:
            assert rule["labels"]["service"] == "payment-api"
            assert rule["labels"]["tier"] == "critical"
            assert rule["labels"]["team"] == "payments-team"

    def test_generate_default_output_path(self, service_with_dependencies, tmp_path, monkeypatch):
        """Without --output, the file goes to generated/{service}/loki-alerts.yaml."""
        monkeypatch.chdir(tmp_path)
        service_file = tmp_path / "service.yaml"
        service_file.write_text(service_with_dependencies)

        result = generate_loki_command(str(service_file))

        assert result == 0
        default_output = tmp_path / "generated" / "payment-api" / "loki-alerts.yaml"
        data = yaml.safe_load(default_output.read_text())
        assert [g["name"] for g in data["groups"]] == ["payment-api"]

    def test_no_dependencies(self, simple_service, tmp_path):
        """A service with no dependencies yields only service-sourced alerts."""
        service_file = tmp_path / "service.yaml"
        service_file.write_text(simple_service)
        output_file = tmp_path / "alerts.yaml"

        result = generate_loki_command(str(service_file), output=str(output_file))

        assert result == 0
        rules = yaml.safe_load(output_file.read_text())["groups"][0]["rules"]
        assert rules
        assert {r["labels"]["source"] for r in rules} == {"service"}
        assert {r["labels"]["tier"] for r in rules} == {"standard"}

    def test_dry_run_large_output(self, service_with_dependencies):
        """Test dry run with large YAML output (truncated)."""
        mock_generator = _mock_generator([], ruler_yaml="x" * 3000)

        with tempfile.TemporaryDirectory() as tmpdir:
            service_file = Path(tmpdir) / "service.yaml"
            service_file.write_text(service_with_dependencies)

            with patch(GENERATOR_CLASS, return_value=mock_generator):
                result = generate_loki_command(str(service_file), dry_run=True)

        assert result == 0
        mock_generator.to_ruler_yaml.assert_called_once()
        mock_generator.write_ruler_file.assert_not_called()

    def test_exception_handling(self, service_with_dependencies):
        """Test handling of exceptions during manifest loading."""
        with tempfile.TemporaryDirectory() as tmpdir:
            service_file = Path(tmpdir) / "service.yaml"
            service_file.write_text(service_with_dependencies)

            with (
                patch(LOAD_MANIFEST, side_effect=ValueError("Invalid service configuration")),
                patch(GENERATOR_CLASS) as mock_generator_class,
            ):
                result = generate_loki_command(str(service_file))

        assert result == 1
        mock_generator_class.return_value.generate_from_manifest.assert_not_called()

    def test_alert_breakdown(self, service_with_dependencies):
        """The full alert list is handed to the ruler YAML renderer."""
        alerts = _alerts(service=3, dependency=5)
        mock_generator = _mock_generator(alerts)

        with tempfile.TemporaryDirectory() as tmpdir:
            service_file = Path(tmpdir) / "service.yaml"
            service_file.write_text(service_with_dependencies)

            with patch(GENERATOR_CLASS, return_value=mock_generator):
                result = generate_loki_command(str(service_file), dry_run=True)

        assert result == 0
        assert mock_generator.to_ruler_yaml.call_args[0][0] == alerts

    def test_no_team(self, tmp_path):
        """A service without a team is rejected by the loader (team is required)."""
        service_file = tmp_path / "service.yaml"
        service_file.write_text("service:\n  name: orphan-api\n  tier: standard\n  type: api\n")

        with patch(GENERATOR_CLASS) as mock_generator_class:
            result = generate_loki_command(str(service_file), dry_run=True)

        assert result == 1
        mock_generator_class.return_value.generate_from_manifest.assert_not_called()


class TestRegisterLokiParser:
    """Tests for register_loki_parser function."""

    def test_register_parser(self):
        """Test parser registration."""
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers()

        register_loki_parser(subparsers)

        # Parse a test command
        args = parser.parse_args(["generate-loki-alerts", "test.yaml"])
        assert args.service_file == "test.yaml"
        assert args.output is None
        assert args.dry_run is False

    def test_register_parser_with_options(self):
        """Test parser registration with all options."""
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers()

        register_loki_parser(subparsers)

        # Parse with all options
        args = parser.parse_args(
            [
                "generate-loki-alerts",
                "test.yaml",
                "--output",
                "output.yaml",
                "--dry-run",
            ]
        )
        assert args.service_file == "test.yaml"
        assert args.output == "output.yaml"
        assert args.dry_run is True

    def test_register_parser_short_options(self):
        """Test parser registration with short options."""
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers()

        register_loki_parser(subparsers)

        # Parse with short options
        args = parser.parse_args(
            [
                "generate-loki-alerts",
                "test.yaml",
                "-o",
                "output.yaml",
            ]
        )
        assert args.output == "output.yaml"


class TestHandleLokiCommand:
    """Tests for handle_loki_command function."""

    @patch("nthlayer_generate.cli.generate_loki.generate_loki_command")
    def test_handle_command(self, mock_generate):
        """Test handle_loki_command."""
        mock_generate.return_value = 0

        args = MagicMock()
        args.service_file = "test.yaml"
        args.output = "output.yaml"
        args.dry_run = True

        result = handle_loki_command(args)

        assert result == 0
        mock_generate.assert_called_once_with(
            service_file="test.yaml",
            output="output.yaml",
            dry_run=True,
        )

    @patch("nthlayer_generate.cli.generate_loki.generate_loki_command")
    def test_handle_command_missing_attrs(self, mock_generate):
        """Test handle_loki_command with missing optional attrs."""
        mock_generate.return_value = 0

        args = MagicMock(spec=["service_file"])  # Only service_file attr
        args.service_file = "test.yaml"

        result = handle_loki_command(args)

        assert result == 0
        mock_generate.assert_called_once_with(
            service_file="test.yaml",
            output=None,
            dry_run=False,
        )
