# openblade2 — puesta a punto sin root

**Fecha:** 2026-10-30
**Máquina:** openblade2, Ubuntu 24.04.5, i5-14500 (20 hilos), 15 GB RAM
**Tailscale:** `100.109.3.56`

---

## El problema

openblade2 llegó sin nada instalado y con una restricción: **`sudo` pide
contraseña**. El primer servidor tiene `NOPASSWD`, este no.

```
$ sudo -n true
sudo: a password is required
```

Y no había base sobre la que trabajar:

```
OpenFOAM:  no instalado
MPI:       no instalado
gmsh:      no instalado
gcc/g++:   no instalados
make/cmake: no instalados
```

Todo se resolvió instalando **bajo `$HOME`**, sin privilegios.

---

## Lo que se instaló y cómo

### 1. Python: pip sin `python3-venv`

El sistema no tiene `ensurepip`, así que `python3 -m venv` crea un venv vacío
sin pip. Y PEP 668 bloquea `pip install` global.

```bash
curl -sSL https://bootstrap.pypa.io/get-pip.py -o /tmp/get-pip.py
python3 /tmp/get-pip.py --user --break-system-packages
python3 -m pip install --user --break-system-packages \
    gmsh==4.15.2 gmshairfoil2d scipy numpy
```

Quedan en `~/.local/lib/python3.12/site-packages`.

### 2. Librerías gráficas para gmsh

`import gmsh` falla porque la librería enlaza contra OpenGL y X11:

```
OSError: libGLU.so.1: cannot open shared object file
```

Se descargan los `.deb` y se extraen con `dpkg-deb -x` (sin `dpkg -i`, que
necesita root):

```bash
apt-get download libglu1-mesa libgl1 libglx-mesa0 libglvnd0 \
                 libxrender1 libxext6 libx11-6 libxcb1 libxau6 libxdmcp6 \
                 libbsd0 libmd0 libglx0 libopengl0 libxcursor1 libxfixes3 \
                 libxft2 libxinerama1 libgomp1
for f in *.deb; do dpkg-deb -x "$f" ./root; done
cp ./root/usr/lib/x86_64-linux-gnu/*.so* ~/lib/gl/
```

**39 librerías** en total. La cadena se descubrió iterando:

```
libGLU -> libXrender -> libXcursor -> libXfixes -> libXft -> libXinerama
```

### 3. OpenFOAM 12

Ubuntu 24.04 no trae `openfoam12` en sus repos. Hay que añadir el de
OpenFOAM, pero sin escribir en `/etc/apt`:

```bash
mkdir -p ~/aptcfg/lists/partial
echo "deb [trusted=yes] http://dl.openfoam.org/ubuntu noble main" \
    > ~/aptcfg/sources.list
apt-get -o Dir::Etc::sourcelist=$HOME/aptcfg/sources.list \
        -o Dir::Etc::sourceparts=/dev/null \
        -o Dir::State::lists=$HOME/aptcfg/lists update
apt-get -o ... download openfoam12
dpkg-deb -x openfoam12_*.deb ./stage
cp -r ./stage/opt/openfoam12 ~/opt/
```

**604 MB** instalados, autocontenidos (traen sus propias libs).

### 4. Open MPI 4.1.6

```bash
apt-get download openmpi-bin libopenmpi3t64 libopenmpi-dev
dpkg-deb -x openmpi-bin*.deb ./stage2   # etc.
```

Aquí aparecieron **tres problemas encadenados**:

**a) `orterun` rechaza todas las opciones** (`-np`, `--version`) y devuelve
`Error: unknown option "-np"`. Causa: el binario no encuentra su árbol de
instalación. Solución: `OPAL_PREFIX`.

```bash
export OPAL_PREFIX=$HOME/ofpkg/stage2/usr
```

**b) PMIx de Ubuntu no encuentra sus ficheros y aborta.** Solución: desactivar
el componente `pmix2`.

```bash
orterun --mca pmix ^pmix2 -np 4 hostname
```

