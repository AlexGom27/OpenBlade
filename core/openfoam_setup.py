import math
import os
import shutil

class OpenFoamSetup:
    def __init__(self, case_dir: str = "openfoam_case") -> None:
        self.case_dir = case_dir
        
    def create_case(self, u_inlet: float = 15.0, p_outlet: float = 0.0, chord: float = 1.0, transient: bool = False, tolerance: str = "1e-4", turbulence: str = "k-Omega SST (RAS)", reynolds: float = 1000000.0, delta_t: str = "1e-3", end_time: str = "0.5", write_interval: str = "0.01", max_co: float = 2.0, max_iters: int = 500, momentum_scheme: str = "limitedLinearV", depth: float = 0.1, bl_dist_min: float = 1e-4, turb_intensity: float = 0.00052, viscosity_ratio: float = 0.009, aoa_flow: float = 0.0, bc_type: str = "entrada_salida", turb_scheme: str = "upwind", grad_scheme: str = "cellMDLimited Gauss linear 1", lap_correction: str = "limited corrected 0.5", relax_p: float = 0.2, relax_eq: float = 0.5, consistent: bool = False, ddt_scheme: str = "backward") -> None:
        # Create directories
        for d in ["0", "constant", "system"]:
            os.makedirs(os.path.join(self.case_dir, d), exist_ok=True)
            
        # Limpieza PROFUNDA para evitar que resultados viejos contaminen el barrido
        if os.path.exists(self.case_dir):
            try:
                # 1. Eliminar postProcessing (Evita leer Cl/Cd viejos)
                pp_path = os.path.join(self.case_dir, "postProcessing")
                if os.path.exists(pp_path):
                    shutil.rmtree(pp_path, ignore_errors=True)
                
                # 2. Eliminar polyMesh (Fuerza a gmshToFoam a crear una malla limpia)
                pm_path = os.path.join(self.case_dir, "constant", "polyMesh")
                if os.path.exists(pm_path):
                    shutil.rmtree(pm_path, ignore_errors=True)

                # 3. Eliminar carpetas numéricas (pasos de tiempo viejos)
                for item in os.listdir(self.case_dir):
                    if item != "0":
                        try:
                            float(item)
                            item_path = os.path.join(self.case_dir, item)
                            if os.path.isdir(item_path):
                                shutil.rmtree(item_path, ignore_errors=True)
                        except Exception:
                            pass

                # 4. Campos y salidas de la corrida anterior: un 0/phi o un run.log
                # viejos viajarian con el paquete y se confundirian con los nuevos.
                cero = os.path.join(self.case_dir, "0")
                for item in os.listdir(cero):
                    os.remove(os.path.join(cero, item))
                for item in os.listdir(self.case_dir):
                    ruta = os.path.join(self.case_dir, item)
                    if item.startswith(("log.", "processor")) or item in (
                            "run.log", "resultado.json", "ficha.json", "status.json", "job.log"):
                        if os.path.isdir(ruta):
                            shutil.rmtree(ruta, ignore_errors=True)
                        else:
                            os.remove(ruta)
            except Exception as e_clean:
                print(f"Aviso: No se pudo limpiar completamente la carpeta del caso: {e_clean}")

        
        # Calcular viscosidad cinemática a partir de Reynolds: nu = U * L / Re
        nu = (float(u_inlet) * float(chord)) / float(reynolds)

        # Angulo por el flujo: la malla no cambia y la entrada y las direcciones de
        # sustentacion y arrastre giran. Con 0 el angulo ya esta en la malla.
        alfa = math.radians(float(aoa_flow))
        self.dir_drag = (math.cos(alfa), math.sin(alfa))
        self.dir_lift = (-math.sin(alfa), math.cos(alfa))
        self.turb_scheme = turb_scheme
        self.grad_scheme = grad_scheme
        self.lap_correction = lap_correction
        self.relax_p = relax_p
        self.relax_eq = relax_eq
        self.consistent = consistent
        self.ddt_scheme = ddt_scheme
            
        self._write_system(u_inlet, chord, transient, tolerance, turbulence, delta_t, end_time, write_interval, max_co, max_iters, momentum_scheme, depth)
        # Se guarda la primera celda: _write_0 la usa para elegir el modelo de
        # pared (LowRe con y+~1, nutk con y+ alto).
        self.bl_dist_min = bl_dist_min
        self.bc_type = bc_type
        self.reynolds = float(reynolds)
        self.turb_intensity = float(turb_intensity)
        self.viscosity_ratio = float(viscosity_ratio)

        self._write_constant(turbulence, nu)
        self._write_0(u_inlet, p_outlet, chord, turbulence, nu)
        
    def _write_system(self, u_inlet: float, chord: float, transient: bool, tolerance: str, turbulence_ui: str, delta_t: str = "1e-3", end_time: str = "0.5", write_interval: str = "0.01", max_co: float = 2.0, max_iters: int = 500, momentum_scheme: str = "limitedLinearV", depth: float = 0.1) -> None:
        app_name = "pimpleFoam" if transient else "simpleFoam"
        initial_dt = delta_t if transient else "1"
        endTime  = end_time if transient else str(max_iters)
        writeControl = "adjustableRunTime" if transient else "timeStep"
        # El ultimo tiempo debe caer en una escritura: sus campos son el resultado.
        writeInterval = write_interval if transient else str(math.gcd(50, int(max_iters)))
        purgeWrite = "0" if transient else "2"
        maxCoStr = f"adjustTimeStep  yes;\nmaxCo           {max_co};\nmaxDeltaT       0.05;" if transient else ""
        
        controlDict = f"""/*--------------------------------*- C++ -*----------------------------------*\\
| =========                 |                                                 |
| \\      /  F ield         | OpenFOAM: The Open Source CFD Toolbox           |
|  \\    /   O peration     | Version:  v2206                                 |
|   \\  /    A nd           | Website:  www.openfoam.com                      |
|    \\/     M anipulation  |                                                 |
\\*---------------------------------------------------------------------------*/
FoamFile
{{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      controlDict;
}}
// * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * //

application     {app_name};
startFrom       startTime;
startTime       0;
stopAt          endTime;
endTime         {endTime};
deltaT          {initial_dt};
writeControl    {writeControl};
writeInterval   {writeInterval};
purgeWrite      {purgeWrite};
{maxCoStr}
writeFormat     ascii;
// gmshToFoam escribe los puntos de la malla con esta precision. Con 6 cifras, un
// punto en x=0.42 se redondea a 1e-6, comparable a una primera celda de 4e-6: las
// celdas de pared quedan deformadas (no ortogonalidad de 85 grados en una malla de
// 39) y una malla con y+ < 1 revienta en pocas iteraciones.
writePrecision  15;
writeCompression off;
timeFormat      general;
timePrecision   6;
runTimeModifiable true;

functions
{{
    // Solo en los tiempos que se guardan: con otro intervalo se crea un
    // directorio por escritura y la E/S domina el coste del solver.
    yPlus
    {{
        type            yPlus;
        libs            ("libfieldFunctionObjects.so");
        executeControl  writeTime;
        writeControl    writeTime;
        patches         (airfoil);
    }}

    // Friccion real en la pared: de aqui sale el y+ del programa (core/yplus.py).
    wallShearStress
    {{
        type            wallShearStress;
        libs            ("libfieldFunctionObjects.so");
        executeControl  writeTime;
        writeControl    writeTime;
        patches         (airfoil);
    }}

    forceCoeffs
    {{
        type            forceCoeffs;
        libs            ("libforces.so");
        writeControl    timeStep;
        writeInterval   1;

        patches         (airfoil);
        rho             rhoInf;
        log             true;
        rhoInf          1.225;
        liftDir         ({self.dir_lift[0]:.12g} {self.dir_lift[1]:.12g} 0);
        dragDir         ({self.dir_drag[0]:.12g} {self.dir_drag[1]:.12g} 0);
        CofR            ({0.25 * chord} 0 0);
        // Hacia -z: Cm positivo es morro arriba, la convencion de los datos de referencia.
        pitchAxis       (0 0 -1);
        magUInf         {float(u_inlet)};
        lRef            {chord};
        // Aref = cuerda x unidad de envergadura.
        // 
        // Estaba como chord * 0.1*chord (el espesor de extrusion), lo que
        // hacia que Cl y Cd salieran 10 veces mayores que los de la
        // literatura. Ladson y el resto de referencias dan coeficientes por
        // unidad de envergadura en 2D.
        // Aref = cuerda x profundidad de extrusion.
        //
        // La malla se extrude depth metros en z. Con Aref = chord
        // se normaliza por un area 1/depth veces mayor que la real y
        // los coeficientes salen depth veces menores (10x con depth=0.1).
        Aref            {chord * depth};
    }}
}}"""
        with open(os.path.join(self.case_dir, "system", "controlDict"), "w") as f:
            f.write(controlDict)

        # "bounded" es para estacionario: quita div(phi)*U, que en transitorio no es un
        # residuo de la convergencia sino parte del paso de tiempo.
        conv = "Gauss" if transient else "bounded Gauss"
        is_laminar = "Laminar" in turbulence_ui
        is_transition = "SST-LM" in turbulence_ui or "gamma-ReTheta" in turbulence_ui
        
        div_turb = ""
        if not is_laminar:
            if is_transition:
                # Modelos de transición necesitan esquemas para gamma y ReThetat
                div_turb = f"""\n    div(phi,k)      {conv} {self.turb_scheme};
    div(phi,omega)  {conv} {self.turb_scheme};
    div(phi,gammaInt) {conv} {self.turb_scheme};
    div(phi,ReThetat) {conv} {self.turb_scheme};"""
            elif "Epsilon" in turbulence_ui:
                div_turb = f"""\n    div(phi,k)      {conv} {self.turb_scheme};
    div(phi,epsilon) {conv} {self.turb_scheme};"""
            elif "Omega" in turbulence_ui:
                div_turb = f"""\n    div(phi,k)      {conv} {self.turb_scheme};
    div(phi,omega)  {conv} {self.turb_scheme};"""
            elif "Spalart" in turbulence_ui:
                div_turb = f"""\n    div(phi,nuTilda) {conv} {self.turb_scheme};"""

        # linearUpwind necesita el esquema de gradiente como argumento;
        # con upwind (1er orden) no aplica.
        # Esquema por defecto: limitedLinearV 1.
        #
        # Medido en el NACA 0012 a Re=6e6, alpha=0, malla no estructurada
        # (117 854 celdas, 434 caras con no-ortogonalidad > 70 grados):
        #
        #   upwind          -> Cd = 0.01758  (+118%)  converge
        #   linearUpwind    -> inestable en esa malla (Cl de -0.01 a -61950)
        #   limitedLinearV  -> Cd = 0.00797  (-1.2%)  converge
        #
        # El limitador de van Leer tolera mallas irregulares donde el
        # segundo orden sin limitar explota, sin perder precision.
        #
        # Cada esquema de convección tiene su sintaxis:
        #   upwind                          -> sin argumentos
        #   linearUpwind                    -> requiere el gradiente: grad(U)
        #   limitedLinearV                  -> requiere un coeficiente 0..1
        # Escribir "limitedLinearV" a secas hace que OpenFOAM aborte al leer
        # fvSchemes. Se normaliza aquí.
        if momentum_scheme == "linearUpwind":
            momentum_grad = " grad(U)"
        elif momentum_scheme.startswith("limitedLinear"):
            momentum_grad = "" if momentum_scheme.split()[-1].replace(".", "").isdigit() \
                else " 1"
        else:
            momentum_grad = ""

        # Euler es de primer orden: con dt ~ 1e-5 su difusion numerica
        # domina el Cd. backward es de segundo orden e implicito, estable.
        ddt = self.ddt_scheme if transient else "steadyState"
        fvSchemes = f"""FoamFile {{ version 2.0; format ascii; class dictionary; object fvSchemes; }}
ddtSchemes {{ default {ddt}; }}
gradSchemes {{ default {self.grad_scheme}; }}
divSchemes {{
    default         none;
    div(phi,U)      {conv} {momentum_scheme}{momentum_grad};{div_turb}
    div((nuEff*dev2(T(grad(U))))) Gauss linear;
    div(div(phi,U)) Gauss linear;
}}
laplacianSchemes {{
    default Gauss linear {self.lap_correction};
    laplacian(1,Phi) Gauss linear corrected;
}}
interpolationSchemes {{ default linear; }}
snGradSchemes {{ default {self.lap_correction}; }}
wallDist {{ method meshWave; }}
"""
        with open(os.path.join(self.case_dir, "system", "fvSchemes"), "w") as f:
            f.write(fvSchemes)

        alg = "PIMPLE" if transient else "SIMPLE"
        p_solver = "GAMG"
        
        # Dinamic fields for solvers
        field_names = "U"
        if not is_laminar:
            if is_transition:
                field_names = "(U|k|omega|gammaInt|ReThetat)"
            elif "Epsilon" in turbulence_ui: field_names = "(U|k|epsilon)"
            elif "Omega" in turbulence_ui: field_names = "(U|k|omega)"
            elif "Spalart" in turbulence_ui: field_names = "(U|nuTilda)"

        fv_solve_algo = f"""
{alg} {{
    nNonOrthogonalCorrectors 3;
    pRefCell 0;
    pRefValue 0;
    consistent {"yes" if self.consistent else "no"};
    residualControl {{
        p               {tolerance};
        U               {tolerance};
        "(k|omega|epsilon|nuTilda|gammaInt|ReThetat)" {tolerance};
    }}
}}
relaxationFactors {{
    fields {{ p {self.relax_p}; }}
    equations {{ "(U|k|omega|epsilon|nuTilda|gammaInt|ReThetat)" {self.relax_eq}; }}
}}
""" if not transient else f"""
{alg} {{
    nNonOrthogonalCorrectors 3;
    nCorrectors     2;
    // 2 basta: en transitorio el avance lo marca dt, no la convergencia
    // del paso. Antes eran 12.
    nOuterCorrectors 2;
    pRefCell        0;
    pRefValue       0;
    // PIMPLE necesita diccionarios, no valores simples: con
    // "p {tolerance};" OF-12 avisa "No corrector convergence criteria found"
    // y agota nOuterCorrectors en todos los pasos, segun lo que midio
    // OpenClaw en otra sesion; aqui no se ha comprobado. En SIMPLE si vale
    // el valor simple, por eso el estacionario no lo necesita.
    outerCorrectorResidualControl
    {{
        "(U|k|omega|epsilon|nuTilda|gammaInt|ReThetat)"
        {{
            tolerance       {tolerance};
            relTol          0;
        }}
        p
        {{
            tolerance       {tolerance};
            relTol          0;
        }}
    }}
}}
relaxationFactors {{
    // Transitorio: sin relajacion. Los factores del estacionario (p 0.2,
    // U/k/omega 0.5) frenan la respuesta temporal y no tienen sentido en
    // PIMPLE, donde el avance lo marca dt, no las iteraciones.
    fields {{ p 1; }}
    equations {{ U 1; k 1; omega 1; epsilon 1; nuTilda 1; gammaInt 1; ReThetat 1; }}
}}
"""

        fvSolution = f"""FoamFile {{ version 2.0; format ascii; class dictionary; object fvSolution; }}
// potentialFoam busca este subdict en el NIVEL SUPERIOR de fvSolution
// (mesh.solution().dict().subDict("potentialFlow")), no dentro de solvers.
// Sin el, potentialFoam aborta con "keyword potentialFlow is undefined"
// y el caso transitorio arranca de un campo uniforme: Cl se dispara a
// valores imposibles (2.7 a alpha=8) y nunca converge.
potentialFlow
{{
    solver          GAMG;
    tolerance       1e-6;
    relTol          0;
    smoother        GaussSeidel;
    nNonOrthogonalCorrectors 2;
}}

solvers {{
    p {{
        solver          {p_solver};
        tolerance       1e-9;
        relTol          0.05;
        smoother        GaussSeidel;
    }}
    pFinal {{
        $p;
        relTol 0;
    }}
    // La tolerancia absoluta debe quedar muy por debajo de relTol. El residuo se
    // normaliza con el campo, y omega en la pared vale del orden de 1e9: con 1e-6 el
    // residuo de k y omega ya cumplia antes de empezar ("No Iterations 0"), los campos
    // quedaban congelados y las fuerzas parecian convergidas. Medido a alfa=10 en
    // 897x257: Cd = 0.0213 con Cf doble del real, y veredicto CONVERGIDO.
    "{field_names}" {{
        solver          PBiCGStab;
        preconditioner  DILU;
        tolerance       1e-14;
        relTol          0.1;
    }}
    "{field_names}Final" {{
        solver          PBiCGStab;
        preconditioner  DILU;
        tolerance       1e-14;
        relTol          0;
    }}
    Phi {{
        solver          GAMG;
        smoother        DIC;
        tolerance       1e-6;
        relTol          0.01;
    }}
}}
{fv_solve_algo}
"""
        with open(os.path.join(self.case_dir, "system", "fvSolution"), "w") as f:
            f.write(fvSolution)

    def _write_constant(self, turbulence_ui: str, nu: float = 1.5e-5) -> None:
        transport = f"""FoamFile {{ version 2.0; format ascii; class dictionary; object transportProperties; }}
transportModel  Newtonian;
nu              [0 2 -1 0 0 0 0] {nu:.6e};
"""
        with open(os.path.join(self.case_dir, "constant", "transportProperties"), "w") as f:
            f.write(transport)

        sim_type = "laminar" if "Laminar" in turbulence_ui else "RAS"
        # kOmegaSSTDES es un modelo LES (híbrido RANS-LES). Es lo que hace
        # falta a angulo alto, donde el flujo separa y el RANS puro falla.
        if "DES" in turbulence_ui:
            sim_type = "LES"
        model = "kOmegaSST"
        if "SST-LM" in turbulence_ui:
            model = "kOmegaSSTLM"
        elif "gamma-ReTheta" in turbulence_ui:
            model = "gammaReThetatSST"  
        elif "Epsilon" in turbulence_ui: model = "kEpsilon"
        elif "Omega" in turbulence_ui and "SST" not in turbulence_ui: model = "kOmega"
        elif "Spalart" in turbulence_ui: model = "SpalartAllmaras"
        elif "DES" in turbulence_ui: model = "kOmegaSSTDES"

        turbulence = f"""FoamFile {{ version 2.0; format ascii; class dictionary; object turbulenceProperties; }}
simulationType  {sim_type};
RAS {{
    RASModel        {model};
    turbulence      on;
    printCoeffs     on;
}}
"""
        with open(os.path.join(self.case_dir, "constant", "turbulenceProperties"), "w") as f:
            f.write(turbulence)

    def _write_0(self, u_inlet: float, p_outlet: float, chord: float, turbulence_ui: str, nu: float = 1.5e-5) -> None:
        is_laminar = "Laminar" in turbulence_ui
        u_vec = f"({float(u_inlet) * self.dir_drag[0]:.12g} {float(u_inlet) * self.dir_drag[1]:.12g} 0)"
        # Contorno exterior: entrada y salida fijas, o libre en todo el contorno, que
        # deja entrar y salir el flujo por donde corresponda segun el angulo.
        libre = getattr(self, "bc_type", "entrada_salida") == "libre"
        if libre:
            u_ent = f"type freestreamVelocity; freestreamValue uniform {u_vec}; value uniform {u_vec};"
            u_sal = u_ent
            p_ent = f"type freestreamPressure; freestreamValue uniform {p_outlet}; value uniform {p_outlet};"
            p_sal = p_ent
        else:
            u_ent = f"type fixedValue; value uniform {u_vec};"
            # La esquina de la salida puede tener reflujo: sin frenarlo crece solo. Medido a 30
            # grados y Re = 1000: Ux = -23 en t = 0.8 s, -309 en t = 2.2 s y Cl = -23 despues.
            # Donde el flujo sale es lo mismo que zeroGradient.
            u_sal = f"type inletOutlet; inletValue uniform (0 0 0); value uniform {u_vec};"
            p_ent = "type zeroGradient;"
            p_sal = f"type fixedValue; value uniform {p_outlet};"

        def exterior(valor: float):
            """Entrada y salida de una variable de turbulencia."""
            if libre:
                c = f"type inletOutlet; inletValue uniform {valor:.6e}; value uniform {valor:.6e};"
                return c, c
            return (f"type fixedValue; value uniform {valor:.6e};",
                    f"type inletOutlet; inletValue uniform {valor:.6e}; value uniform {valor:.6e};")
        
        # Boundary/Initial Conditions for U and p (common)
        U_content = f"""FoamFile {{ version 2.0; format ascii; class volVectorField; object U; }}
dimensions      [0 1 -1 0 0 0 0];
internalField   uniform {u_vec};
boundaryField {{
    inlet {{ {u_ent} }}
    outlet {{ {u_sal} }}
    farfield {{ type slip; }}
    airfoil {{ type noSlip; }}
    frontAndBack {{ type empty; }}
    defaultFaces {{ type empty; }}
}}
"""
        with open(os.path.join(self.case_dir, "0", "U"), "w") as f: f.write(U_content)

        P_content = f"""FoamFile {{ version 2.0; format ascii; class volScalarField; object p; }}
dimensions      [0 2 -2 0 0 0 0];
internalField   uniform 0;
boundaryField {{
    inlet {{ {p_ent} }}
    outlet {{ {p_sal} }}
    farfield {{ type zeroGradient; }}
    airfoil {{ type zeroGradient; }}
    frontAndBack {{ type empty; }}
    defaultFaces {{ type empty; }}
}}
"""
        with open(os.path.join(self.case_dir, "0", "p"), "w") as f: f.write(P_content)

        if is_laminar: return

        # --- Condiciones de turbulencia en la entrada ---------------------
        #
        # NASA TMR da la entrada del SST como Tu y razon de viscosidades:
        #     k     = 1.5 * (U * Tu)^2
        #     omega = k / (nut/nu * nu)
        # con Tu = 0.052 % y nut/nu = 0.009 por defecto. La formula vale para
        # cualquier velocidad y Reynolds.
        #
        # Antes estaban fijos I = 5 % y l = 0.07c, que daban nut/nu = 14 000 a
        # Re = 6e6. Medido con la malla por defecto, 6000 iteraciones:
        #   alpha=0: Cd = 0.01204 (+49 % frente a Ladson); con TMR 0.00776 (-3.7 %)
        #   alpha=8: diverge (Cl de -897 a +728); con TMR Cl = 0.9345, Cd = 0.01061
        u_flt = float(u_inlet)
        Tu = float(getattr(self, "turb_intensity", 0.00052))
        k_val = 1.5 * (u_flt * Tu) ** 2
        omega_val = k_val / (float(getattr(self, "viscosity_ratio", 0.009)) * nu)
        epsilon_val = 0.09 * k_val * omega_val
        # Spalart-Allmaras tiene su propio estado libre: nuTilda = 3 nu (TMR).
        nuTilda_val = 3.0 * nu
        is_transition = "SST-LM" in turbulence_ui or "gamma-ReTheta" in turbulence_ui

        # Write fields based on model
        if "Epsilon" in turbulence_ui or "Omega" in turbulence_ui or is_transition:
            # k is used in k-epsilon, k-omega, and transition models
            k_content = f"""FoamFile {{ version 2.0; format ascii; class volScalarField; object k; }}
dimensions      [0 2 -2 0 0 0 0];
internalField   uniform {k_val:.6e};
boundaryField {{
    inlet {{ {exterior(k_val)[0]} }}
    outlet {{ {exterior(k_val)[1]} }}
    farfield {{ type zeroGradient; }}
    airfoil {{ type kqRWallFunction; value uniform {k_val:.6e}; }}
    frontAndBack {{ type empty; }}
    defaultFaces {{ type empty; }}
}}
"""
            with open(os.path.join(self.case_dir, "0", "k"), "w") as f: f.write(k_content)

        if "Epsilon" in turbulence_ui:
            eps_content = f"""FoamFile {{ version 2.0; format ascii; class volScalarField; object epsilon; }}
dimensions      [0 2 -3 0 0 0 0];
internalField   uniform {epsilon_val:.6e};
boundaryField {{
    inlet {{ {exterior(epsilon_val)[0]} }}
    outlet {{ {exterior(epsilon_val)[1]} }}
    farfield {{ type zeroGradient; }}
    airfoil {{ type epsilonWallFunction; value uniform {epsilon_val:.6e}; }}
    frontAndBack {{ type empty; }}
    defaultFaces {{ type empty; }}
}}
"""
            with open(os.path.join(self.case_dir, "0", "epsilon"), "w") as f: f.write(eps_content)

        if "Omega" in turbulence_ui or is_transition:
            om_content = f"""FoamFile {{ version 2.0; format ascii; class volScalarField; object omega; }}
dimensions      [0 0 -1 0 0 0 0];
internalField   uniform {omega_val:.6e};
boundaryField {{
    inlet {{ {exterior(omega_val)[0]} }}
    outlet {{ {exterior(omega_val)[1]} }}
    farfield {{ type zeroGradient; }}
    airfoil {{ type omegaWallFunction; value uniform {omega_val:.6e}; }}
    frontAndBack {{ type empty; }}
    defaultFaces {{ type empty; }}
}}
"""
            with open(os.path.join(self.case_dir, "0", "omega"), "w") as f: f.write(om_content)

        if "Spalart" in turbulence_ui:
            nt_content = f"""FoamFile {{ version 2.0; format ascii; class volScalarField; object nuTilda; }}
dimensions      [0 2 -1 0 0 0 0];
internalField   uniform {nuTilda_val:.6e};
boundaryField {{
    inlet {{ {exterior(nuTilda_val)[0]} }}
    outlet {{ {exterior(nuTilda_val)[1]} }}
    farfield {{ type zeroGradient; }}
    airfoil {{ type fixedValue; value uniform 0; }} 
    frontAndBack {{ type empty; }}
    defaultFaces {{ type empty; }}
}}
"""
            with open(os.path.join(self.case_dir, "0", "nuTilda"), "w") as f: f.write(nt_content)

        # Campos de transición (gammaInt y ReThetat)
        if is_transition:
            gamma_content = f"""FoamFile {{ version 2.0; format ascii; class volScalarField; object gammaInt; }}
dimensions      [0 0 0 0 0 0 0];
internalField   uniform 1;
boundaryField {{
    inlet {{ type fixedValue; value uniform 1; }}
    outlet {{ type zeroGradient; }}
    farfield {{ type zeroGradient; }}
    airfoil {{ type zeroGradient; }}
    frontAndBack {{ type empty; }}
    defaultFaces {{ type empty; }}
}}
"""
            with open(os.path.join(self.case_dir, "0", "gammaInt"), "w") as f: f.write(gamma_content)

            # ReThetat: correlación de Langtry y Menter, con Tu en porcentaje.
            tu_pct = max(100.0 * Tu, 0.027)
            if tu_pct <= 1.3:
                Re_theta = 1173.51 - 589.428 * tu_pct + 0.2196 / tu_pct ** 2
            else:
                Re_theta = 331.5 * (tu_pct - 0.5658) ** -0.671
            re_theta_content = f"""FoamFile {{ version 2.0; format ascii; class volScalarField; object ReThetat; }}
dimensions      [0 0 0 0 0 0 0];
internalField   uniform {Re_theta:.1f};
boundaryField {{
    inlet {{ type fixedValue; value uniform {Re_theta:.1f}; }}
    outlet {{ type zeroGradient; }}
    farfield {{ type zeroGradient; }}
    airfoil {{ type zeroGradient; }}
    frontAndBack {{ type empty; }}
    defaultFaces {{ type empty; }}
}}
"""
            with open(os.path.join(self.case_dir, "0", "ReThetat"), "w") as f: f.write(re_theta_content)

        # nut is always needed for RAS.
        #
        # La condicion de pared se elige segun el y+ que produce la malla, que
        # depende de la primera celda (bl_dist_min). Medido en el NACA 0012 a
        # Re = 6e6:
        #
        #   bl_dist_min = 2.5e-4  ->  y+ medio 11.9, max 57.8   (buffer)
        #   bl_dist_min = 2e-5    ->  y+ ~ 1                    (subcapa resuelta)
        #
        # Modelos y donde valen:
        #   nutLowReWallFunction      y+ ~ 1   resuelve la subcapa
        #   nutkWallFunction          y+ > 30  ley logaritmica pura
        #   nutUSpaldingWallFunction  continuo, pero NO converge en buffer
        #
        # Medido con y+ ~ 12 (buffer):
        #   nutkWallFunction  -> converge, pero Cl(r) = 50% de la sustentacion
        #                        (normal ~10%) y Cd +310% respecto a Ladson
        #   nutUSpalding      -> no converge: Cl cae de 15.8 a 2.17 en 800 iter
        #
        # Se elige con el y+ que da la primera celda a este Reynolds: con y+ < 5
        # (subcapa) va LowRe, el unico que resuelve donde se genera el cortante.
        from core.yplus import YP_VISCOSA, estimate_yplus
        y_mas = estimate_yplus(float(getattr(self, "bl_dist_min", 1e-4)),
                               float(getattr(self, "reynolds", 1e6)))
        if "Spalart" in turbulence_ui or y_mas < YP_VISCOSA:
            nut_wall = "nutLowReWallFunction"
        else:
            nut_wall = "nutkWallFunction"

        nut_content = f"""FoamFile {{ version 2.0; format ascii; class volScalarField; object nut; }}
dimensions      [0 2 -1 0 0 0 0];
internalField   uniform 0;
boundaryField {{
    inlet {{ type calculated; value uniform 0; }}
    outlet {{ type calculated; value uniform 0; }}
    farfield {{ type calculated; value uniform 0; }}
    airfoil {{ type {nut_wall}; value uniform 0; }}
    frontAndBack {{ type empty; }}
    defaultFaces {{ type empty; }}
}}
"""
        with open(os.path.join(self.case_dir, "0", "nut"), "w") as f: f.write(nut_content)
