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


# The longest repr of an offending value quoted in an error message. The
# callers print the message as a warning, and YAML can put anything there.
_MAX_VALUE_REPR = 80


class TemplateFieldError(ValueError):
    """A required template field is not a non-blank string.

    YAML reads an unquoted ``on``, ``yes``, ``no``, ``true``, ``false``,
    ``null``, a bare number or a date as something other than a string, so a
    file declaring ``name: on`` has a bool for a name (opensrm-dpf8).

    ``problem`` is ``"blank"`` for a string that is empty or only whitespace
    and ``"not_a_string"`` for any other type; ``value`` is the value as loaded.
    """

    def __init__(self, path: Path, field: str, value: Any) -> None:
        # The three arguments are the exception's args, so copy and pickle
        # can rebuild it; the message is composed in __str__.
        super().__init__(path, field, value)
        self.path = path
        self.field = field
        self.value = value
        self.problem = "blank" if isinstance(value, str) else "not_a_string"

    def __str__(self) -> str:
        if self.problem == "blank":
            return f"Template field '{self.field}' is blank in template: {self.path}."
        shown = repr(self.value)
        if len(shown) > _MAX_VALUE_REPR:
            shown = shown[:_MAX_VALUE_REPR] + "..."
        return (
            f"Template field '{self.field}' must be a string, got "
            f"{type(self.value).__name__} ({shown}) in template: {self.path}. "
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
            ValueError: If the file is empty, is not a mapping, or is missing
                a required field
            TemplateFieldError: If name, description, tier or type is not a
                non-blank string (a ValueError)
        """
        if not path.exists():
            raise FileNotFoundError(f"Template file not found: {path}")

        with open(path, encoding="utf-8") as f:
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
