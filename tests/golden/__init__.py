"""Golden harness for nthlayer-generate (opensrm-wo62.1).

Pins generate's outputs over the example corpus, so any change to the
manifest model or the generators shows up as a reviewable golden diff. See
``_corpus`` for the inputs, ``_golden`` for the comparison (and how to update
goldens), and ``test_golden_harness`` for the tests that keep the corpus and
the stored goldens honest.
"""
