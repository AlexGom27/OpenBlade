# OpenBlade 2D

English · [Español](README.es.md)

**Verifiable 2D RANS airfoil analysis with OpenFOAM.**

OpenBlade builds the mesh and the case on your computer, runs OpenFOAM 12 locally (through Docker) or on your own Linux servers over SSH, and gives every result with a convergence verdict, a grid uncertainty band and a record of exactly what produced it.

Developed at the Instituto Tecnológico del Valle de Etla (ITVE, TecNM), Mexico, by Alejandro Gómez Sánchez, Jesús Miguel Ruiz Martínez and Heriberto Cruz Martínez.

What is validated, with which tolerances, and what does not pass is in [docs/VALIDACION.md](docs/VALIDACION.md) (Spanish). Read it before using the numbers.

---

## What it does

- **Airfoils:** NACA 4-digit profiles, or any profile from a coordinates file (Selig or Lednicer format).
- **Mesh:** its own nested structured C-grid (225×65, 449×129, 897×257), with y+ estimated before the run and measured after it. The angle of attack is set by the flow, so all angles share one mesh.
- **Solvers and models:** steady (simpleFoam) and transient (pimpleFoam); k-ω SST, k-ε, Spalart-Allmaras and k-ω SST-LM transition.
- **A verdict for every run:** CONVERGIDO, NO CONVERGIDO (with an "oscillates" flag) or DIVERGIDO, from the drift of the forces. Points that did not converge are flagged and do not get an uncertainty band.
- **Grid uncertainty:** grid studies with the Grid Convergence Index (GCI) on three nested levels, each level started from the solution of the previous one.
- **Traceability:** every case is a package with a `ficha.json` holding the sha256 of the mesh and every dictionary, program version and parameters. A server refuses a package that was altered after it was built. The same package gives byte-identical forces on two servers with the same hardware.
- **Several servers, one window:** each run is a package with its own folder. Packages go to the least busy server, and each server keeps its own queue, so work goes on if you close the program or your computer sleeps. The **Servidor** (Server) tab lists every server and every case with its progress.
- **Outputs:** Cl, Cd, Cm, Cp and Cf, 3D field views, residuals, polars with uncertainty bands, PDF reports, and the converged polar points exported in XFOIL text format.

## Current validation, in short

| Case | Result |
|---|---|
| NACA 0012, Re = 6×10⁶, SST, tripped | Cl within 1.7 % of Ladson (NASA TM 4074) from 4° to 17°. Validation bench: 35 of 40 checks pass |
| NACA 0012, Re = 3.99×10⁶ | Passes the tolerances fixed before running |
| NACA 0012, Re = 2×10⁶ | Fails two of three checks |
| NACA 4412 and NACA 63₃-418, cambered, Re = 6×10⁶ | Drag and moment within tolerance. NACA 63₃-418 lift is 3 to 5 % high against modern data; NACA 4412 lift is 6 to 11 % high against a reading of Abbott and von Doenhoff that still needs a second source |
| Stall | **Not predicted** with SST |
| Transition (SST-LM) | Not validated: drag depends on the turbulence that reaches the airfoil |
| Fluid-structure interaction (**Análisis FSI**) | Experimental: the Turek-Hron benchmark was not completed because the coupling diverges. Do not use its results |

---

## Requirements

| Software | Version | Why |
|---|---|---|
| Python | 3.10 or newer | The application |
| Docker | Desktop 4.0+ or Engine | OpenFOAM on your own computer. Not needed if you only use servers |
| Git | 2.0+ | To get the code |
| rsync | any | To send packages to servers |

On each server: Linux with OpenFOAM 12, `python3`, `rsync` and `flock` (util-linux). Tested with macOS (Apple silicon) as the desktop and Ubuntu 24.04 servers. The Linux and Windows desktop instructions below have not been re-tested for this release.

## Installation

### macOS

```bash
brew install python@3.12
```

