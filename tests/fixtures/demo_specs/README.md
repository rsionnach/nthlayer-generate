# Demo specs (vendored)

The four srm/v1 manifests the NthLayer demo runs on, copied unmodified from
the front-door repository:

- Source: https://github.com/rsionnach/nthlayer, `demo/specs/`
- Commit: c93f34f628fdd0b8119cb24d9a946eadab05719f

`tests/test_cli_migrate_manifest.py::TestDemoSpecsViaCLI` migrates each one
with `nthlayer migrate-manifest`. They live here, not in a sibling checkout,
so the test runs wherever this repository is checked out and cannot skip
(opensrm-w658).

These are copies. If the demo's specs change, refresh them from the source
and update the commit above; this test says nothing about specs it has not
been given.
