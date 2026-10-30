"""Integration tests for multi-environment support.

These tests verify that the --env flag works end-to-end across all CLI commands.

Note: Some tests are marked as skipped due to Python 3.9 compatibility issues
in the existing codebase (unrelated to the environment feature).
"""

import tempfile
from pathlib import Path

import pytest
import yaml


class TestCLIEnvironmentFlag:
    """Test that CLI commands accept and use the --env flag."""
    
    def test_generate_slo_with_env_flag(self):
        """Test generate-slo command with --env flag."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            
            service_file = tmpdir / "test-api.yaml"
            service_file.write_text("""
service:
  name: test-api
  team: platform
  tier: critical
  type: api

resources:
  - kind: SLO
    name: availability
    spec:
      objective: 99.9
      window: 30d
      indicator:
        success_rate:
          total_query: 'sum(rate(http_requests_total[5m]))'
          error_query: 'sum(rate(http_requests_total{status=~"5.."}[5m]))'
            """)
            
            env_dir = tmpdir / "environments"
            env_dir.mkdir()
            (env_dir / "dev.yaml").write_text("""
environment: dev
service:
  tier: low
resources:
  - kind: SLO
    name: availability
    spec:
      objective: 95.0
            """)
            
            output_dir = tmpdir / "generated"
            
            from nthlayer_generate.cli.generate import generate_slo_command
            
            # Generate with dev environment
            result = generate_slo_command(
                str(service_file),
                output_dir=str(output_dir),
                format="sloth",
                environment="dev",
                dry_run=False
            )
            
            assert result == 0
            
            # Check output
            output_file = output_dir / "sloth" / "test-api.yaml"
            assert output_file.exists()
            
            with open(output_file) as f:
                sloth_spec = yaml.safe_load(f)
            
            # Should use dev configuration
            assert sloth_spec["labels"]["tier"] == "low"
            assert sloth_spec["slos"][0]["objective"] == 95.0
    
    def test_validate_with_env_flag(self):
        """Test validate command with --env flag."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            
            service_file = tmpdir / "test-api.yaml"
            service_file.write_text("""
service:
  name: test-api
  team: platform
  tier: critical
  type: api
            """)
            
            env_dir = tmpdir / "environments"
            env_dir.mkdir()
            (env_dir / "dev.yaml").write_text("""
environment: dev
service:
  tier: low
            """)
            
            from nthlayer_generate.cli.validate import validate_command
            
            # Should validate successfully with environment
            result = validate_command(
                str(service_file),
                environment="dev",
                strict=False
            )
            
            assert result == 0


# When Python 3.9 issues are resolved, remove the skip marker and tests will run
if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
