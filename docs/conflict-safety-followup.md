# Follow-up to PR #1: observation preservation and conflict safety

Baseline: `e984171709846002bc6efdfb8cc13291f7c49e56`.

## Changes

- Tencent validates numeric values instead of deleting zero/negative/unparseable
  volume observations before validation. Valid zero-volume rows are preserved.
  The existing execution layer rejects them as `UNTRADABLE_VOLUME`.
- Zero volume does not establish a market closure, suspension, or an official
  trading session. Special closures still require independently sourced calendar
  corrections; this patch does not certify the calendar or fill missing sessions.
- New source conflicts include both observed numbers and are saved atomically to
  `data/quality/unresolved_conflicts.json` before processed prices are written.
- Preparation imports historical `data/preparations/*/report.json` conflicts.
  Unreadable evidence fails closed. Legacy records without numbers remain open;
  their values must be recovered from archived responses/backups, not invented.
- Cached preparation, `status`, and `run --offline` all enforce open conflicts
  for selected stocks, research dates and configured warmup dates. Other stocks
  are not blocked solely by unrelated conflicts. Frozen historical replay remains
  a replay of its captured evidence, not a claim that current live data is clean.
- Conflict evidence is ignored by Git. The JSON contains data observations and
  must stay with the local data backup, not be committed to the public repo.

## Deliberate boundary

This patch does **not** resolve the reported 44 real conflicts or select a
winning provider. No adjudication evidence is available in this workspace.
It supplies a reviewed-resolution command instead of a bulk-clear switch:

```
python -m hk_quant workflow resolve-conflict --data-root DATA --file decision.json
```

The decision file must contain `conflict_id`, `reason`, `source_url`,
`reviewed_by`, `evidence_file` (relative to the decision file or absolute), and
`accepted_values` (every disputed field). Use an actual saved source response,
page, or document as evidence. The command verifies that accepted values match
one stored row, archives the evidence with SHA256, and retains the original
conflict. If a data correction is needed, back up and apply it with provenance
before recording the resolution; this command does not rewrite market values.
Later changes to the accepted numbers reopen the conflict. Altered/missing
archived evidence blocks use. Source attribution and the reason are reviewer
assertions, not automatic proof that a provider is correct. Never submit dummy
evidence or close all conflicts by assuming the first source wins.

Legacy conflict reports lack numeric values. Recover them from saved responses
and backups where possible; if evidence is insufficient, leave them open.
Deleting the registry alone cannot clear conflicts recorded in old reports.

Neither the legacy ranking entry nor every direct low-level backtest API is
converted into a unified data safety entry here. Research on the live data root
should use the workflow entry; a legacy run is not acceptance of these gates.

## Local verification

`PYTHONPATH=src python -m unittest tests.workflow.test_conflict_safety tests.workflow.test_workflow -q`

47 passed (14 new safety tests + 33 existing workflow tests).

`PYTHONPATH=src python -m unittest discover -s tests/unit_stdlib -q`

10 passed. `compileall` passed. Full pytest and live integration remain unrun
in this workspace because pytest/pyarrow/duckdb/akshare are unavailable.

Pi must also run `tests/data/test_tencent_adapter.py`, full offline/integration
tests, and the real-data preparation on Windows. No new market data was obtained.
