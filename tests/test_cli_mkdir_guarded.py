"""A directory the CLI cannot create is reported, not raised (opensrm-mnzi).

`Path.mkdir(exist_ok=True)` only forgives an existing DIRECTORY. A regular
file or a dangling symlink at the path raises FileExistsError, and a read-only
parent raises PermissionError. opensrm-h9fq fixed one such call in
`cli/setup.py` and left its twin, earlier in the same file, bare.

The structural test covers every directory-creating call under `cli/`
(`Path.mkdir`, `os.mkdir`, `os.makedirs`), so the next one cannot be missed
the same way. The behavioural tests drive the two commands that had an
unguarded call, `nthlayer setup` and `migrate-manifest`, through real
filesystem states. For setup that includes the writes that follow the
directory: storing a secret and saving the configuration.
"""

from __future__ import annotations

import ast
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

import nthlayer_generate.cli as cli_package
from nthlayer_generate.cli.migrate_manifest import migrate_manifest_command
from nthlayer_generate.cli.setup import _quick_setup
from nthlayer_generate.config.secrets import SecretConfig, SecretResolver

CLI_DIR = Path(cli_package.__file__).parent
CLI_MODULES = sorted(CLI_DIR.rglob("*.py"))
# An empty list would make the structural test pass having read nothing.
assert CLI_MODULES, f"no modules found under {CLI_DIR}"

# Handler types that catch every OSError. A narrower one (FileExistsError,
# PermissionError) does not count: each leaves another state raising.
_CATCHES_OSERROR = {"OSError", "Exception", "BaseException"}


# Every spelling that creates a directory: Path.mkdir, os.mkdir, os.makedirs,
# and either function imported by name.
_MKDIR_NAMES = {"mkdir", "makedirs"}


