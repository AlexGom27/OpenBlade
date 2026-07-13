from qtpy.QtCore import QThread, Signal, QProcess, QObject
import os
import sys
import json
import time
import subprocess
import numpy as np
from typing import Dict, Any, List


class MeshWorker(QThread):
    finished = Signal(str, str)
    error = Signal(str)
    log_msg = Signal(str)
    
    def __init__(self, params: Dict[str, Any], msh_file: str, case_dir: str) -> None:
        super().__init__()
        self.p = params
        self.msh_file = msh_file
        self.case_dir = case_dir
        
    def run(self) -> None:
        try:
            self.log_msg.emit("⏳ Iniciando mallado aislado...")
            json_path = "temp_params_mesh.json"
            with open(json_path, 'w') as f:
                json.dump(self.p, f)
            
            cmd = [sys.executable, "-m", "core.mesh_script", json_path, self.msh_file]
            res = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace')
            self.log_msg.emit(res.stdout)
            if res.returncode == 0:
                self.finished.emit(self.msh_file, self.msh_file.replace(".msh", ".vtk"))
            else:
                self.error.emit(res.stderr)
        except Exception as e:
            self.error.emit(str(e))


class SimWorker(QObject):
    """
    Ejecuta el solver CFD usando QProcess (event-loop based).
    No hereda QThread porque QProcess ya es asíncrono y necesita
    correr en el hilo principal del event loop de Qt.
    """
    finished = Signal(int)
    error = Signal(str)
    log_msg = Signal(str)
    force_data = Signal(str, str)
    residual_data = Signal(str, float, float)
    
    def __init__(self, solver_runner, params: Dict[str, Any], msh_file: str, parent=None) -> None:
        super().__init__(parent)
        self.p = params
        self.msh_file = msh_file
        self.process = None

    def start_sim(self):
        json_path = "temp_params_solve.json"
        with open(json_path, 'w') as f:
            json.dump(self.p, f)
            
        self.process = QProcess()
        self.process.setProcessChannelMode(QProcess.MergedChannels)
        self.process.readyReadStandardOutput.connect(self.on_output)
        self.process.finished.connect(self.on_finished)
        
        cmd = sys.executable
        args = ["-m", "core.solve_script", json_path, self.msh_file]
        self.log_msg.emit("🚀 Lanzando simulador nativo (QProcess)...")
        self.process.start(cmd, args)

    def on_output(self):
        data = self.process.readAllStandardOutput().data().decode(errors='replace')
        lines = data.splitlines()
        
        # Procesar solo las últimas líneas si hay demasiadas para evitar saturación
        if len(lines) > 50:
            lines = lines[-50:]
            
        for line in lines:
            clean = line.strip()
            if not clean:
                continue
            try:
                if clean.startswith("RESIDUAL_DATA|"):
                    p = clean.split("|")
                    if len(p) == 4: self.residual_data.emit(p[1], float(p[2]), float(p[3]))
                elif clean.startswith("FORCE_DATA|"):
                    p = clean.split("|")
                    if len(p) == 3: self.force_data.emit(p[1], p[2])
                elif clean.startswith("SIM_DONE|"):
                    pass
                else:
                    # Emitir cualquier otra cosa al log (incluyendo errores, setup, gmshToFoam, etc)
                    # Limitamos para no inundar si es iteración sin Time =
                    if "Time =" in clean or "ClockTime =" in clean or "Ejecutando" in clean or "DEBUG" in clean or clean.startswith("✅") or clean.startswith("❌") or clean.startswith("🌊") or clean.startswith("🚀") or clean.startswith("📝") or clean.startswith("🔄") or clean.startswith("⚠️") or "FOAM" in clean or "error" in clean.lower():
                        self.log_msg.emit(clean)
            except Exception:
                pass

    def on_finished(self, exit_code):
        self.finished.emit(exit_code)
        if os.path.exists("temp_params_solve.json"):
            os.remove("temp_params_solve.json")


