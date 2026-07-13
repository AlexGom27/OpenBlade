import os
import shutil

class OpenFoamSetup:
    def __init__(self, case_dir: str = "openfoam_case") -> None:
        self.case_dir = case_dir
        
    def create_case(self, u_inlet: float = 15.0, p_outlet: float = 0.0, chord: float = 1.0, transient: bool = False, tolerance: str = "1e-4", turbulence: str = "k-Omega SST (RAS)", reynolds: float = 1000000.0, delta_t: str = "1e-3", end_time: str = "0.5", write_interval: str = "0.01", max_co: float = 2.0, max_iters: int = 500) -> None:
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
            except Exception as e_clean:
                print(f"Aviso: No se pudo limpiar completamente la carpeta del caso: {e_clean}")

        
        # Calcular viscosidad cinemática a partir de Reynolds: nu = U * L / Re
        nu = (float(u_inlet) * float(chord)) / float(reynolds)
            
        self._write_system(u_inlet, chord, transient, tolerance, turbulence, delta_t, end_time, write_interval, max_co, max_iters)
        self._write_constant(turbulence, nu)
        self._write_0(u_inlet, p_outlet, chord, turbulence, nu)
        
    def _write_system(self, u_inlet: float, chord: float, transient: bool, tolerance: str, turbulence_ui: str, delta_t: str = "1e-3", end_time: str = "0.5", write_interval: str = "0.01", max_co: float = 2.0, max_iters: int = 500) -> None:
        app_name = "pimpleFoam" if transient else "simpleFoam"
        initial_dt = delta_t if transient else "1"
        endTime  = end_time if transient else str(max_iters)
        writeControl = "adjustableRunTime" if transient else "timeStep"
        writeInterval = write_interval if transient else "50"
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
writePrecision  6;
writeCompression off;
timeFormat      general;
timePrecision   6;
runTimeModifiable true;

functions
{{
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
        liftDir         (0 1 0);
        dragDir         (1 0 0);
        CofR            ({0.25 * chord} 0 0);
        pitchAxis       (0 0 1);
        magUInf         {float(u_inlet)};
        lRef            {chord};
        Aref            {chord * (0.1 * chord)};
    }}
}}
"""
        with open(os.path.join(self.case_dir, "system", "controlDict"), "w") as f:
            f.write(controlDict)

        is_laminar = "Laminar" in turbulence_ui
        is_transition = "SST-LM" in turbulence_ui or "gamma-ReTheta" in turbulence_ui
        
        div_turb = ""
        if not is_laminar:
            if is_transition:
                # Modelos de transición necesitan esquemas para gamma y ReThetat
                div_turb = """\n    div(phi,k)      bounded Gauss upwind;
    div(phi,omega)  bounded Gauss upwind;
    div(phi,gammaInt) bounded Gauss upwind;
    div(phi,ReThetat) bounded Gauss upwind;"""
            elif "Epsilon" in turbulence_ui:
                div_turb = """\n    div(phi,k)      bounded Gauss upwind;
    div(phi,epsilon) bounded Gauss upwind;"""
            elif "Omega" in turbulence_ui:
                div_turb = """\n    div(phi,k)      bounded Gauss upwind;
    div(phi,omega)  bounded Gauss upwind;"""
            elif "Spalart" in turbulence_ui:
                div_turb = """\n    div(phi,nuTilda) bounded Gauss upwind;"""

        ddt = "Euler" if transient else "steadyState"
        fvSchemes = f"""FoamFile {{ version 2.0; format ascii; class dictionary; object fvSchemes; }}
