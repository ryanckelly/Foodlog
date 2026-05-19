"""Body-composition scenario simulator.

A mechanistic energy-balance model (Hall et al. extended) for simulating
counterfactual diet/exercise scenarios. Designed for notebook-driven research
on top of the foodlog database. Phase 1 uses population-default parameters;
Phase 2 personalizes via PyMC Bayesian inference.

See docs/superpowers/specs/2026-05-18-body-composition-simulator-design.md
for the design.
"""

__version__ = "0.1.0"