class SweepWorker(QThread):
    """
    Ejecuta un barrido paramétrico de ángulos de ataque (polar).
    Para cada ángulo:
      1. Genera una nueva malla con el ángulo actual
      2. Configura el caso OpenFOAM
      3. Ejecuta la simulación en estado estacionario
      4. Extrae Cl y Cd del postprocessing
    
    Emite finished(aoa_list, cl_list, cd_list, cm_list) al terminar.
    """
    finished = Signal(list, list, list, list)
    error = Signal(str)
    log_msg = Signal(str)
    progress = Signal(int, int)  # (current, total)
    mesh_generated = Signal(str) # Ruta al VTK para previsualización
    
    def __init__(self, params: Dict[str, Any], case_dir: str) -> None:
        super().__init__()
        self.p = params.copy()
        self.case_dir = case_dir
        self._stop_requested = False
        
    def request_stop(self):
        """Solicitar detención segura del barrido."""
        self._stop_requested = True
        
    def run(self) -> None:
        aoa_min = self.p.get("aoa_min", -4.0)
        aoa_max = self.p.get("aoa_max", 24.0)
        aoa_step = self.p.get("aoa_step", 2.0)
        
        # Generar lista de ángulos
        angles = []
        aoa = aoa_min
        while aoa <= aoa_max + 1e-6:
            angles.append(round(aoa, 2))
            aoa += aoa_step
        
        total = len(angles)
        self.log_msg.emit(f"📊 Barrido de ángulos: {total} puntos de {aoa_min}° a {aoa_max}° (paso {aoa_step}°)")
        
        aoa_results = []
        cl_results = []
        cd_results = []
        cm_results = []
        
        naca = self.p.get("naca", "0012")
        
        for i, angle in enumerate(angles):
            if self._stop_requested:
                self.log_msg.emit("⚠️ Barrido detenido por el usuario.")
                break
                
            self.progress.emit(i + 1, total)
            self.log_msg.emit(f"━━━ [{i+1}/{total}] AoA = {angle}° ━━━")
            
            # Actualizar AoA en parámetros
            sweep_params = self.p.copy()
            sweep_params["aoa"] = angle
            # Forzar estacionario para barrido
            sweep_params["regime"] = "Estacionario (simpleFoam)"
            
            try:
                # Paso 1: Generar malla con nuevo AoA
                msh_file = f"perfil_{naca}_sweep.msh"
                self.log_msg.emit(f"  🔧 Generando malla (AoA={angle}°)...")
                
                json_path = "temp_params_sweep.json"
                with open(json_path, 'w') as f:
                    json.dump(sweep_params, f)
                
                result = subprocess.run(
                    [sys.executable, "-m", "core.mesh_script", json_path, msh_file],
                    capture_output=True, text=True, encoding='utf-8', errors='replace',
                    timeout=300
                )
                
                if result.returncode != 0:
                    self.log_msg.emit(f"  ❌ Error en malla: {result.stderr[:200]}")
                    continue
                
                # Emitir señal para actualizar la vista 3D en la interfaz
                vtk_file = msh_file.replace(".msh", ".vtk")
                if os.path.exists(vtk_file):
                    self.mesh_generated.emit(vtk_file)
                
                # Paso 2: Configurar y ejecutar simulación
                self.log_msg.emit(f"  🚀 Simulando...")
                
                result = subprocess.run(
                    [sys.executable, "-m", "core.solve_script", json_path, msh_file],
                    capture_output=True, text=True, encoding='utf-8', errors='replace',
                    timeout=1200
                )
                
                # Paso 3: Extraer Cl y Cd de la salida
                cl, cd, cm = self._extract_coefficients(result.stdout)
                
                if cl is not None and cd is not None:
                    aoa_results.append(angle)
                    cl_results.append(cl)
                    cd_results.append(cd)
                    cm_results.append(cm if cm is not None else 0.0)
                    self.log_msg.emit(f"  ✅ AoA={angle}°: Cl={cl:.4f}, Cd={cd:.4f}")
                else:
                    # Intentar extraer desde archivos de postprocessing
                    cl, cd, cm = self._extract_from_postprocessing()
                    if cl is not None:
                        aoa_results.append(angle)
                        cl_results.append(cl)
                        cd_results.append(cd)
                        cm_results.append(cm if cm is not None else 0.0)
                        self.log_msg.emit(f"  ✅ (postprocess) AoA={angle}°: Cl={cl:.4f}, Cd={cd:.4f}")
                    else:
                        self.log_msg.emit(f"  ⚠️ No se pudieron extraer coeficientes para AoA={angle}°")
                        
            except subprocess.TimeoutExpired:
                self.log_msg.emit(f"  ⏱️ Timeout en AoA={angle}°, saltando...")
                continue
            except Exception as e:
                self.log_msg.emit(f"  ❌ Error en AoA={angle}°: {e}")
                continue
        
        # Limpiar archivos temporales
        for f in ["temp_params_sweep.json", f"perfil_{naca}_sweep.msh", 
                   f"perfil_{naca}_sweep.vtk"]:
            if os.path.exists(f):
                try: os.remove(f)
                except: pass
        
        self.log_msg.emit(f"📊 Barrido completado: {len(aoa_results)}/{total} puntos exitosos")
        self.finished.emit(aoa_results, cl_results, cd_results, cm_results)
    
    def _extract_coefficients(self, output: str):
        """Extrae Cl, Cd, Cm de la salida del solver (FORCE_DATA lines)."""
        cl, cd, cm = None, None, None
        for line in output.splitlines():
            clean = line.strip()
            if clean.startswith("FORCE_DATA|"):
                parts = clean.split("|")
                if len(parts) >= 3:
                    name = parts[1].lower()
                    try:
                        val = float(parts[2])
                        if "cl" in name: cl = val
                        elif "cd" in name: cd = val
                        elif "cm" in name: cm = val
                    except ValueError:
                        pass
        return cl, cd, cm
    
    def _extract_from_postprocessing(self):
        """Extrae coeficientes del directorio de postprocessing de OpenFOAM."""
        try:
            coeff_dir = os.path.join(self.case_dir, "postProcessing", "forceCoeffs")
            if not os.path.exists(coeff_dir):
                return None, None, None
                
            # Encontrar el último directorio de tiempo
            time_dirs = sorted([d for d in os.listdir(coeff_dir) 
                              if os.path.isdir(os.path.join(coeff_dir, d))],
                             key=lambda x: float(x) if x.replace('.', '').isdigit() else 0)
            
            if not time_dirs:
                return None, None, None
                
            coeff_file = os.path.join(coeff_dir, time_dirs[-1], "coefficient.dat")
            if not os.path.exists(coeff_file):
                coeff_file = os.path.join(coeff_dir, time_dirs[-1], "forceCoeffs.dat")
            
            if not os.path.exists(coeff_file):
                return None, None, None
            
            # Leer la última línea de datos
            with open(coeff_file, 'r') as f:
                lines = [l.strip() for l in f.readlines() if l.strip() and not l.startswith('#')]
            
            if lines:
                parts = lines[-1].split()
                if len(parts) >= 8:
                    # Formato OpenFOAM v2xxx:
                    # Time  Cd  Cd(f)  Cd(r)  Cl  Cl(f)  Cl(r)  CmPitch  CmRoll  CmYaw ...
                    cd = float(parts[1])
                    cl = float(parts[4])
                    cm = float(parts[7])
                    return cl, cd, cm
                elif len(parts) >= 4:
                    # Formato antiguo (fallback): Time Cm Cd Cl
                    cm = float(parts[1])
                    cd = float(parts[2])
                    cl = float(parts[3])
                    return cl, cd, cm
                    
        except Exception as e:
            print(f"Error leyendo postprocessing: {e}")
        
        return None, None, None
