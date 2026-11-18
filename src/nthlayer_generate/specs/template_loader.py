"""Template loader for NthLayer service templates."""

from pathlib import Path
from typing import Any, Dict

import structlog
import yaml

from nthlayer_generate.core.errors import ConfigurationError

from .models import Resource
from .templates import ServiceTemplate, TemplateRegistry

logger = structlog.get_logger()

# The fields every template file must declare, each as a non-blank string.
_REQUIRED_STRING_FIELDS = ("name", "description", "tier", "type")


class TemplateFieldError(ValueError):
    """A required template field is not a non-blank string.

    YAML reads an unquoted ``on``, ``yes``, ``no``, ``true``, ``false``,
    ``null``, a bare number or a date as something other than a string, so a
    file declaring ``name: on`` has a bool for a name (opensrm-dpf8).
    """

    def __init__(self, path: Path, field: str, value: Any) -> None:
        self.path = path
        self.field = field
        self.value = value
        super().__init__(
            f"Template field '{field}' must be a non-empty string, got "
            f"{type(value).__name__} ({value!r}) in template: {path}. "
            "Quote the value if YAML reads it as another type."
        )


class TemplateLoader:
    """Loads service templates from YAML files."""

    @staticmethod
    def load_from_file(path: Path) -> ServiceTemplate:
        """Load single template from YAML file.

        Args:
            path: Path to template YAML file

        Returns:
            ServiceTemplate object

        Raises:
            FileNotFoundError: If template file doesn't exist
            ValueError: If template YAML is invalid
        """
        if not path.exists():
            raise FileNotFoundError(f"Template file not found: {path}")

        with open(path) as f:
            data = yaml.safe_load(f)

        if not data:
            raise ValueError(f"Empty template file: {path}")
        if not isinstance(data, dict):
            raise ValueError(f"Template file is not a mapping: {path}")

        # Validate required fields: present, and strings. The registry is
        # keyed by name and the CLI joins and prints these values, so a bool
        # or None from YAML must stop here, at the boundary.
        for field in _REQUIRED_STRING_FIELDS:
            if field not in data:
                raise ValueError(f"Missing required field '{field}' in template: {path}")
            value = data[field]
            if not isinstance(value, str) or not value.strip():
                raise TemplateFieldError(path, field, value)

        # Parse resources (no context yet - added during application)
        resources = []
        for resource_data in data.get("resources", []):
            # Create resource without context (will be added when applied)
            resource = Resource(
                kind=resource_data["kind"],
                name=resource_data["name"],
                spec=resource_data.get("spec", {}),
                context=None,  # Context added when template is applied
            )
            resources.append(resource)

        return ServiceTemplate(
            name=data["name"],
            description=data["description"],
            tier=data["tier"],
            type=data["type"],
            resources=resources,
        )

    @staticmethod
    def load_builtin() -> TemplateRegistry:
        """Load all built-in templates from builtin_templates directory.

        Returns:
            TemplateRegistry with all built-in templates

        Raises:
            RuntimeError: If builtin templates directory doesn't exist
        """
        templates_dir = Path(__file__).parent / "builtin_templates"

        if not templates_dir.exists():
            raise ConfigurationError(f"Built-in templates directory not found: {templates_dir}")

        templates: Dict[str, ServiceTemplate] = {}

        for yaml_file in sorted(templates_dir.glob("*.yaml")):
            try:
                template = TemplateLoader.load_from_file(yaml_file)
                templates[template.name] = template
            except Exception as e:
                # Log warning but continue loading other templates
                logger.warning("Failed to load template %s: %s", yaml_file.name, e)

        return TemplateRegistry(templates=templates)
