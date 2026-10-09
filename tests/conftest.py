"""Root test configuration."""

import logging

import structlog


def pytest_configure(config):
    """Configure structlog for tests to suppress debug/info output."""
    logging.basicConfig(level=logging.WARNING, force=True)
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.processors.add_log_level,
            structlog.processors.format_exc_info,
            structlog.dev.ConsoleRenderer(),
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=False,
    )


# The service-name rule's case table, shared by the tests that assert every
# caller agrees with it (opensrm-t4rd, opensrm-h9fq). It lives here rather than
# in one test module because two modules need it, and a test class used as a
# data container across modules only resolves via pytest's rootdir sys.path.
#
# PROVENANCE: derived from the shared rule in specs/manifest.py, which is
# generate's authority for names it GENERATES -- not from what any old private
# guard happened to accept, and not from opensrm's schema, which does not
# constrain this field (opensrm-fwnp).
SERVICE_NAME_CASES = [
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