ddtSchemes {{ default {ddt}; }}
gradSchemes {{ default cellMDLimited Gauss linear 1; }}
divSchemes {{
    default         none;
    div(phi,U)      bounded Gauss upwind;{div_turb}
    div((nuEff*dev2(T(grad(U))))) Gauss linear;
    div(div(phi,U)) Gauss linear;
}}
laplacianSchemes {{
    default Gauss linear limited corrected 0.5;
    laplacian(1,Phi) Gauss linear corrected;
}}
interpolationSchemes {{ default linear; }}
snGradSchemes {{ default limited corrected 0.5; }}
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
    residualControl {{
        p               {tolerance};
        U               {tolerance};
        "(k|omega|epsilon|nuTilda|gammaInt|ReThetat)" {tolerance};
    }}
}}
relaxationFactors {{
    fields {{ p 0.3; }}
    equations {{ U 0.7; k 0.7; omega 0.7; epsilon 0.7; nuTilda 0.7; gammaInt 0.7; ReThetat 0.7; }}
}}
""" if not transient else f"""
{alg} {{
    nNonOrthogonalCorrectors 3;
    nCorrectors     2;
    nOuterCorrectors 3;
    residualControl {{
        p               {{ tolerance {tolerance}; relTol 0; }}
        U               {{ tolerance {tolerance}; relTol 0; }}
        "(k|omega|epsilon|nuTilda|gammaInt|ReThetat)" {{ tolerance {tolerance}; relTol 0; }}
    }}
}}
relaxationFactors {{
    fields {{ p 0.3; }}
    equations {{ U 0.7; k 0.7; omega 0.7; epsilon 0.7; nuTilda 0.7; gammaInt 0.7; ReThetat 0.7; }}
}}
"""

        fvSolution = f"""FoamFile {{ version 2.0; format ascii; class dictionary; object fvSolution; }}
