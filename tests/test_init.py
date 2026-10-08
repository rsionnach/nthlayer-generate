"""Tests for init command."""

import ast
import importlib
import json
import pathlib
import re
from unittest.mock import MagicMock, patch

import pytest
import yaml

from nthlayer_generate.cli.init import (
    SERVICE_TYPES,
    _build_resources_yaml,
    _format_template_resources,
    _generate_config_yaml,
    _generate_service_yaml,
    _generate_service_yaml_v2,
    _is_valid_service_name,
    _is_valid_team,
    _quoted_yaml_scalar,
    _yaml_scalar,
    init_command,
)
from nthlayer_generate.cli.setup import (
    _is_valid_service_name as _setup_is_valid_service_name,
)
from nthlayer_generate.specs.manifest import is_valid_service_name
from nthlayer_generate.specs.template_loader import TemplateLoader
from nthlayer_generate.specs.validator import validate_service_file


class TestInitCommand:
    """Tests for init_command function."""

    def test_init_creates_service_file(self, tmp_path, monkeypatch):
        """Should create service YAML file."""
        monkeypatch.chdir(tmp_path)

        result = init_command(
            service_name="my-api", team="my-team", template="critical-api", interactive=False
        )

        assert result == 0
        assert (tmp_path / "my-api.yaml").exists()

        # Check file content
        content = (tmp_path / "my-api.yaml").read_text()
        assert "name: my-api" in content
        assert "team: my-team" in content
        assert "template: critical-api" in content

    def test_init_creates_config_directory(self, tmp_path, monkeypatch):
        """Should create .nthlayer directory and config."""
        monkeypatch.chdir(tmp_path)

        result = init_command("my-api", "my-team", "critical-api", interactive=False)

        assert result == 0
        assert (tmp_path / ".nthlayer").exists()
        assert (tmp_path / ".nthlayer" / "config.yaml").exists()

        # Check config content
        config = (tmp_path / ".nthlayer" / "config.yaml").read_text()
        assert "error_budgets" in config
        assert "inherited_attribution" in config

    def test_init_does_not_overwrite_config(self, tmp_path, monkeypatch):
        """Should not overwrite existing config file."""
        monkeypatch.chdir(tmp_path)

        # Create existing config
        (tmp_path / ".nthlayer").mkdir()
        (tmp_path / ".nthlayer" / "config.yaml").write_text("existing: config")

        result = init_command("my-api", "my-team", "critical-api", interactive=False)

        assert result == 0
        # Should not overwrite
        config = (tmp_path / ".nthlayer" / "config.yaml").read_text()
        assert config == "existing: config"

    def test_init_rejects_existing_file(self, tmp_path, monkeypatch):
        """Should error if service file already exists."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "my-api.yaml").write_text("existing")

        result = init_command("my-api", "my-team", "critical-api", interactive=False)

        assert result == 1  # Error

    def test_init_requires_service_name(self, tmp_path, monkeypatch):
        """Should error if service name not provided in non-interactive mode."""
        monkeypatch.chdir(tmp_path)

        result = init_command(
            service_name=None, team="my-team", template="critical-api", interactive=False
        )

        assert result == 1

    def test_init_requires_team(self, tmp_path, monkeypatch):
        """Should error if team not provided in non-interactive mode."""
        monkeypatch.chdir(tmp_path)

        result = init_command(
            service_name="my-api", team=None, template="critical-api", interactive=False
        )

        assert result == 1

    def test_init_works_without_template(self, tmp_path, monkeypatch):
        """Should work without template in non-interactive mode (uses defaults)."""
        monkeypatch.chdir(tmp_path)

        result = init_command(
            service_name="my-api", team="my-team", template=None, interactive=False
        )

        # Should succeed with default tier=standard, type=api
        assert result == 0
        assert (tmp_path / "my-api.yaml").exists()

        content = (tmp_path / "my-api.yaml").read_text()
        assert "name: my-api" in content
        assert "tier: standard" in content
        assert "type: api" in content

    def test_init_rejects_unknown_template(self, tmp_path, monkeypatch):
        """Should error on unknown template."""
        monkeypatch.chdir(tmp_path)

        result = init_command(
            service_name="my-api",
            team="my-team",
            template="nonexistent-template",
            interactive=False,
        )

        assert result == 1

    def test_init_with_different_templates(self, tmp_path, monkeypatch):
        """Should work with different template types."""
        monkeypatch.chdir(tmp_path)

        templates = ["critical-api", "standard-api", "low-api", "background-job", "pipeline"]

        for template in templates:
            service_name = f"test-{template}"
            result = init_command(service_name, "team", template, interactive=False)

            assert result == 0
            assert (tmp_path / f"{service_name}.yaml").exists()

            content = (tmp_path / f"{service_name}.yaml").read_text()
            assert f"template: {template}" in content


class TestServiceNameValidation:
    """init's end-to-end rejection of a bad name.

    The two table-driven tests that were here are gone (opensrm-t4rd): every
    shape they covered -- uppercase, underscore, space, leading and trailing
    hyphen, empty, period, an inner double hyphen, digits -- is in
    `TestServiceNameRuleIsShared.NAMES`, which additionally asserts that the
    CLI guard and the shared rule agree on each one. The old list also carried
    `my--api` under `invalid_names` with an `if name == "my--api"` branch
    asserting the opposite, which is the kind of contradiction a single table
    makes impossible.
    """

    def test_init_rejects_invalid_name(self, tmp_path, monkeypatch):
        """Should error on invalid service name."""
        monkeypatch.chdir(tmp_path)

        result = init_command(
            service_name="MyInvalidApi",  # uppercase
            team="my-team",
            template="critical-api",
            interactive=False,
        )

        assert result == 1


class TestGeneratedServiceFile:
    """Tests for generated service file content."""

    def test_generated_file_is_valid_yaml(self, tmp_path, monkeypatch):
        """Generated file should be valid YAML."""
        monkeypatch.chdir(tmp_path)

        init_command("my-api", "my-team", "critical-api", interactive=False)

        # Should be parseable

        with open(tmp_path / "my-api.yaml") as f:
            data = yaml.safe_load(f)

        assert data["service"]["name"] == "my-api"
        assert data["service"]["team"] == "my-team"
        assert data["service"]["template"] == "critical-api"

    def test_generated_file_validates(self, tmp_path, monkeypatch):
        """Generated file should pass validation."""
        monkeypatch.chdir(tmp_path)

        init_command("my-api", "my-team", "critical-api", interactive=False)

        # Should be parseable by our parser
        from nthlayer_generate.specs.parser import parse_service_file

        context, resources = parse_service_file(tmp_path / "my-api.yaml")

        assert context.name == "my-api"
        assert context.team == "my-team"
        assert context.template == "critical-api"
        assert len(resources) == 3  # From template

    def test_generated_file_includes_comments(self, tmp_path, monkeypatch):
        """Generated file should include helpful comments."""
        monkeypatch.chdir(tmp_path)

        init_command("my-api", "my-team", "critical-api", interactive=False)

        content = (tmp_path / "my-api.yaml").read_text()

        # Should have header comments
        assert "# my-api Service Definition" in content
        assert "# Generated by NthLayer" in content


class TestInitCommandInteractive:
    """Tests for interactive mode of init_command."""

    @patch("nthlayer_generate.cli.init.text_input")
    @patch("nthlayer_generate.cli.init.select")
    @patch("nthlayer_generate.cli.init.multi_select")
    def test_interactive_prompts_for_service_name(
        self, mock_multi_select, mock_select, mock_text_input, tmp_path, monkeypatch
    ):
        """Test interactive mode prompts for service name."""
        monkeypatch.chdir(tmp_path)
        mock_text_input.side_effect = ["my-api", "my-team"]
        mock_select.side_effect = [
            "standard - Standard tier",
            "api - REST/GraphQL API service",
            "none - Generate from selections above",
        ]
        mock_multi_select.return_value = []

        result = init_command(service_name=None, team=None, interactive=True)

        assert result == 0
        assert (tmp_path / "my-api.yaml").exists()

    @patch("nthlayer_generate.cli.init.text_input")
    @patch("nthlayer_generate.cli.init.select")
    @patch("nthlayer_generate.cli.init.multi_select")
    def test_interactive_tier_selection(
        self, mock_multi_select, mock_select, mock_text_input, tmp_path, monkeypatch
    ):
        """Test interactive tier selection."""
        monkeypatch.chdir(tmp_path)
        mock_text_input.return_value = "my-team"
        mock_select.side_effect = [
            "critical - Critical tier",
            "api - REST/GraphQL API service",
            "none - Generate from selections above",
        ]
        mock_multi_select.return_value = []

        result = init_command(service_name="my-api", team=None, interactive=True)

        assert result == 0
        content = (tmp_path / "my-api.yaml").read_text()
        assert "tier: critical" in content

    @patch("nthlayer_generate.cli.init.text_input")
    @patch("nthlayer_generate.cli.init.select")
    @patch("nthlayer_generate.cli.init.multi_select")
    def test_interactive_service_type_selection(
        self, mock_multi_select, mock_select, mock_text_input, tmp_path, monkeypatch
    ):
        """Test interactive service type selection."""
        monkeypatch.chdir(tmp_path)
        mock_text_input.return_value = "my-team"
        mock_select.side_effect = [
            "standard - Standard tier",
            "worker - Background job processor",
            "none - Generate from selections above",
        ]
        mock_multi_select.return_value = []

        result = init_command(service_name="my-api", team=None, interactive=True)

        assert result == 0
        content = (tmp_path / "my-api.yaml").read_text()
        assert "type: worker" in content

    @patch("nthlayer_generate.cli.init.text_input")
    @patch("nthlayer_generate.cli.init.select")
    @patch("nthlayer_generate.cli.init.multi_select")
    @pytest.mark.parametrize("menu_type", ["stream", "database", "ai-gate", "x-web"])
    def test_selecting_a_type_with_no_template_offers_none(
        self,
        mock_multi_select,
        mock_select,
        mock_text_input,
        tmp_path,
        monkeypatch,
        menu_type,
    ):
        """The template filter must not offer a template of a different type.

        Before opensrm-8qpd the filter translated through
        SERVICE_TYPE_TO_TEMPLATE_TYPE, which mapped the menu's `stream` to
        the `pipeline` template — whose type resolves to `batch`. So
        choosing a stream processor offered you a batch template, and
        accepting it would have typed the manifest `batch`.

        No built-in template declares any of these four types, so the
        correct behaviour is to offer none and never reach a third
        `select`. All four are the same branch, parametrised because the
        empty-filter path is only interesting when it is actually empty —
        api, worker and batch do match templates, and
        test_interactive_service_type_selection covers that side.

        A third CALL is the regression. It surfaces as an exhausted
        `side_effect` — StopIteration — rather than as the assertion below,
        which cannot run once select has raised. The assertion is kept as a
        belt-and-braces check on the count, not as the mechanism.
        """
        monkeypatch.chdir(tmp_path)
        mock_text_input.return_value = "my-team"
        mock_select.side_effect = [
            "standard - Standard tier",
            f"{menu_type} - {SERVICE_TYPES[menu_type]}",
        ]
        mock_multi_select.return_value = []

        result = init_command(service_name="my-svc", team=None, interactive=True)

        assert result == 0
        assert mock_select.call_count == 2, (
            f"init prompted for a template when none matches {menu_type!r}"
        )
        assert f"type: {menu_type}" in (tmp_path / "my-svc.yaml").read_text()

    @patch("nthlayer_generate.cli.init.text_input")
    @patch("nthlayer_generate.cli.init.select")
    @patch("nthlayer_generate.cli.init.multi_select")
    def test_interactive_dependencies_selection(
        self, mock_multi_select, mock_select, mock_text_input, tmp_path, monkeypatch
    ):
        """Test interactive dependencies selection."""
        monkeypatch.chdir(tmp_path)
        mock_text_input.return_value = "my-team"
        mock_select.side_effect = [
            "standard - Standard tier",
            "api - REST/GraphQL API service",
            "none - Generate from selections above",
        ]
        mock_multi_select.return_value = ["postgresql", "redis"]

        result = init_command(service_name="my-api", team=None, interactive=True)

        assert result == 0
        content = (tmp_path / "my-api.yaml").read_text()
        assert "Dependencies" in content
        assert "postgresql" in content
        assert "redis" in content

    @patch("nthlayer_generate.cli.init.text_input")
    @patch("nthlayer_generate.cli.init.select")
    @patch("nthlayer_generate.cli.init.multi_select")
    def test_interactive_template_selection(
        self, mock_multi_select, mock_select, mock_text_input, tmp_path, monkeypatch
    ):
        """Test interactive template selection."""
        monkeypatch.chdir(tmp_path)
        mock_text_input.return_value = "my-team"
        mock_select.side_effect = [
            "standard - Standard tier",
            "api - REST/GraphQL API service",
            "critical-api - Critical API template",
        ]
        mock_multi_select.return_value = []

        result = init_command(service_name="my-api", team=None, interactive=True)

        assert result == 0
        content = (tmp_path / "my-api.yaml").read_text()
        assert "template: critical-api" in content


class TestInitCommandErrorHandling:
    """Tests for error handling in init_command."""

    @patch("nthlayer_generate.cli.init.CustomTemplateLoader.load_all_templates")
    def test_handles_template_loading_error(self, mock_load, tmp_path, monkeypatch):
        """Test handling of template loading errors."""
        monkeypatch.chdir(tmp_path)
        mock_load.side_effect = Exception("Template loading failed")

        result = init_command("my-api", "my-team", interactive=False)

        assert result == 1

    def test_handles_file_write_error(self, tmp_path, monkeypatch):
        """Test handling of file write errors."""
        monkeypatch.chdir(tmp_path)
        # Make directory read-only
        (tmp_path / "my-api.yaml").write_text("")  # Create file first

        with patch("pathlib.Path.write_text", side_effect=OSError("Permission denied")):
            result = init_command("new-api", "my-team", interactive=False)

        # Should handle the error
        assert result == 1

    def test_handles_directory_creation_error(self, tmp_path, monkeypatch):
        """Test handling of .nthlayer directory creation errors."""
        monkeypatch.chdir(tmp_path)

        with patch("pathlib.Path.mkdir", side_effect=OSError("Permission denied")):
            # Should still succeed (just warn about directory)
            result = init_command("my-api", "my-team", interactive=False)

        # May or may not fail depending on which mkdir fails
        # But the file should exist if the first part succeeded
        assert (tmp_path / "my-api.yaml").exists() or result == 1


class TestBuildResourcesYaml:
    """Tests for _build_resources_yaml function."""

    def test_builds_slo_for_critical_tier(self):
        """Test SLO generation for critical tier."""
        result = _build_resources_yaml("my-api", "critical", "api", [])

        assert "kind: SLO" in result
        assert "availability" in result
        assert "objective: 99.95" in result  # Critical tier default

    def test_builds_slo_for_standard_tier(self):
        """Test SLO generation for standard tier."""
        result = _build_resources_yaml("my-api", "standard", "api", [])

        assert "kind: SLO" in result
        assert "objective: 99.9" in result

    def test_builds_slo_for_low_tier(self):
        """Test SLO generation for low tier."""
        result = _build_resources_yaml("my-api", "low", "api", [])

        assert "kind: SLO" in result
        # Low tier uses standard defaults (99.9 availability, 99.0 latency)
        assert "availability" in result
        assert "objective: 99.9" in result

    def test_includes_pagerduty_for_critical(self):
        """Test PagerDuty included for critical tier."""
        result = _build_resources_yaml("my-api", "critical", "api", [])

        assert "kind: PagerDuty" in result
        assert "urgency: high" in result

    def test_no_pagerduty_for_low_tier(self):
        """Test PagerDuty not included for low tier."""
        result = _build_resources_yaml("my-api", "low", "api", [])

        assert "kind: PagerDuty" not in result

    def test_builds_database_dependencies(self):
        """Test database dependency generation."""
        result = _build_resources_yaml("my-api", "standard", "api", ["postgresql", "mysql"])

        assert "kind: Dependencies" in result
        assert "databases:" in result
        assert "my-api-postgresql" in result
        assert "my-api-mysql" in result

    def test_builds_cache_dependencies(self):
        """Test cache dependency generation."""
        result = _build_resources_yaml("my-api", "standard", "api", ["redis", "elasticsearch"])

        assert "caches:" in result
        assert "my-api-redis" in result
        assert "my-api-elasticsearch" in result

    def test_builds_queue_dependencies(self):
        """Test queue dependency generation."""
        result = _build_resources_yaml("my-api", "standard", "api", ["kafka", "rabbitmq"])

        assert "queues:" in result
        assert "my-api-kafka" in result
        assert "my-api-rabbitmq" in result

    def test_builds_mixed_dependencies(self):
        """Test mixed dependency types."""
        deps = ["postgresql", "redis", "kafka"]
        result = _build_resources_yaml("my-api", "standard", "api", deps)

        assert "databases:" in result
        assert "caches:" in result
        assert "queues:" in result


class TestGenerateServiceYaml:
    """Tests for legacy _generate_service_yaml function."""

    def test_generates_yaml_with_template(self):
        """Test YAML generation with template."""
        mock_template = MagicMock()
        mock_template.name = "critical-api"
        mock_template.tier = "critical"
        mock_template.type = "api"
        mock_template.resources = []

        result = _generate_service_yaml("my-api", "my-team", mock_template)

        assert "name: my-api" in result
        assert "team: my-team" in result
        assert "tier: critical" in result
        assert "template: critical-api" in result

    def test_includes_template_resources_as_comments(self):
        """Test template resources shown in comments."""
        mock_resource = MagicMock()
        mock_resource.kind = "SLO"
        mock_resource.name = "availability"

        mock_template = MagicMock()
        mock_template.name = "critical-api"
        mock_template.tier = "critical"
        mock_template.type = "api"
        mock_template.resources = [mock_resource]

        result = _generate_service_yaml("my-api", "my-team", mock_template)

        assert "# Template provides:" in result


class TestFormatTemplateResources:
    """Tests for _format_template_resources function."""

    def test_formats_resources(self):
        """Test resource formatting."""
        mock_resource1 = MagicMock()
        mock_resource1.kind = "SLO"
        mock_resource1.name = "availability"

        mock_resource2 = MagicMock()
        mock_resource2.kind = "Alert"
        mock_resource2.name = "high-latency"

        mock_template = MagicMock()
        mock_template.resources = [mock_resource1, mock_resource2]

        result = _format_template_resources(mock_template)

        assert "#   - SLO: availability" in result
        assert "#   - Alert: high-latency" in result

    def test_handles_empty_resources(self):
        """Test formatting with no resources."""
        mock_template = MagicMock()
        mock_template.resources = []

        result = _format_template_resources(mock_template)

        assert "(no resources)" in result


class TestGenerateServiceYamlV2:
    """Tests for _generate_service_yaml_v2 function."""

    def test_generates_yaml_without_template(self):
        """Test YAML generation without template."""
        result = _generate_service_yaml_v2("my-api", "my-team", "standard", "api", [], None)

        assert "name: my-api" in result
        assert "team: my-team" in result
        assert "tier: standard" in result
        assert "type: api" in result
        assert "template:" not in result

    def test_generates_yaml_with_template(self):
        """Test YAML generation with template."""
        mock_template = MagicMock()
        mock_template.name = "critical-api"

        result = _generate_service_yaml_v2(
            "my-api", "my-team", "critical", "api", [], mock_template
        )

        assert "template: critical-api" in result


class TestGenerateConfigYaml:
    """Tests for _generate_config_yaml function."""

    def test_generates_valid_config(self):
        """Test config generation."""
        result = _generate_config_yaml()

        assert "NthLayer Configuration" in result
        assert "error_budgets:" in result
        assert "inherited_attribution" in result


class TestServiceNameRuleIsShared:
    """opensrm-t4rd: init's guard and the validator must not disagree.

    They did, and `nthlayer init 1-svc --team ops` exited 0 writing a file that
    `nthlayer validate` then refused. The divergence itself is recorded once,
    at the rule in specs/manifest.py.

    PROVENANCE OF THIS TABLE: derived from that shared rule, which is
    generate's authority for names it GENERATES -- not from what either old
    guard happened to accept, and not from opensrm's schema, which does not
    constrain this field and is looser where it speaks at all. The bead's
    acceptance asked for a schema-derived table; one is not available here, and
    saying so is part of the finding. The spec gap is opensrm-fwnp.
    """

    # (name, expected) — every rejection names the rule it breaks.
    NAMES = [
        ("svc", True),
        ("my-api", True),
        ("service123", True),
        ("my--api", True),  # a double hyphen INSIDE is fine
        ("s", True),  # single character
        ("1-svc", False),  # leading digit: validator rejected, old guard did not
        ("-svc", False),  # leading hyphen
        ("svc-", False),  # trailing hyphen: old guard rejected, validator did not
        ("MyApi", False),  # uppercase
        ("my_api", False),  # underscore
        ("my api", False),  # space
        ("my.api", False),  # period
        ("", False),  # empty
        ("café", False),  # non-ASCII lowercase: str.islower() is True for 'é'
        ("ａbc", False),  # FULLWIDTH 'a': str.islower() is True for it too
        ("٣svc", False),  # Arabic-Indic digit: str.isdigit() is True for it
        ("svc\n", False),  # trailing newline: `re.match(..."$")` would ACCEPT this
        # Accepted names that YAML resolves to a non-string. Absent from this
        # table, `test_every_accepted_name_produces_a_valid_manifest` passed
        # while `nthlayer init no` exited 0 writing a manifest whose name
        # loaded as False -- and `init yes` made the validator raise TypeError.
        # The predicate was right; the table had no fixture of the hostile
        # shape, which is the ecosystem fixture-provenance rule in one line.
        ("no", True),
        ("yes", True),
        ("on", True),
        ("off", True),
        ("true", True),
        ("false", True),
        ("null", True),
        ("n", True),  # a plain string in pyyaml, unlike `no`
        ("y", True),
    ]

    @pytest.mark.parametrize(("name", "expected"), NAMES)
    def test_guard_matches_the_shared_rule(self, name, expected):
        assert is_valid_service_name(name) is expected
        assert _is_valid_service_name(name) is expected, (
            "the CLI guard has diverged from the shared rule again"
        )

    def test_the_table_is_not_vacuous(self):
        """Both outcomes must be represented, or a broken rule could pass.

        A predicate that returns a constant satisfies an all-True or all-False
        table. Cheap guard against this class landing by edit.
        """
        outcomes = {expected for _, expected in self.NAMES}
        assert outcomes == {True, False}

    def test_trailing_newline_is_why_fullmatch(self):
        """Pins the specific reason the rule uses fullmatch, not match + `$`.

        In Python `$` also matches just before a final newline, so the old
        `re.match(r"^[a-z][a-z0-9-]*$", "svc\\n")` SUCCEEDED. A trailing newline
        is an ordinary authoring accident from a YAML block scalar. opensrm v2's
        schema documents a deliberate `not: {pattern: "\\n"}` guard against
        exactly this for ServiceType.
        """
        from nthlayer_generate.specs.manifest import SERVICE_NAME_PATTERN

        assert re.match(SERVICE_NAME_PATTERN + "$", "svc\n") is not None, (
            "if this fails, Python changed and the fullmatch rationale needs revisiting"
        )
        assert re.compile(SERVICE_NAME_PATTERN).fullmatch("svc\n") is None


class TestInitOutputSurvivesItsOwnValidator:
    """opensrm-t4rd: the single test that catches defects 1 and 2 together.

    The bead asked for a test that runs init and loads the result "through the
    real manifest parser". The parser is not enough: measured, `load_manifest`
    accepts `-svc`, `AB`, `café` and `sv_c` without complaint, because it does
    not enforce the name pattern at all. The authority that rejected init's
    output is `specs/validator.py`, so that is what this runs.
    """

    def test_a_colon_in_team_survives_init_and_the_validator(self, tmp_path, monkeypatch):
        """A colon in a team name is ordinary, and used to break the document.

        Before the fix: `--team 'Platform: Core'` produced YAML that failed to
        parse, at exit 0.
        """
        monkeypatch.chdir(tmp_path)

        assert init_command("svc", "Platform: Core", None, interactive=False) == 0

        written = tmp_path / "svc.yaml"

        data = yaml.safe_load(written.read_text())
        assert data["service"]["team"] == "Platform: Core"
        assert data["service"]["name"] == "svc", "team must not be able to reach name"

        result = validate_service_file(written)
        assert result.valid, f"init wrote something its own validator rejects: {result.errors}"

    def test_a_newline_in_team_cannot_inject_a_field(self, tmp_path, monkeypatch):
        """The dangerous case: an injected `tier:` VALIDATED CLEAN before the fix.

        `--team $'ops\\ntier: critical'` wrote a second tier line, shadowed by the
        generated one, and the manifest passed validation carrying it. Rejected at
        the boundary now, so nothing is written at all.
        """
        monkeypatch.chdir(tmp_path)

        assert init_command("svc", "ops\ntier: critical", None, interactive=False) == 1
        assert not (tmp_path / "svc.yaml").exists(), (
            "a rejected run must not leave a manifest behind"
        )

    def test_every_accepted_name_produces_a_valid_manifest(self, tmp_path, monkeypatch):
        """The guard/validator agreement, end to end rather than unit-to-unit.

        This is the assertion that would have failed before the fix: `1-svc` is
        absent from the accepted set now, but had the guard stayed looser than the
        validator, any name it admitted and the validator refused would surface
        here.
        """
        accepted = [n for n, ok in TestServiceNameRuleIsShared.NAMES if ok]
        assert accepted, "vacuous: no accepted names to check"

        for name in accepted:
            d = tmp_path / name
            d.mkdir()
            monkeypatch.chdir(d)
            assert init_command(name, "ops", None, interactive=False) == 0
            result = validate_service_file(d / f"{name}.yaml")
            assert result.valid, (
                f"init accepted {name!r} but its validator rejects it: {result.errors}"
            )


class TestTeamIsNotImplicitlyRetyped:
    """opensrm-t4rd, found by the R5 correctness pass on the fix itself.

    The quoting allowlist excluded every YAML *indicator*, which is what the
    original defect was about, and then stopped. It said nothing about implicit
    *type resolution*, so a second family of `--team` values matched the
    allowlist, was emitted unquoted, and loaded back as something that is not a
    string -- reproducing both of the bead's own failure shapes one field over.

    HOSTILE is NOT derived from the implementation. Every entry is proved to be
    a real hazard against the loader in
    `test_every_hostile_value_is_actually_hostile` below: if pyyaml stops
    resolving one of these, that test fails rather than this suite quietly
    testing nothing. That is the fixture-provenance rule -- a fixture written
    from the code under test agrees with the code under test, including its
    bugs.
    """

    # Overlaps TestQuotingMechanismRoundTrips.HAZARDS on a couple of values,
    # deliberately: that class exercises the quoting helper directly, this one
    # drives the same value through `init_command` end to end. Dropping a value
    # from either list loses coverage at that layer.
    HOSTILE = [
        "null",
        "NULL",
        "~",
        "yes",
        "Yes",
        "no",
        "on",
        "off",
        "true",
        "false",
        "123",
        "1_000",
        "1.5",
        "0x1f",
        "0b101",
        "2026-01-01",
        "ops ",
    ]

    def test_the_hostile_table_is_not_empty(self):
        """Same vacuity guard as TestQuotingMechanismRoundTrips."""
        assert self.HOSTILE

    def test_every_hostile_value_is_actually_hostile(self):
        """Provenance guard: each fixture must be a value the loader retypes.

        Traces the table to the authority (what pyyaml actually does) rather
        than to `_emits_as_same_string`, which is the code under test.
        """
        for value in self.HOSTILE:
            loaded = yaml.safe_load(value)
            assert not (isinstance(loaded, str) and loaded == value), (
                f"{value!r} is no longer retyped by the loader "
                f"(got {loaded!r}); it no longer proves anything -- "
                f"replace or remove it"
            )

    @pytest.mark.parametrize("team", HOSTILE)
    def test_hostile_team_round_trips_as_the_exact_string(self, team, tmp_path, monkeypatch):
        """init must write a team that reads back as the string it was given.

        Before the fix, measured at exit 0: `--team null` loaded as None and the
        validator then rejected the manifest; `--team yes` loaded as True and
        the manifest VALIDATED CLEAN carrying a bool in a field declared `str`;
        `--team 'ops '` silently lost its trailing space.
        """
        monkeypatch.chdir(tmp_path)

        assert init_command("svc", team, None, interactive=False) == 0

        written = tmp_path / "svc.yaml"
        data = yaml.safe_load(written.read_text())
        assert isinstance(data["service"]["team"], str), (
            f"--team {team!r} was implicitly retyped to {type(data['service']['team']).__name__}"
        )
        assert data["service"]["team"] == team

    @pytest.mark.parametrize("team", HOSTILE)
    def test_hostile_team_still_passes_the_real_validator(self, team, tmp_path, monkeypatch):
        """The exit-0-then-invalid shape, which is the bead's whole subject."""
        monkeypatch.chdir(tmp_path)

        assert init_command("svc", team, None, interactive=False) == 0

        result = validate_service_file(tmp_path / "svc.yaml")
        assert result.valid, (
            f"init exited 0 writing a manifest its own validator rejects "
            f"for --team {team!r}: {result.errors}"
        )