Install [Docker Desktop](https://www.docker.com/products/docker-desktop/) and wait until it reports that it is running. Then:

```bash
git clone https://github.com/AlexGom27/OpenBlade.git OpenBlade2D
```

```bash
cd OpenBlade2D
```

```bash
pip3 install -r requirements.txt
```

```bash
docker build --platform linux/amd64 -t openblade/openfoam12:20250206 -f docker/Dockerfile.openfoam12 docker
```

```bash
python3 main.py
```

If macOS says Python cannot be opened because the developer cannot be verified, allow it in **System Settings → Privacy & Security**.

### Linux (Ubuntu or Debian)

```bash
sudo apt install -y python3 python3-pip python3-venv git rsync libgl1 libxkbcommon-x11-0 libxcb-xinerama0 libegl1
```

Install Docker Engine following [the official guide](https://docs.docker.com/engine/install/ubuntu/) and add your user to the `docker` group. Then:

```bash
git clone https://github.com/AlexGom27/OpenBlade.git OpenBlade2D && cd OpenBlade2D
```

```bash
python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt
```

```bash
docker build --platform linux/amd64 -t openblade/openfoam12:20250206 -f docker/Dockerfile.openfoam12 docker
```

```bash
python3 main.py
```

If Qt has graphics problems, run `export QT_QPA_PLATFORM=xcb` first.

### Windows

Install Python from [python.org](https://www.python.org/downloads/) and tick **Add Python to PATH**. Install [Docker Desktop](https://www.docker.com/products/docker-desktop/), which needs WSL 2. Then, in PowerShell:

```powershell
git clone https://github.com/AlexGom27/OpenBlade.git OpenBlade2D; cd OpenBlade2D
```

```powershell
pip install -r requirements.txt
```

```powershell
docker build --platform linux/amd64 -t openblade/openfoam12:20250206 -f docker/Dockerfile.openfoam12 docker
```

```powershell
python main.py
```

Running on servers from Windows needs `ssh` and `rsync`, for example inside WSL.

---

## Running on servers

1. In **Ejecución** (Execution), choose **Servidor (SSH)**, type `user@host` and press **Probar conexión** (Test connection).
2. The first time on each computer, press **Configurar acceso…** (Configure access) and type the server password once. An SSH key is installed; the password is not stored.
3. To use several servers, add them in the **Trabajos** (Jobs) tab and set how many processes (**Procesos**) and simultaneous runs (**A la vez**) each takes. Then choose **Repartir entre máquinas** (Spread across machines).

Packages are uploaded with `rsync` and kept in `~/openblade_jobs/` on the server. The mesh and the case are always built on your computer; servers only compute.

Two things still need the launching computer to be on: stopping early when the forces no longer change (without it the run goes on to its iteration limit), and starting the finer levels of a grid study, which begin from the field of the previous level.

## First run

1. If you run locally, open Docker first.
2. Run `python3 main.py`.
3. Set the airfoil, flow conditions and where to run.
4. Press **Iniciar Análisis** (Run Analysis).
5. Read the verdict in the banner before using any number.
6. Press **Ver Resultados** (View Results).

Suggested first case: NACA 0012, 5°, 15 m/s, steady, k-ω SST, 40000 iterations (an upper limit: the run stops earlier when the forces no longer change).

## Without the window

The command line uses the same functions as the window.

```bash
python3 -m core.cli doctor --hosts user@a,user@b
```

Checks versions, disk space, Docker, access to each server and OpenFOAM, without running anything.

```bash
python3 -m core.cli polar --maquinas user@a:8:2,user@b:8:2 --angulos 0,4,8,12 --gci 0,8 reynolds=6e6
```

One package per angle, a three-level GCI at the angles in `--gci`, and `polar.csv`, `polar.json`, `polar.png` and `polar_xfoil.txt` as output. `--continuar` resumes an interrupted campaign.

```bash
python3 -m core.cli banco --maquinas user@a:8:2 --salida bench
```

Runs the NACA 0012 validation bench against NASA TMR and Ladson and writes a PDF report.

```bash
python3 -m core.cli control --hosts user@a,user@b --procesos 8
```

Runs the same package on each server and checks that the forces match.

## Tests

```bash
python3 -m pytest -q
```

## Troubleshooting

| Problem | What to do |
|---|---|
| `docker: command not found` | Open Docker and wait until it is ready |
| Verdict DIVERGIDO | Check the inlet turbulence and the mesh; those coefficients are not a result |
| Verdict NO CONVERGIDO | Raise the iteration limit, or use the transient solver if Cl oscillates |
| `Paquete alterado, no se calcula` | A file changed after the package was built; run the analysis again |
| `ModuleNotFoundError` | Run `pip install -r requirements.txt` again |

The interface is in Spanish.

## License

OpenBlade is free software under the [GNU General Public License, version 3](LICENSE) (GPL-3.0-only). It can be used, also commercially, modified and redistributed; redistributed versions, modified or not, must use the same license and include their source code. It comes without warranty: see sections 15 and 16 of the license and the validation limits in [docs/VALIDACION.md](docs/VALIDACION.md).

Contact: alejandro.gs@itvalletla.edu.mx
