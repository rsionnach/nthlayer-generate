"""The service-name rule's case table, shared by every test that asserts a
caller agrees with it (opensrm-t4rd, opensrm-h9fq).

It lives in a module of its own rather than in a test class, because a test
class used as a data container is a surprising thing to import, and rather than
in `conftest.py`, which is the hook and fixture module — a reader looking for a
shared table looks for a file named after it. Both homes resolve identically
via the `tests/` directory on `sys.path`, so the move is about where a reader
expects to find it, not about import mechanics.

PROVENANCE: derived from the shared rule in `specs/manifest.py`, which is
generate's authority for names it GENERATES. Not from what any old private
guard happened to accept, and not from opensrm's schema, which does not
constrain this field at all (opensrm-fwnp). Several rows are names the old
private guards got WRONG, which is the opposite of reading a table off the
implementation.
"""

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