class TestTeamGuardScope:
    """opensrm-t4rd clarity pass: the guard rejected more than it claimed.

    `_is_valid_team` was `bool(team.strip()) and not any(...)`, but its summary
    said only "free of control characters" and the CLI told the user "must not
    contain line breaks, tabs or control characters". A whitespace-only --team
    therefore got a message that was false for it.

    Blankness moved to the caller's `if not team or not team.strip()` branch,
    which already had the right message, leaving this guard doing exactly what
    it says.

    Asserted structurally rather than by scraping the console, per the
    project's test-assertion rule. What that leaves UNASSERTED, stated rather
    than implied: nothing here checks which message a given input produces,
    only that the two branches separate and that every rejected team exits 1
    writing nothing. The wording was verified by hand when it changed.
    """

    def test_the_guard_no_longer_judges_blankness(self):
        """It answers only the control-character question now."""
        assert _is_valid_team("   ") is True
        assert _is_valid_team("") is True
        assert _is_valid_team("\t") is False  # a tab IS a control character

    @pytest.mark.parametrize("team", ["\n", "\r", "\t", "\x00", "ops\nx"])
    def test_the_guard_rejects_the_four(self, team):
        """Each of the four, plus one embedded in an otherwise ordinary name.

        That exactness is the *other* half -- see
        `test_the_guard_passes_what_quoting_handles`.
        """
        assert _is_valid_team(team) is False

    @pytest.mark.parametrize("team", ["\x1b", "\x07", "\x0b", "caf\u00e9", "a b"])
    def test_the_guard_passes_what_quoting_handles(self, team):
        """The rest are odd, not dangerous -- `_yaml_scalar` quotes them."""
        assert _is_valid_team(team) is True

    @pytest.mark.parametrize("team", ["", "   ", "\t", "o\tps", "ops\nname: x"])
    def test_every_rejected_team_still_exits_1_and_writes_nothing(
        self, team, tmp_path, monkeypatch
    ):
        """Whichever branch catches it, the contract is the same."""
        monkeypatch.chdir(tmp_path)

        assert init_command("svc", team, None, interactive=False) == 1
        assert not (tmp_path / "svc.yaml").exists()


