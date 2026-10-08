"""Tests for init command."""

from unittest.mock import MagicMock, patch

import pytest

from nthlayer_generate.cli.init import (
    SERVICE_TYPES,
    _build_resources_yaml,
    _format_template_resources,
    _generate_config_yaml,
    _generate_service_yaml,
    _generate_service_yaml_v2,
    _is_valid_service_name,
    init_command,
)


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
    """Tests for service name validation."""

    def test_valid_service_names(self):
        """Should accept valid service names."""
        valid_names = [
            "my-api",
            "payment-api",
            "user-service",
            "api-v2",
            "service123",
            "my-api-v1",
        ]

        for name in valid_names:
            assert _is_valid_service_name(name), f"{name} should be valid"

    def test_invalid_service_names(self):
        """Should reject invalid service names."""
        invalid_names = [
            "MyApi",  # uppercase
            "my_api",  # underscore
            "my api",  # space
            "-my-api",  # starts with hyphen
            "my-api-",  # ends with hyphen
            "my--api",  # double hyphen is ok actually
            "",  # empty
            "my.api",  # period
        ]

        for name in invalid_names:
            if name == "my--api":
                # Double hyphen is actually valid
                assert _is_valid_service_name(name)
            else:
                assert not _is_valid_service_name(name), f"{name} should be invalid"

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
        import yaml

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

    They did. `cli/init.py`'s guard looped over `char.islower() or
    char.isdigit()`, which are UNICODE predicates, and rejected only a leading or
    trailing hyphen. `specs/validator.py` applied `^[a-z][a-z0-9-]*$`. So
    `nthlayer init 1-svc --team ops` exited 0, wrote the file, and `nthlayer
    validate` on that file exited 1 — and an exit code is what a CI gate keys on.

    PROVENANCE OF THIS TABLE. It is derived from the shared rule in
    specs/manifest.py, which is generate's authority for names it GENERATES, not
    from what either old guard happened to accept. It is deliberately not derived
    from opensrm's schema, because the schema does not constrain the field init
    writes: v1 `properties.service.properties.name` is unconstrained, and v1
    `definitions.Metadata.properties.name` is `^[a-z0-9-]+$`, which is LOOSER —
    it admits `1-svc` and even `-svc`. The bead's acceptance asked for a
    schema-derived table; that is not available for this field, and saying so is
    part of the finding. The spec gap is tracked separately.
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
    ]

    @pytest.mark.parametrize(("name", "expected"), NAMES)
    def test_guard_matches_the_shared_rule(self, name, expected):
        from nthlayer_generate.cli.init import _is_valid_service_name
        from nthlayer_generate.specs.manifest import is_valid_service_name

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
        import re

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
        import yaml

        data = yaml.safe_load(written.read_text())
        assert data["service"]["team"] == "Platform: Core"
        assert data["service"]["name"] == "svc", "team must not be able to reach name"

        from nthlayer_generate.specs.validator import validate_service_file

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
        from nthlayer_generate.specs.validator import validate_service_file

        accepted = [n for n, ok in TestServiceNameRuleIsShared.NAMES if ok]
        assert accepted, "vacuous: no accepted names to check"

        for name in accepted:
            d = tmp_path / name
            d.mkdir()
            monkeypatch.chdir(d)
            assert init_command(name, "ops", None, interactive=False) == 0
            result = validate_service_file(d / f"{name}.yaml")
            assert result.valid, f"init accepted {name!r} but its validator rejects it: {result.errors}"


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

    def test_every_hostile_value_is_actually_hostile(self):
        """Provenance guard: each fixture must be a value the loader retypes.

        Traces the table to the authority (what pyyaml actually does) rather
        than to `_emits_as_same_string`, which is the code under test.
        """
        import yaml

        for value in self.HOSTILE:
            loaded = yaml.safe_load(value)
            assert not (isinstance(loaded, str) and loaded == value), (
                f"{value!r} is no longer retyped by the loader "
                f"(got {loaded!r}); it no longer proves anything -- "
                f"replace or remove it"
            )

    @pytest.mark.parametrize("team", HOSTILE)
    def test_hostile_team_round_trips_as_the_exact_string(
        self, team, tmp_path, monkeypatch
    ):
        """init must write a team that reads back as the string it was given.

        Before the fix, measured at exit 0: `--team null` loaded as None and the
        validator then rejected the manifest; `--team yes` loaded as True and
        the manifest VALIDATED CLEAN carrying a bool in a field declared `str`;
        `--team 'ops '` silently lost its trailing space.
        """
        import yaml

        monkeypatch.chdir(tmp_path)

        assert init_command("svc", team, None, interactive=False) == 0

        written = tmp_path / "svc.yaml"
        data = yaml.safe_load(written.read_text())
        assert isinstance(data["service"]["team"], str), (
            f"--team {team!r} was implicitly retyped to "
            f"{type(data['service']['team']).__name__}"
        )
        assert data["service"]["team"] == team

    @pytest.mark.parametrize("team", HOSTILE)
    def test_hostile_team_still_passes_the_real_validator(
        self, team, tmp_path, monkeypatch
    ):
        """The exit-0-then-invalid shape, which is the bead's whole subject."""
        from nthlayer_generate.specs.validator import validate_service_file

        monkeypatch.chdir(tmp_path)

        assert init_command("svc", team, None, interactive=False) == 0

        result = validate_service_file(tmp_path / "svc.yaml")
        assert result.valid, (
            f"init exited 0 writing a manifest its own validator rejects "
            f"for --team {team!r}: {result.errors}"
        )


class TestQuotedTeamRoundTrips:
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
        "\U0001F389 platform",  # non-BMP: json emits a surrogate PAIR
        "\U0001D11E",
        "\U0010FFFF",
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
        "caf\u00e9",  # BMP non-ASCII
        "\u1e93algo",
        "\u00a0",  # NBSP
    ]

    CORPUS = HAZARDS + STRUCTURAL

    def test_hazards_are_provable_hazards(self):
        """Provenance guard: every HAZARDS entry must be demonstrably hostile.

        Derived from what `json` and `yaml` actually do, never from
        `_quoted_yaml_scalar`, which is the code under test.
        """
        import json

        import yaml

        for value in self.HAZARDS:
            try:
                json_round_trips = (
                    yaml.safe_load(f"t: {json.dumps(value)}\n")["t"] == value
                )
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
        import yaml

        from nthlayer_generate.cli.init import _yaml_scalar

        doc = f"service:\n  name: svc\n  team: {_yaml_scalar(team)}\n"
        loaded = yaml.safe_load(doc)
        assert loaded["service"]["team"] == team
        assert loaded["service"]["name"] == "svc", "team must not reach name"

    @pytest.mark.parametrize("team", CORPUS)
    def test_team_survives_a_utf8_write(self, team):
        """A value holding lone surrogates cannot be written to a file at all.

        The surrogate-pair defect produced exactly that, and `.encode("utf-8")`
        refuses it -- so this is the assertion that would have caught it even
        without a round-trip comparison.
        """
        import yaml

        from nthlayer_generate.cli.init import _yaml_scalar

        doc = f"service:\n  team: {_yaml_scalar(team)}\n"
        assert yaml.safe_load(doc.encode("utf-8"))["service"]["team"] == team

    @pytest.mark.parametrize("team", CORPUS)
    def test_emitted_scalar_never_spans_lines(self, team):
        """The document is built by interpolation, so a newline would corrupt it."""
        from nthlayer_generate.cli.init import _yaml_scalar

        assert "\n" not in _yaml_scalar(team)

    @pytest.mark.parametrize("team", CORPUS)
    def test_quoted_form_carries_no_document_end_marker(self, team):
        """Why `_quoted_yaml_scalar` strips only the trailing newline.

        Asserted on the quoted branch specifically: an unquoted plain scalar may
        legitimately end in `...` (see `ops...` in STRUCTURAL).
        """
        from nthlayer_generate.cli.init import _quoted_yaml_scalar

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
        from nthlayer_generate.cli.init import _quoted_yaml_scalar

        assert _quoted_yaml_scalar("caf\u00e9") == '"caf\u00e9"'
        assert "\\x" not in _quoted_yaml_scalar("caf\u00e9")

    def test_init_does_not_crash_on_a_value_pyyaml_cannot_parse(
        self, tmp_path, monkeypatch
    ):
        """`--team 0b_` raised an uncaught ValueError and wrote nothing.

        pyyaml's int constructor reaches `int("", 2)` for this input, which is a
        ValueError, not a YAMLError.
        """
        import yaml

        from nthlayer_generate.specs.validator import validate_service_file

        monkeypatch.chdir(tmp_path)

        assert init_command("svc", "0b_", None, interactive=False) == 0

        written = tmp_path / "svc.yaml"
        assert yaml.safe_load(written.read_text())["service"]["team"] == "0b_"
        assert validate_service_file(written).valid

    @pytest.mark.parametrize(
        "team", ["\U0001F389 platform", "caf\u00e9", "\U0001D11E"]
    )
    def test_non_ascii_team_survives_init_end_to_end(
        self, team, tmp_path, monkeypatch
    ):
        """The regression, end to end: emoji round-tripped before the first fix."""
        import yaml

        from nthlayer_generate.specs.validator import validate_service_file

        monkeypatch.chdir(tmp_path)

        assert init_command("svc", team, None, interactive=False) == 0

        written = tmp_path / "svc.yaml"
        assert yaml.safe_load(written.read_text())["service"]["team"] == team
        assert validate_service_file(written).valid


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