def _is_mkdir_call(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
    return name in _MKDIR_NAMES


def _handler_catches_oserror(handler: ast.ExceptHandler) -> bool:
    # A handler that re-raises still ends in a traceback, and one that only
    # passes reports nothing: neither is a guard.
    if any(isinstance(stmt, ast.Raise) and stmt.exc is None for stmt in handler.body):
        return False
    if all(isinstance(stmt, ast.Pass) for stmt in handler.body):
        return False
    if handler.type is None:
        return True
    types = handler.type.elts if isinstance(handler.type, ast.Tuple) else [handler.type]
    return any(isinstance(t, ast.Name) and t.id in _CATCHES_OSERROR for t in types)


def unguarded_mkdir_lines(source: str) -> tuple[list[int], int]:
    """Return (lines of mkdir calls outside an OSError handler, calls seen).

    A call is guarded when it sits in the BODY of a `try` that has a handler
    catching OSError and doing more than re-raising, within the same function:
    a `try` around a nested `def` does not guard the calls inside it, and
    neither does the `try`'s own `except`, `else` or `finally` block.

    Not seen: a call inside a generator expression that is consumed after the
    `try` has ended, which runs outside the handler it is written in.

    Refused although guarded, on purpose (the check fails closed):
    `contextlib.suppress(OSError)`, `except IOError` or `os.error`, and a
    decorator or default argument evaluated inside the `try`.
    """
    unguarded: list[int] = []
    seen = 0

    def visit(node: ast.AST, guarded: bool) -> None:
        nonlocal seen
        if _is_mkdir_call(node):
            seen += 1
            if not guarded:
                unguarded.append(node.lineno)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            guarded = False
        if isinstance(node, ast.Try):
            catches = any(_handler_catches_oserror(h) for h in node.handlers)
            for child in node.body:
                visit(child, guarded or catches)
            for child in [*node.handlers, *node.orelse, *node.finalbody]:
                visit(child, guarded)
            return
        for child in ast.iter_child_nodes(node):
            visit(child, guarded)

    visit(ast.parse(source), False)
    return unguarded, seen


HANDLERS_THAT_DO_NOT_REPORT = [
    pytest.param("    raise\n", id="re-raise"),
    pytest.param("    log()\n    raise\n", id="log-then-re-raise"),
    pytest.param("    pass\n", id="pass"),
]
assert HANDLERS_THAT_DO_NOT_REPORT

OTHER_MKDIR_SPELLINGS = ["os.mkdir('x')", "os.makedirs('x')", "mkdir('x')", "makedirs('x')"]
assert OTHER_MKDIR_SPELLINGS


class TestEveryCliMkdirIsGuarded:
    def test_no_mkdir_in_cli_is_outside_an_oserror_handler(self):
        offenders = []
        total = 0
        for module in CLI_MODULES:
            lines, seen = unguarded_mkdir_lines(module.read_text(encoding="utf-8"))
            total += seen
            offenders += [f"{module.relative_to(CLI_DIR)}:{line}" for line in lines]

        # cli/ had nine mkdir calls when this was written. Fewer than the two
        # this bead fixed means the walker stopped finding them.
        assert total >= 2, f"the guard found only {total} mkdir calls under {CLI_DIR}"
        assert not offenders, (
            "mkdir outside a `try` that catches OSError: "
            + ", ".join(offenders)
            + ". exist_ok=True does not cover a file, a dangling symlink or a "
            "read-only parent; report the failure instead (opensrm-mnzi)."
        )

    def test_a_bare_mkdir_is_reported(self):
        lines, seen = unguarded_mkdir_lines("from pathlib import Path\nPath('x').mkdir()\n")
        assert (lines, seen) == ([2], 1)

    def test_a_mkdir_in_a_try_that_catches_oserror_is_accepted(self):
        source = "try:\n    p.mkdir()\nexcept (ValueError, OSError) as e:\n    error(e)\n"
        assert unguarded_mkdir_lines(source) == ([], 1)

    def test_a_handler_for_one_oserror_subclass_is_not_enough(self):
        source = "try:\n    p.mkdir()\nexcept FileExistsError:\n    pass\n"
        assert unguarded_mkdir_lines(source) == ([2], 1)

    def test_a_mkdir_in_the_except_block_is_not_guarded_by_its_own_try(self):
        source = "try:\n    pass\nexcept OSError:\n    p.mkdir()\n"
        assert unguarded_mkdir_lines(source) == ([4], 1)

    @pytest.mark.parametrize("call", OTHER_MKDIR_SPELLINGS)
    def test_every_spelling_of_mkdir_is_seen(self, call):
        assert unguarded_mkdir_lines(f"{call}\n") == ([1], 1)

    @pytest.mark.parametrize("handler_body", HANDLERS_THAT_DO_NOT_REPORT)
    def test_a_handler_that_re_raises_or_does_nothing_is_not_a_guard(self, handler_body):
        source = f"try:\n    p.mkdir()\nexcept OSError:\n{handler_body}"
        assert unguarded_mkdir_lines(source) == ([2], 1)

    def test_a_handler_that_raises_a_new_error_is_still_a_guard(self):
        # `raise SomeError(...) from e` is a report by another route, unlike a
        # bare `raise`, which lets the OSError through as it is.
        source = "try:\n    p.mkdir()\nexcept OSError as e:\n    raise UsageError(str(e)) from e\n"
        assert unguarded_mkdir_lines(source) == ([], 1)

    def test_a_try_around_a_nested_function_does_not_guard_its_body(self):
        source = "try:\n    def f():\n        p.mkdir()\nexcept OSError:\n    pass\n"
        assert unguarded_mkdir_lines(source) == ([3], 1)


def _nthlayer_is_a_file(home: Path) -> None:
    (home / ".nthlayer").write_text("x", encoding="utf-8")


def _nthlayer_is_a_dangling_symlink(home: Path) -> None:
    (home / ".nthlayer").symlink_to(home / "nowhere")


def _home_is_read_only(home: Path) -> None:
    home.chmod(0o555)


def _config_is_a_directory(home: Path) -> None:
    (home / ".nthlayer" / "config.yaml").mkdir(parents=True)


def _mkdir_config_dir(home: Path) -> None:
    (home / ".nthlayer").mkdir(exist_ok=True)


def _open_config_file(home: Path) -> None:
    with open(home / ".nthlayer" / "config.yaml", "w", encoding="utf-8"):
        pass


# (how to put the home directory in the state, the plain call that state breaks)
UNUSABLE_HOME_STATES = [
    pytest.param(_nthlayer_is_a_file, _mkdir_config_dir, id="nthlayer-is-a-file"),
    pytest.param(_nthlayer_is_a_dangling_symlink, _mkdir_config_dir, id="dangling-symlink"),
    pytest.param(_home_is_read_only, _mkdir_config_dir, id="read-only-home"),
    pytest.param(_config_is_a_directory, _open_config_file, id="config-is-a-directory"),
]
assert UNUSABLE_HOME_STATES
# The first three: `~/.nthlayer` itself cannot be created.
UNCREATABLE_CONFIG_DIR_STATES = UNUSABLE_HOME_STATES[:3]
assert len(UNCREATABLE_CONFIG_DIR_STATES) == 3


def _credentials_is_a_directory(home: Path) -> None:
    (home / ".nthlayer" / "credentials.yaml").mkdir(parents=True)


def _nthlayer_is_read_only(home: Path) -> None:
    (home / ".nthlayer").mkdir()
    (home / ".nthlayer").chmod(0o555)


def _open_credentials_file(home: Path) -> None:
    with open(home / ".nthlayer" / "credentials.yaml", "w", encoding="utf-8"):
        pass


# The config directory exists, so setup gets as far as storing the secret.
UNWRITABLE_CREDENTIALS_STATES = [
    pytest.param(_credentials_is_a_directory, _open_credentials_file, id="credentials-is-a-dir"),
    pytest.param(_nthlayer_is_read_only, _open_credentials_file, id="read-only-nthlayer"),
]
assert UNWRITABLE_CREDENTIALS_STATES


@pytest.fixture
def home(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    yield home
    # so pytest can remove what a test made read-only
    home.chmod(0o755)
    if (home / ".nthlayer").is_dir():
        (home / ".nthlayer").chmod(0o755)


# The answers to setup's three yes/no questions (Prometheus authentication,
# configure Grafana, configure PagerDuty) that lead to each secret prompt, and
# what the file backend then holds for a secret typed as "s3cret".
SECRET_PROMPTS = [
    pytest.param(
        [True, False, False], {"prometheus": {"password": "s3cret"}}, id="prometheus-password"
    ),
    pytest.param([False, True, False], {"grafana": {"api_key": "s3cret"}}, id="grafana-key"),
    pytest.param([False, False, True], {"pagerduty": {"api_key": "s3cret"}}, id="pagerduty-key"),
]
assert SECRET_PROMPTS
NO_SECRETS = [False, False, False]


class TestQuickSetupReportsAnUnusableConfigDirectory:
    @staticmethod
    def _run(home: Path, answers: list[bool]):
        """Run the wizard for real under `home`, answering its yes/no questions.

        The resolver is a real one over the real file backend, built while
        `Path.home` is patched, so secrets and configuration are written to
        `home`. Returns the exit code, the `error` and `success` mocks, and how
        many times the user was asked anything.
        """
        confirmations = iter(answers)
        with (
            patch.object(Path, "home", return_value=home),
            patch(
                "nthlayer_generate.cli.setup._prompt", return_value="http://localhost:9090"
            ) as prompt,
            patch("nthlayer_generate.cli.setup._prompt_secret", return_value="s3cret") as secret,
            patch(
                "nthlayer_generate.cli.setup._confirm",
                side_effect=lambda *a, **k: next(confirmations),
            ) as confirm,
            patch("nthlayer_generate.cli.setup.error") as reported,
            patch("nthlayer_generate.cli.setup.success") as succeeded,
        ):
            resolver = SecretResolver(SecretConfig())
            with patch("nthlayer_generate.cli.setup.get_secret_resolver", return_value=resolver):
                rc = _quick_setup()
            asked = prompt.call_count + secret.call_count + confirm.call_count
        return rc, reported, succeeded, asked

    @pytest.mark.parametrize(("make", "plain_call"), UNUSABLE_HOME_STATES)
    def test_the_failure_is_reported_and_setup_stops(self, make, plain_call, home):
        make(home)
        # The state must really break the call. Where it does not (chmod is a
        # no-op for root), this fails here instead of passing for nothing.
        with pytest.raises(OSError):
            plain_call(home)

        rc, reported, succeeded, _ = self._run(home, NO_SECRETS)

        assert rc == 1
        reported.assert_called_once()
        succeeded.assert_not_called()
        assert not (home / ".nthlayer" / "config.yaml").is_file()

    @pytest.mark.parametrize(("make", "plain_call"), UNCREATABLE_CONFIG_DIR_STATES)
    def test_a_directory_that_cannot_be_created_stops_setup_before_any_question(
        self, make, plain_call, home
    ):
        # Otherwise the user types their secrets and only then learns that
        # nothing can be saved.
        make(home)
        with pytest.raises(OSError):
            plain_call(home)

        rc, reported, _, asked = self._run(home, [True, True, True])

        assert rc == 1
        reported.assert_called_once()
        assert asked == 0

    @pytest.mark.parametrize(("answers", "stored"), SECRET_PROMPTS)
    @pytest.mark.parametrize(("make", "plain_call"), UNWRITABLE_CREDENTIALS_STATES)
    def test_a_secret_that_cannot_be_stored_is_reported_and_setup_stops(
        self, make, plain_call, answers, stored, home
    ):
        # Entering a secret writes credentials.yaml into the config directory,
        # before the configuration is saved.
        make(home)
        with pytest.raises(OSError):
            plain_call(home)

        rc, reported, succeeded, _ = self._run(home, answers)

        assert rc == 1
        reported.assert_called_once()
        succeeded.assert_not_called()
        assert not (home / ".nthlayer" / "config.yaml").exists()

    @pytest.mark.parametrize(("answers", "stored"), SECRET_PROMPTS)
    def test_a_secret_is_stored_beside_the_configuration(self, answers, stored, home):
        rc, reported, succeeded, _ = self._run(home, answers)

        assert rc == 0
        reported.assert_not_called()
        succeeded.assert_called_once()
        credentials = home / ".nthlayer" / "credentials.yaml"
        assert yaml.safe_load(credentials.read_text(encoding="utf-8")) == stored

    def test_a_usable_home_still_saves_the_configuration(self, home):
        rc, reported, succeeded, _ = self._run(home, NO_SECRETS)

        assert rc == 0
        reported.assert_not_called()
        succeeded.assert_called_once()
        saved = yaml.safe_load((home / ".nthlayer" / "config.yaml").read_text(encoding="utf-8"))
        assert saved["prometheus"]["profiles"]["default"]["url"] == "http://localhost:9090"


def _parent_is_a_file(tmp_path: Path) -> tuple[Path, bool]:
    (tmp_path / "blocker").write_text("x", encoding="utf-8")
    return tmp_path / "blocker" / "svc.v2.yaml", False


def _parent_is_read_only(tmp_path: Path) -> tuple[Path, bool]:
    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(0o555)
    return locked / "out" / "svc.v2.yaml", False


def _output_is_a_directory(tmp_path: Path) -> tuple[Path, bool]:
    (tmp_path / "svc.v2.yaml").mkdir()
    return tmp_path / "svc.v2.yaml", True  # it exists, so only --force reaches the write


# Each returns (the output path to ask for, whether --force is needed).
UNWRITABLE_OUTPUTS = [
    pytest.param(_parent_is_a_file, id="parent-is-a-file"),
    pytest.param(_parent_is_read_only, id="read-only-parent"),
    pytest.param(_output_is_a_directory, id="output-is-a-directory"),
]
assert UNWRITABLE_OUTPUTS

SRM_V1_MANIFEST = {
    "apiVersion": "srm/v1",
    "kind": "ServiceReliabilityManifest",
    "metadata": {"name": "svc", "team": "team-a", "tier": "critical"},
    "spec": {
        "type": "api",
        "slos": {
            "availability": {
                "target": 99.9,
                "window": "30d",
                "indicator": {"query": "rate(http[5m])"},
            },
        },
    },
}


class TestMigrateManifestReportsAnUnwritableOutput:
    @pytest.fixture
    def manifest(self, tmp_path):
        path = tmp_path / "svc.yaml"
        path.write_text(yaml.safe_dump(SRM_V1_MANIFEST), encoding="utf-8")
        yield path
        locked = tmp_path / "locked"
        if locked.exists():
            locked.chmod(0o755)

    @pytest.mark.parametrize("make", UNWRITABLE_OUTPUTS)
    def test_the_failure_is_reported_with_exit_1(self, make, manifest, tmp_path):
        out_path, force = make(tmp_path)
        # As above: the state must really refuse the write.
        with pytest.raises(OSError):
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text("probe", encoding="utf-8")

        with patch("nthlayer_generate.cli.migrate_manifest.error") as reported:
            rc = migrate_manifest_command(str(manifest), output_path=str(out_path), force=force)

        assert rc == 1
        reported.assert_called_once()
        assert not out_path.is_file()

    def test_a_writable_output_directory_is_still_created(self, manifest, tmp_path):
        out_path = tmp_path / "new" / "deeper" / "svc.v2.yaml"

        with patch("nthlayer_generate.cli.migrate_manifest.error") as reported:
            rc = migrate_manifest_command(str(manifest), output_path=str(out_path))

        assert rc == 0
        reported.assert_not_called()
        assert yaml.safe_load(out_path.read_text(encoding="utf-8"))["metadata"]["name"] == "svc"
