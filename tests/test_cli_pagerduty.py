"""Tests for cli/pagerduty.py.

Tests for PagerDuty setup CLI command.

Fixtures are real YAML loaded by nthlayer-common's ``load_manifest``:
legacy shapes follow examples/services/payment-api-pagerduty-demo.yaml
(``service: {name, team, tier, type}`` plus a ``kind: PagerDuty`` resource,
read by parser/loader.py ``_extract_ownership``); the srm/v1 shape follows
examples/opensrm/api-critical.reliability.yaml (``spec.ownership.pagerduty``).
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from nthlayer_common.manifest import load_manifest

from nthlayer_generate.cli.pagerduty import setup_pagerduty_command

SERVICE_WITH_PAGERDUTY = """
service:
  name: payment-api
  team: payments-team
  tier: critical
  type: api
resources:
  - kind: PagerDuty
    name: primary
    spec:
      escalation_policy: platform-oncall
      urgency: high
"""

SERVICE_WITHOUT_PAGERDUTY = """
service:
  name: simple-api
  team: simple-team
  tier: standard
  type: api
"""

SERVICE_WITH_FULL_PAGERDUTY = """
service:
  name: critical-api
  team: platform-team
  tier: critical
  type: api
resources:
  - kind: PagerDuty
    name: primary
    spec:
      escalation_policy: platform-oncall
      urgency: low
      auto_resolve_timeout: 14400
      create_escalation_policy:
        name: auto-created-policy
        users:
          - user@example.com
"""

# Overlay shape: examples/environments/payment-api-prod.yaml (a PagerDuty
# resource merged by (kind, name) onto the base, parser/legacy.py).
STAGING_OVERLAY = """
environment: staging
resources:
  - kind: PagerDuty
    name: primary
    spec:
      escalation_policy: staging-oncall
      urgency: low
"""

SRM_V1_WITH_PAGERDUTY = """
apiVersion: srm/v1
kind: ServiceReliabilityManifest
metadata:
  name: payment-api
  team: payments
  tier: critical
spec:
  type: api
  ownership:
    team: payments
    escalation: payments-escalation
    pagerduty:
      service_id: P123ABC
      escalation_policy_id: P456DEF