class TestQuotingMechanismRoundTrips:
    """opensrm-t4rd, found by the R5 correctness pass iteration 2.

    Two defects in the quoting path itself, both reproducing shapes the bead
    exists to close: `--team 0b_` crashed with an uncaught ValueError, and any
    non-BMP team name was silently corrupted into a manifest that VALIDATED
    CLEAN -- a regression, since the raw interpolation this replaced passed
    emoji through intact.

    The corpus is split by how each entry earns its place, because claiming all
    of them are proven hazards would be false.
    """

    # Values some naive mechanism provably gets wrong: `json.dumps`-based
    # quoting fails to round-trip them, or pyyaml raises on them, or pyyaml
    # retypes them. `test_hazards_are_provable_hazards` re-derives this from the
    # libraries, so a library change fails the test rather than quietly
    # emptying the corpus.
    HAZARDS = [
        "\U0001f389 platform",  # non-BMP: json emits a surrogate PAIR
        "\U0001d11e",
        "\U0010ffff",
        "Platform: Core",
        "ops ",
        "\u2028",
        "\u2029",
        "\u0085",
        "\u007f",
        "\ufeff",
        "0b_",  # pyyaml's int constructor raises ValueError
        "0x_",
        "null",
        "...",
    ]

    # Chosen deliberately, and NOT mechanically hazardous -- the naive
    # mechanism happens to handle these correctly. They are here as regression
    # guards on YAML's structural characters and on the readability path, so a
    # future change to the quoting cannot break them unnoticed.
    STRUCTURAL = [
        'he said "hi"',  # the quote character
        "a\\b",  # the escape character
        "ops...",  # a document-end-marker lookalike that is ordinary text
        # Long enough to cross pyyaml's 80-column default wrap. Without these
        # nothing in the corpus reached the threshold, so deleting
        # `width=_NO_WRAP` left every test here green (opensrm-t4rd edge cases).
        # It is the SPACES that make this wrap -- pyyaml breaks at a space -- so
        # this is the value that pins `width=_NO_WRAP`. `"x" * 10_000` below is
        # emitted unwrapped and pins length handling only.
        "platform team " * 20,
        "x" * 10_000,
        "caf\u00e9",  # BMP non-ASCII
        "\u1e93algo",
        "\u00a0",  # NBSP
    ]

    CORPUS = HAZARDS + STRUCTURAL

    def test_the_corpora_are_not_empty(self):
        """Emptying either list would make every test here pass vacuously.

        The parametrised tests would collect zero cases and the provenance
        guard would iterate nothing, both silently green.
        """
        assert self.HAZARDS
        assert self.STRUCTURAL
        assert len(self.CORPUS) == len(self.HAZARDS) + len(self.STRUCTURAL)

    def test_hazards_are_provable_hazards(self):
        """Provenance guard: every HAZARDS entry must be demonstrably hostile.

        Derived from what `json` and `yaml` actually do, never from
        `_quoted_yaml_scalar`, which is the code under test.
        """
        for value in self.HAZARDS:
            try:
                json_round_trips = yaml.safe_load(f"t: {json.dumps(value)}\n")["t"] == value
            except Exception:
                json_round_trips = False
            try:
                loaded = yaml.safe_load(value)
                load_agrees = isinstance(loaded, str) and loaded == value
            except Exception:
                load_agrees = False
            assert not (json_round_trips and load_agrees), (
                f"{value!r} is no longer hostile to either naive mechanism; "
                f"it proves nothing -- move it to STRUCTURAL or remove it"
            )

    @pytest.mark.parametrize("team", CORPUS)
    def test_team_round_trips_through_a_real_document(self, team):
        """The emitted scalar must read back as the exact string given."""
        doc = f"service:\n  name: svc\n  team: {_yaml_scalar(team)}\n"
        loaded = yaml.safe_load(doc)
        assert loaded["service"]["team"] == team
        assert loaded["service"]["name"] == "svc", "team must not reach name"

    @pytest.mark.parametrize("team", CORPUS)
    def test_team_survives_a_real_utf8_file(self, team, tmp_path):
        """A value holding lone surrogates cannot be written to a file at all.

        The surrogate-pair defect produced exactly that. This version WRITES a
        file: the original only did `doc.encode("utf-8")` in memory, so it
        passed regardless of what init actually wrote, and it was the test that
        should have caught the default-encoding crash the edge-case pass found.
        """
        doc = f"service:\n  team: {_yaml_scalar(team)}\n"
        written = tmp_path / "svc.yaml"
        written.write_text(doc, encoding="utf-8")
        assert yaml.safe_load(written.read_text(encoding="utf-8"))["service"]["team"] == team

    @pytest.mark.parametrize("team", CORPUS)
    def test_emitted_scalar_never_spans_lines(self, team):
        """The document is built by interpolation, so a newline would corrupt it."""
        assert "\n" not in _yaml_scalar(team)

    @pytest.mark.parametrize("team", CORPUS)
    def test_quoted_form_carries_no_document_end_marker(self, team):
        """Why `_quoted_yaml_scalar` strips only the trailing newline.

        Asserted on the quoted branch specifically: an unquoted plain scalar may
        legitimately end in `...` (see `ops...` in STRUCTURAL).
        """
        emitted = _quoted_yaml_scalar(team)
        assert emitted.startswith('"') and emitted.endswith('"')
        assert "\n" not in emitted

    def test_bmp_non_ascii_is_emitted_literally_not_escaped(self):
        """Pins `allow_unicode=True`, which is a readability choice.

        Correctness does not depend on it -- flipping it to False leaves every
        other test in this class green, because pyyaml round-trips its own
        escapes either way. Without this test the flag would be unpinned and
        could be dropped silently, turning every accented team name in a
        generated manifest into an escape sequence.
        """
        assert _quoted_yaml_scalar("caf\u00e9") == '"caf\u00e9"'
        assert "\\x" not in _quoted_yaml_scalar("caf\u00e9")

    def test_init_does_not_crash_on_a_value_pyyaml_cannot_parse(self, tmp_path, monkeypatch):
        """`--team 0b_` raised an uncaught ValueError and wrote nothing.

        pyyaml's int constructor reaches `int("", 2)` for this input, which is a
        ValueError, not a YAMLError.
        """
        monkeypatch.chdir(tmp_path)

        assert init_command("svc", "0b_", None, interactive=False) == 0

        written = tmp_path / "svc.yaml"
        assert yaml.safe_load(written.read_text())["service"]["team"] == "0b_"
        assert validate_service_file(written).valid

    @pytest.mark.parametrize("team", ["\U0001f389 platform", "caf\u00e9", "\U0001d11e"])
    def test_non_ascii_team_survives_init_end_to_end(self, team, tmp_path, monkeypatch):
        """The regression, end to end: emoji round-tripped before the first fix."""
        monkeypatch.chdir(tmp_path)

        assert init_command("svc", team, None, interactive=False) == 0

        written = tmp_path / "svc.yaml"
        assert yaml.safe_load(written.read_text())["service"]["team"] == team
        assert validate_service_file(written).valid


