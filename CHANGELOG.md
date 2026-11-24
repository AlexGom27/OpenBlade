# Changelog

All notable changes to OpenBlade are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[semantic versioning](https://semver.org/spec/v2.0.0.html).

Validation figures quoted below come from `docs/VALIDACION.md`, which this release
updates to the `bb27cca` campaign: every number in the manuscript now comes from one
commit.

## [1.0.2] — 2026-11-23

No changes to the analysis code: the mesh, the case files, the solver setup and the
verdict logic are identical to `bb27cca`. This release is documentation, tests and
metadata only, so the numbers reported in the manuscript are exactly those a user gets
from this version.

### Added

- `CHANGELOG.md` (this file).
- Regression tests with real force histories from the `bb27cca` campaign
  (`tests/test_regresion_v102.py`, with fixtures in `tests/fixtures/`): NACA 0012 at
  Re = 6×10⁶, level 2, at 0° and 10°, and the three mesh levels of the 14° and 10°
  grid studies. They pin the coefficients (Cl 1.0656 and Cd 0.01142 at 10°; Cd 0.00784
  at 0°), the verdict, the GCI order (1.30 at 10°), the extrapolated values and both
  uncertainty bands. `banda` is the band of the finest level (±3.86 % on Cd) and
  `banda_media` the band of the mesh actually used for the polar (10.01 %); the tests
  keep them apart because confusing them was a real defect found in review.
- `tests/test_sensibilidad_veredicto.py`: the verdict is stable when its window or drift
  thresholds move, and the range threshold (1 % of the window) is the one that actually
  decides. Narrowing it to 0.5 % rejects a run whose Cd range is 0.8 %, which is how the
  sensitivity analysis rejects 15 of the 49 converged runs.
- `docs/VALIDACION.md`: the 14° grid study (band ±0.026 in Cl and ±0.0023 in Cd,
  narrower than the interpolation it replaces), the measured wall-clock times of a clean
  polar (20 jobs in 120 min; a converged level-2 point in 16 to 48 min including upload
  and download), the verdict sensitivity analysis (63 SST runs, 49 converged, no level-3
  verdict changes under any threshold), and which polar rows carry an interpolated band.

### Changed

- `docs/VALIDACION.md` now states that every figure comes from the `bb27cca` campaign
  and replaces the old "16 to 24 minutes" timing, which came from runs that shared
  servers with other flows and therefore measured queueing, not compute.
- `docs/VALIDACION.md` explains what turbulence actually reaches the airfoil: the
  0.0062 % figure is with Tu = 0.2 % at the inlet, not with the default
  (Tu = 0.052 %, νt/ν = 0.009, which arrives at 0.0005 %).
- README: current test count (426 collected: 423 passing, 3 skipped, 9 of them new in
  this release).

### Fixed

- `docs/VALIDACION.md` was missing the `lm_x2_gci` study. It is now documented as
  **not monotonic** (Cd 0.00662, 0.00638, 0.00647 across levels 1 to 3), so no order
  can be estimated and no band is reported; it is kept separate from the ×4
  chord-refinement study, which does converge.

### Known limitations

Unchanged from v1.0.1, and documented in `docs/VALIDACION.md` §9: stall is not
predicted; drag from 14° up is 10 to 15 % high against Ladson; level 2 is enough for Cl
but not for Cd within 5 % of TMR; SST-LM drag is not validated; k-ε, k-ω,
Spalart-Allmaras and FSI are not validated and the interface does not label them as
such yet (planned for v1.0.3).

## [1.0.1] — 2026-11-0x

Earlier release; see the Git history and the archived version at
[10.5281/zenodo.24045781](https://doi.org/10.5281/zenodo.24045781).

## [1.0.0] — 2026-11-0x

First public release: [10.5281/zenodo.24028940](https://doi.org/10.5281/zenodo.24028940).
