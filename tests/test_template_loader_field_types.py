"""A template file's name, description, tier and type must be strings (opensrm-dpf8).

YAML reads several unquoted scalars as something other than a string: `on`,
`yes`, `no`, `true` and `false` as booleans, `null` and `~` as None, bare
numbers as int or float, an ISO date as a date. A template declaring
`name: on` therefore loaded with a bool for a name, the registry gained a
bool key, and `nthlayer init --template <unknown>` died joining the template
names for its error message.

Fixture provenance: every malformed value below is YAML text, and each test
first checks what `yaml.safe_load` makes of it, so the cases come from what
YAML does and not from what the loader accepts. The well-formed fields are
those of the built-in templates (specs/builtin_templates/*.yaml).
"""

from __future__ import annotations

import copy
import pickle
from pathlib import Path

import pytest
import yaml

from nthlayer_generate.cli.init import init_command
from nthlayer_generate.specs.custom_templates import CustomTemplateLoader
from nthlayer_generate.specs.template_loader import TemplateFieldError, TemplateLoader

BUILTIN_TEMPLATE_NAMES = {
    "background-job",
    "critical-api",
    "low-api",
    "pipeline",
    "standard-api",
}

# The four fields a template must declare, with a value a built-in uses.
WELL_FORMED = {
    "name": "team-api",
    "description": "An API template",
    "tier": "standard",
    "type": "api",
}

FIELDS = sorted(WELL_FORMED)
# At import: a parametrize over an empty list would collect nothing.
assert FIELDS, "no required template fields listed"

# YAML text that is not a non-blank string once loaded.
NOT_A_STRING = [
    pytest.param("on", id="on"),
    pytest.param("yes", id="yes"),
    pytest.param("no", id="no"),
    pytest.param("true", id="true"),
    pytest.param("false", id="false"),
    pytest.param("null", id="null"),
    pytest.param("~", id="tilde"),
    pytest.param("123", id="int"),
    pytest.param("1.5", id="float"),
    pytest.param("2026-01-01", id="date"),
    pytest.param("[a, b]", id="list"),
    pytest.param("{a: b}", id="mapping"),
    pytest.param('""', id="empty"),
    pytest.param('"   "', id="blank"),
]


def _template_text(**overrides: str) -> str:
    """A template file's text; *overrides* are raw YAML for a field's value."""
    fields = {key: f'"{value}"' for key, value in WELL_FORMED.items()}
    fields.update(overrides)
    lines = [f"{key}: {value}" for key, value in fields.items()]
    return "\n".join(lines) + "\nresources: []\n"


def _write(path: Path, **overrides: str) -> Path:
    path.write_text(_template_text(**overrides), encoding="utf-8")
    return path


def test_well_formed_template_loads(tmp_path: Path) -> None:
    template = TemplateLoader.load_from_file(_write(tmp_path / "team-api.yaml"))

    assert (template.name, template.description, template.tier, template.type) == (
        "team-api",
        "An API template",
        "standard",
        "api",
    )


@pytest.mark.parametrize("field", FIELDS)
@pytest.mark.parametrize("raw", NOT_A_STRING)
def test_field_that_is_not_a_string_is_rejected(tmp_path: Path, field: str, raw: str) -> None:
    path = _write(tmp_path / "malformed.yaml", **{field: raw})
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))[field]
    assert not (isinstance(loaded, str) and loaded.strip()), "YAML reads this as a string"

    with pytest.raises(TemplateFieldError) as excinfo:
        TemplateLoader.load_from_file(path)

    assert (excinfo.value.path, excinfo.value.field) == (path, field)
    assert excinfo.value.value == loaded


def test_quoted_name_that_looks_like_a_boolean_is_a_string(tmp_path: Path) -> None:
    """Quoting is the fix the error message recommends: `name: "on"` loads."""
    template = TemplateLoader.load_from_file(_write(tmp_path / "on.yaml", name='"on"'))

    assert template.name == "on"


def test_template_file_that_is_not_a_mapping_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "list.yaml"
    path.write_text("- name: team-api\n", encoding="utf-8")

    with pytest.raises(ValueError):
        TemplateLoader.load_from_file(path)


def test_builtin_templates_still_load() -> None:
    registry = TemplateLoader.load_builtin()

    assert set(registry.templates) == BUILTIN_TEMPLATE_NAMES


@pytest.fixture
def project_with_a_boolean_named_template(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A project whose .nthlayer/templates holds one template named `on`."""
    templates = tmp_path / ".nthlayer" / "templates"
    templates.mkdir(parents=True)
    _write(templates / "on.yaml", name="on")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_malformed_custom_template_is_left_out_of_the_registry(
    project_with_a_boolean_named_template: Path,
) -> None:
    registry = CustomTemplateLoader.load_all_templates()

    assert set(registry.templates) == BUILTIN_TEMPLATE_NAMES


def test_init_reports_an_unknown_template_beside_a_malformed_one(
    project_with_a_boolean_named_template: Path,
) -> None:
    """The user asked for a template that does not exist. They get exit 1,
    not a TypeError from listing the available templates."""
    code = init_command(
        service_name="my-api", team="my-team", template="no-such-template", interactive=False
    )

    assert code == 1
    assert not (project_with_a_boolean_named_template / "my-api.yaml").exists()


# --- the error itself (opensrm-dpf8, edge cases) ------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        pytest.param('""', id="empty"),
        pytest.param('"   "', id="spaces"),
        pytest.param('"\\t\\n"', id="tab-newline"),
        pytest.param('"\\u00a0"', id="nbsp"),
    ],
)
def test_blank_string_is_reported_as_blank_not_as_another_type(tmp_path: Path, raw: str) -> None:
    """A blank value is already a string, so "quote it" is the wrong advice."""
    path = _write(tmp_path / "blank.yaml", name=raw)
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))["name"]
    assert isinstance(loaded, str) and not loaded.strip(), "YAML does not read this as blank"

    with pytest.raises(TemplateFieldError) as excinfo:
        TemplateLoader.load_from_file(path)

    assert excinfo.value.problem == "blank"


def test_value_of_another_type_is_reported_as_not_a_string(tmp_path: Path) -> None:
    with pytest.raises(TemplateFieldError) as excinfo:
        TemplateLoader.load_from_file(_write(tmp_path / "on.yaml", name="on"))

    assert excinfo.value.problem == "not_a_string"


def test_message_stays_short_for_a_large_value(tmp_path: Path) -> None:
    """The callers print the message as a warning; a 2000-item list for a
    description must not become a line thousands of characters long."""
    path = _write(tmp_path / "big.yaml", description="[" + ", ".join(["1"] * 2000) + "]")
    assert len(yaml.safe_load(path.read_text(encoding="utf-8"))["description"]) == 2000

    with pytest.raises(TemplateFieldError) as excinfo:
        TemplateLoader.load_from_file(path)

    assert len(excinfo.value.value) == 2000  # the attribute keeps the whole value
    assert len(str(excinfo.value)) < 400 + len(str(path))


def test_error_survives_copy_and_pickle(tmp_path: Path) -> None:
    with pytest.raises(TemplateFieldError) as excinfo:
        TemplateLoader.load_from_file(_write(tmp_path / "on.yaml", name="on"))
    original = excinfo.value

    for clone in (copy.copy(original), pickle.loads(pickle.dumps(original))):
        assert (clone.path, clone.field, clone.value, clone.problem) == (
            original.path,
            "name",
            True,
            "not_a_string",
        )
        assert str(clone) == str(original)