class TestServiceNameIsNotImplicitlyRetyped:
    """opensrm-t4rd, found by the R5 correctness pass iteration 3.

    `service_name` was the one field still interpolated raw, and the shared
    rule accepts `yes no on off true false null` -- all of which YAML resolves
    to a bool or None. Measured, at exit 0:

      nthlayer init no   -> name loads as False -> validate reports invalid
      nthlayer init yes  -> name loads as True  -> validate RAISES TypeError
      nthlayer init null -> name loads as None  -> validate reports invalid

    The predicate was correct the whole time; `NAMES` simply had no fixture of
    that shape, so the end-to-end test agreed with the bug.
    """

    RESOLVABLE = ["no", "yes", "on", "off", "true", "false", "null"]

    def test_the_table_is_not_empty(self):
        assert self.RESOLVABLE

    def test_every_resolvable_name_is_accepted_by_the_rule(self):
        """Provenance: these matter only because the rule admits them.

        If the rule is ever tightened to reject them, this test fails and says
        so, rather than leaving the cases below quietly testing nothing.
        """
        for name in self.RESOLVABLE:
            assert is_valid_service_name(name), (
                f"{name!r} is no longer an accepted name; these cases exist "
                f"because the rule accepts names YAML retypes"
            )

    def test_every_resolvable_name_is_retyped_by_the_loader(self):
        """Provenance: and only because the loader retypes them."""
        for name in self.RESOLVABLE:
            loaded = yaml.safe_load(name)
            assert not (isinstance(loaded, str) and loaded == name), (
                f"{name!r} is no longer retyped by the loader; it proves nothing"
            )

    @pytest.mark.parametrize("name", RESOLVABLE)
    def test_init_writes_a_name_that_reads_back_as_a_string(self, name, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)

        assert init_command(name, "ops", None, interactive=False) == 0

        written = yaml.safe_load((tmp_path / f"{name}.yaml").read_text())
        assert written["service"]["name"] == name
        assert isinstance(written["service"]["name"], str)

    # Validator-validity for these names is covered end to end by
    # TestInitOutputSurvivesItsOwnValidator, because RESOLVABLE is a subset of
    # NAMES. What that does NOT assert is the TYPE of the written value, which
    # is the point of the test above.