"""


@pytest.fixture
def write_service(tmp_path):
    def _write(content: str, name: str = "service.yaml") -> Path:
        path = tmp_path / name
        path.write_text(content)
        return path

    return _write


def _mock_client(mock_client_cls, **result_fields) -> MagicMock:
    """Wire a PagerDutyClient mock whose setup_service returns a result."""
    fields = {
        "success": True,
        "created_service": True,
        "service_id": "PSERVICE1",
        "service_url": "https://pd.example.com/services/PSERVICE1",
        "created_escalation_policy": False,
        "escalation_policy_id": None,
        "team_id": None,
        "created_team": False,
        "warnings": [],
    }
    fields.update(result_fields)
    mock_result = MagicMock(**fields)
    mock_instance = MagicMock()
    mock_instance.setup_service.return_value = mock_result
    mock_instance.__enter__ = MagicMock(return_value=mock_instance)
    mock_instance.__exit__ = MagicMock(return_value=False)
    mock_client_cls.return_value = mock_instance
    return mock_instance


class TestSetupPagerDutyCommand:
    """Tests for setup_pagerduty_command function."""

    def test_missing_api_key(self, write_service):
        """Test when no API key is provided."""
        service_file = write_service(SERVICE_WITH_PAGERDUTY)

        with patch.dict("os.environ", {}, clear=True):
            with patch("nthlayer_generate.cli.pagerduty.load_manifest") as mock_load:
                result = setup_pagerduty_command(str(service_file))

        assert result == 1
        # Fails on the key check, before the manifest is read.
        mock_load.assert_not_called()

    @patch("nthlayer_generate.cli.pagerduty.PagerDutyClient")
    def test_api_key_from_env(self, mock_client, write_service):
        """Test API key from environment variable."""
        _mock_client(mock_client)
        service_file = write_service(SERVICE_WITH_PAGERDUTY)

        with patch.dict("os.environ", {"PAGERDUTY_API_KEY": "test-key"}):
            result = setup_pagerduty_command(str(service_file))

        assert result == 0
        mock_client.assert_called_once_with("test-key")

    def test_missing_service_file(self):
        """Test with non-existent service file."""
        result = setup_pagerduty_command(
            "/nonexistent/service.yaml",
            api_key="test-key",
        )

        assert result == 1

    def test_invalid_yaml(self, write_service):
        """Test with invalid YAML file."""
        bad_file = write_service("not: valid: yaml: {{", name="bad.yaml")

        result = setup_pagerduty_command(str(bad_file), api_key="test-key")

        assert result == 1

    @patch("nthlayer_generate.cli.pagerduty.PagerDutyClient")
    def test_no_pagerduty_resource(self, mock_client, write_service):
        """Test with service that has no PagerDuty resource."""
        service_file = write_service(SERVICE_WITHOUT_PAGERDUTY)
        # The fixture is a valid manifest, so exit 1 is the missing
        # PagerDuty resource and not a load failure.
        ownership = load_manifest(service_file, suppress_deprecation_warning=True).ownership
        assert ownership is not None
        assert ownership.pagerduty is None

        result = setup_pagerduty_command(str(service_file), api_key="test-key")

        assert result == 1
        mock_client.assert_not_called()

    @patch("nthlayer_generate.cli.pagerduty.PagerDutyClient")
    def test_dry_run(self, mock_client, write_service):
        """Test dry run mode."""
        service_file = write_service(SERVICE_WITH_PAGERDUTY)

        result = setup_pagerduty_command(
            str(service_file),
            api_key="test-key",
            dry_run=True,
        )

        assert result == 0
        mock_client.assert_not_called()

    @patch("nthlayer_generate.cli.pagerduty.PagerDutyClient")
    def test_dry_run_with_environment(self, mock_client, write_service):
        """Test dry run mode with environment specified."""
        service_file = write_service(SERVICE_WITH_PAGERDUTY)

        result = setup_pagerduty_command(
            str(service_file),
            api_key="test-key",
            environment="production",
            dry_run=True,
        )

        assert result == 0
        mock_client.assert_not_called()

    @patch("nthlayer_generate.cli.pagerduty.PagerDutyClient")
    def test_successful_setup_new_service(self, mock_client, write_service):
        """Test successful setup creating new service."""
        mock_instance = _mock_client(mock_client)
        service_file = write_service(SERVICE_WITH_PAGERDUTY)

        result = setup_pagerduty_command(str(service_file), api_key="test-key")

        assert result == 0
        mock_instance.setup_service.assert_called_once_with(
            service_name="payment-api",
            team_name="payments-team",
            escalation_policy_name="platform-oncall",
            # Legacy: common stores the policy NAME in escalation_policy_id,
            # so the command must not pass it on as an ID.
            escalation_policy_id=None,
            urgency="high",
            auto_resolve_timeout=None,
            create_escalation_policy_config=None,
        )

    @patch("nthlayer_generate.cli.pagerduty.PagerDutyClient")
    def test_successful_setup_existing_service(self, mock_client, write_service):
        """Test successful setup with existing service."""
        mock_instance = _mock_client(mock_client, created_service=False, team_id="PTEAM1")
        service_file = write_service(SERVICE_WITH_PAGERDUTY)

        result = setup_pagerduty_command(str(service_file), api_key="test-key")

        assert result == 0
        mock_instance.setup_service.assert_called_once()

    @patch("nthlayer_generate.cli.pagerduty.PagerDutyClient")
    def test_setup_creates_escalation_policy(self, mock_client, write_service):
        """Test setup that creates escalation policy."""
        mock_instance = _mock_client(
            mock_client,
            created_escalation_policy=True,
            escalation_policy_id="PPOLICY1",
            team_id="PTEAM1",
            created_team=True,
        )
        service_file = write_service(SERVICE_WITH_FULL_PAGERDUTY)

        result = setup_pagerduty_command(str(service_file), api_key="test-key")

        assert result == 0
        kwargs = mock_instance.setup_service.call_args.kwargs
        assert kwargs["create_escalation_policy_config"] == {
            "name": "auto-created-policy",
            "users": ["user@example.com"],
        }
        assert kwargs["urgency"] == "low"
        assert kwargs["auto_resolve_timeout"] == 14400
        assert kwargs["service_name"] == "critical-api"
        assert kwargs["team_name"] == "platform-team"

    @patch("nthlayer_generate.cli.pagerduty.PagerDutyClient")
    def test_urgency_defaults_to_high(self, mock_client, write_service):
        """A PagerDuty resource without urgency is set up as high urgency."""
        mock_instance = _mock_client(mock_client)
        service_file = write_service(SERVICE_WITH_PAGERDUTY.replace("      urgency: high\n", ""))

        result = setup_pagerduty_command(str(service_file), api_key="test-key")

        assert result == 0
        assert mock_instance.setup_service.call_args.kwargs["urgency"] == "high"

    @patch("nthlayer_generate.cli.pagerduty.PagerDutyClient")
    def test_srm_v1_passes_escalation_policy_id(self, mock_client, write_service):
        """srm/v1 carries a real policy ID, passed alongside the policy name.

        The fixture without service_id: a declared service_id is refused
        (test_declared_service_id_is_refused). Derived from
        examples/opensrm/api-critical.reliability.yaml's ownership block.
        """
        mock_instance = _mock_client(mock_client)
        service_file = write_service(
            SRM_V1_WITH_PAGERDUTY.replace("      service_id: P123ABC\n", ""),
            name="payment-api.reliability.yaml",
        )

        result = setup_pagerduty_command(str(service_file), api_key="test-key")

        assert result == 0
        kwargs = mock_instance.setup_service.call_args.kwargs
        assert kwargs["service_name"] == "payment-api"
        assert kwargs["team_name"] == "payments"
        assert kwargs["escalation_policy_name"] == "payments-escalation"
        assert kwargs["escalation_policy_id"] == "P456DEF"
        assert kwargs["urgency"] == "high"
        assert kwargs["create_escalation_policy_config"] is None

    @patch("nthlayer_generate.cli.pagerduty.PagerDutyClient")
    def test_setup_failure(self, mock_client, write_service):
        """Test setup that fails."""
        _mock_client(mock_client, success=False, error="Escalation policy not found")
        service_file = write_service(SERVICE_WITH_PAGERDUTY)

        result = setup_pagerduty_command(str(service_file), api_key="test-key")

        assert result == 1

    @patch("nthlayer_generate.cli.pagerduty.PagerDutyClient")
    def test_setup_with_warnings(self, mock_client, write_service):
        """Test setup that succeeds with warnings."""
        mock_instance = _mock_client(
            mock_client, warnings=["Team not found, using default", "Integration key reused"]
        )
        service_file = write_service(SERVICE_WITH_PAGERDUTY)

        result = setup_pagerduty_command(str(service_file), api_key="test-key")

        assert result == 0
        mock_instance.setup_service.assert_called_once()

    @patch("nthlayer_generate.cli.pagerduty.PagerDutyClient")
    def test_unexpected_exception(self, mock_client, write_service):
        """Test handling of unexpected exceptions."""
        mock_client.side_effect = RuntimeError("Connection failed")
        service_file = write_service(SERVICE_WITH_PAGERDUTY)

        result = setup_pagerduty_command(str(service_file), api_key="test-key")

        assert result == 1

    @patch("nthlayer_generate.cli.pagerduty.PagerDutyClient")
    def test_setup_with_environment(self, mock_client, write_service, tmp_path):
        """The environment overlay's PagerDuty spec reaches setup_service."""
        mock_instance = _mock_client(mock_client)
        service_file = write_service(SERVICE_WITH_PAGERDUTY)
        (tmp_path / "environments").mkdir()
        (tmp_path / "environments" / "staging.yaml").write_text(STAGING_OVERLAY)

        result = setup_pagerduty_command(
            str(service_file),
            api_key="test-key",
            environment="staging",
        )

        assert result == 0
        kwargs = mock_instance.setup_service.call_args.kwargs
        assert kwargs["escalation_policy_name"] == "staging-oncall"
        assert kwargs["urgency"] == "low"

    @patch("nthlayer_generate.cli.pagerduty.PagerDutyClient")
    def test_setup_creates_team(self, mock_client, write_service):
        """Test setup that creates a new team."""
        mock_instance = _mock_client(mock_client, team_id="PTEAM1", created_team=True)
        service_file = write_service(SERVICE_WITH_PAGERDUTY)

        result = setup_pagerduty_command(str(service_file), api_key="test-key")

        assert result == 0
        assert mock_instance.setup_service.call_args.kwargs["team_name"] == "payments-team"


@pytest.mark.parametrize("dry_run", [False, True], ids=["live", "dry-run"])
@patch("nthlayer_generate.cli.pagerduty.PagerDutyClient")
def test_declared_service_id_is_refused(mock_client, dry_run):
    """examples/opensrm/api-critical.reliability.yaml declares service_id
    P123ABC. setup_service finds services by name and creates one when that
    misses, so it could duplicate the declared service. Rob, 2026-10-29:
    refuse, before any client is built."""
    path = (
        Path(__file__).resolve().parents[1]
        / "examples"
        / "opensrm"
        / "api-critical.reliability.yaml"
    )

    assert setup_pagerduty_command(str(path), api_key="test-key", dry_run=dry_run) == 1
    mock_client.assert_not_called()
