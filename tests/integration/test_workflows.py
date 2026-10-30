"""Integration tests for end-to-end workflows."""

from nthlayer_generate.cli.generate import generate_slo_command
from nthlayer_generate.cli.init import init_command
from nthlayer_generate.cli.validate import validate_command


class TestEndToEndWorkflows:
    """Test complete user workflows from init to generation."""

    def test_init_validate_generate_workflow(self, tmp_path, monkeypatch):
        """Complete happy path: init → validate → generate."""
        monkeypatch.chdir(tmp_path)

        # 1. Init service
        result = init_command("test-api", "test-team", "critical-api", interactive=False)
        assert result == 0
        assert (tmp_path / "test-api.yaml").exists()

        # 2. Validate
        result = validate_command(str(tmp_path / "test-api.yaml"))
        assert result == 0

        # 3. Generate SLOs
        result = generate_slo_command(
            str(tmp_path / "test-api.yaml"), output_dir=str(tmp_path / "generated"), format="sloth"
        )
        assert result == 0
        assert (tmp_path / "generated" / "sloth" / "test-api.yaml").exists()

        # 4. Verify generated SLOs
        sloth_file = tmp_path / "generated" / "sloth" / "test-api.yaml"
        import yaml

        with open(sloth_file) as f:
            sloth_spec = yaml.safe_load(f)

        assert sloth_spec["service"] == "test-api"
        assert len(sloth_spec["slos"]) == 2  # From critical-api template

    def test_all_templates_workflow(self, tmp_path, monkeypatch):
        """Test workflow works for all templates."""
        monkeypatch.chdir(tmp_path)

        templates = ["critical-api", "standard-api", "low-api", "background-job", "pipeline"]

        for template in templates:
            service_name = f"test-{template}"

            # Init
            result = init_command(service_name, "team", template, interactive=False)
            assert result == 0

            # Validate
            service_file = tmp_path / f"{service_name}.yaml"
            result = validate_command(str(service_file))
            assert result == 0

            # Generate
            result = generate_slo_command(
                str(service_file), output_dir=str(tmp_path / "generated"), format="sloth"
            )
            assert result == 0

            # Verify
            sloth_file = tmp_path / "generated" / "sloth" / f"{service_name}.yaml"
            assert sloth_file.exists()


class TestErrorHandling:
    """Test error handling in workflows."""

    def test_invalid_service_name_in_init(self, tmp_path, monkeypatch):
        """Init should reject invalid service names."""
        monkeypatch.chdir(tmp_path)

        result = init_command(
            "InvalidName",  # Uppercase not allowed
            "team",
            "critical-api",
            interactive=False,
        )

        assert result == 1  # Error

    def test_unknown_template_in_init(self, tmp_path, monkeypatch):
        """Init should reject unknown templates."""
        monkeypatch.chdir(tmp_path)

        result = init_command("test-api", "team", "nonexistent-template", interactive=False)

        assert result == 1  # Error


class TestRealWorldScenarios:
    """Test realistic scenarios users might encounter."""

    def test_multiple_services_in_project(self, tmp_path, monkeypatch):
        """Multiple services can coexist in same project."""
        monkeypatch.chdir(tmp_path)

        services = [
            ("payment-api", "payments", "critical-api"),
            ("admin-api", "platform", "standard-api"),
            ("email-worker", "notifications", "background-job"),
        ]

        for name, team, template in services:
            # Init each service
            result = init_command(name, team, template, interactive=False)
            assert result == 0

            # Validate each
            result = validate_command(str(tmp_path / f"{name}.yaml"))
            assert result == 0

            # Generate each
            result = generate_slo_command(
                str(tmp_path / f"{name}.yaml"), output_dir=str(tmp_path / "generated")
            )
            assert result == 0

        # All services should have their own SLO files
        assert (tmp_path / "generated" / "sloth" / "payment-api.yaml").exists()
        assert (tmp_path / "generated" / "sloth" / "admin-api.yaml").exists()
        assert (tmp_path / "generated" / "sloth" / "email-worker.yaml").exists()

    def test_config_file_shared_across_services(self, tmp_path, monkeypatch):
        """Config file is created once and shared."""
        monkeypatch.chdir(tmp_path)

        # Init first service
        init_command("service1", "team", "critical-api", interactive=False)
        assert (tmp_path / ".nthlayer" / "config.yaml").exists()

        # Modify config
        config_file = tmp_path / ".nthlayer" / "config.yaml"
        config_file.write_text("custom: config")

        # Init second service
        init_command("service2", "team", "standard-api", interactive=False)

        # Config should not be overwritten
        assert config_file.read_text() == "custom: config"
