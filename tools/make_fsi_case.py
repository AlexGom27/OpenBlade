"""Genera un caso FSI mínimo acoplado por preCICE: canal 2D con pared superior
deformable (fluido pimpleFoam) y placa elástica encima (sólido Python).

Uso:  python3 tools/make_fsi_case.py /tmp/fsi_channel
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.fsi_precice import FsiCase, FsiConfig  # noqa: E402

LX, LY = 1.0, 0.1      # canal
SOLID_H = 0.02
DT = 1.0e-3
END = 5.0e-3           # 5 ventanas

HEADER = """/*--------------------------------*- C++ -*----------------------------------*\\
| =========                 |                                                 |
| \\\\      /  F ield         | OpenFOAM: The Open Source CFD Toolbox           |
|  \\\\    /   O peration     | Version:  v2512                                 |
|   \\\\  /    A nd           | Website:  www.openfoam.com                      |
|    \\\\/     M anipulation  |                                                 |
\\*---------------------------------------------------------------------------*/
"""

BLOCKMESH = HEADER + """
FoamFile {{ version 2.0; format ascii; class dictionary;
            object blockMeshDict; }}
convertToMeters 1;
vertices
(
    (0 0 0) ({lx} 0 0) ({lx} {ly} 0) (0 {ly} 0)
    (0 0 {dz}) ({lx} 0 {dz}) ({lx} {ly} {dz}) (0 {ly} {dz})
);
blocks
(
    hex (0 1 2 3 4 5 6 7) ({nx} {ny} 1) simpleGrading (1 1 1)
);
edges ( );
boundary
(
    inlet     {{ type patch; faces ((0 4 7 3)); }}
    outlet    {{ type patch; faces ((1 2 6 5)); }}
    bottom    {{ type wall;  faces ((0 1 5 4)); }}
    interface {{ type wall;  faces ((3 7 6 2)); }}
    frontAndBack {{ type empty; faces ((0 3 2 1) (4 5 6 7)); }}
);
"""

FIELD_U = HEADER + """
FoamFile { version 2.0; format ascii; class volVectorField; object U; }
dimensions      [0 1 -1 0 0 0 0];
internalField   uniform (0.1 0 0);
boundaryField
{
    inlet           { type fixedValue; value uniform (0.1 0 0); }
    outlet          { type zeroGradient; }
    bottom          { type noSlip; }
    interface       { type movingWallVelocity; value uniform (0 0 0); }
    frontAndBack    { type empty; }
}
"""

FIELD_P = HEADER + """
FoamFile { version 2.0; format ascii; class volScalarField; object p; }
dimensions      [0 2 -2 0 0 0 0];
internalField   uniform 0;
boundaryField
{
    inlet           { type zeroGradient; }
    outlet          { type fixedValue; value uniform 0; }
    bottom          { type zeroGradient; }
    interface       { type zeroGradient; }
    frontAndBack    { type empty; }
}
"""

FIELD_PD = HEADER + """
FoamFile { version 2.0; format ascii; class pointVectorField; object pointDisplacement; }
dimensions      [0 1 0 0 0 0 0];
internalField   uniform (0 0 0);
boundaryField
{
    inlet           { type fixedValue; value uniform (0 0 0); }
    outlet          { type fixedValue; value uniform (0 0 0); }
    bottom          { type fixedValue; value uniform (0 0 0); }
    interface       { type fixedValue; value uniform (0 0 0); }
    frontAndBack    { type empty; }
}
"""

CONTROLDICT = HEADER + """
FoamFile {{ version 2.0; format ascii; class dictionary; object controlDict; }}
application     pimpleFoam;
startFrom       startTime;
startTime       0;
stopAt          endTime;
endTime         {end};
deltaT          {dt};
writeControl    timeStep;
writeInterval   1;
purgeWrite      0;
writeFormat     ascii;
writePrecision  8;
writeCompression off;
timeFormat      general;
timePrecision   6;
runTimeModifiable true;
adjustTimeStep  no;