class TestNoFieldBypassesTheQuotingHelper:
    """The class guard for opensrm-t4rd, added after three fix iterations.

    Correctness found the same defect three times in three fields -- `team`,
    then `name`, then `template` -- because nothing FORCED a new interpolated
    field through `_yaml_scalar`. Each round closed an instance. This closes
    the class.

    Functions are DISCOVERED BY SHAPE, not listed by name. The first version of
    this guard used a three-name allowlist, and the correctness pass pointed out
    it could not notice a fourth builder -- and that it was already missing one:
    `_format_template_resources` interpolated `resource.kind` and
    `resource.name` raw, and my EXEMPT entry for it claimed it was an
    "already-rendered YAML block", which was false. An allowlist only guards
    what someone remembered to list.

    Why the mechanism stays an f-string: the generated manifests carry
    explanatory comments (`# Availability SLO`) that `yaml.safe_dump` of a dict
    cannot emit, and `test_block_is_byte_identical_to_real_output` pins them as
    the docs-vs-reality guard from opensrm-noc6. So the mechanism stays and
    gets enforcement instead.

    Known limits, stated rather than implied: this reads `cli/init.py` only,
    and `.format()`/`%` interpolation would be invisible. Raw `+`
    concatenation IS checked.
    """

    MODULE = "nthlayer_generate.cli.init"
    WRAPPERS = ("_yaml_scalar",)

    # Expression -> why it needs no wrapper. Anything else, in any
    # YAML-shaped f-string in the module, fails. Keep every reason checkable.
    EXEMPT = {
        # Closed sets. No --tier/--type flags exist; tier comes from
        # TIER_CONFIGS or a template whose __post_init__ validates it, and
        # dependencies come from the DEPENDENCIES multi-select.
        "tier": "closed set (TIER_CONFIGS keys)",
        "service_type": "closed set (SERVICE_TYPES keys, resolved)",
        "template.tier": "ServiceTemplate.__post_init__ raises on a bad tier",
        "template.type": "ServiceTemplate.__post_init__ resolves or raises",
        "db": "closed set (DEPENDENCIES)",
        "cache": "closed set (DEPENDENCIES)",
        "queue": "closed set (DEPENDENCIES)",
        # Already-rendered YAML, produced by a function this guard also covers,
        # so its own interpolations are checked there rather than here.
        "resources_yaml": "rendered by _build_resources_yaml, covered below",
        "template_line": "rendered line, its value is wrapped at the source",
        "_format_template_resources(template)": (
            "rendered by _format_template_resources, covered below"
        ),
        # Bare `service_name` reaches only a comment line or a scalar composed
        # with a literal hyphen, so it can never resolve to a non-string. The
        # comment case is safe because the name rule forbids a newline --
        # pinned by ("svc\n", False) in TestServiceNameRuleIsShared.NAMES.
        "service_name": "comment line, or composed with a literal hyphen",
    }

    @staticmethod
    def _yaml_shaped(joined):
        """True if this f-string emits document structure rather than console text.

        Multi-line with a `key:` in its literal part, or a comment line. Keeps
        the guard off `init_command`'s menu strings like `f"{k} - {v}"`, which
        are console output and would otherwise need meaningless exemptions.
        """
        literals = "".join(
            v.value
            for v in joined.values
            if isinstance(v, ast.Constant) and isinstance(v.value, str)
        )
        has_key = re.search(r"[\w-]+:\s*(\n|$)", literals) is not None
        return ("\n" in literals and has_key) or literals.lstrip().startswith("#")

    def _covered(self):
        """Every YAML-shaped interpolation in the module, by function."""
        module = importlib.import_module(self.MODULE)
        tree = ast.parse(pathlib.Path(module.__file__).read_text(encoding="utf-8"))
        found = {}
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for joined in [n for n in ast.walk(fn) if isinstance(n, ast.JoinedStr)]:
                if not self._yaml_shaped(joined):
                    continue
                for value in joined.values:
                    if isinstance(value, ast.FormattedValue):
                        found.setdefault(fn.name, []).append(value.value)
        return found

    # The four YAML-emitting functions and the number of interpolations they
    # carried when this guard was written. Floors, not exact counts: adding a
    # field should not fail here, but losing coverage should.
    MIN_FUNCTIONS = 4
    MIN_INTERPOLATIONS = 15

    def test_the_guard_covers_something(self):
        """Anti-vacuity: a guard that inspects nothing passes everything.

        If `_yaml_shaped` stops matching -- a reformat that splits a template,
        a move to `.format()` -- every other test in this class goes green by
        finding nothing. These floors are what makes that loud.
        """
        covered = self._covered()
        total = sum(len(v) for v in covered.values())
        assert len(covered) >= self.MIN_FUNCTIONS, (
            f"found only {len(covered)} YAML-emitting functions "
            f"({sorted(covered)}), expected at least {self.MIN_FUNCTIONS}. "
            f"`_yaml_shaped` has probably stopped matching the templates, so "
            f"this guard is now inspecting almost nothing. Fix the heuristic "
            f"rather than lowering this floor."
        )
        assert total >= self.MIN_INTERPOLATIONS, (
            f"found only {total} interpolations across {sorted(covered)}, "
            f"expected at least {self.MIN_INTERPOLATIONS}. Same cause and same "
            f"remedy as above: if a template genuinely shrank, lower the floor "
            f"deliberately and say why in the commit."
        )

    def test_every_interpolation_is_wrapped_or_exempt(self):
        for fn_name, nodes in sorted(self._covered().items()):
            for node in nodes:
                expr = ast.unparse(node)
                # An AST shape check, not a prefix match: `_yaml_scalar(x) + raw`
                # and `_yaml_scalar(x)[1:-1]` both START with the wrapper name
                # while defeating it.
                wrapped = (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id in self.WRAPPERS
                )
                assert wrapped or expr in self.EXEMPT, (
                    f"{fn_name} interpolates {expr!r} raw into generated YAML. "
                    f"Wrap it: {{_yaml_scalar({expr})}}. If it genuinely cannot "
                    f"carry a hostile value, add it to "
                    f"TestNoFieldBypassesTheQuotingHelper.EXEMPT with the reason "
                    f"(opensrm-t4rd: three CRITICALs were exactly this)."
                )

    def test_no_raw_string_concatenation_in_a_covered_function(self):
        """`deps_yaml += "  - name: " + dep` would evade the f-string walk.

        `_build_resources_yaml` already builds with `+=`, so this is the
        idiomatic next edit there.
        """
        module = importlib.import_module(self.MODULE)
        tree = ast.parse(pathlib.Path(module.__file__).read_text(encoding="utf-8"))
        covered = set(self._covered())
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if fn.name not in covered:
                continue
            for node in ast.walk(fn):
                operands = []
                if isinstance(node, ast.AugAssign) and isinstance(node.op, ast.Add):
                    operands = [node.value]
                elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
                    operands = [node.left, node.right]
                for operand in operands:
                    if isinstance(operand, (ast.Constant, ast.JoinedStr)):
                        continue
                    wrapped = (
                        isinstance(operand, ast.Call)
                        and isinstance(operand.func, ast.Name)
                        and operand.func.id in self.WRAPPERS
                    )
                    assert wrapped, (
                        f"{fn.name} concatenates {ast.unparse(operand)!r} into "
                        f"generated YAML without a wrapper. The f-string walk "
                        f"cannot see concatenation, which is why this exists."
                    )

    def test_the_exempt_map_has_no_dead_entries(self):
        """A stale exemption would hide a field that no longer exists."""
        live = {ast.unparse(n) for ns in self._covered().values() for n in ns}
        dead = set(self.EXEMPT) - live
        assert not dead, (
            f"EXEMPT lists expressions no longer interpolated anywhere: "
            f"{sorted(dead)} -- remove them so the map stays honest"
        )

    def test_the_known_sensitive_fields_are_wrapped(self):
        """Asserts the positive directly, not just the absence of a negative."""
        live = {ast.unparse(n) for ns in self._covered().values() for n in ns}
        for expr in (
            "_yaml_scalar(service_name)",
            "_yaml_scalar(team)",
            "_yaml_scalar(template.name)",
            "_yaml_scalar(resource.kind)",
            "_yaml_scalar(resource.name)",
        ):
            assert expr in live, f"{expr} is no longer wrapped anywhere"


