# OpenBlade 2D — Guía de Instalación y Uso

[English](README.md) · Español

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.24028939.svg)](https://doi.org/10.5281/zenodo.24028939) · Para citarlo: v1.0.0, [10.5281/zenodo.24028940](https://doi.org/10.5281/zenodo.24028940); detalles en [CITATION.cff](CITATION.cff).

**Workbench CFD 2D para Perfiles Aerodinámicos**

Programa desarrollado en el Instituto Tecnológico del Valle de Etla (ITVE-TecNM).  
Directores: Alejandro Gómez Sánchez, Heriberto Cruz Martínez.  
Desarrollador: Jesús Miguel Ruiz Martínez.

---

## Descripción

OpenBlade 2D es un entorno de simulación CFD (Computational Fluid Dynamics) para el análisis aerodinámico de perfiles alares. Genera la malla en esta máquina y resuelve con **OpenFOAM 12**, en local (vía Docker) o en servidores por SSH, con una interfaz gráfica construida en Python.

Lo que se ha validado, con qué tolerancias y lo que no cumple está en [docs/VALIDACION.md](docs/VALIDACION.md).

### Características principales
- Generación automática de perfiles NACA (4 dígitos) o importación de perfiles personalizados
- Malla C estructurada propia, con niveles anidados para estudios de malla (GCI), y con y+ estimado antes de calcular y medido después
- Solvers estacionarios (simpleFoam) y transitorios (pimpleFoam)
- Inicialización de flujo potencial (potentialFoam)
- Modelos de turbulencia: k-ω SST, k-ε, Spalart-Allmaras, k-ω SST-LM (transición)
- Visualización 3D interactiva de resultados (campos de presión/velocidad)
- Barrido paramétrico de ángulo de ataque con curvas Cl vs α, Cd vs α
- Monitor de convergencia en tiempo real (residuos)
- Veredicto en cada corrida: CONVERGIDO, NO CONVERGIDO o DIVERGIDO, con media y amplitud de Cl, Cd y Cm
- Ficha por caso con las huellas sha256 de la malla y de los diccionarios, versiones y checkMesh
- Cola de trabajos: cada paquete tiene su carpeta y se reparte entre Local y varios servidores
- Estudio de malla con incertidumbre (GCI) y banco de validación frente a NASA TMR y Ladson, con informe PDF

---

## Requisitos Previos (Todas las Plataformas)

| Software | Versión mínima | Propósito |
|---|---|---|
| Python | 3.10+ | Motor de la aplicación |
| Docker Desktop | 4.0+ | Ejecutar OpenFOAM en Local sin compilar (no hace falta si solo se usan servidores) |
| Git | 2.0+ | Descargar el código fuente |

---

## 🍎 Instalación en macOS

### 1. Instalar Python
```bash
# Opción A: Desde python.org (recomendado)
# Descargar de https://www.python.org/downloads/

# Opción B: Con Homebrew
brew install python@3.12
```

### 2. Instalar Docker Desktop
1. Descargar desde [docker.com/products/docker-desktop](https://www.docker.com/products/docker-desktop/)
2. Abrir el archivo `.dmg` e instalar arrastrando a Aplicaciones
3. Abrir Docker Desktop y esperar a que la ballena 🐳 esté quieta en la barra superior

### 3. Construir la imagen de OpenFOAM

Es OpenFOAM 12, la misma versión que usan los servidores. Se construye una sola vez, después del paso 4.
```bash
docker build --platform linux/amd64 -t openblade/openfoam12:20250206 -f docker/Dockerfile.openfoam12 docker
```

### 4. Descargar OpenBlade 2D
```bash
git clone https://github.com/AlexGom27/OpenBlade.git OpenBlade2D
cd OpenBlade2D
```

### 5. Instalar dependencias de Python
```bash
pip3 install -r requirements.txt
```

### 6. Ejecutar
```bash
python3 main.py
```

> **⚠️ Nota macOS:** Si aparece el mensaje `"Python" no se puede abrir porque no se puede verificar al desarrollador`, ve a **Preferencias del Sistema → Seguridad y Privacidad → Abrir de todos modos**.

---

## 🐧 Instalación en Linux (Ubuntu/Debian)

### 1. Instalar Python y dependencias del sistema
```bash
sudo apt update
sudo apt install -y python3 python3-pip python3-venv git
sudo apt install -y libgl1-mesa-glx libxkbcommon-x11-0 libxcb-xinerama0 libegl1
```

### 2. Instalar Docker Engine
```bash
# Añadir repositorio oficial de Docker
sudo apt install -y ca-certificates curl gnupg
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io

# Permitir usar Docker sin sudo
sudo usermod -aG docker $USER
newgrp docker
```

### 3. Construir la imagen de OpenFOAM

Es OpenFOAM 12, la misma versión que usan los servidores. Se construye una sola vez, después del paso 4.
```bash
docker build --platform linux/amd64 -t openblade/openfoam12:20250206 -f docker/Dockerfile.openfoam12 docker
```

### 4. Descargar OpenBlade 2D
```bash
git clone https://github.com/AlexGom27/OpenBlade.git OpenBlade2D
cd OpenBlade2D
```

### 5. Crear entorno virtual e instalar dependencias
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 6. Ejecutar
```bash
source venv/bin/activate  # (si no está activado)
python3 main.py
```

> **💡 Tip Linux:** Si tienes problemas gráficos con Qt, prueba: `export QT_QPA_PLATFORM=xcb` antes de ejecutar.

---

## 🪟 Instalación en Windows

### 1. Instalar Python
1. Descargar desde [python.org/downloads](https://www.python.org/downloads/)
2. **IMPORTANTE:** Marca la casilla ☑️ **"Add Python to PATH"** durante la instalación

### 2. Instalar Docker Desktop
1. Descargar desde [docker.com/products/docker-desktop](https://www.docker.com/products/docker-desktop/)
2. Instalar y reiniciar la computadora cuando lo solicite
3. Si pide activar WSL 2, seguir las instrucciones en pantalla
4. Abrir Docker Desktop y esperar a que esté listo (icono verde)

### 3. Construir la imagen de OpenFOAM

Es OpenFOAM 12, la misma versión que usan los servidores. Se construye una sola vez, después del paso 4.
```powershell
docker build --platform linux/amd64 -t openblade/openfoam12:20250206 -f docker/Dockerfile.openfoam12 docker
```

### 4. Descargar OpenBlade 2D
```powershell
git clone https://github.com/AlexGom27/OpenBlade.git OpenBlade2D
cd OpenBlade2D
```

### 5. Instalar dependencias de Python
```powershell
pip install -r requirements.txt
```

### 6. Ejecutar
```powershell
python main.py
```

> **⚠️ Nota Windows:** Docker Desktop requiere **WSL 2** (Windows Subsystem for Linux). Si al instalar Docker te pide habilitarlo, ejecuta en PowerShell como Administrador:
> ```powershell
> wsl --install
> ```
> Y reinicia la computadora.

---

## Correr en un servidor

En la sección **Ejecución** del panel elige *Servidor (SSH)*, escribe `usuario@host`, pulsa **Probar conexión** e indica los procesos. El programa genera la malla y prepara el caso en esta máquina, lo sube con `rsync`, lo ejecuta en el servidor y descarga los resultados al terminar.

La primera vez en cada computadora, pulsa **Configurar acceso…** y escribe la contraseña del servidor: se instala una clave SSH y la contraseña no se guarda (Mac y Linux; en Windows, desde WSL).

Requisitos: `rsync` en esta máquina, y `rsync`, `python3` y OpenFOAM en el servidor. Los trabajos quedan en `~/openblade_jobs/`. Cerrar la app no los detiene: al abrirla de nuevo los retoma.

## Trabajos y reparto

Cada **Iniciar Análisis** envía un paquete con su propia carpeta en `~/.openblade/jobs/`; se puede lanzar otro sin esperar al anterior. La pestaña **Trabajos** muestra todos, con su máquina, estado y veredicto; con doble clic se ve uno en la ventana.

Con **Correr en: Repartir entre máquinas**, cada paquete va al servidor marcado con menos trabajo. Cada servidor guarda su propia cola y corre a la vez los indicados en «A la vez». Un barrido de ángulos envía un paquete por ángulo y la polar se completa a medida que terminan. La pestaña **Servidor** muestra todos los servidores y todos sus casos, con su avance.

Los mismos parámetros dan el mismo archivo de malla, y cada máquina verifica la ficha antes de calcular: un paquete alterado se rechaza. El mismo paquete con los mismos procesos da fuerzas idénticas en Local y en los servidores.

## Sin ventana

```bash
python3 -m core.cli doctor --hosts usuario@a,usuario@b
```

`doctor` comprueba sin lanzar nada que todo está listo: versiones, espacio en disco, Docker, acceso a cada servidor y OpenFOAM.

```bash
python3 -m core.cli correr --host usuario@host --procesos 8 aoa=8 reynolds=6e6
```

```bash
python3 -m core.cli control --hosts usuario@a,usuario@b --procesos 8
```

`control` corre el caso de control en cada máquina y evalúa sus 8 compuertas: misma malla, mismas fuerzas fila por fila, convergencia y comparación con Ladson.

```bash
python3 -m core.cli banco --maquinas usuario@a:10:1,usuario@b:8:1 --salida carpeta
```

`banco` corre el NACA 0012 frente a NASA TMR y Ladson y deja un informe PDF con lo que cumple y lo que no.

```bash
python3 -m core.cli polar --maquinas usuario@a:10:1 --angulos 0,4,8 --gci 0,8 --urans reynolds=6e6
```

`polar` lanza un paquete por ángulo, añade un GCI de tres mallas en los ángulos de `--gci` y deja `polar.csv`, `polar.json` y `polar.png`. Con `--urans` repite en transitorio los ángulos que no convergen, arrancando de su campo estacionario. Con `--continuar` retoma una campaña interrumpida: lo terminado no se repite y lo que sigue en su máquina se recoge.

Lo enviado sigue en los servidores aunque esta computadora se duerma, se cierre el programa o se cierre la sesión; al abrir de nuevo, los trabajos aparecen y se descargan. Dos cosas dependen todavía de esta computadora: la parada temprana (sin conexión, el cálculo llega al tope de iteraciones) y los niveles finos de un estudio de malla.

Todas estas órdenes usan las mismas funciones que la ventana. En la ventana están en el botón **Banco de Validación** y en **Análisis: Estudio de Malla**. Para abrir un proyecto guardado: `python3 main.py proyecto.obp`.

## 🚀 Uso Rápido

### Flujo de trabajo recomendado:

```
1. Si vas a correr en Local, abrir Docker Desktop y esperar a que esté listo
2. Ejecutar: python3 main.py
3. Configurar perfil, condiciones de frontera y dónde correr
4. Pulsar "Generar Malla" para verla (opcional: el análisis la genera si no existe)
5. Pulsar "Iniciar Análisis"
6. Leer el veredicto en la franja superior antes de usar los números
7. Pulsar "Ver Resultados"
```

### Parámetros recomendados para primera simulación:

| Parámetro | Valor |
|---|---|
| Perfil | NACA 0012 |
| Ángulo de ataque | 5° |
| Velocidad de entrada | 15 m/s |
| Régimen | Estacionario (simpleFoam) |
| Modelo de turbulencia | k-Omega SST |
| Iteraciones máximas | 40000 (es un tope: termina antes si las fuerzas ya no cambian) |

---

## 🔧 Solución de Problemas Comunes

| Problema | Solución |
|---|---|
| `docker: command not found` | Abre Docker Desktop y espera a que esté listo |
| `ERROR: Comando 'docker' no encontrado` | Docker Desktop no está abierto o no está instalado |
| El veredicto dice DIVERGIDO | Revisa Tu y νt/ν de entrada y la malla; esos coeficientes no son un resultado |
| El veredicto dice NO CONVERGIDO | Aumenta las iteraciones, o usa el régimen transitorio si Cl oscila |
| `Paquete alterado, no se calcula` | Un archivo cambió después de crear la ficha: lanza el análisis de nuevo |
| La GUI se congela | Espera a que termine el proceso actual; no dar doble clic |
| `ModuleNotFoundError` | Ejecuta `pip install -r requirements.txt` de nuevo |
| Pantalla negra en visualización 3D | Actualiza tus drivers gráficos (especialmente en Linux) |

---

## 📄 Licencia

OpenBlade es software libre bajo la [Licencia Pública General de GNU, versión 3](LICENSE.txt) (GPL-3.0-only). Puede usarse, también en empresas, modificarse y redistribuirse; quien lo redistribuya, modificado o no, debe hacerlo bajo la misma licencia y con su código fuente. Se distribuye sin garantía: ver las secciones 15 y 16 de la licencia y los límites de validación en [docs/VALIDACION.md](docs/VALIDACION.md).

Desarrollado en el ITVE-TecNM.  
Contacto: alejandro.gs@itvalletla.edu.mx
