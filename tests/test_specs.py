"""Tests for service specification parsing and validation."""

import pytest

from nthlayer_generate.specs.models import Resource, ServiceContext
from nthlayer_generate.specs.validator import validate_service_file


class TestServiceContext:
    """Test ServiceContext model."""

    def test_create_service_context(self):
        """Test creating service context with required fields."""
        ctx = ServiceContext(
            name="payment-api",
            team="payments",
            tier="critical",
            type="api",
        )

        assert ctx.name == "payment-api"
        assert ctx.team == "payments"
        assert ctx.tier == "critical"
        assert ctx.type == "api"

    def test_service_context_to_dict(self):
        """Test converting service context to dict for templates."""
        ctx = ServiceContext(
            name="payment-api",
            team="payments",
            tier="critical",
            type="api",
            language="java",
        )

        d = ctx.to_dict()

        assert d["service"] == "payment-api"
        assert d["team"] == "payments"
        assert d["tier"] == "critical"
        assert d["type"] == "api"
        assert d["language"] == "java"

    def test_service_context_requires_fields(self):
        """Test that required fields are validated."""
        with pytest.raises(ValueError, match="Service name is required"):
            ServiceContext(name="", team="team", tier="critical", type="api")


class TestResource:
    """Test Resource model."""

    def test_create_resource(self):
        """Test creating resource with context."""
        ctx = ServiceContext(
            name="payment-api",
            team="payments",
            tier="critical",
            type="api",
        )

        resource = Resource(
            kind="SLO",
            name="availability",
            spec={"objective": 99.9},
            context=ctx,
        )

        assert resource.kind == "SLO"
        assert resource.name == "availability"
        assert resource.spec == {"objective": 99.9}
        assert resource.context == ctx

    def test_resource_full_name(self):
        """Test full resource name generation."""
        ctx = ServiceContext(
            name="payment-api",
            team="payments",
            tier="critical",
            type="api",
        )

        resource = Resource(
            kind="SLO",
            name="availability",
            spec={},
            context=ctx,
        )

        assert resource.full_name == "payment-api-availability"

    def test_resource_full_name_without_name(self):
        """Test that resource names are now required."""
        ctx = ServiceContext(
            name="payment-api",
            team="payments",
            tier="critical",
            type="api",
        )

        # Resource names are now required
        with pytest.raises(ValueError, match="Resource name is required"):
            Resource(
                kind="PagerDuty",
                spec={},
                context=ctx,
            )


class TestValidateServiceFile:
    """Test service file validation."""

    def test_validate_valid_file(self, tmp_path):
        """Test validating valid service file."""
        service_file = tmp_path / "test-service.yaml"
        service_file.write_text(
            """
service:
  name: test-service
  team: test-team
  tier: standard
  type: api

resources:
  - kind: SLO
    name: availability
    spec:
      objective: 99.9
"""
        )

        result = validate_service_file(service_file)

        assert result.valid
        assert len(result.errors) == 0
        assert result.service == "test-service"
        assert result.resource_count == 1

    def test_validate_invalid_service_name(self, tmp_path):
        """Test validation fails for invalid service name."""
        service_file = tmp_path / "test-service.yaml"
        service_file.write_text(
            """
service:
  name: Invalid_Name
  team: test-team
  tier: standard
  type: api
"""
        )

        result = validate_service_file(service_file)

        assert not result.valid
        assert any("Invalid service name" in e for e in result.errors)

    def test_validate_invalid_tier(self, tmp_path):
        """Test validation fails for invalid tier."""
        service_file = tmp_path / "test-service.yaml"
        service_file.write_text(
            """
service:
  name: test-service
  team: test-team
  tier: invalid-tier
  type: api
"""
        )

        result = validate_service_file(service_file)

        assert not result.valid
        assert any("Invalid tier" in e for e in result.errors)

    def test_validate_duplicate_resource_names(self, tmp_path):
        """Test validation fails for duplicate resource names."""
        service_file = tmp_path / "test-service.yaml"
        service_file.write_text(
            """
service:
  name: test-service
  team: test-team
  tier: standard
  type: api

resources:
  - kind: SLO
    name: availability
    spec:
      objective: 99.9
  - kind: SLO
    name: availability
    spec:
      objective: 99.5
"""
        )

        result = validate_service_file(service_file)

        assert not result.valid
        assert any("Duplicate resource names" in e for e in result.errors)
