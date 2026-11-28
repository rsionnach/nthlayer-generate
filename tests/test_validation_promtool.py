"""The promtool runner: three states, and a missing binary is never a pass.

Fixture provenance: the rule group and unit test below follow the Prometheus
documentation's formats (configuration/recording_rules: ``groups[].rules[]``
with ``record`` and ``expr``; configuration/unit_testing_rules:
``input_series`` with expanding notation and ``promql_expr_test`` with
``exp_samples``). The fake binaries print what ``promtool --version``
prints: ``promtool, version <v> (branch: ..., revision: ...)``.
"""

from __future__ import annotations

import importlib.util
import stat
from pathlib import Path

import pytest

from nthlayer_generate.validation.promtool import (
    PROMTOOL_VERSION,
    PromtoolResult,
    PromtoolStatus,
    find_promtool,
    promtool_version,
    run_rule_tests,
)

REPO = Path(__file__).resolve().parents[1]

GROUPS = [
    {
        "name": "example",
        "rules": [{"record": "job:requests:rate5m", "expr": "sum(rate(requests_total[5m]))"}],
    }
]


def _test(expected_value: float) -> list[dict]:
    # 1 request a second: the counter grows by 60 each minute.
    return [
        {
            "interval": "1m",
            "input_series": [{"series": "requests_total", "values": "0+60x10"}],
            "promql_expr_test": [
                {
                    "expr": "job:requests:rate5m",
                    "eval_time": "10m",
                    "exp_samples": [{"labels": "job:requests:rate5m", "value": expected_value}],
                }
            ],
        }
    ]


def _fake_promtool(directory: Path, version_line: str) -> None:
    binary = directory / "promtool"
    binary.write_text(f"#!/bin/sh\necho '{version_line}'\nexit 0\n", encoding="utf-8")
    binary.chmod(binary.stat().st_mode | stat.S_IXUSR)


def test_the_pinned_promtool_is_installed():
    """Every rule test in the suite depends on this; say so in one place."""
    binary = find_promtool()
    assert binary is not None, "promtool is not on PATH: run `make promtool`"
    assert promtool_version(binary) == PROMTOOL_VERSION, "wrong promtool: run `make promtool`"


def test_a_true_expectation_passes():
    result = run_rule_tests(GROUPS, _test(1.0))
    assert result.status is PromtoolStatus.PASSED, result.output or result.reason
    assert result.passed is True
    assert result.version == PROMTOOL_VERSION


def test_a_false_expectation_fails():
    result = run_rule_tests(GROUPS, _test(2.0))
    assert result.status is PromtoolStatus.FAILED, result.output or result.reason
    assert result.passed is False


def test_a_rule_that_does_not_parse_fails():
    broken = [{"name": "example", "rules": [{"record": "job:x", "expr": "sum(rate("}]}]
    result = run_rule_tests(broken, _test(1.0))
    assert result.status is PromtoolStatus.FAILED
    assert result.passed is False


@pytest.mark.parametrize(
    "tests",
    [
        [],
        # A test that states no expectation checks nothing.
        [{"interval": "1m", "input_series": [], "promql_expr_test": []}],
        [{"interval": "1m", "input_series": [], "alert_rule_test": []}],
    ],
    ids=["no-tests", "empty-expr-test", "empty-alert-test"],
)
def test_nothing_to_check_is_not_a_pass(tests: list[dict]) -> None:
    # promtool itself exits 0 on a file with nothing in it. A caller whose
    # generated test list came out empty must not be told its rules passed.
    result = run_rule_tests(GROUPS, tests)

    assert result.status is PromtoolStatus.FAILED
    assert not result.passed


def test_an_alert_expectation_alone_is_something_to_check() -> None:
    # alert_rule_test is the other kind of expectation: no alert is firing.
    tests = [
        {
            "interval": "1m",
            "input_series": [{"series": "requests_total", "values": "0+60x10"}],
            "alert_rule_test": [{"eval_time": "10m", "alertname": "Nothing", "exp_alerts": []}],
        }
    ]
    assert run_rule_tests(GROUPS, tests).passed


def test_a_missing_promtool_is_unavailable_and_not_a_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("PATH", str(tmp_path))  # an empty directory
    assert find_promtool() is None
    result = run_rule_tests(GROUPS, _test(1.0))
    assert result.status is PromtoolStatus.UNAVAILABLE
    assert result.passed is False
    assert result.version is None
    assert result.reason


def test_another_version_is_unavailable_and_not_a_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    # A binary that would "pass" anything (exit 0), at a version that is not
    # the pinned one: the runner must refuse it before running a test.
    _fake_promtool(tmp_path, "promtool, version 0.0.1 (branch: HEAD, revision: abc)")
    monkeypatch.setenv("PATH", str(tmp_path))
    result = run_rule_tests(GROUPS, _test(2.0))
    assert result.status is PromtoolStatus.UNAVAILABLE
    assert result.passed is False
    assert result.version == "0.0.1"


def test_a_binary_that_reports_no_version_is_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    _fake_promtool(tmp_path, "hello")
    monkeypatch.setenv("PATH", str(tmp_path))
    assert promtool_version(tmp_path / "promtool") is None
    result = run_rule_tests(GROUPS, _test(1.0))
    assert result.status is PromtoolStatus.UNAVAILABLE
    assert result.passed is False


def test_passed_is_true_for_the_passed_state_only():
    assert {s: PromtoolResult(status=s).passed for s in PromtoolStatus} == {
        PromtoolStatus.PASSED: True,
        PromtoolStatus.FAILED: False,
        PromtoolStatus.UNAVAILABLE: False,
    }


# The version is written once. CI, the Makefile and the docs install it with
# scripts/install_promtool.py, which imports the constant; none may name a
# version of its own.
VERSION_READERS = [
    ".github/workflows/ci.yml",
    "Makefile",
    "docs/testing.md",
    "scripts/install_promtool.py",
]
assert VERSION_READERS, "no files to check"


@pytest.mark.parametrize("relative", VERSION_READERS)
def test_the_version_is_written_only_in_the_runner(relative: str):
    text = (REPO / relative).read_text(encoding="utf-8")
    assert PROMTOOL_VERSION not in text
    if relative != "scripts/install_promtool.py":
        assert "install_promtool.py" in text or "make promtool" in text


def test_the_install_script_reads_the_runner_constant():
    text = (REPO / "scripts" / "install_promtool.py").read_text(encoding="utf-8")
    assert "from nthlayer_generate.validation.promtool import PROMTOOL_VERSION" in text


def _install_script():
    # scripts/ is not a package: load the file as the interpreter would run it.
    spec = importlib.util.spec_from_file_location(
        "install_promtool", REPO / "scripts" / "install_promtool.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_installer_says_when_path_does_not_lead_to_what_it_installed(tmp_path: Path) -> None:
    # The runner takes promtool from PATH. Told only "installed", a user with
    # another promtool first on PATH, or with the install directory off it,
    # is sent back to the installer by the runner's own message.
    path_warning = _install_script().path_warning
    target = tmp_path / "bin" / "promtool"
    target.parent.mkdir()
    target.write_text("", encoding="utf-8")
    elsewhere = tmp_path / "usr" / "promtool"
    elsewhere.parent.mkdir()
    elsewhere.write_text("", encoding="utf-8")

    assert path_warning(target, str(target)) == ""
    # A symlink to the installed binary is the installed binary.
    link = tmp_path / "link"
    link.symlink_to(target)
    assert path_warning(target, str(link)) == ""

    assert str(elsewhere) in path_warning(target, str(elsewhere))
    assert str(target.parent) in path_warning(target, None)
