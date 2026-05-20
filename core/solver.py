import subprocess
import os
import threading
from typing import Optional, Callable

class SolverRunner:
    def __init__(self, case_dir: str = "openfoam_case", docker_image: str = "opencfd/openfoam-default", native: bool = False) -> None:
        self.case_dir = case_dir
        self.docker_image = docker_image
        self.native = native
        self.process = None
        # No ejecutar limpieza automática en hilo para evitar conflictos con el GIL al arrancar

    def is_docker_ready(self) -> bool:
        """Verifica si el daemon de Docker está respondiendo"""
        try:
            # -t 2 para que no se quede colgado si Docker está muerto
            subprocess.run(["docker", "version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True, timeout=3)
            return True
        except Exception:
            return False

    def _get_docker_exec(self) -> str:
        """Localiza el ejecutable de Docker de forma robusta."""
        import shutil
        docker = shutil.which("docker")
        if not docker:
            for p in ['/usr/local/bin/docker', '/usr/bin/docker', 
                      '/opt/homebrew/bin/docker', 
                      '/Applications/Docker.app/Contents/Resources/bin/docker']:
                if os.path.exists(p):
                    return p
        return docker or "docker"

    def _force_cleanup(self, log_callback: Optional[Callable] = None) -> None:
        """Elimina contenedores huérfanos de la imagen de OpenFOAM para liberar recursos"""
        if log_callback: log_callback("🔍 Limpiando procesos de Docker previos para evitar saturación...")
        try:
            # Buscar IDs de contenedores que usan nuestra imagen
            out = subprocess.check_output(["docker", "ps", "-q", "--filter", f"ancestor={self.docker_image}"], text=True)
            ids = out.strip().split()
            if ids:
                if log_callback: log_callback(f"🛑 Deteniendo {len(ids)} contenedores residuales...")
                subprocess.run(["docker", "kill"] + ids, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                if log_callback: log_callback("✅ Limpieza completada.")
            else:
                if log_callback: log_callback("✨ No se detectaron procesos residuales.")
        except Exception as e:
            if log_callback: log_callback(f"⚠️ Aviso: Error durante la limpieza: {e}")

    def run_gmshToFoam(self, msh_file: str, log_callback: Optional[Callable] = None) -> None:
        """Converts Gmsh mesh to OpenFOAM format using Docker or local installation"""
        # 0. Verificación de Salud
        if not self.native and not self.is_docker_ready():
            msg = "❌ ERROR: El motor de Docker no responde y el modo Nativo está deshabilitado."
            if log_callback: log_callback(msg)
            return
        
        # 0. Limpieza Preventiva
        if not self.native:
            self._force_cleanup(log_callback=log_callback)
        
        if log_callback: log_callback("Preparando conversión de malla (gmshToFoam)...")
        log_file = os.path.join(self.case_dir, "log.gmshToFoam")
        
        try:
            # 1. Copiar archivo .msh dentro de la carpeta del caso para simplificar montaje
            import shutil
            msh_basename = os.path.basename(msh_file)
            local_msh = os.path.join(self.case_dir, msh_basename)
            if os.path.abspath(msh_file) != os.path.abspath(local_msh):
                if log_callback: log_callback(f"Copiando malla {msh_basename} a la carpeta del caso...")
                shutil.copy2(msh_file, local_msh)
            
            # 2. Configurar rutas para Docker (montar SOLO la carpeta openfoam_case)
            case_abs_path = os.path.abspath(self.case_dir)
            
            if self.native:
                docker_cmd = ["gmshToFoam", local_msh, "-case", case_abs_path]
                exec_name = "NATIVO"
            else:
                docker_exec = self._get_docker_exec()
                docker_cmd = [
                    docker_exec, "run", "--rm", "-i",
                    "-v", f"{case_abs_path}:/data",
                    self.docker_image,
                    "gmshToFoam", f"/data/{msh_basename}", "-case", "/data"
                ]
                exec_name = f"Docker ({docker_exec})"
            
            if log_callback: log_callback(f"Ejecutando gmshToFoam en modo {exec_name}...")
            
            # Ejecutar con streaming de salida
            process = subprocess.Popen(
                docker_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                errors='replace'
            )

            
            with open(log_file, "w") as f:
                for line in process.stdout:
                    f.write(line)
                    # Silenciamos el log_callback aquí porque gmshToFoam escupe millones de líneas 
                    # y satura la memoria RAM del QProcess en Mac, provocando un SIGKILL
            
            process.wait()
            
            # PAUSA CRÍTICA para Mac (Permite que Docker libere los archivos)
            import time
            time.sleep(1.0)
            
            if process.returncode != 0:
                raise subprocess.CalledProcessError(process.returncode, docker_cmd)

            # Ajustar boundary file para compatibilidad OpenFOAM 2D
            # Usamos regex tolerante a variaciones de espaciado de gmshToFoam.
            boundary_file = os.path.join(self.case_dir, "constant", "polyMesh", "boundary")
            if os.path.exists(boundary_file):
                try:
                    import re
                    with open(boundary_file, 'r') as f:
                        content = f.read()

                    def _patch_type(text: str, patch_name: str, new_type: str) -> tuple:
                        # Reemplaza el campo `type ...;` dentro del bloque del patch indicado.
                        # Devuelve (texto_modificado, hubo_cambio).
                        pattern = re.compile(
                            r"(" + re.escape(patch_name) + r"\s*\{[^}]*?type\s+)\w+(\s*;)",
                            re.DOTALL,
                        )
                        new_text, n = pattern.subn(r"\g<1>" + new_type + r"\g<2>", text, count=1)
                        return new_text, n > 0

                    changes = []
                    for name, t in [("frontAndBack", "empty"), ("airfoil", "wall"), ("defaultFaces", "empty")]:
                        content, ok = _patch_type(content, name, t)
                        changes.append(f"{name}→{t}{'✅' if ok else '⚠️(no encontrado)'}")

                    with open(boundary_file, 'w') as f:
                        f.write(content)

                    if log_callback:
                        log_callback("🔧 Parches de frontera: " + ", ".join(changes))
                except Exception as e:
                    if log_callback: log_callback(f"⚠️ Aviso: No se pudo actualizar el archivo boundary: {e}")
            
            if log_callback:
                log_callback("✅ gmshToFoam finalizó correctamente.")
                
        except FileNotFoundError as e:
            if "docker" in str(e).lower():
                msg = "❌ ERROR: Comando 'docker' no encontrado en el sistema."
            else:
                msg = f"❌ ERROR: Archivo no encontrado: {str(e)}"
            if log_callback: log_callback(msg)
        except subprocess.CalledProcessError as e:
            msg = f"❌ ERROR: gmshToFoam falló (Código {e.returncode}). Revisa el log detallado."
            if log_callback: log_callback(msg)
        except Exception as e:
            msg = f"❌ Error inesperado: {str(e)}"
            if log_callback: log_callback(msg)

    def run_potentialFoam(self, log_callback: Optional[Callable] = None, done_callback: Optional[Callable] = None) -> None:
        """Ejecuta potentialFoam para inicializar el campo de flujo potencial"""
        # Verificación
        if not self.native and not self.is_docker_ready():
            msg = "❌ ERROR: El motor de Docker no responde. Activa el modo Nativo."
            if log_callback: log_callback(msg)
            if done_callback: done_callback(1)
            return
        
        if log_callback: log_callback("🌊 Inicializando flujo potencial (potentialFoam)...")
        
        def run():
            try:
                root_dir = os.path.abspath(os.path.join(self.case_dir, ".."))
                case_name = os.path.basename(os.path.normpath(self.case_dir))
                case_abs_path = os.path.abspath(self.case_dir)
                
                if self.native:
                    cmd = ["potentialFoam", "-case", case_abs_path, "-writep"]
                else:
                    docker_exec = self._get_docker_exec()
                    cmd = [
                        docker_exec, "run", "--rm",
                        "-v", f"{root_dir}:/data",
                        "opencfd/openfoam-default",
                        "potentialFoam", "-case", f"/data/{case_name}", "-writep"
                    ]
                
                process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1
                )
                
                for line in process.stdout:
                    clean = line.strip()
                    if log_callback and clean:
                        log_callback(clean)
                
                process.wait()
                
                # PAUSA CRÍTICA para Mac
                import time
                time.sleep(1.0)
                
                if process.returncode == 0:
                    if log_callback: log_callback("✅ Flujo potencial inicializado correctamente. Los campos U y p ahora tienen una distribución suave.")
                else:
                    if log_callback: log_callback(f"⚠️ potentialFoam terminó con código {process.returncode}. La simulación aún puede continuar.")
                
                if done_callback:
                    done_callback(process.returncode)
                    
            except Exception as e:
                if log_callback: log_callback(f"❌ Error en potentialFoam: {str(e)}")
                if done_callback: done_callback(1)
        
        thread = threading.Thread(target=run, daemon=True)
        thread.start()


    def run_solver(self, algo_name: str = "simpleFoam", log_callback: Optional[Callable] = None, force_callback: Optional[Callable] = None, residual_callback: Optional[Callable] = None, done_callback: Optional[Callable] = None) -> None:
        """Runs the CFD solver asynchronously via Docker or Native"""
        # 0. Verificación
        if not self.native and not self.is_docker_ready():
            msg = "❌ ERROR: El motor de Docker no responde. Activa modo Nativo."
            if log_callback: log_callback(msg)
            return
            
        # 0. Limpieza Preventiva
        if not self.native:
            self._force_cleanup(log_callback=log_callback)
        
        print(f"Ejecutando {algo_name} en modo {'Nativo' if self.native else 'Docker'}...")
        
        def run():
            import re
            import time
            try:
                case_abs_path = os.path.abspath(self.case_dir)
                root_dir = os.path.abspath(os.path.join(self.case_dir, ".."))
                case_name = os.path.basename(os.path.normpath(self.case_dir))
                
                if self.native:
                    cmd = [algo_name, "-case", case_abs_path]
                else:
                    docker_exec = self._get_docker_exec()
                    cmd = [
                        docker_exec, "run", "--rm", "-i", "--init",
                        "-v", f"{root_dir}:/data",
                        self.docker_image,
                        algo_name, "-case", f"/data/{case_name}"
                    ]
                
                self.process = subprocess.Popen(
                    cmd, 
                    stdout=subprocess.PIPE, 
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    errors='replace'
                )
                self.process_started = True


                
                # Read line by line to send to UI
                current_time = 0
                last_flush_time = time.time()
                log_buffer = []
                
                def flush_logs():
                    if log_buffer and log_callback:
                        log_callback("\n".join(log_buffer))
                        log_buffer.clear()

                for line in self.process.stdout:
                    clean_line = line.strip()
                    if log_callback:
                        log_buffer.append(clean_line)
                    
                    time_match = re.search(r"^Time = ([0-9\.]+)", clean_line)
                    if time_match:
                        current_time = float(time_match.group(1))
                        
                    if residual_callback and current_time > 0:
                        res_match = re.search(r"Solving for (\w+), Initial residual = ([0-9eE\.\+\-]+)", clean_line)
                        if res_match:
                            field_name = res_match.group(1)
                            val = float(res_match.group(2))
                            residual_callback(field_name, val, current_time)
                    
                    if force_callback:
                        cd_match = re.search(r"^\s*Cd\s*[:=]\s*([0-9eE\.\+\-]+)", clean_line)
                        if cd_match:
                            force_callback("Cd", cd_match.group(1))
                        
                        cl_match = re.search(r"^\s*Cl\s*[:=]\s*([0-9eE\.\+\-]+)", clean_line)
                        if cl_match:
                            force_callback("Cl", cl_match.group(1))
                            
                        cm_match = re.search(r"^\s*CmPitch\s*[:=]\s*([0-9eE\.\+\-]+)", clean_line)
                        if cm_match:
                            force_callback("Cm", cm_match.group(1))
                            
                    # Flush logs periodically
                    if time.time() - last_flush_time > 0.1 or len(log_buffer) > 100:
                        try:
                            flush_logs()
                        except Exception:
                            pass
                        last_flush_time = time.time()
                
                flush_logs()
                self.process.wait()
                
                # PAUSA CRÍTICA para Mac
                time.sleep(1.0)
                
                if done_callback:
                    done_callback(self.process.returncode)
            except Exception as e:
                msg = f"ERROR CRÍTICO: No se pudo iniciar el proceso: {str(e)}"
                print(msg)
                if log_callback: log_callback(msg)
                if done_callback: done_callback(1)

        thread = threading.Thread(target=run, daemon=True)
        thread.start()

    def stop(self) -> None:
        if self.process and self.process.poll() is None:
            self.process.terminate()