class TestSetupGuardStillDiverges:
    """A tripwire, not an endorsement (opensrm-h9fq).

    `specs/manifest.py` says its rule is not exhaustive because
    `cli/setup.py` keeps a third copy. That is a claim about another file, so
    it is asserted here rather than left as prose that can rot -- the
    ecosystem convention after six such comments went stale.

    When h9fq is fixed this test FAILS, which is the point: it forces the
    comment and the bead to be closed together.
    """

    # Measured against the real function, not a reimplementation of it:
    # setup.py DOES reject `svc-` (it checks both end characters), so that
    # one belongs in the agreeing set, not here.
    DIVERGENT = ["123", "caf\u00e9", "1-svc"]
    AGREED_REJECTED = ["svc-", "-svc", ""]

    def test_setup_accepts_names_the_shared_rule_rejects(self):
        for name in self.DIVERGENT:
            assert _setup_is_valid_service_name(name), (
                f"setup.py no longer accepts {name!r} -- if its guard now "
                f"delegates to the shared rule, close opensrm-h9fq and delete "
                f"this test plus the caveat in specs/manifest.py"
            )
            assert not is_valid_service_name(name), (
                f"the shared rule now accepts {name!r}; this table is stale"
            )

    def test_both_guards_already_agree_on_these(self):
        """The divergence is partial, so pin where it is NOT."""
        for name in self.AGREED_REJECTED:
            assert not _setup_is_valid_service_name(name)
            assert not is_valid_service_name(name)


