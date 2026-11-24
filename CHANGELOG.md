# Changelog

All notable changes to OpenBlade are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[semantic versioning](https://semver.org/spec/v2.0.0.html).

Validation figures quoted below come from `docs/VALIDACION.md`, which this release
updates to the `bb27cca` campaign: every number in the manuscript now comes from one
commit.

## [1.0.3] — 2026-11-24

**Documentation only; code identical to v1.0.2.** No file that executes has changed:
`core/`, `gui/`, `tests/` and `docker/` are byte-for-byte the same as v1.0.2, so the
figures a user gets from this release are exactly those of v1.0.2. No new runs: every
number comes from the existing `bb27cca` campaign. The suite is unchanged: 433 tests
collected, 430 passing and 3 skipped, the same as v1.0.2.

### Fixed

- `docs/VALIDACION.md`: the main polar table mixed two Ladson data sets. Rows 0°–12°
  used the 80-grit series and rows 14°–17° used the 180-grit one, so the drag
  differences above 12° were overstated. All rows now use 80 grit, which is what the
  program has always done (`core/bench.py`, `ladson(aoa, zona="80 grit")`) and what the
  manuscript reports. Drag from 14° to 17° is 8.2 % to 12.8 % above Ladson, not 10.5 %
  to 15.0 %; lift changes by less than a tenth and no conclusion moves. The summary row
  and the limits section were updated to match.
- `docs/VALIDACION.md`: the polar command said `--gci 0,10,15`. The `bb27cca` campaign
  used `--gci 0,10,14,15`, which is also what the manuscript reports.
- `docs/VALIDACION.md`: a paragraph on the 8-versus-9-process comparison (`control_p8`
  against `control_p9_bb27cca`). The force histories differ from the first iteration
  (different md5), while the converged means at 8° are Cl 0.8615 and 0.8614 and Cd
  0.00987 and 0.00989, inside the 0.6 % range of Cd in the window. Those report values
  are the ones the manuscript uses.
- `docs/VALIDACION.md`: the polar section states which rows carry a measured band (0°,
  10°, 14°, 15°) and which an interpolated one (2°, 4°, 6°, 8°, 12°), and the stale
  "GCI at 0°, 10° and 15°" line is corrected.
- `docs/VALIDACION.md`: a note in the 2026-11-03 entry pointing to the Pinkerton table at
  the matching Reynolds number, so the historical +17 %/+11 % (which compared
  Re = 3×10⁶ data against 6×10⁶ runs) is not read as a like-for-like result. The
  original record is kept.

### Added

- `docs/VALIDACION.md`: the NACA 4412 at Re = 3×10⁶ against Pinkerton, at his effective
  angle. It was a pending test and is now done: lift is 8.1 % to 15.5 % high and the
  5 % tolerance fails at all five angles (0°, 2°, 4°, 6° and 8°), the same excess seen
  against Abbott at 6×10⁶.
- `docs/VALIDACION.md`: the maximum y+ (1.63) next to the mean (0.69) in the grid-level
  table, both from the NACA 0012 level 2 at 10°.
- `docs/VALIDACION.md`: a precise description of the verdict as `core/verdict.py`
  implements it —drift between the last two fifths with runs of at least 500
  iterations, Cd mean under 0.3 %, Cl mean under 0.15 % of max(|Cl|, 0.1); ranges over
  the last 500 iterations, Cd under 1 %, Cl and Cm under 1 % or 0.002; DIVERGIDO above
  |Cl| or |Cd| = 5 or with negative Cd— and the statement that residuals do not enter
  the verdict.
- `docs/VALIDACION.md`: gmsh meshes added to the list of what is not validated, next to
  k-ε, k-ω, Spalart–Allmaras and FSI.

### Changed

- `docs/VALIDACION.md` §9: who stops a run. With `bb27cca` the server-side watcher
  (`core/remote_job.py`, `veredicto_de_series`) stops the run when the drag and lift
  checks pass, without looking at the pitching moment; the moment is checked on the Mac
  when the results arrive. The 1e-6 `residualControl` can also end a run on its own, and
  that run is still judged by its forces.
- `CITATION.cff`: version 1.0.3, released 2026-11-24. The v1.0.3 DOI does not exist until
  Zenodo creates it on release, so the file keeps the concept DOI
  (10.5281/zenodo.24028939) and adds v1.0.2 = 10.5281/zenodo.24488753 to the list.
- `README.md` and `README.es.md`: the citation note now lists v1.0.2
  (10.5281/zenodo.24488753) and says that v1.0.3 is the same code with corrected
  documentation.

### Not in this release

The code fixes found while reviewing the campaign move to v1.0.4: re-downloading
`constant/polyMesh`, the shared SSH control channel per host, non-atomic writes of
`controlDict`, a failed download marking a finished run as failed, solver-only timings in
`job.json`, back-off for the repeated "no response" notice, a visible label for
unvalidated models, `banda_origen` in `polar.json`, and recording when the GCI order is
capped.

## [1.0.2] — 2026-11-23

No changes to the analysis code: the mesh, the case files, the solver setup and the
verdict logic are identical to `bb27cca`. This release is documentation, tests and
metadata only, so the numbers reported in the manuscript are exactly those a user gets
from this version.

### Added

- `CHANGELOG.md` (this file).
- Regression tests with real force histories from the `bb27cca` campaign
  (`tests/test_regresion_v102.py`, with fixtures in `tests/fixtures/`): NACA 0012 at
  Re = 6×10⁶, level 2, at 0°, 10° and 14°, and the three mesh levels of the 10° and 14°
  grid studies. Over a fixed history the computation is deterministic, so the exact
  values the code produces are pinned at `rel=1e-9` —verdict, n_rows, Cl, Cd, Cm, the
  GCI order, the extrapolated value and both uncertainty bands— and, in separate
  assertions, that those values rounded are the ones the manuscript publishes. A shift
  of a single row in the averaging window is enough to fail them. `banda` is the band of
  the finest level (3.85 % on Cd at 10°) and `banda_media` the band of the mesh actually
  used for the polar (9.99 %); the tests keep them apart because confusing them was a
  real defect found in review.
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
- README: current test count (433 collected: 430 passing, 3 skipped, 16 of them new in
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

## [1.0.1] — 2026-11-07

Earlier release; see the Git history and the archived version at
[10.5281/zenodo.24045781](https://doi.org/10.5281/zenodo.24045781).

## [1.0.0] — 2026-11-06

First public release: [10.5281/zenodo.24028940](https://doi.org/10.5281/zenodo.24028940).
