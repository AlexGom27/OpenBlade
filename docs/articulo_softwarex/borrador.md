# OpenBlade: verifiable 2D RANS airfoil polars with per-point verdict, grid uncertainty and traceable packages

Draft for SoftwareX (Original Software Publication). Status: outline with measured results; sections marked TODO are pending. Limit about 3000 words, to be checked against the current Guide for Authors.

## Code metadata

| Nr | Code metadata description | Value |
|---|---|---|
| C1 | Current code version | TODO: tag a release (no tag yet) |
| C2 | Permanent link to code/repository | https://github.com/AlexGom27/OpenBlade (must be public before submission) |
| C3 | Permanent link to reproducible capsule | TODO (optional) |
| C4 | Legal code license | GPL-3.0-only |
| C5 | Code versioning system used | git |
| C6 | Software code languages, tools and services used | Python 3, PySide6, gmsh, NumPy, SciPy, OpenFOAM 12 |
| C7 | Compilation requirements, operating environments and dependencies | macOS or Linux desktop; OpenFOAM 12 locally (Docker) or on Linux servers over SSH; `requirements.txt` with pinned versions |
| C8 | Link to developer documentation/manual | `README.md`, `docs/VALIDACION.md` |
| C9 | Support email for questions | alejandro.gs@itvalletla.edu.mx |

## 1. Motivation and significance

Airfoil polars feed blade element momentum and vortex codes used for wind turbines. They are usually produced with panel and boundary-layer methods, which are fast but limited near and beyond stall, or with RANS run by hand, where mesh, stopping criterion and convergence are left to the user. OpenBlade generates the mesh and case on the desktop, sends only the computation to the user's servers, and returns each polar point with a verdict, a grid uncertainty band and a hashed record of everything that produced it.

Contribution: not a new solver, but a workflow that makes RANS polar results checkable and repeatable, and that refuses to present unconverged or unsupported results as valid.

## 2. Software description

### 2.1 Architecture
- Desktop window and command line share the same core (`core/`).
- Own nested C-grid generator: levels 225×65, 449×129, 897×257; fixed across angles, flow rotated.
- Package: case, mesh and `ficha.json` with sha256 of every file, program version and parameters. Servers refuse altered packages.
- Job queue across several servers, several jobs per server, resumed after network cuts or sleep.

### 2.2 Functionalities
- Verdict per point: CONVERGIDO, NO CONVERGIDO (with "oscillates" flag), DIVERGIDO, SIN DATOS, from the drift between the last two fifths of the run.
- Grid study with GCI (r=2, Fs=1.25), chained starts from the coarser level.
- Polar with mesh band, rescue of failed points from a neighbouring angle, export of converged points only.
- Warnings: open trailing edge closed by the mesh (with Hoerner base drag), inlet turbulence that decays before the airfoil in transition runs.

## 3. Illustrative examples (measured)

- NACA 0012, Re=6e6, SST: Cl within 1.7 % of Ladson from 4 to 17 degrees; Cd within its grid band up to 12 degrees. Bench: 35 of 40 checks.
- Reproducibility: forces identical byte by byte on two servers over full runs.
- Finding reported by the tool: on the default mesh the closeness of Cd to experiment is partly error compensation; refining moves Cd away from Ladson and towards the NASA TMR codes.
- Limits reported by the tool: no stall prediction with SST; SST-LM drag depends on the turbulence reaching the airfoil.
- TODO: NACA 0012 at Re 2e6 and 4e6 with grid study; NACA 4412 and NACA 63(3)-418 against Abbott and von Doenhoff (tolerances fixed before running, see `docs/VALIDACION.md`).

## 4. Impact
TODO: teaching use at ITVE-TecNM, research use, comparison with typical manual RANS workflows.

## 5. Conclusions
TODO.

## Pending before submission
- Make the repository public and tag a release.
- Confirm the Guide for Authors: word limit, metadata fields, accepted licenses, fee (secondary sources give USD 760 or 970, not confirmed).
- Authors and affiliations; software registration number.
- Figures: polar with bands, grid study, window screenshot.
