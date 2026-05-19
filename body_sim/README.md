# body_sim

Body-composition scenario simulator. Mechanistic energy-balance model with
Bayesian personalization, consumed by notebooks under `notebooks/`.

See the design spec for full architecture:
`docs/superpowers/specs/2026-05-18-body-composition-simulator-design.md`

## Module map

| Module | Role |
|---|---|
| `config.py` | User profile (age, sex, height) + literature-default constants |
| `keytel.py` | HR(t) → kcal/min; daily integration |
| `rmr.py` | Mifflin-St Jeor resting metabolic rate |
| `tef.py` | Thermic effect of food per macro |
| `glycogen.py` | Carb intake → glycogen → bound water |
| `sodium.py` | Sodium intake → water retention |
| `partition.py` | Forbes p; protein-protection modifier |
| `adaptation.py` | Adaptive thermogenesis |
| `model.py` | One-day state update composing the above |
| `pipeline.py` | SQLite → daily-rollup pandas DataFrame |
| `simulate.py` | Forward-simulate N days with uncertainty bands |
| `validation.py` | Forward-walking validation harness |
| `evaluate.py` | MAE, calibration coverage, residual diagnostics |
| `plotting.py` | The three required validation plots |

## Running

From the project root:

```bash
pip install -e ".[body_sim]"
jupyter notebook --notebook-dir=notebooks --port 7777
```

Tests:

```bash
pytest tests/body_sim/ -v
```
