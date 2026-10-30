"""Tests for service template system."""

from nthlayer_generate.specs.template_loader import TemplateLoader
from nthlayer_generate.specs.templates import ServiceTemplate, TemplateRegistry


class TestTemplateLoader:
    """Tests for TemplateLoader class."""

    def test_load_builtin_templates(self):
        """Should load all built-in templates."""
        registry = TemplateLoader.load_builtin()

        assert isinstance(registry, TemplateRegistry)
        assert "critical-api" in registry.templates
        assert "standard-api" in registry.templates
        assert "low-api" in registry.templates
        assert "background-job" in registry.templates
        assert "pipeline" in registry.templates

        # At least 5 templates
        assert len(registry.templates) >= 5

    def test_template_registry_get(self):
        """Should get template by name."""
        registry = TemplateLoader.load_builtin()

        template = registry.get("critical-api")
        assert template is not None
        assert isinstance(template, ServiceTemplate)
        assert template.name == "critical-api"

        # Non-existent template
        assert registry.get("nonexistent") is None

    def test_template_registry_list(self):
        """Should list all templates sorted."""
        registry = TemplateLoader.load_builtin()

        templates = registry.list()
        assert len(templates) >= 5

        # Should be sorted
        names = [t.name for t in templates]
        assert names == sorted(names)

    def test_template_registry_exists(self):
        """Should check template existence."""
        registry = TemplateLoader.load_builtin()

        assert registry.exists("critical-api")
        assert registry.exists("standard-api")
        assert not registry.exists("nonexistent")


class TestBuiltinTemplates:
    """Tests for built-in template content."""

    def test_critical_api_template(self):
        """Critical API template should have correct configuration."""
        registry = TemplateLoader.load_builtin()
        template = registry.get("critical-api")

        assert template.tier == "critical"
        assert template.type == "api"
        assert "99.9" in template.description

        # Should have 3 resources: 2 SLOs + PagerDuty
        assert len(template.resources) == 3

        # Check SLOs
        slos = [r for r in template.resources if r.kind == "SLO"]
        assert len(slos) == 2
        assert any(r.name == "availability" for r in slos)
        assert any(r.name == "latency-p95" for r in slos)

        # Check PagerDuty
        pd = [r for r in template.resources if r.kind == "PagerDuty"]
        assert len(pd) == 1
        assert pd[0].spec["urgency"] == "high"

    def test_standard_api_template(self):
        """Standard API template should have correct configuration."""
        registry = TemplateLoader.load_builtin()
        template = registry.get("standard-api")

        assert template.tier == "standard"
        assert template.type == "api"

        # Should have 3 resources
        assert len(template.resources) == 3

        # PagerDuty should be low urgency
        pd = [r for r in template.resources if r.kind == "PagerDuty"]
        assert len(pd) == 1
        assert pd[0].spec["urgency"] == "low"

    def test_low_api_template(self):
        """Low API template should have correct configuration."""
        registry = TemplateLoader.load_builtin()
        template = registry.get("low-api")

        assert template.tier == "low"
        assert template.type == "api"

        # Should have 2 SLOs (no PagerDuty for low tier)
        assert len(template.resources) == 2
        slos = [r for r in template.resources if r.kind == "SLO"]
        assert len(slos) == 2

    def test_background_job_template(self):
        """Background job template should have success rate SLO."""
        registry = TemplateLoader.load_builtin()
        template = registry.get("background-job")

        assert template.tier == "standard"
        # The template is NAMED background-job; its type resolves to the
        # manifest value `worker` (opensrm-8qpd). The name is an identifier,
        # the type is a vocabulary value, and only the latter reaches a
        # manifest — via cli/init.py's template-derived type fallback.
        assert template.type == "worker"

        # Should have success-rate SLO
        slos = [r for r in template.resources if r.kind == "SLO"]
        assert any(r.name == "success-rate" for r in slos)

    def test_pipeline_template(self):
        """Pipeline template should have appropriate SLOs."""
        registry = TemplateLoader.load_builtin()
        template = registry.get("pipeline")

        assert template.tier == "standard"
        # Named pipeline, typed batch — `pipeline` is a manifest alias, not
        # a manifest type (opensrm-8qpd). See test_background_job_template.
        assert template.type == "batch"

        # Should have success rate and freshness SLOs
        slos = [r for r in template.resources if r.kind == "SLO"]
        assert any(r.name == "success-rate" for r in slos)
        assert any(r.name == "freshness-p95" for r in slos)
