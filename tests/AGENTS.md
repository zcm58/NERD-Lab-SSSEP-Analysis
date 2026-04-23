# AGENTS.md

## Test Strategy

This directory holds fast unit tests plus one optional regression test that can
run against a user-provided local `.bdf` file.

Keep the default test suite lightweight:

- Prefer synthetic NumPy arrays.
- Prefer small constructed MNE objects.
- Avoid large fixtures and avoid committing EEG binary files to the repo.

## Current Test Layout

- `analysis/`
  Metrics and spectrum helpers.
- `events/`
  Trigger parsing, intended-event filtering, and epoch extraction behavior.
- `preprocess/`
  Channel validation, downsampling helpers, and filter-rule tests.
- `test_pipeline.py`
  High-signal orchestration behavior that can be tested with stubs.
- `test_regression_external_bdf.py`
  Optional real-data regression path using an external local fixture.

## Regression Fixture Rule

The repository intentionally does not store a `.bdf` fixture.

Use the `SSSEP_TEST_BDF` environment variable when a real-data regression is
needed. The regression test must skip cleanly when that variable is unset or
points to a missing file.

Do not convert the regression test into a mandatory repo-backed binary fixture
unless the user explicitly asks for that tradeoff.

## What To Test When Changing Core Code

- `analysis/`
  Numeric behavior, output shapes, expected frequency peaks, and invalid-input
  handling.
- `events/`
  Trigger-code filtering, epoch counts, out-of-bounds behavior, and FIR
  edge-exclusion counts.
- `preprocess/`
  Filter-setting validation, no-op vs resample behavior, and channel
  validation.
- `pipeline.py`
  Only high-value orchestration behavior. Keep heavy signal-processing details
  in lower-level tests where possible.

## Test Writing Guidance

1. Keep tests deterministic.
2. Prefer one clear behavior per test.
3. Use monkeypatching in pipeline tests to isolate orchestration from heavy I/O.
4. If a bug changed math or sample indexing, add a regression-style test for
   that exact failure mode.
5. If a change only affects docs or markdown files, do not add unnecessary test
   churn.
