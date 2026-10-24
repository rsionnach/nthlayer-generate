"""Generate's own service-name rule (opensrm-t4rd, opensrm-h9fq).

Moved here unchanged from ``specs/manifest.py`` when generate's manifest
model was retired in favour of nthlayer-common's (opensrm-wo62.1, D13). The
rule is generate's, not the format's, so it does not belong in common.
"""

from __future__ import annotations

import re

# THE service-name rule for every path that writes a manifest (opensrm-t4rd,
# opensrm-h9fq). Two copies of it disagreed:
# cli/init.py's guard looped over `char.islower() or char.isdigit()`, which are
# UNICODE predicates, and rejected only a leading or trailing hyphen — so
# `1-svc`, `café` and fullwidth `ａbc` all passed the CLI and were then rejected
# by specs/validator.py, which applies the pattern below. `nthlayer init` exited
# 0 having written a manifest its own validator refuses, and an exit code is
# what a CI gate keys on.
#
# Now genuinely the only copy: cli/init.py and cli/setup.py both delegate here,
# and specs/validator.py applies it (opensrm-h9fq retired the third copy). That
# is a claim about other files, so it is asserted rather than left as prose:
# test_cli_setup.py::TestTheNameRuleHasExactlyOneHome drives BOTH CLI guards
# over the shared table. specs/validator.py is not driven there -- it calls
# this function directly, with no copy of its own to diverge.
#
# Same shape as the service-type divergence recorded under opensrm-z3ab
# (docs/architecture.md, "Service types: resolved vs authored").
#
# AUTHORITY: this pattern is generate's own, and is deliberately STRICTER than
# the opensrm schema, so schema-valid documents exist that `init` refuses to
# write. That gap is a spec decision, tracked in opensrm-fwnp — which is also
# where the schema's actual patterns are recorded, rather than quoted here
# where they would rot. (An earlier note here said generate's CI had no
# `opensrm/` checkout; it has one — .github/workflows/ci.yml places it beside
# the repo — so that is no longer a reason a schema test could not exist.)
#
# The rule is the union of what the two old guards each enforced:
#   - must start with a lowercase letter   (validator.py had this; the CLI did not)
#   - must not end with a hyphen           (the CLI had this; validator.py did not)
# Neither was right alone, so aligning to either one would have loosened the
# other. Checked before tightening: no leading- or trailing-hyphen service name
# was in use anywhere in this repo.
SERVICE_NAME_PATTERN = r"[a-z]([a-z0-9-]*[a-z0-9])?"
_SERVICE_NAME_RE = re.compile(SERVICE_NAME_PATTERN)


def is_valid_service_name(name: str) -> bool:
    """True if *name* is a legal service name for generated manifests.

    Uses ``fullmatch``, not ``match`` with a trailing ``$``. In Python ``$``
    also matches just before a final newline, so ``re.match(r"...$", "svc\n")``
    SUCCEEDS — and a trailing newline is an ordinary authoring accident from a
    YAML block scalar. Pinned in test_init.py by
    ``test_trailing_newline_is_why_fullmatch``.

    ``isinstance`` is checked first because the loader hands this whatever YAML
    resolved: a manifest with ``name: yes`` yields ``True``, which passes
    ``bool(name)`` and then makes ``fullmatch`` raise ``TypeError``, so
    ``nthlayer validate`` died with a traceback instead of reporting the error.
    A non-str name is never valid, so returning False is both safe and correct.
    """
    return isinstance(name, str) and bool(name) and _SERVICE_NAME_RE.fullmatch(name) is not None