class TestTemplateNameIsQuoted:
    """opensrm-t4rd iteration 3: `template:` was the last raw interpolation.

    Narrower than the others -- it needs a custom template file on disk -- but
    the same shape. And `template.name` is `data["name"]` straight from the
    loader with no coercion, and `ServiceTemplate.__post_init__` validates only
    `tier`, so a template declaring `name: on` makes it a bool. Routing it
    through `_yaml_scalar` without the non-str branch would have turned a
    silent corruption into a TypeError crash.
    """

    def test_a_template_named_on_does_not_corrupt_the_manifest(self, tmp_path, monkeypatch):
        templates = tmp_path / ".nthlayer" / "templates"
        templates.mkdir(parents=True)
        (templates / "t.yaml").write_text(
            "name: on\ndescription: d\ntier: standard\ntype: api\nresources: []\n"
        )

        loaded = TemplateLoader.load_from_file(templates / "t.yaml")
        # the fixture is only meaningful if the loader really hands back a bool
        assert loaded.name is True, (
            "template.name is no longer retyped by the loader; this case proves nothing"
        )

        doc = f"service:\n  name: svc\n  template: {_yaml_scalar(loaded.name)}\n"
        parsed = yaml.safe_load(doc)
        assert isinstance(parsed["service"]["template"], str)
        assert parsed["service"]["name"] == "svc"

    @pytest.mark.parametrize("value", [True, False, None, 123, 1.5])
    def test_a_non_string_is_quoted_not_raised(self, value):
        """`re.fullmatch` raises TypeError on a non-str, so the branch is needed."""
        emitted = _yaml_scalar(value)
        assert emitted.startswith('"') and emitted.endswith('"')
        assert yaml.safe_load(f"t: {emitted}\n")["t"] == str(value)


class TestValidatorSurvivesARetypedName:
    """opensrm-t4rd: the rule is fed whatever the loader resolved.

    Independent of init -- a hand-written manifest reaches this too, which is
    why the guard lives in the rule rather than at the call site.
    """

    @pytest.mark.parametrize(
        ("literal", "loads_as"),
        [("yes", True), ("no", False), ("null", None), ("123", 123), ("1.5", 1.5)],
    )
    def test_a_non_string_name_is_reported_not_raised(self, literal, loads_as, tmp_path):
        """Before the guard, `name: yes` made `fullmatch` raise TypeError.

        `nthlayer validate` died with a traceback instead of reporting the
        problem, so the operator saw a crash rather than an error message.
        """
        manifest = tmp_path / "svc.yaml"
        manifest.write_text(
            f"service:\n  name: {literal}\n  team: ops\n  tier: standard\n"
            f"  type: api\nresources: []\n"
        )
        # the fixture is only meaningful if the loader really retypes it
        assert yaml.safe_load(manifest.read_text())["service"]["name"] == loads_as

        result = validate_service_file(manifest)
        assert not result.valid
        assert any("name" in e.lower() for e in result.errors), result.errors

    def test_the_rule_rejects_non_str_directly(self):
        for value in (True, False, None, 123, 1.5, [], {}):
            assert is_valid_service_name(value) is False


class TestWritesAreExplicitlyUtf8:
    """opensrm-t4rd edge-case pass: the writes used the locale's encoding.

    `write_text(content)` encodes with `locale.getpreferredencoding()`. On a
    non-UTF-8 system an ordinary accented team name therefore raised
    UnicodeEncodeError -- which is a ValueError, NOT an OSError, so the
    `except OSError` handler missed it and init died by traceback. And
    `write_text` had already created the file, so a ZERO-BYTE manifest was left
    behind; every later run then hit the `exists()` guard and refused,
    permanently, until someone deleted it by hand.

    The diff had WIDENED this: `allow_unicode=True` emits non-ASCII literally,
    where escaping would have kept the output pure ASCII and survived any sink.

    An AST guard rather than a locale test, because pytest cannot portably
    change the interpreter's filesystem encoding mid-process, and a test that
    tried would skip on most machines -- the silent-skip failure mode this
    project has been bitten by twice.
    """

    def test_no_text_io_in_init_omits_an_explicit_encoding(self):
        module = importlib.import_module("nthlayer_generate.cli.init")
        tree = ast.parse(pathlib.Path(module.__file__).read_text(encoding="utf-8"))

        offenders = []
        checked = 0
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            # A method call (`path.write_text`, `io.open`) OR the bare `open()`
            # builtin. The first version read only `.attr`, which is None for a
            # plain Name call, so a bare `open("x")` without encoding= passed
            # untouched -- and bare `open()` is this repo's dominant idiom,
            # roughly 40 sites, so it is the likeliest future form.
            if isinstance(node.func, ast.Attribute):
                name = node.func.attr
                # `os.open` returns a file DESCRIPTOR and takes no encoding, so
                # demanding one would be wrong. Every other `.open` does.
                if name == "open" and getattr(node.func.value, "id", None) == "os":
                    continue
            elif isinstance(node.func, ast.Name):
                name = node.func.id
            else:
                continue
            # `NamedTemporaryFile` and `fdopen` are here because they are the
            # primitives an atomic create-or-fail write uses (opensrm-may6), so
            # the guard would otherwise go blind at the moment it matters most.
            # Both default to the locale's encoding in text mode. Verified
            # evasions before this list grew.
            if name not in (
                "write_text",
                "read_text",
                "open",
                "fdopen",
                "NamedTemporaryFile",
                "TemporaryFile",
                "SpooledTemporaryFile",
            ):
                continue
            checked += 1
            if not any(kw.arg == "encoding" for kw in node.keywords):
                offenders.append(f"{name}() at line {node.lineno}")

        assert checked >= 2, (
            f"found only {checked} text-IO calls in cli/init.py; this guard has "
            f"stopped matching, so it is inspecting almost nothing"
        )
        assert not offenders, (
            "text IO without an explicit encoding= in cli/init.py: "
            + ", ".join(offenders)
            + ". The locale's encoding is not UTF-8 everywhere, and a failed "
            "encode still leaves the file created but empty (opensrm-t4rd)."
        )

    def test_a_non_ascii_team_is_written_and_reads_back(self, tmp_path, monkeypatch):
        """End to end, through a real file rather than an in-memory encode."""
        monkeypatch.chdir(tmp_path)

        assert init_command("svc", "caf\u00e9 \U0001f389", None, interactive=False) == 0

        written = tmp_path / "svc.yaml"
        assert written.stat().st_size > 0
        loaded = yaml.safe_load(written.read_text(encoding="utf-8"))
        assert loaded["service"]["team"] == "caf\u00e9 \U0001f389"


