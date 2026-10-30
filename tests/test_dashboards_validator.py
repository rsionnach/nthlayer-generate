"""Tests for dashboards/validator.py.

Tests for dashboard validation logic including ValidationResult,
DashboardValidator, and extraction functions.
"""

from unittest.mock import MagicMock, patch

from nthlayer_generate.dashboards.resolver import ResolutionStatus
from nthlayer_generate.dashboards.validator import (
    DashboardValidator,
    IntentResult,
    ValidationResult,
)


class TestIntentResult:
    """Tests for IntentResult dataclass."""

    def test_create_resolved_intent(self):
        """Test creating a resolved intent result."""
        result = IntentResult(
            name="postgresql.connections.active",
            status=ResolutionStatus.RESOLVED,
            metric_name="pg_stat_activity_count",
        )

        assert result.name == "postgresql.connections.active"
        assert result.status == ResolutionStatus.RESOLVED
        assert result.metric_name == "pg_stat_activity_count"
        assert result.message is None
        assert result.synthesis_expr is None

    def test_create_unresolved_intent(self):
        """Test creating an unresolved intent result."""
        result = IntentResult(
            name="postgresql.missing",
            status=ResolutionStatus.UNRESOLVED,
            message="No matching metric found",
        )

        assert result.name == "postgresql.missing"
        assert result.status == ResolutionStatus.UNRESOLVED
        assert result.metric_name is None
        assert result.message == "No matching metric found"

    def test_create_synthesized_intent(self):
        """Test creating a synthesized intent result."""
        result = IntentResult(
            name="postgresql.rate",
            status=ResolutionStatus.SYNTHESIZED,
            metric_name="synthesized_rate",
            synthesis_expr="rate(pg_total[5m])",
        )

        assert result.status == ResolutionStatus.SYNTHESIZED
        assert result.synthesis_expr == "rate(pg_total[5m])"


class TestValidationResult:
    """Tests for ValidationResult dataclass."""

    def test_empty_result(self):
        """Test empty validation result."""
        result = ValidationResult()

        assert result.total == 0
        assert result.resolved_count == 0
        assert result.has_unresolved is False
        assert result.get_exit_code(has_prometheus=True) == 0

    def test_total_property(self):
        """Test total property calculation."""
        result = ValidationResult(
            resolved=[IntentResult(name="r1", status=ResolutionStatus.RESOLVED)],
            fallback=[IntentResult(name="f1", status=ResolutionStatus.FALLBACK)],
            unresolved=[IntentResult(name="u1", status=ResolutionStatus.UNRESOLVED)],
            custom=[IntentResult(name="c1", status=ResolutionStatus.CUSTOM)],
            synthesized=[IntentResult(name="s1", status=ResolutionStatus.SYNTHESIZED)],
        )

        assert result.total == 5

    def test_resolved_count_includes_synthesized(self):
        """Test resolved_count includes synthesized intents."""
        result = ValidationResult(
            resolved=[
                IntentResult(name="r1", status=ResolutionStatus.RESOLVED),
                IntentResult(name="r2", status=ResolutionStatus.RESOLVED),
            ],
            synthesized=[
                IntentResult(name="s1", status=ResolutionStatus.SYNTHESIZED),
            ],
        )

        assert result.resolved_count == 3

    def test_has_unresolved(self):
        """Test has_unresolved property."""
        result = ValidationResult(
            resolved=[IntentResult(name="r1", status=ResolutionStatus.RESOLVED)],
            unresolved=[IntentResult(name="u1", status=ResolutionStatus.UNRESOLVED)],
        )

        assert result.has_unresolved is True

    def test_get_exit_code_success(self):
        """Test exit code 0 for successful validation."""
        result = ValidationResult(
            resolved=[IntentResult(name="r1", status=ResolutionStatus.RESOLVED)],
        )

        assert result.get_exit_code(has_prometheus=True) == 0
        assert result.get_exit_code(has_prometheus=False) == 0

    def test_get_exit_code_unresolved_with_prometheus(self):
        """Test exit code 2 for unresolved with prometheus."""
        result = ValidationResult(
            unresolved=[IntentResult(name="u1", status=ResolutionStatus.UNRESOLVED)],
        )

        assert result.get_exit_code(has_prometheus=True) == 2

    def test_get_exit_code_unresolved_without_prometheus(self):
        """Test exit code 0 for unresolved without prometheus."""
        result = ValidationResult(
            unresolved=[IntentResult(name="u1", status=ResolutionStatus.UNRESOLVED)],
        )

        assert result.get_exit_code(has_prometheus=False) == 0