solvers {{
    p {{
        solver          {p_solver};
        tolerance       1e-6;
        relTol          0.1;
        smoother        GaussSeidel;
    }}
    pFinal {{
        $p;
        relTol 0;
    }}
    "{field_names}" {{
        solver          PBiCGStab;
        preconditioner  DILU;
        tolerance       1e-6;
        relTol          0.1;
    }}
    "{field_names}Final" {{
        solver          PBiCGStab;
        preconditioner  DILU;
        tolerance       1e-6;
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
        model = "kOmegaSST"
        if "SST-LM" in turbulence_ui:
            model = "kOmegaSSTLM"
        elif "gamma-ReTheta" in turbulence_ui:
            model = "gammaReThetatSST"  
        elif "Epsilon" in turbulence_ui: model = "kEpsilon"
        elif "Omega" in turbulence_ui and "SST" not in turbulence_ui: model = "kOmega"
        elif "Spalart" in turbulence_ui: model = "SpalartAllmaras"

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
        
        # Boundary/Initial Conditions for U and p (common)
        U_content = f"""FoamFile {{ version 2.0; format ascii; class volVectorField; object U; }}
dimensions      [0 1 -1 0 0 0 0];
internalField   uniform ({u_inlet} 0 0);
boundaryField {{
    inlet {{ type fixedValue; value uniform ({u_inlet} 0 0); }}
    outlet {{ type zeroGradient; }}
    walls_TB {{ type slip; }}
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
    inlet {{ type zeroGradient; }}
    outlet {{ type fixedValue; value uniform {p_outlet}; }}
    walls_TB {{ type zeroGradient; }}
    airfoil {{ type zeroGradient; }}
    frontAndBack {{ type empty; }}
    defaultFaces {{ type empty; }}
}}
"""
        with open(os.path.join(self.case_dir, "0", "p"), "w") as f: f.write(P_content)

        if is_laminar: return

        # Turbulence estimations using the calculated nu
        u_flt = float(u_inlet)
        I = 0.01
        k_val = max(1.5 * (u_flt * I)**2, 1e-5)
        omega_val = max(k_val / (10.0 * nu), 1e-3)
        epsilon_val = max(0.09 * (k_val**1.5) / (0.07 * chord), 1e-4)
        nuTilda_val = 3.0 * nu
        is_transition = "SST-LM" in turbulence_ui or "gamma-ReTheta" in turbulence_ui

        # Write fields based on model
        if "Epsilon" in turbulence_ui or "Omega" in turbulence_ui or is_transition:
            # k is used in k-epsilon, k-omega, and transition models
            k_content = f"""FoamFile {{ version 2.0; format ascii; class volScalarField; object k; }}
dimensions      [0 2 -2 0 0 0 0];
internalField   uniform {k_val:.6f};
boundaryField {{
    inlet {{ type fixedValue; value uniform {k_val:.6f}; }}
    outlet {{ type zeroGradient; }}
    walls_TB {{ type zeroGradient; }}
    airfoil {{ type kqRWallFunction; value uniform {k_val:.6f}; }}
    frontAndBack {{ type empty; }}
    defaultFaces {{ type empty; }}
}}
"""
            with open(os.path.join(self.case_dir, "0", "k"), "w") as f: f.write(k_content)

        if "Epsilon" in turbulence_ui:
            eps_content = f"""FoamFile {{ version 2.0; format ascii; class volScalarField; object epsilon; }}
dimensions      [0 2 -3 0 0 0 0];
internalField   uniform {epsilon_val:.6f};
boundaryField {{
    inlet {{ type fixedValue; value uniform {epsilon_val:.6f}; }}
    outlet {{ type zeroGradient; }}
    walls_TB {{ type zeroGradient; }}
    airfoil {{ type epsilonWallFunction; value uniform {epsilon_val:.6f}; }}
    frontAndBack {{ type empty; }}
    defaultFaces {{ type empty; }}
}}
"""
            with open(os.path.join(self.case_dir, "0", "epsilon"), "w") as f: f.write(eps_content)

        if "Omega" in turbulence_ui or is_transition:
            om_content = f"""FoamFile {{ version 2.0; format ascii; class volScalarField; object omega; }}
dimensions      [0 0 -1 0 0 0 0];
internalField   uniform {omega_val:.6f};
boundaryField {{
    inlet {{ type fixedValue; value uniform {omega_val:.6f}; }}
    outlet {{ type zeroGradient; }}
    walls_TB {{ type zeroGradient; }}
    airfoil {{ type omegaWallFunction; value uniform {omega_val:.6f}; }}
    frontAndBack {{ type empty; }}
    defaultFaces {{ type empty; }}
}}
"""
            with open(os.path.join(self.case_dir, "0", "omega"), "w") as f: f.write(om_content)

        if "Spalart" in turbulence_ui:
            nt_content = f"""FoamFile {{ version 2.0; format ascii; class volScalarField; object nuTilda; }}
dimensions      [0 2 -1 0 0 0 0];
internalField   uniform {nuTilda_val:.6f};
boundaryField {{
    inlet {{ type fixedValue; value uniform {nuTilda_val:.6f}; }}
    outlet {{ type zeroGradient; }}
    walls_TB {{ type zeroGradient; }}
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
    walls_TB {{ type zeroGradient; }}
    airfoil {{ type zeroGradient; }}
    frontAndBack {{ type empty; }}
    defaultFaces {{ type empty; }}
}}
"""
            with open(os.path.join(self.case_dir, "0", "gammaInt"), "w") as f: f.write(gamma_content)

            # ReThetat: estimación a partir de correlación empírica
            Re_theta = max(100.0, 1173.51 - 589.428 * (I * 100) + 0.2196 / ((I * 100)**2))
            re_theta_content = f"""FoamFile {{ version 2.0; format ascii; class volScalarField; object ReThetat; }}
dimensions      [0 0 0 0 0 0 0];
internalField   uniform {Re_theta:.1f};
boundaryField {{
    inlet {{ type fixedValue; value uniform {Re_theta:.1f}; }}
    outlet {{ type zeroGradient; }}
    walls_TB {{ type zeroGradient; }}
    airfoil {{ type zeroGradient; }}
    frontAndBack {{ type empty; }}
    defaultFaces {{ type empty; }}
}}
"""
            with open(os.path.join(self.case_dir, "0", "ReThetat"), "w") as f: f.write(re_theta_content)

        # nut is always needed for RAS
        nut_content = """FoamFile { version 2.0; format ascii; class volScalarField; object nut; }
dimensions      [0 2 -1 0 0 0 0];
internalField   uniform 0;
boundaryField {
    inlet { type calculated; value uniform 0; }
    outlet { type calculated; value uniform 0; }
    walls_TB { type calculated; value uniform 0; }
    airfoil { type nutkWallFunction; value uniform 0; }
    frontAndBack { type empty; }
    defaultFaces { type empty; }
}
"""
        with open(os.path.join(self.case_dir, "0", "nut"), "w") as f: f.write(nut_content)
