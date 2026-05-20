# body_sim — sub-project guidance

The body-composition scenario simulator: a notebook-driven research workflow that consumes the foodlog SQLite DB and produces forecasts of weight + body-fat trajectories under counterfactual diet/exercise scenarios. Lives alongside the foodlog FastAPI app but does not deploy with it — this is research code.

## Pointers

- **Design spec:** `docs/superpowers/specs/2026-05-18-body-composition-simulator-design.md`
- **Phase 1 implementation plan:** `docs/superpowers/plans/2026-05-18-body-sim-phase-1.md`
- **Beads (filter to sub-project):** `bd list --label=body-sim`
- **Phase epics:**
  - `foodlog-jok` — Phase 1 (extended Hall + population defaults) — **CLOSED**
  - `foodlog-j90` — Phase 2 (personalize `intake_bias` + `RMR_scale` via PyMC) — open, awaiting more data
  - `foodlog-6bi` — Phase 3 (add NEAT, protein_protection, activity_bias)
  - `foodlog-evq` — Phase 4 (optional ML residual layer)

## Layout

```
body_sim/                  this package — pure-math modules + pipeline + simulator + validation
notebooks/                 Jupyter notebooks (02 → 07) — execute against the live DB
notebooks/predictions/     parquet rollup artifact + JSONL live-forecast log
tests/body_sim/            in-memory-SQLite tests for every module
```

The package is flat-layout (`body_sim/`, not `src/body_sim/`) to match the foodlog repo convention. Module map is in `README.md`.

## Conventions for new work

All beads in this sub-project carry **two labels**: `body-sim` and exactly one of `phase-1` / `phase-2` / `phase-3` / `phase-4`. See `/opt/foodlog/CLAUDE.md` (root) for the full convention.

```bash
bd create --type=task --labels=body-sim,phase-2 --title="..." --description="..."
```

## Data exclusions

The model in this sub-project excludes the following `body_composition` readings from analysis. **The DB rows themselves are not modified** by the body_sim pipeline — the exclusion is enforced at pipeline-read time only, so the foodlog dashboard and MCP tools continue to see the full data.

The exclusion list is maintained as a constant in `body_sim/pipeline.py`:

```python
EXCLUDED_BODY_COMP_IDS: frozenset[str] = frozenset({
    "users/7108215177813058725/dataTypes/weight/dataPoints/1777669898000",
    "users/7108215177813058725/dataTypes/weight/dataPoints/1777824995000",
})
```

| external_id | measured_at | weight_kg | bf% | Reason for exclusion |
|---|---|---|---|---|
| `.../weight/dataPoints/1777669898000` | 2026-05-02 00:11:38 | 85.3 | — | Taken with clothes on, outside the regular morning-routine time-of-day. ~2 kg heavier than subsequent readings, missing body-fat measurement (consistent with the scale not being able to measure bf% on a clothed weigh-in). |
| `.../weight/dataPoints/1777824995000` | 2026-05-03 19:16:35 | 84.75 | — | Same reason. Evening weigh-in, off the established methodology. |

The rest of the body_composition history is a consistent post-void naked morning routine (~10–11 AM) with paired weight + body-fat readings from a Withings/Renpho scale via Fitbit Web API sync.

**To add more exclusions later:** append the row's `external_id` to `EXCLUDED_BODY_COMP_IDS` and re-execute the notebooks. No schema migration required, no DB writes needed. The exclusion test (`test_body_comp_rollup_skips_excluded_external_ids` in `tests/body_sim/test_pipeline_other.py`) verifies the filter is wired up.

If a single methodologically-clean reading later proves to be a real outlier (illness, dehydration, hardware fault) and you want to exclude it, the same mechanism applies — get the row's `external_id` from `body_composition.external_id` and add it to the constant.

## Phase 1 known limitations (open Phase 2 inputs)

These came out of the Phase 1 validation run on 2026-05-19 and are documented in `foodlog-j90` notes:

- **State-seeding doesn't back out glycogen-water.** `validation._seed_state` treats the observed weight as fat+lean, but the model's `predicted_weight_kg` adds back glycogen water (~1.4 kg at default `INITIAL_GLYCOGEN_G`) and sodium water. Result: day-1 predicted weight is systematically ~1.4 kg above the seed. Calibration in Phase 1 reflects this offset.
- **Keytel overcounts at sedentary HR.** Integrated over 24 h at resting band, `ee_hr_keytel_kcal` averages ~3,400 kcal/day — implausible. Phase 2 will fit `activity_bias`; if the posterior centers near ~0.2–0.3, the structural fix is needed (rest-baseline subtraction or HR-zone-only signal). See `foodlog-j90` notes for the decision tree.
- **Only 12 weigh-ins (post-exclusion).** Phase 2 fitting kicks in once we have ~30 paired food+weight days.

## Re-executing the notebooks

From `/opt/foodlog/`:

```bash
for nb in 02_data_pipeline 03_descriptive_eda 04_hall_baseline 06_scenario_simulator 07_live_tracking; do
    .venv/bin/jupyter nbconvert --to notebook --execute notebooks/${nb}.ipynb \
        --output ${nb}.ipynb --ExecutePreprocessor.timeout=600
done
```

Notebook 02 must run first — it produces the parquet artifact that the others consume.