class TestDashboardValidator:
    """Tests for DashboardValidator class."""

    def test_init_with_url(self):
        """Test validator initialization with URL."""
        validator = DashboardValidator(prometheus_url="http://prometheus:9090")

        assert validator.prometheus_url == "http://prometheus:9090"

    def test_init_without_url(self):
        """Test validator initialization without URL."""
        validator = DashboardValidator()

        assert validator.prometheus_url is None

    @patch("nthlayer_generate.dashboards.validator.create_resolver")
    @patch("nthlayer_generate.dashboards.validator.get_intents_for_technology")
    def test_validate_without_prometheus(self, mock_get_intents, mock_create_resolver):
        """Test validation without prometheus URL."""
        mock_resolver = MagicMock()
        mock_resolution = MagicMock()
        mock_resolution.status = ResolutionStatus.UNRESOLVED
        mock_resolution.metric_name = None
        mock_resolution.message = "No discovery"
        mock_resolver.resolve.return_value = mock_resolution
        mock_create_resolver.return_value = mock_resolver

        mock_get_intents.return_value = {"postgresql.test": MagicMock()}

        validator = DashboardValidator()
        result = validator.validate(
            service_name="test-service",
            technologies={"postgresql"},
        )

        assert result.discovery_count == 0
        mock_resolver.discover_for_service.assert_not_called()

    @patch("nthlayer_generate.dashboards.validator.create_resolver")
    @patch("nthlayer_generate.dashboards.validator.get_intents_for_technology")
    def test_validate_with_prometheus_discovery(self, mock_get_intents, mock_create_resolver):
        """Test validation with prometheus discovery."""
        mock_resolver = MagicMock()
        mock_resolver.discover_for_service.return_value = 50
        mock_resolution = MagicMock()
        mock_resolution.status = ResolutionStatus.RESOLVED
        mock_resolution.metric_name = "pg_test"
        mock_resolution.message = None
        mock_resolver.resolve.return_value = mock_resolution
        mock_create_resolver.return_value = mock_resolver

        mock_get_intents.return_value = {"postgresql.test": MagicMock()}

        validator = DashboardValidator(prometheus_url="http://prometheus:9090")
        result = validator.validate(
            service_name="test-service",
            technologies={"postgresql"},
        )

        assert result.discovery_count == 50
        mock_resolver.discover_for_service.assert_called_once_with("test-service")

    @patch("nthlayer_generate.dashboards.validator.create_resolver")
    @patch("nthlayer_generate.dashboards.validator.get_intents_for_technology")
    def test_validate_discovery_error(self, mock_get_intents, mock_create_resolver):
        """Test validation handles discovery errors."""
        mock_resolver = MagicMock()
        mock_resolver.discover_for_service.side_effect = ConnectionError("Connection refused")
        mock_create_resolver.return_value = mock_resolver

        mock_get_intents.return_value = {}

        validator = DashboardValidator(prometheus_url="http://prometheus:9090")
        result = validator.validate(
            service_name="test-service",
            technologies={"postgresql"},
        )

        assert result.discovery_error == "Connection refused"

    @patch("nthlayer_generate.dashboards.validator.create_resolver")
    @patch(
        "nthlayer_generate.dashboards.validator.ALL_INTENTS",
        {"intent.one": MagicMock(), "intent.two": MagicMock()},
    )
    def test_validate_all_intents(self, mock_create_resolver):
        """Test validating all intents."""
        mock_resolver = MagicMock()
        mock_resolution = MagicMock()
        mock_resolution.status = ResolutionStatus.RESOLVED
        mock_resolution.metric_name = "test"
        mock_resolution.message = None
        mock_resolver.resolve.return_value = mock_resolution
        mock_create_resolver.return_value = mock_resolver

        validator = DashboardValidator()
        result = validator.validate(
            service_name="test-service",
            technologies=set(),
            validate_all=True,
        )

        assert result.total == 2

    @patch("nthlayer_generate.dashboards.validator.create_resolver")
    @patch("nthlayer_generate.dashboards.validator.get_intents_for_technology")
    def test_validate_categorizes_results(self, mock_get_intents, mock_create_resolver):
        """Test that validation categorizes results correctly."""
        mock_resolver = MagicMock()

        # Create different resolution types using startswith for exact matching
        def mock_resolve(intent_name):
            resolution = MagicMock()
            if intent_name.startswith("ok."):
                resolution.status = ResolutionStatus.RESOLVED
            elif intent_name.startswith("custom."):
                resolution.status = ResolutionStatus.CUSTOM
            elif intent_name.startswith("fallback."):
                resolution.status = ResolutionStatus.FALLBACK
            elif intent_name.startswith("synth."):
                resolution.status = ResolutionStatus.SYNTHESIZED
            else:
                resolution.status = ResolutionStatus.UNRESOLVED
            resolution.metric_name = f"metric_{intent_name}"
            resolution.message = None
            return resolution

        mock_resolver.resolve.side_effect = mock_resolve
        mock_create_resolver.return_value = mock_resolver

        mock_get_intents.return_value = {
            "ok.intent": MagicMock(),
            "custom.intent": MagicMock(),
            "fallback.intent": MagicMock(),
            "synth.intent": MagicMock(),
            "missing.intent": MagicMock(),
        }

        validator = DashboardValidator()
        result = validator.validate(
            service_name="test-service",
            technologies={"test"},
        )

        assert len(result.resolved) == 1
        assert len(result.custom) == 1
        assert len(result.fallback) == 1
        assert len(result.synthesized) == 1
        assert len(result.unresolved) == 1

    @patch("nthlayer_generate.dashboards.validator.create_resolver")
    @patch("nthlayer_generate.dashboards.validator.get_intents_for_technology")
    def test_validate_with_custom_overrides(self, mock_get_intents, mock_create_resolver):
        """Test validation passes custom overrides to resolver."""
        mock_resolver = MagicMock()
        mock_create_resolver.return_value = mock_resolver
        mock_get_intents.return_value = {}

        validator = DashboardValidator()
        custom_overrides = {"postgresql.connections": "custom_metric"}

        validator.validate(
            service_name="test-service",
            technologies=set(),
            custom_overrides=custom_overrides,
        )

        mock_create_resolver.assert_called_once_with(
            prometheus_url=None,
            custom_overrides=custom_overrides,
        )