class TestAFailedWriteLeavesNothingBehind:
    """opensrm-t4rd defect 3's rollback half, which was missing.

    A partial failure must not leave an artifact that blocks the next run.
    """

    @staticmethod
    def _raise_after_creating(exc):
        """Mimic `write_text`: create the file, then fail encoding it."""
        real = pathlib.Path.write_text

        def fake(self, *args, **kwargs):
            if self.name == "svc.yaml":
                self.touch()
                raise exc
            return real(self, *args, **kwargs)

        return fake

    @pytest.mark.parametrize(
        "exc",
        [
            UnicodeEncodeError("ascii", "x", 0, 1, "simulated"),
            OSError(28, "No space left on device"),
        ],
    )
    def test_exit_1_and_no_partial_manifest(self, exc, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)

        with patch.object(pathlib.Path, "write_text", self._raise_after_creating(exc)):
            assert init_command("svc", "ops", None, interactive=False) == 1

        assert not (tmp_path / "svc.yaml").exists(), (
            "a failed run left a partial manifest, which the exists() guard "
            "turns into a permanent refusal"
        )

    def test_a_rerun_after_a_failed_write_succeeds(self, tmp_path, monkeypatch):
        """The property that made the zero-byte file unrecoverable."""
        monkeypatch.chdir(tmp_path)

        with patch.object(
            pathlib.Path,
            "write_text",
            self._raise_after_creating(UnicodeEncodeError("ascii", "x", 0, 1, "s")),
        ):
            assert init_command("svc", "ops", None, interactive=False) == 1

        assert init_command("svc", "ops", None, interactive=False) == 0
        assert (tmp_path / "svc.yaml").stat().st_size > 0


class TestConfigFileShapes:
    """opensrm-t4rd edge-case pass: `exists()` again, one line up.

    `.nthlayer/config.yaml` was guarded by `exists()`, which is True when the
    path is a DIRECTORY -- so the write was skipped and init reported success
    for a config it had never written, with no warning. The identical
    confusion this bead fixed for `.nthlayer` itself.

    Asserted on the filesystem, not the console: `warning()` shells out to
    `gum` when it is installed, which bypasses capture entirely.
    """

    def test_a_directory_named_config_yaml_does_not_become_a_config(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".nthlayer").mkdir()
        (tmp_path / ".nthlayer" / "config.yaml").mkdir()

        assert init_command("svc", "ops", None, interactive=False) == 0

        config = tmp_path / ".nthlayer" / "config.yaml"
        assert config.is_dir(), "fixture no longer sets up a directory"
        assert not config.is_file()
        # the manifest, which is the primary artifact, is still correct
        assert (
            yaml.safe_load((tmp_path / "svc.yaml").read_text(encoding="utf-8"))["service"]["team"]
            == "ops"
        )

    def test_a_directory_named_config_yaml_is_reported_not_passed_over(self, tmp_path, monkeypatch):
        """The half the filesystem cannot show.

        With `exists()` instead of `is_file()` the state asserted above is
        IDENTICAL -- the write is skipped either way and the directory stays a
        directory. The only difference is whether the user is told, so that is
        what this asserts, by patching `warning` at init's own lookup path
        rather than reading the console: `ux.warning` shells out to `gum` when
        it is installed, which bypasses capsys entirely.
        """
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".nthlayer").mkdir()
        (tmp_path / ".nthlayer" / "config.yaml").mkdir()

        with patch("nthlayer_generate.cli.init.warning") as warned:
            assert init_command("svc", "ops", None, interactive=False) == 0

        said = " ".join(str(call) for call in warned.call_args_list)
        assert "config.yaml" in said, (
            f"init reported success without mentioning the config it never "
            f"wrote; warnings were: {warned.call_args_list}"
        )

    def test_a_normal_run_does_not_warn_about_the_config(self, tmp_path, monkeypatch):
        """Guards the assertion above against passing for the wrong reason."""
        monkeypatch.chdir(tmp_path)

        with patch("nthlayer_generate.cli.init.warning") as warned:
            assert init_command("svc", "ops", None, interactive=False) == 0

        said = " ".join(str(call) for call in warned.call_args_list)
        assert "config.yaml" not in said, f"unexpected warning: {warned.call_args_list}"

    def test_an_existing_config_file_is_not_overwritten(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".nthlayer").mkdir()
        config = tmp_path / ".nthlayer" / "config.yaml"
        config.write_text("# mine\n", encoding="utf-8")

        assert init_command("svc", "ops", None, interactive=False) == 0
        assert config.read_text(encoding="utf-8") == "# mine\n"


class TestInitIsNotSilentlyIdempotent:
    """A second run must refuse rather than overwrite, and leave the first alone."""

    def test_a_second_run_refuses_and_preserves_the_manifest(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)

        assert init_command("svc", "ops", None, interactive=False) == 0
        first = (tmp_path / "svc.yaml").read_bytes()

        assert init_command("svc", "other-team", None, interactive=False) == 1
        assert (tmp_path / "svc.yaml").read_bytes() == first, (
            "the refused run still modified the existing manifest"
        )


class TestTemplateResourceContainers:
    """`resource.kind`/`resource.name` arrive from a template file unvalidated.

    `_yaml_scalar` renders a non-str via `str(value)`, so a list or dict yields
    an ugly but harmless quoted scalar. What matters is that it stays ONE
    comment line and cannot reach the document body.
    """

    # The plain-str entries carry this class. `str()` of a CONTAINER renders a
    # newline as `\n` inside a repr, so no container value can break the line --
    # with only those, this class passed with the escaping removed entirely
    # (opensrm-t4rd edge-case pass, iteration 2).
    @pytest.mark.parametrize(
        "value",
        [
            "a\nb",
            "x\nservice:\n  name: hijacked",
            # pyyaml's scan_line_break treats all four of these as line breaks,
            # so each can end the comment and start a key. The earlier
            # `count("\n") == 0` assertion was blind to every one of them.
            "ok\rinjected: 1",
            "ok\u0085injected: 1",
            "ok\u2028injected: 1",
            "ok\u2029injected: 1",
            None,
            [1, 2],
            {"a": "x\ny"},
            [[1], [2]],
            1.5,
            True,
        ],
    )
    def test_a_container_stays_one_comment_line(self, value):
        resource = MagicMock()
        resource.kind = "SLO"
        resource.name = value
        template = MagicMock()
        template.resources = [resource]

        rendered = _format_template_resources(template)

        # Parse it, rather than looking for "\n". A comment can be ended by CR,
        # NEL, LS or PS as well as LF, and the previous assertion saw none of
        # them -- so `ok\rinjected: 1` satisfied it while adding a key
        # (opensrm-t4rd edge-case pass, iteration 3).
        document = f"service:\n  name: svc\n  team: ops\n{rendered}\n"
        parsed = yaml.safe_load(document)

        assert set(parsed) == {"service"}, (
            f"{value!r} escaped the comment and added {sorted(set(parsed) - {'service'})}"
        )
        assert parsed["service"] == {"name": "svc", "team": "ops"}
        assert rendered.lstrip().startswith("#")


class TestNthlayerDirFalseSuccess:
    """opensrm-t4rd defect 3: success was reported for a directory not created."""

    def test_a_file_named_nthlayer_does_not_produce_a_success_line(
        self, tmp_path, monkeypatch, capsys
    ):
        """`.nthlayer` as a regular FILE.

        mkdir raises FileExistsError and the config write raises
        NotADirectoryError; both are OSError, so both are downgraded to warnings.
        The old check was `nthlayer_dir.exists()`, True *because it is a file*, so
        init printed "Created .nthlayer/" for a directory it had not created.
        """
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".nthlayer").write_text("not a directory")

        # ux.warning() shells out to `gum` when it is installed, which writes to
        # the real file descriptor and so bypasses capsys entirely. Forced off,
        # or this test would pass or fail depending on whether the machine has
        # gum — measured: it is installed here, and the warning was invisible.
        monkeypatch.setattr("nthlayer_generate.cli.ux.has_gum", lambda: False)

        rc = init_command("svc", "ops", None, interactive=False)
        out = capsys.readouterr().out

        # Structured state first: this part cannot depend on how output is rendered.
        assert not (tmp_path / ".nthlayer").is_dir(), "no directory should exist"
        assert not (tmp_path / ".nthlayer" / "config.yaml").exists(), "no config written"

        assert "Created .nthlayer/" not in out, "claimed to create a directory it did not"
        assert "was not created" in out, "the failure must be stated, not merely implied"

        assert (tmp_path / ".nthlayer").is_file(), "the pre-existing file must be untouched"
        assert (tmp_path / "svc.yaml").exists(), "the manifest is the primary artifact"
        assert rc == 0, (
            "deliberately NOT fatal: the manifest was written correctly, so a CI "
            "gate keying on the exit code is right to pass (opensrm-t4rd)"
        )
