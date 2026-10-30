# OpenBlade 2D — Guía de Instalación y Uso

**Workbench CFD 2D para Perfiles Aerodinámicos**

Programa desarrollado en el Instituto Tecnológico del Valle de Etla (ITVE-TecNM).  
Directores: Alejandro Gómez Sánchez, Heriberto Cruz Martínez.  
Desarrollador: Jesús Miguel Ruiz Martínez.

---

## Descripción

OpenBlade 2D es un entorno de simulación CFD (Computational Fluid Dynamics) para el análisis aerodinámico de perfiles alares. Utiliza **Gmsh** para la generación de mallas y **OpenFOAM** (vía Docker) como solver Navier-Stokes, con una interfaz gráfica profesional construida en Python.

### Características principales
- Generación automática de perfiles NACA (4 dígitos) o importación de perfiles personalizados
- Mallado estructurado con hexaedros, tetraedros o malla mixta
- Solvers estacionarios (simpleFoam) y transitorios (pimpleFoam)
- Inicialización de flujo potencial (potentialFoam)
- Modelos de turbulencia: k-ω SST, k-ε, Spalart-Allmaras, k-ω SST-LM (transición)
- Visualización 3D interactiva de resultados (campos de presión/velocidad)
- Barrido paramétrico de ángulo de ataque con curvas Cl vs α, Cd vs α
- Monitor de convergencia en tiempo real (residuos)

---

## Requisitos Previos (Todas las Plataformas)

| Software | Versión mínima | Propósito |
|---|---|---|
| Python | 3.10+ | Motor de la aplicación |
| Docker Desktop | 4.0+ | Ejecutar OpenFOAM sin compilar |
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

### 3. Descargar la imagen de OpenFOAM
```bash
docker pull opencfd/openfoam-default
```

### 4. Descargar OpenBlade 2D
```bash
git clone <URL_DEL_REPOSITORIO> OpenBlade2D
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

## Correr en un servidor

En la sección **Ejecución** del panel elige *Servidor (SSH)*, escribe `usuario@host`, pulsa **Probar conexión** e indica los procesos. El programa genera la malla y prepara el caso en esta máquina, lo sube con `rsync`, lo ejecuta en el servidor y descarga los resultados al terminar.

Requisitos: clave SSH sin contraseña, y `rsync`, `python3` y OpenFOAM en el servidor. Los trabajos quedan en `~/openblade_jobs/`. Cerrar la app no los detiene: al volver a iniciar en modo servidor se ofrece reconectar.

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

### 3. Descargar la imagen de OpenFOAM
```bash
docker pull opencfd/openfoam-default
```

### 4. Descargar OpenBlade 2D
```bash
git clone <URL_DEL_REPOSITORIO> OpenBlade2D
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

### 3. Descargar la imagen de OpenFOAM
```powershell
docker pull opencfd/openfoam-default
```

### 4. Descargar OpenBlade 2D
```powershell
git clone <URL_DEL_REPOSITORIO> OpenBlade2D
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

## 🚀 Uso Rápido

### Flujo de trabajo recomendado:

```
1. Abrir Docker Desktop (esperar a que esté listo)
2. Ejecutar: python3 main.py
3. Configurar perfil NACA y condiciones de frontera
4. Pulsar "1. Construir Geometría"
5. Pulsar "2. Generar Malla"
6. Pulsar "🌊 Inicializar Flujo Potencial" (recomendado)
7. Pulsar "3. Iniciar Análisis"
8. Pulsar "4. Ver Resultados"
```

### Parámetros recomendados para primera simulación:

| Parámetro | Valor |
|---|---|
| Perfil | NACA 0012 |
| Ángulo de ataque | 5° |
| Velocidad de entrada | 15 m/s |
| Régimen | Estacionario (simpleFoam) |
| Modelo de turbulencia | k-Omega SST |
| Tipo de elemento | Hexaedros |

---

## 🔧 Solución de Problemas Comunes

| Problema | Solución |
|---|---|
| `docker: command not found` | Abre Docker Desktop y espera a que esté listo |
| `ERROR: Comando 'docker' no encontrado` | Docker Desktop no está abierto o no está instalado |
| Residuos divergen explosivamente | Usa "Inicializar Flujo Potencial" antes del análisis |
| La GUI se congela | Espera a que termine el proceso actual; no dar doble clic |
| `ModuleNotFoundError` | Ejecuta `pip install -r requirements.txt` de nuevo |
| Pantalla negra en visualización 3D | Actualiza tus drivers gráficos (especialmente en Linux) |

---

## 📄 Licencia

Software académico desarrollado en el ITVE-TecNM.  
Contacto: alejandro.gs@itvalletla.edu.mx