functions
{{
    preciceAdapterFunctionObject
    {{
        type            preciceAdapterFunctionObject;
        libs            ("libpreciceAdapterFunctionObject.so");
    }}
}}
"""

FVSCHEMES = HEADER + """
FoamFile { version 2.0; format ascii; class dictionary; object fvSchemes; }
ddtSchemes      { default Euler; }
gradSchemes     { default Gauss linear; }
divSchemes
{
    default         none;
    div(phi,U)      Gauss linearUpwind grad(U);
    div(phi,p)      Gauss linear;
    div((nuEff*dev2(T(grad(U))))) Gauss linear;
}
laplacianSchemes { default Gauss linear corrected; }
interpolationSchemes { default linear; pointInterpolation linear; }
snGradSchemes   { default corrected; }
fluxRequired    { default no; p; }
"""

FVSOLUTION = HEADER + """
FoamFile { version 2.0; format ascii; class dictionary; object fvSolution; }
solvers
{
    p
    {
        solver          GAMG;
        tolerance       1e-8;
        relTol          0.01;
        smoother        DICGaussSeidel;
    }
    pFinal
    {
        $p;
        relTol          0;
    }
    U
    {
        solver          smoothSolver;
        smoother        symGaussSeidel;
        tolerance       1e-8;
        relTol          0.01;
    }
    UFinal
    {
        $U;
        relTol          0;
    }
    cellDisplacement
    {
        solver          GAMG;
        smoother        GaussSeidel;
        tolerance       1e-8;
        relTol          0;
    }
    cellDisplacementFinal
    {
        $cellDisplacement;
        relTol          0;
    }
    pcorr
    {
        solver          GAMG;
        smoother        GaussSeidel;
        tolerance       1e-8;
        relTol          0;
    }
    pcorrFinal
    {
        $pcorr;
        relTol          0;
    }
}
PIMPLE
{
    correctPhi       yes;
    nOuterCorrectors 2;
    nCorrectors      2;
    nNonOrthogonalCorrectors 0;
    pRefCell        0;
    pRefValue       0;
}
"""

DYNAMICMESH = HEADER + """
FoamFile { version 2.0; format ascii; class dictionary; object dynamicMeshDict; }
dynamicFvMesh   dynamicMotionSolverFvMesh;
motionSolverLibs ("libfvMotionSolvers.so");
solver          displacementLaplacian;
displacementLaplacianCoeffs
{
    diffusivity inverseDistance (interface);
}
"""

TRANSPORT = HEADER + """
FoamFile { version 2.0; format ascii; class dictionary; object transportProperties; }
transportModel  Newtonian;
nu              [0 2 -1 0 0 0 0] 1e-05;
"""

PRECICEDICT = HEADER + """
FoamFile { version 2.0; format ascii; class dictionary; object preciceDict; }

// El adaptador v1.4.0 lee su configuración de AQUÍ, no de controlDict.
// Sin este archivo aborta con "cannot find file system/preciceDict" y el
// caso corre desacoplado (el desplazamiento se queda en cero).
preciceConfig   "precice-config.xml";

participant     Fluid;

modules         (FSI);

// Densidad que el adaptador usa para convertir la presión cinemática en
// fuerza/tracción. Sin esta entrada aborta con "Entry 'rho' not found".
FSI
{
    // dimensionedScalar explícito: el adaptador no acepta la indirección
    // "rho rhoInf" y aborta con "attempt to read beyond EOF".
    rho             [1 -3 0 0 0 0 0] 1.0;
}

interfaces
{
    interface
    {
        mesh            Fluid-Mesh;
        patches         (interface);
        writeData       (Stress);
        readData        (Displacement);
    }
}
"""

MOMENTUM = HEADER + """
FoamFile { version 2.0; format ascii; class dictionary; object momentumTransport; }
simulationType  laminar;
"""

TURBULENCE = HEADER + """
FoamFile { version 2.0; format ascii; class dictionary; object turbulenceProperties; }
simulationType  laminar;
"""


def main(dest: str) -> int:
    root = Path(dest).resolve()
    case = root / "fluid"
    for sub in ("0", "constant", "system"):
        (case / sub).mkdir(parents=True, exist_ok=True)

    (case / "system" / "blockMeshDict").write_text(
        BLOCKMESH.format(lx=LX, ly=LY, dz=0.01, nx=100, ny=10)
    )
    (case / "0" / "U").write_text(FIELD_U)
    (case / "0" / "p").write_text(FIELD_P)
    (case / "0" / "pointDisplacement").write_text(FIELD_PD)
    (case / "system" / "controlDict").write_text(
        CONTROLDICT.format(end=END, dt=DT)
    )
    (case / "system" / "fvSchemes").write_text(FVSCHEMES)
    (case / "system" / "fvSolution").write_text(FVSOLUTION)
    (case / "system" / "preciceDict").write_text(PRECICEDICT)
    (case / "constant" / "dynamicMeshDict").write_text(DYNAMICMESH)
    (case / "constant" / "transportProperties").write_text(TRANSPORT)
    (case / "constant" / "momentumTransport").write_text(MOMENTUM)
    (case / "constant" / "turbulenceProperties").write_text(TURBULENCE)

    cfg = FsiConfig(
        fluid_participant="Fluid",
        solid_participant="Solid",
        fluid_mesh="Fluid-Mesh",
        solid_mesh="Solid-Mesh",
        force_data="Stress",
        displacement_data="Displacement",
        interface_patch="interface",
        dimensions=2,
        dt=DT,
        end_time=END,
        coupling_scheme="serial-implicit",
        max_iterations=20,
        relaxation="constant",
        relaxation_factor=0.5,
        convergence_limit=1e-4,
    )
    FsiCase(str(case), cfg).write_precice_config()

    print("caso generado en", case)
    print("ventanas:", round(END / DT))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "/tmp/fsi_channel"))
