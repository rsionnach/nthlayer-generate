"""Golden harness for nthlayer-generate (opensrm-wo62.1, Checkpoint B).

Pins generate's current outputs over the example corpus so a later change of
manifest model produces a reviewable golden diff. See ``_corpus`` for the
inputs, ``_golden`` for the comparison, and ``test_golden_harness`` for the
tests that keep the corpus and the stored goldens honest.
"""
