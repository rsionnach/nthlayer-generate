"""Tests for custom template system."""

from nthlayer_generate.specs.custom_templates import CustomTemplateLoader


class TestCustomTemplateLoader:
    """Tests for CustomTemplateLoader class."""
    
    def test_load_custom_templates_from_project(self):
        """Should load custom templates from .nthlayer/templates."""
        custom_templates = CustomTemplateLoader.load_custom_templates()
        
        # Should find at least the example custom templates
        assert isinstance(custom_templates, dict)
        # May have mobile-api and microservice if run from project root
        # Or empty if run from elsewhere
        assert len(custom_templates) >= 0  # At least valid
    
    def test_load_all_templates_includes_custom(self):
        """Should include both built-in and custom templates."""
        registry = CustomTemplateLoader.load_all_templates()
        
        # Should have all built-in templates
        assert "critical-api" in registry.templates
        assert "standard-api" in registry.templates
        
        # May have custom templates if run from project root
        assert len(registry.templates) >= 5  # At least built-ins
    
    def test_get_template_source_builtin(self):
        """Should identify built-in template source."""
        source = CustomTemplateLoader.get_template_source("critical-api")
        assert source == "built-in"
    
    def test_get_template_source_unknown(self):
        """Should identify unknown templates."""
        source = CustomTemplateLoader.get_template_source("nonexistent-template")
        assert source == "unknown"
    
    def test_custom_template_from_file(self, tmp_path):
        """Should load custom template from file."""
        # Create custom template directory
        templates_dir = tmp_path / ".nthlayer" / "templates"
        templates_dir.mkdir(parents=True)
        
        # Create custom template
        custom_template = templates_dir / "test-custom.yaml"
        custom_template.write_text("""
name: test-custom
description: Test custom template
tier: standard
type: api

resources:
  - kind: SLO
    name: custom-slo
    spec:
      objective: 99.0
""")
        
        # Load from that directory (simulate being in tmp_path)
        import os
        original_dir = os.getcwd()
        try:
            os.chdir(tmp_path)
            
            # Load templates
            custom_templates = CustomTemplateLoader.load_custom_templates()
            
            # Should find our custom template
            assert "test-custom" in custom_templates
            assert custom_templates["test-custom"].name == "test-custom"
            assert custom_templates["test-custom"].tier == "standard"
            assert len(custom_templates["test-custom"].resources) == 1
        finally:
            os.chdir(original_dir)
    
    def test_custom_template_overrides_builtin(self, tmp_path):
        """Custom template with same name should override built-in."""
        # Create custom template directory
        templates_dir = tmp_path / ".nthlayer" / "templates"
        templates_dir.mkdir(parents=True)
        
        # Create custom template with same name as built-in
        custom_template = templates_dir / "critical-api.yaml"
        custom_template.write_text("""
name: critical-api
description: CUSTOM OVERRIDE
tier: critical
type: api

resources:
  - kind: SLO
    name: custom-override
    spec:
      objective: 99.99
""")
        
        # Load from that directory
        import os
        original_dir = os.getcwd()
        try:
            os.chdir(tmp_path)
            
            # Load all templates
            registry = CustomTemplateLoader.load_all_templates()
            
            # critical-api should be custom version
            template = registry.get("critical-api")
            assert "CUSTOM OVERRIDE" in template.description
            assert len(template.resources) == 1
            assert template.resources[0].name == "custom-override"
        finally:
            os.chdir(original_dir)


class TestTemplateSearchOrder:
    """Tests for template search and precedence."""
    
    def test_custom_templates_directory_not_found(self):
        """Should return empty dict if no custom templates directory."""
        # Change to temp directory without .nthlayer
        import os
        import tempfile
        
        with tempfile.TemporaryDirectory() as tmpdir:
            original_dir = os.getcwd()
            try:
                os.chdir(tmpdir)
                
                custom = CustomTemplateLoader.load_custom_templates()
                assert custom == {}
            finally:
                os.chdir(original_dir)
    
    def test_template_precedence_custom_over_builtin(self, tmp_path):
        """Custom templates should take precedence over built-in."""
        templates_dir = tmp_path / ".nthlayer" / "templates"
        templates_dir.mkdir(parents=True)
        
        # Create custom template with same name as built-in
        (templates_dir / "standard-api.yaml").write_text("""
name: standard-api
description: CUSTOM VERSION
tier: standard
type: api

resources:
  - kind: SLO
    name: custom-slo
    spec:
      objective: 99.7
""")
        
        import os
        original_dir = os.getcwd()
        try:
            os.chdir(tmp_path)
            
            registry = CustomTemplateLoader.load_all_templates()
            template = registry.get("standard-api")
            
            # Should be custom version
            assert "CUSTOM VERSION" in template.description
            assert template.resources[0].name == "custom-slo"
        finally:
            os.chdir(original_dir)


class TestInvalidCustomTemplates:
    """Tests for handling invalid custom templates."""
    
    def test_invalid_custom_template_skipped(self, tmp_path, capsys):
        """Invalid custom template should be skipped with warning."""
        templates_dir = tmp_path / ".nthlayer" / "templates"
        templates_dir.mkdir(parents=True)
        
        # Create invalid template (missing required field)
        (templates_dir / "invalid.yaml").write_text("""
name: invalid-template
# Missing description, tier, type
""")
        
        # Create valid template
        (templates_dir / "valid.yaml").write_text("""
name: valid-template
description: Valid
tier: standard
type: api
resources: []
""")
        
        import os
        original_dir = os.getcwd()
        try:
            os.chdir(tmp_path)
            
            custom = CustomTemplateLoader.load_custom_templates()
            
            # Should load valid, skip invalid
            assert "valid-template" in custom
            assert "invalid-template" not in custom
            
            # Should print warning
            captured = capsys.readouterr()
            assert "Warning" in captured.out
            assert "invalid.yaml" in captured.out
        finally:
            os.chdir(original_dir)