**c) Faltaban dependencias**: `libhwloc15`, `libevent-core`, `libpmix2t64`,
`libmunge2`, `libscotch-7.0`, `libscotch-dev`, `libptscotch-7.0`.

### 5. Entorno

Todo queda en `~/ofenv.sh`, que hay que cargar antes de usar OpenFOAM:

```bash
source ~/ofenv.sh
```

---

## Los dos fallos de OpenFOAM que hay que conocer

### La librería dummy de Pstream

```
FOAM FATAL ERROR: Trying to use the dummy Pstream library.
This dummy library cannot be used in parallel mode
```

OpenFOAM trae dos `libPstream.so`:

```
$FOAM_LIBBIN/dummy/libPstream.so          <- monoproceso, no vale
$FOAM_LIBBIN/openmpi-system/libPstream.so <- la buena
```

Si `dummy` entra antes en el `LD_LIBRARY_PATH`, el solver paralelo aborta. Hay
que poner `openmpi-system` **primero** y `FOAM_MPI=openmpi-system`.

Pero `libmetisDecomp.so` (que necesita `decomposePar`) **solo** existe en
`dummy/`. Por eso el orden correcto es:

```
openmpi-system : gl : local : mpi : scotch : lib : dummy
```

`openmpi-system` al principio, `dummy` al final como último recurso.

### `MPI_BUFFER_SIZE`

```
FOAM FATAL ERROR: environment variable MPI_BUFFER_SIZE not defined
```

Normalmente lo pone `etc/config.sh/mpi`, que se ejecuta desde el `bashrc` del
sistema. Cargando el entorno a mano hay que definirlo:

```bash
export MPI_BUFFER_SIZE=20000000
```

---

## Verificación

```
foamRun          ok        mpirun        ok
simpleFoam       ok        gmsh          ok
blockMesh        ok        gmshToFoam    ok
decomposePar     ok        potentialFoam ok

python3 -c "import gmsh,numpy,scipy,gmshairfoil2d"   -> ok
```

Prueba completa ejecutada: malla de 20 MB → `gmshToFoam` → `decomposePar` en 4
particiones → `mpirun -np 4 foamRun` con 50 iteraciones, `rc=0`.

---

## Diferencias con el primer servidor

| | openblade | openblade2 |
|---|---|---|
| Tailscale | 100.85.66.123 | 100.109.3.56 |
| CPU | 20 hilos / 10 físicos | i5-14500, 20 hilos |
| RAM | 15 GB | 15 GB |
| Disco | 466 GB (406 libres) | **100 GB (85 libres)** |
| sudo | NOPASSWD | **pide contraseña** |
| OpenFOAM | `/opt/openfoam12` (apt) | `~/opt/openfoam12` (extraído) |
| MPI | sistema | `~/ofpkg` + `OPAL_PREFIX` |

---

## Pendiente

**1. Ampliar el volumen LVM.** El disco físico es de 473 GB pero el volumen
lógico solo 100 GB:

```
nvme0n1                    476.9G
  ubuntu--vg-ubuntu--lv    100G  /
```

Hay **374 GB sin asignar**. Ampliarlo requiere root:

```bash
sudo lvextend -l +100%FREE /dev/ubuntu-vg/ubuntu-lv
sudo resize2fs /dev/ubuntu-vg/ubuntu-lv
```

Con 85 GB libres alcanza para la campaña actual (el primer servidor usa 40 GB
con 44 casos), pero no para muchas más.

**2. Instalación limpia con root.** Si consigues la contraseña, es más robusto:

```bash
sudo apt install openfoam12 openmpi-bin gmsh
```

Eso evita `OPAL_PREFIX`, el `--mca pmix ^pmix2`, los 39 `.so` de X11 y el
`MPI_BUFFER_SIZE` manual. El entorno quedaría en una línea:
`source /opt/openfoam12/etc/bashrc`.

**3. Repo en openblade2.** Copiado por `tar` desde el primer servidor, sin `.git`
(no hay clave SSH de GitHub en esta máquina). Para trabajar con git habría que
añadir una clave.
