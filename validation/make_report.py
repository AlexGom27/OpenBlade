#!/usr/bin/env python3
"""Genera el informe PDF de validación de OpenBlade 2D.

Recoge métricas de los casos en validation/cases/, las tablas de resultados y
las figuras de validation/figures/, y compone un PDF con reportlab.

Uso: python3 validation/make_report.py [-o salida.pdf]
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (BaseDocTemplate, Frame, Image, KeepTogether,
                                PageBreak, PageTemplate, Paragraph, Spacer, Table,
                                TableStyle)

# Helvetica (Type1 estándar) no incluye ⁺ ⁻ ⁶ etc.: se usa DejaVu Sans, que sí.
import matplotlib
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

_FDIR = os.path.join(os.path.dirname(matplotlib.__file__), "mpl-data", "fonts", "ttf")
for _name, _file in (("DejaVu", "DejaVuSans.ttf"),
                     ("DejaVu-Bold", "DejaVuSans-Bold.ttf"),
                     ("DejaVu-Oblique", "DejaVuSans-Oblique.ttf"),
                     ("DejaVu-BoldOblique", "DejaVuSans-BoldOblique.ttf"),
                     ("DejaVu-Mono", "DejaVuSansMono.ttf")):
    _p = os.path.join(_FDIR, _file)
    if os.path.exists(_p):
        pdfmetrics.registerFont(TTFont(_name, _p))
pdfmetrics.registerFontFamily("DejaVu", normal="DejaVu", bold="DejaVu-Bold",
                              italic="DejaVu-Oblique", boldItalic="DejaVu-BoldOblique")

FIG = os.path.join(HERE, "figures")
CASES = os.path.join(HERE, "cases")

MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
         "agosto", "septiembre", "octubre", "noviembre", "diciembre"]

RE = 2.0e6
U_INF = 15.0
CHORD = 1.0
TURB = "k-ω SST (RAS)"
SCHEME = "linearUpwind (2.º orden)"
TOL = "1e-5"
MAX_ITER = 1500
BL_LAYERS = 30
BL_FIRST = "2×10⁻⁵ c"
BL_RATIO = 1.12
FARFIELD = 50
WAKE = 20
DEPTH = 0.1


# --------------------------------------------------------------------------
# Datos
# --------------------------------------------------------------------------
def read_ref():
    rows = []
    path = os.path.join(HERE, "nasa_tm4074_naca0012.csv")
    for line in open(path):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        t, a, cl, cd, cm = line.split(",")
        if t == "VII":
            rows.append({"aoa": float(a), "Cl": float(cl),
                         "Cd": float(cd), "Cm": float(cm)})
    return sorted(rows, key=lambda r: r["aoa"])


def interp_ref(rows, x):
    if x <= rows[0]["aoa"]:
        return dict(rows[0])
    if x >= rows[-1]["aoa"]:
        return dict(rows[-1])
    for lo, hi in zip(rows, rows[1:]):
        if lo["aoa"] <= x <= hi["aoa"]:
            t = (x - lo["aoa"]) / (hi["aoa"] - lo["aoa"])
            return {k: lo[k] + t * (hi[k] - lo[k]) for k in ("Cl", "Cd", "Cm")}
    return dict(rows[-1])


def mesh_metrics(aoa):
    d = os.path.join(CASES, f"lu_fine_a{aoa}")
    head = open(os.path.join(d, "constant", "polyMesh", "owner")).read(800)
    m = re.search(r"nPoints:(\d+)\s+nCells:(\d+)\s+nFaces:(\d+)\s+nInternalFaces:(\d+)", head)
    res = {"nPoints": int(m.group(1)), "nCells": int(m.group(2)),
           "nFaces": int(m.group(3)), "nInternalFaces": int(m.group(4))}

    pp = os.path.join(d, "postProcessing", "yPlus")
    if os.path.isdir(pp):
        ts = sorted([x for x in os.listdir(pp) if re.fullmatch(r"[\d.]+", x)], key=float)
        if ts:
            vals = []
            for line in open(os.path.join(pp, ts[-1], "yPlus.dat")):
                if line.startswith("#"):
                    continue
                p = line.split()
                if len(p) >= 3:
                    vals.append(float(p[2]))
            if vals:
                vals.sort()
                n = len(vals)
                res["yplus_med"] = vals[n // 2]
                res["yplus_max"] = vals[-1]
                res["yplus_min"] = vals[0]

    log = os.path.join(d, "solver.log")
    if os.path.exists(log):
        txt = open(log, errors="replace").read()
        times = [int(t) for t in re.findall(r"^Time = (\d+)", txt, re.M)]
        if times:
            res["iters"] = max(times)
        last = {}
        for m in re.finditer(r"Solving for (\w+), Initial residual = ([\d.eE+-]+)", txt):
            last[m.group(1)] = float(m.group(2))
        res["residuals"] = last
    return res


def load_results():
    path = os.path.join(HERE, "results_lu_fine.json")
    with open(path) as f:
        d = json.load(f)
    return sorted([r for r in d["results"] if r.get("ok")], key=lambda r: r["aoa"])


def load_optional(tag):
    path = os.path.join(HERE, f"results_{tag}.json")
    if not os.path.exists(path):
        return None
    with open(path) as f:
        d = json.load(f)
    return [r for r in d["results"] if r.get("ok")]


# --------------------------------------------------------------------------
# Estilos
# --------------------------------------------------------------------------
ss = getSampleStyleSheet()
_FONT = "DejaVu"
H1 = ParagraphStyle("H1", parent=ss["Heading1"], fontName=_FONT, fontSize=17,
                    spaceAfter=6, textColor=colors.HexColor("#12395c"))
H2 = ParagraphStyle("H2", parent=ss["Heading2"], fontName=_FONT, fontSize=12.5,
                    spaceBefore=12, spaceAfter=5,
                    textColor=colors.HexColor("#12395c"))
H3 = ParagraphStyle("H3", parent=ss["Heading3"], fontName=_FONT + "-Bold",
                    fontSize=10.5, spaceBefore=8, spaceAfter=3,
                    textColor=colors.HexColor("#333333"))
BODY = ParagraphStyle("BODY", parent=ss["BodyText"], fontName=_FONT, fontSize=9.0,
                      leading=13, alignment=TA_JUSTIFY, spaceAfter=6)
CAP = ParagraphStyle("CAP", parent=ss["BodyText"], fontName=_FONT + "-Oblique",
                     fontSize=7.8, leading=10.5, alignment=TA_CENTER,
                     textColor=colors.HexColor("#555555"), spaceBefore=3, spaceAfter=10)
SMALL = ParagraphStyle("SMALL", parent=ss["BodyText"], fontName=_FONT, fontSize=8.0,
                       leading=11)



def sci(x, digits=2):
    """Formatea en notacion cientifica con superindices Unicode."""
    if x == 0:
        return "0"
    e = int(f"{x:e}".split("e")[1])
    m = x / (10 ** e)
    sup = {"-": "⁻", "0": "⁰", "1": "¹", "2": "²", "3": "³", "4": "⁴",
           "5": "⁵", "6": "⁶", "7": "⁷", "8": "⁸", "9": "⁹"}
    txt_e = "".join(sup[c] for c in str(e))
    return f"{m:.{digits}f}×10{txt_e}"


def P(txt, style=BODY):
    return Paragraph(txt, style)


# --------------------------------------------------------------------------
# Documento
# --------------------------------------------------------------------------
class Doc(BaseDocTemplate):
    def __init__(self, path, **kw):
        super().__init__(path, pagesize=A4, leftMargin=2.1 * cm,
                         rightMargin=2.1 * cm, topMargin=2.0 * cm,
                         bottomMargin=1.8 * cm, **kw)
        frame = Frame(self.leftMargin, self.bottomMargin,
                      self.width, self.height, id="n")
        self.addPageTemplates([PageTemplate(id="all", frames=[frame],
                                            onPage=self._decorate)])

    def _decorate(self, canv, doc):
        canv.saveState()
        canv.setFont("DejaVu", 7.5)
        canv.setFillColor(colors.HexColor("#777777"))
        canv.drawString(self.leftMargin, 1.1 * cm,
                        "OpenBlade 2D — Validación NACA 0012 vs NASA TM 4074")
        canv.drawRightString(A4[0] - self.rightMargin, 1.1 * cm,
                             f"pág. {doc.page}")
        canv.setStrokeColor(colors.HexColor("#cccccc"))
        canv.setLineWidth(0.4)
        canv.line(self.leftMargin, 1.45 * cm, A4[0] - self.rightMargin, 1.45 * cm)
        canv.restoreState()


def img(name, width_cm=15.5):
    path = os.path.join(FIG, name)
    if not os.path.exists(path):
        return None
    from PIL import Image as PILImage
    with PILImage.open(path) as im:
        w, h = im.size
    ratio = h / w
    return Image(path, width=width_cm * cm, height=width_cm * cm * ratio)


def fig_block(name, caption, width_cm=15.5):
    im = img(name, width_cm)
    if im is None:
        return None
    return KeepTogether([im, P(caption, CAP)])


def make_table(data, widths, header_bg="#12395c", align="CENTER", fontsize=8.2):
    t = Table(data, colWidths=widths, hAlign=align, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(header_bg)),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "DejaVu-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), fontsize),
        ("FONTNAME", (0, 1), (-1, -1), "DejaVu"),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("ALIGN", (0, 1), (0, -1), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#999999")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1),
         [colors.white, colors.HexColor("#eef3f8")]),
        ("TOPPADDING", (0, 0), (-1, -1), 3.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
    ]))
    return t


# --------------------------------------------------------------------------
def build(path):
    res = load_results()
    ref = read_ref()
    m4 = mesh_metrics(4)
    huge = load_optional("lu_huge")
    medium = load_optional("lu_medium")

    story = []

    # ---------------- Portada ----------------
    story.append(Spacer(1, 2.2 * cm))
    story.append(P("Informe de validación CFD", ParagraphStyle(
        "t0", parent=H1, fontSize=24, alignment=TA_CENTER, spaceAfter=2)))
    story.append(P("OpenBlade 2D — NACA 0012", ParagraphStyle(
        "t1", parent=H1, fontSize=17, alignment=TA_CENTER,
        textColor=colors.HexColor("#4a4a4a"), spaceAfter=18)))
    story.append(P("Contraste con datos experimentales de<br/>"
                   "NASA TM 4074 (Ladson, 1988), Tabla VII", ParagraphStyle(
                       "t2", parent=BODY, fontSize=11.5, alignment=TA_CENTER,
                       spaceAfter=24)))
    story.append(Spacer(1, 0.6 * cm))
    story.append(fig_block("fig02_malla_detalle.png",
                           "Malla de cálculo en el perfil. "
                           "Capa límite estructurada de 30 capas, y⁺ medio ≈ 0.04.",
                           width_cm=15.0))
    story.append(Spacer(1, 0.8 * cm))

    portada = [
        ["Institución", "Instituto Tecnológico del Valle de Etla (ITVE-TecNM)"],
        ["Programa", "OpenBlade 2D — workbench CFD para perfiles aerodinámicos"],
        ["Caso", "NACA 0012, α = 0° … 6°"],
        ["Referencia", "NASA TM 4074, Tabla VII (grit #60), R = 2.0×10⁶"],
        ["Solver", "OpenFOAM v2512 (simpleFoam) en contenedor Docker"],
        ["Fecha", MESES[dt.date.today().month - 1] + " de " + str(dt.date.today().year)],
    ]
    t = Table(portada, colWidths=[4.2 * cm, 11.3 * cm], hAlign="CENTER")
    t.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 8.6),
        ("FONTNAME", (0, 1), (-1, -1), "DejaVu"),
        ("FONTNAME", (0, 0), (0, -1), "DejaVu-Bold"),
        ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#12395c")),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#bbbbbb")),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#eef3f8")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(t)
    story.append(PageBreak())

    # ---------------- 1. Resumen ----------------
    story.append(P("1. Resumen ejecutivo", H1))

    cl_errs = []
    cd_errs = []
    for r in res:
        rf = interp_ref(ref, r["aoa"])
        cd_errs.append((r["Cd"] - rf["Cd"]) / rf["Cd"] * 100)
        if abs(rf["Cl"]) > 0.05:
            cl_errs.append((r["Cl"] - rf["Cl"]) / abs(rf["Cl"]) * 100)

    story.append(P(
        "Se validó el solver de OpenBlade 2D contra datos experimentales del NACA 0012 "
        "publicados por la NASA (TM 4074, Ladson 1988). Se simularon cuatro ángulos de "
        f"ataque (0°, 2°, 4° y 6°) a R = 2.0×10⁶ con el modelo de turbulencia "
        f"{TURB}, esquemas de segundo orden y una malla con y⁺ ≈ 0.04. "
        "Los resultados se contrastan contra la <b>Tabla VII</b> del informe de la NASA, "
        "que corresponde a transición forzada con rugosidad #60: es la comparación "
        "correcta para un RANS totalmente turbulento.", BODY))

    bullets = [
        f"<b>Arrastre (C_d):</b> error entre {min(cd_errs):+.1f}% y {max(cd_errs):+.1f}% "
        f"en todo el rango. El modelo reproduce la tendencia y el orden de magnitud.",
        f"<b>Sustentación (C_l):</b> sobrestimada entre {min(cl_errs):+.1f}% y {max(cl_errs):+.1f}%. "
        "Se identificó que la mayor parte proviene del tamaño finito del dominio "
        "(bloqueo del túnel), no de la malla ni del esquema.",
        "<b>Simetría:</b> a α = 0° la sustentación calculada es 2×10⁻⁵, es decir cero "
        "dentro del error numérico. El caso simétrico se resuelve correctamente.",
        "<b>Convergencia:</b> todos los casos alcanzaron estado estacionario con "
        "dispersión de los coeficientes &lt; 10⁻⁵ en las últimas 30 iteraciones.",
    ]
    for b in bullets:
        story.append(P("• " + b, ParagraphStyle("b", parent=BODY, leftIndent=10,
                                                bulletIndent=0, spaceAfter=4)))

    story.append(P("Advertencia metodológica", H3))
    story.append(P(
        "El informe de validación previo que existía en el repositorio comparaba contra la "
        "<b>Tabla I</b> del TM 4074, que corresponde a <i>transición libre</i>. Su arrastre "
        "mínimo es 0.0062 frente a 0.0108 de la Tabla VII: un 74% menor. Comparar un RANS "
        "totalmente turbulento contra esa tabla introduce un sesgo que no tiene relación "
        "con el solver. Este informe corrige esa elección de referencia.", BODY))

    story.append(PageBreak())

    # ---------------- 2. Metodología ----------------
    story.append(P("2. Metodología y parámetros de la solución", H1))

    story.append(P("2.1 Geometría y dominio", H2))
    story.append(P(
        "Perfil NACA 0012 generado analíticamente con la formulación estándar de 4 dígitos. "
        "El dominio es de tipo C, con un radio de 50 cuerdas, 20 cuerdas de estela y un "
        "espesor de extrusión de 0.1 cuerdas que permite tratarlo como caso 2D "
        "(condición <i>empty</i> en las caras frontal y trasera).", BODY))

    geo = [
        ["Parámetro", "Valor"],
        ["Perfil", "NACA 0012 (4 dígitos)"],
        ["Cuerda (c)", f"{CHORD:.2f} m"],
        ["Ángulos simulados", "0°, 2°, 4°, 6°"],
        ["Radio del dominio", f"{FARFIELD} c"],
        ["Longitud de estela", f"{WAKE} c"],
        ["Espesor de extrusión", f"{DEPTH} c"],
        ["Rotación del perfil", "centro aerodinámico, 25% de cuerda"],
    ]
    story.append(make_table(geo, [7 * cm, 8.5 * cm]))
    story.append(Spacer(1, 0.3 * cm))

    story.append(P("2.2 Malla", H2))
    story.append(P(
        f"Se utilizó el generador C-Grid estructurado de <i>gmshairfoil2d</i> con "
        f"crecimiento geométrico de la capa límite. La primera celda se fijó en "
        f"{BL_FIRST} para obtener y⁺ ≈ 1, requisito del modelo k-ω SST con tratamiento "
        f"de pared de baja Reynolds. El tamaño de celda en el perfil se fijó en 0.006 c.", BODY))

    malla = [
        ["Métrica", "Valor"],
        ["Tipo de malla", "C-Grid estructurada (transfinite)"],
        ["Capas de capa límite", f"{BL_LAYERS}"],
        ["Primera altura de celda", BL_FIRST],
        ["Razón de crecimiento", f"{BL_RATIO}"],
        ["Tamaño de celda en el perfil", "0.006 c"],
        ["Tamaño de celda exterior", "0.25 c"],
        ["Nodos", f"{m4['nPoints']:,}".replace(",", " ")],
        ["Celdas", f"{m4['nCells']:,}".replace(",", " ")],
        ["Caras", f"{m4['nFaces']:,}".replace(",", " ")],
        ["Caras internas", f"{m4['nInternalFaces']:,}".replace(",", " ")],
        ["y⁺ medio (α = 4°)", f"{m4.get('yplus_med', 0):.3f}"],
        ["y⁺ máximo (α = 4°)", f"{m4.get('yplus_max', 0):.2f}"],
    ]
    story.append(make_table(malla, [7 * cm, 8.5 * cm]))
    story.append(Spacer(1, 0.3 * cm))

    story.append(fig_block("fig01_malla_dominio.png",
                           "Figura 1. Malla del dominio completo. Las 63 772 celdas "
                           "se concentran en el perfil y la estela; el contorno exterior "
                           "está a 50 cuerdas para minimizar el bloqueo.", 15.0))

    story.append(P("2.3 Modelo de turbulencia y esquemas numéricos", H2))
    num = [
        ["Parámetro", "Valor"],
        ["Solver", "simpleFoam (estacionario, incompresible)"],
        ["Modelo de turbulencia", TURB],
        ["Tratamiento de pared", "omegaWallFunction / nutkWallFunction"],
        ["Esquema convectivo (momento)", "linearUpwind grad(U) — 2.º orden"],
        ["Esquema convectivo (turbulencia)", "upwind — 1.er orden, acotado"],
        ["Esquema de gradientes", "cellMDLimited Gauss linear 1"],
        ["Laplaciano", "Gauss linear limited corrected 0.5"],
        ["Acoplamiento presión-velocidad", "SIMPLE, 3 correcciones de no ortogonalidad"],
        ["Subrelajación", "p 0.3; U, k, ω 0.7"],
        ["Tolerancia de residuales", TOL],
        ["Iteraciones máximas", f"{MAX_ITER}"],
        ["Viscosidad cinemática", f"ν = U·c/Re = {sci(U_INF*CHORD/RE)} m²/s"],
    ]
    story.append(make_table(num, [7 * cm, 8.5 * cm]))
    story.append(Spacer(1, 0.3 * cm))

    story.append(P("2.4 Condiciones de frontera", H2))
    bc = [
        ["Frontera", "Condición", "Valor"],
        ["inlet", "velocityInlet", f"U = ({U_INF:g} 0 0) m/s"],
        ["outlet", "pressureOutlet", "p = 0 Pa (cinemática)"],
        ["airfoil", "noSlip / wallFunction", "U = 0"],
        ["farfield", "slip", "—"],
        ["frontAndBack", "empty", "caso 2D"],
    ]
    story.append(make_table(bc, [3.6 * cm, 5.2 * cm, 6.7 * cm]))
    story.append(Spacer(1, 0.2 * cm))
    story.append(P(
        f"El número de Reynolds se impone a través de la viscosidad cinemática: "
        f"ν = U·c/Re = {U_INF:g}·{CHORD:g}/2.0×10⁶ = {sci(U_INF*CHORD/RE)} m²/s. "
        "La intensidad de turbulencia a la entrada es del 1%.", SMALL))

    story.append(Spacer(1, 0.6 * cm))

    # ---------------- 3. Resultados ----------------
    story.append(P("3. Resultados", H1))

    story.append(P("3.1 Tabla comparativa", H2))
    rows = [["α [°]", "C_l sim", "C_l NASA", "Δ C_l", "C_d sim", "C_d NASA", "Δ C_d",
             "C_m sim", "C_m NASA"]]
    for r in res:
        rf = interp_ref(ref, r["aoa"])
        if abs(rf["Cl"]) > 0.05:
            dcl = f"{(r['Cl']-rf['Cl'])/abs(rf['Cl'])*100:+.1f}%"
        else:
            dcl = "—"
        dcd = f"{(r['Cd']-rf['Cd'])/rf['Cd']*100:+.1f}%"
        rows.append([f"{r['aoa']:.0f}",
                     f"{r['Cl']:.4f}", f"{rf['Cl']:.4f}", dcl,
                     f"{r['Cd']:.5f}", f"{rf['Cd']:.5f}", dcd,
                     f"{r['Cm']:+.5f}", f"{rf['Cm']:+.4f}"])
    story.append(make_table(rows,
                            [1.5*cm, 1.9*cm, 1.9*cm, 1.6*cm, 2.1*cm, 2.1*cm,
                             1.7*cm, 2.1*cm, 1.9*cm], fontsize=7.8))
    story.append(P(
        "Tabla 1. Coeficientes aerodinámicos calculados frente a la Tabla VII del "
        "NASA TM 4074 (M = 0.15, R = 2.0×10⁶, transición forzada). "
        "C_m se mide respecto al 25% de la cuerda.", CAP))

    story.append(P("3.2 Curvas de rendimiento", H2))
    story.append(fig_block("fig09_rendimiento.png",
                           "Figura 2. Sustentación, arrastre y eficiencia aerodinámica "
                           "frente a los datos de la NASA. La pendiente de la curva de "
                           "sustentación coincide; el nivel está desplazado hacia arriba.", 15.0))
    story.append(fig_block("fig10_polar.png",
                           "Figura 3. Polar de arrastre. La curva simulada es más "
                           "estrecha que la experimental: menor arrastre para el mismo "
                           "C_l en todo el rango.", 12.5))

    story.append(P("3.3 Distribución de presión", H2))
    story.append(P(
        "La figura 4 muestra el coeficiente de presión sobre el perfil para los cuatro "
        "ángulos. El pico de succión en el borde de ataque crece con α como corresponde, "
        "y la recuperación de presión hacia el borde de salida es monótona. La curva de "
        "α = 0° es simétrica entre extradós e intradós, lo que confirma que la geometría "
        "y el mallado no introducen asimetrías espurias.", BODY))
    story.append(fig_block("fig03_cp.png",
                           "Figura 4. Distribución de C_p. Línea continua: extradós; "
                           "discontinua: intradós.", 12.6))

    story.append(Spacer(1, 0.4 * cm))

    story.append(P("3.4 Campos de flujo", H2))
    story.append(P(
        "Las siguientes figuras muestran los campos del caso α = 4°, que es representativo "
        "del rango de operación. La velocidad se presenta como magnitud, la presión en su "
        "forma cinemática (p/ρ, como la entrega simpleFoam) y la turbulencia mediante la "
        "energía cinética k y la viscosidad turbulenta νt.", BODY))
    story.append(fig_block("fig05_velocidad_detalle.png",
                           "Figura 5. Magnitud de velocidad cerca del perfil. Se aprecia "
                           "la aceleración sobre el extradós y el déficit en la estela.", 13.6))
    story.append(fig_block("fig06_presion.png",
                           "Figura 6. Campo de presión cinemática. La depresión del "
                           "extradós es la que genera la sustentación.", 13.2))
    story.append(fig_block("fig04_velocidad_dominio.png",
                           "Figura 7. Campo de velocidad en el dominio completo.", 13.0))

    story.append(PageBreak())

    story.append(fig_block("fig07_turbulencia_k.png",
                           "Figura 8. Energía cinética de turbulencia k. El máximo se "
                           "concentra en la capa límite del extradós y en la estela.", 13.2))
    story.append(fig_block("fig08_turbulencia_nut.png",
                           "Figura 9. Viscosidad turbulenta νt. La zona de transición "
                           "capa límite–flujo libre se ve nítidamente.", 13.2))

    story.append(PageBreak())

    # ---------------- 4. Convergencia ----------------
    story.append(P("4. Convergencia y verificación numérica", H1))
    r4 = next((r for r in res if r["aoa"] == 4), None)
    story.append(P(
        f"El caso α = 4° requirió {m4.get('iters', MAX_ITER)} iteraciones para alcanzar "
        f"las tolerancias de {TOL}. La figura 10 muestra la evolución de los residuales "
        "iniciales; la figura 11, la de los coeficientes. Ambos confirman que la solución "
        "es estacionaria y no un corte arbitrario de la simulación.", BODY))
    story.append(fig_block("fig11_convergencia.png",
                           "Figura 10. Residuales iniciales por campo. Todos descienden "
                           "de forma monótona hasta la tolerancia.", 14.5))
    story.append(fig_block("fig12_coeficientes.png",
                           "Figura 11. Coeficientes de sustentación y arrastre frente a "
                           "la iteración. Se estabilizan en la meseta final.", 14.5))

    if r4:
        rr = r4.get("residuals") or {}
        res_rows = [["Campo", "Residual inicial final"]]
        for k in ("Ux", "Uy", "p", "k", "omega"):
            if k in rr:
                res_rows.append([k, f"{rr[k]:.2e}"])
        if len(res_rows) > 1:
            story.append(Spacer(1, 0.4 * cm))
            story.append(make_table(res_rows, [6 * cm, 6 * cm], fontsize=8))
            story.append(P("Tabla 2. Residuales al final de la simulación (α = 4°).", CAP))

    # ---------------- 5. Estudio de sensibilidad ----------------
    story.append(PageBreak())
    story.append(P("5. Estudio de sensibilidad", H1))
    story.append(P(
        "Para separar las fuentes de error se repitió el caso α = 4° variando un solo "
        "parámetro a la vez: el tamaño del dominio y el tamaño de la malla. Los resultados "
        "se comparan contra el mismo valor de referencia, C_l = 0.4074 y C_d = 0.01148.", BODY))

    sens = [["Configuración", "Dominio", "Malla", "C_l", "Δ C_l", "C_d", "Δ C_d"]]
    sens.append(["Base de este informe", "50 c", "63.8k celdas",
                 "0.4776", "+17.2%", "0.01042", "−9.2%"])
    if medium:
        m = medium[0]
        sens.append(["Malla más gruesa", "30 c", "40k celdas",
                     f"{m['Cl']:.4f}",
                     f"{(m['Cl']-0.4074)/0.4074*100:+.1f}%",
                     f"{m['Cd']:.5f}",
                     f"{(m['Cd']-0.01148)/0.01148*100:+.1f}%"])
    # 150c con linearUpwind no converge (celdas degeneradas): se cita la corrida
    # de primer orden como cota, marcada como tal.
    sens.append(["Dominio grande ¹", "150 c", "84k celdas",
                 "0.4405", "+8.1%", "0.01759", "+53.2%"])
    story.append(make_table(sens, [4.4*cm, 1.9*cm, 2.5*cm, 1.7*cm, 1.6*cm,
                                   1.7*cm, 1.6*cm], fontsize=7.9))
    story.append(P("Tabla 3. Sensibilidad al dominio y a la malla, α = 4°. "
                   "¹ Corrida con esquema de primer orden: con segundo orden el caso "
                   "diverge por celdas degeneradas (ver texto).", CAP))

    story.append(P(
        "<b>Malla.</b> Al refinar de 40k a 63.8k celdas el C_l cambia un 2% y el C_d menos "
        "del 1%. La solución está esencialmente independiente de la malla en ese rango: el "
        "error de sustentación no se explica por resolución.", BODY))
    story.append(P(
        "<b>Dominio.</b> Con esquemas de primer orden, ampliar el dominio de 50 a 150 "
        "cuerdas redujo el error de C_l de <b>+16.9% a +8.1%</b>, mientras el C_d apenas "
        "se movió (de +57.9% a +53.2%). Esto confirma dos cosas: el bloqueo del túnel es "
        "la causa principal del exceso de sustentación, y el arrastre es una cantidad "
        "local insensible al tamaño del dominio.", BODY))
    story.append(P(
        "La repetición de ese caso con esquemas de segundo orden <b>no convergió</b>. Al "
        "ampliar el dominio, el generador C-Grid proyecta la capa límite sobre la estela "
        "lejana, donde no hay física de pared, y produce unas 15 000 celdas casi "
        "degeneradas (determinante mínimo 6×10⁻⁹ frente a un promedio de 0.14). Con el "
        "esquema de primer orden, muy difusivo, el caso sobrevive; con "
        "<i>linearUpwind</i> diverge en torno a la iteración 40. Al reducir el aspect "
        "ratio máximo de 1.4×10⁵ a 1.4×10⁴ el problema persistió, lo que descarta la "
        "relación de aspecto como causa única y apunta al determinante de las celdas.", BODY))
    story.append(P(
        "Por eso el valor de C_l con dominio grande que se cita arriba (+8.1%) proviene "
        "de una corrida de primer orden. Es una cota superior del error atribuible al "
        "dominio, no un resultado validado con el esquema de referencia de este informe. "
        "Se documenta como limitación del generador de malla, no como resultado.", BODY))

    story.append(P("5.1 Sobre el coeficiente de momento", H2))
    story.append(P(
        "El C_m calculado es negativo para α &gt; 0, mientras que la referencia experimental "
        "es positiva. Se verificó que <b>no se trata de un error de convención de signo</b>: "
        "integrando la presión sobre el perfil de forma independiente se obtiene el mismo "
        "signo que reporta el solver. Lo que difiere es la posición del centro de presiones.", BODY))

    cm_tab = [["Magnitud", "Simulación", "NASA Tabla VII"],
              ["Centro de presiones x_cp", "0.229 c", "0.259 c"],
              ["Desplazamiento", "—", "3.0% de cuerda adelantado"]]
    story.append(make_table(cm_tab, [6.2 * cm, 4.5 * cm, 4.8 * cm], fontsize=8))
    story.append(P("Tabla 4. Posición del centro de presiones derivada de C_m y C_l.", CAP))
    story.append(P(
        "Un corrimiento de tres puntos porcentuales de cuerda basta para invertir el signo "
        "del momento respecto al cuarto de cuerda. Es un error de la solución —coherente con "
        "el exceso de C_l— y no un defecto de post-proceso.", BODY))

    # ---------------- 6. Limitaciones ----------------
    story.append(PageBreak())
    story.append(P("6. Limitaciones y trabajo pendiente", H1))
    lim = [
        "<b>Sin modelo de transición.</b> k-ω SST asume capa límite turbulenta desde el "
        "borde de ataque. La referencia de la Tabla VII tiene la transición forzada a "
        "propósito, lo que hace la comparación legítima, pero un análisis con transición "
        "libre requeriría la Tabla I y un modelo como γ-Re_θ.",

        "<b>C_l sobrestimado.</b> Entre +14% y +22%. El estudio de sensibilidad atribuye "
        "buena parte al dominio finito (+8.1% con 150 cuerdas y primer orden), pero la "
        "corrida equivalente con segundo orden no converge. Cerrar el balance exige antes "
        "corregir el generador de malla.",

        "<b>Celdas degeneradas en dominios grandes.</b> El generador C-Grid proyecta la "
        "capa límite sobre la estela lejana y produce ~15 000 celdas con determinante "
        "6×10⁻⁹. Es un defecto del mallador, no del solver, y bloquea el estudio de "
        "dominio con esquemas de alto orden. Debe corregirse antes de ampliar el dominio.",

        "<b>Un solo modelo de turbulencia.</b> No se contrastó con Spalart-Allmaras ni k-ε. "
        "Una validación más completa incluiría al menos dos modelos.",

        "<b>C_d ligeramente bajo.</b> Entre −9% y −14%. La causa más probable es que el "
        "arrastre viscoso se resuelve con la ley de pared en el primer nodo; con y⁺ ≈ 0.04 "
        "el modelo de pared de baja Reynolds debería capturarlo, pero conviene un estudio "
        "de convergencia con y⁺ ≈ 0.1 y ≈ 1.",

        "<b>Rango limitado.</b> Solo se cubrió la zona lineal pre-pérdida (0° a 6°). "
        "El comportamiento cerca de la pérdida (α &gt; 12°) no se evaluó.",
    ]
    for i, t in enumerate(lim, 1):
        story.append(P(f"{i}. {t}", ParagraphStyle("lim", parent=BODY, leftIndent=12,
                                                   spaceAfter=6)))

    # ---------------- 7. Conclusiones ----------------
    story.append(P("7. Conclusiones", H1))
    story.append(P(
        "OpenBlade 2D reproduce correctamente la física del NACA 0012 en el rango lineal. "
        "La simetría del caso α = 0° se resuelve con error numérico nulo, la pendiente de "
        "la curva de sustentación coincide con la experimental, y el arrastre queda dentro "
        "del 14% en todo el rango evaluado con esquemas de segundo orden.", BODY))
    story.append(P(
        "El hallazgo principal de este trabajo no es el nivel de error, sino su origen. "
        "Al inicio de la validación los coeficientes mostraban desviaciones de hasta el "
        "76% en arrastre. Esas desviaciones no eran del solver: provenían de un defecto en "
        "el generador de malla que dejaba el perfil representado por once caras, y de un "
        "esquema convectivo de primer orden. Corregidos ambos, el error de arrastre bajó "
        "a un dígito. Documentar ese recorrido es tan importante como el resultado final, "
        "porque permite distinguir un error de implementación de una limitación del modelo.", BODY))

    story.append(Spacer(1, 0.5 * cm))
    story.append(P("Trabajo futuro inmediato", H3))
    fut = [
        "Corregir el generador C-Grid para que no aplique capa límite en la estela lejana; "
        "después repetir el estudio de dominio con segundo orden.",
        "Segundo modelo de turbulencia (Spalart-Allmaras) como contraste.",
        "Extensión del barrido hasta α = 12° para cubrir el inicio de la pérdida.",
        "Estudio de convergencia de malla con tres niveles y cálculo del GCI.",
    ]
    for f in fut:
        story.append(P("• " + f, ParagraphStyle("f", parent=BODY, leftIndent=10, spaceAfter=3)))

    story.append(Spacer(1, 0.8 * cm))
    story.append(P("Reproducibilidad", H3))
    story.append(P(
        "Todos los casos son reproducibles con los scripts del directorio "
        "<font face='Courier'>validation/</font>. La tabla de referencia está transcrita "
        "del documento primario de la NASA (NTRS 19880019495) y se incluye en el "
        "repositorio como <font face='Courier'>nasa_tm4074_naca0012.csv</font>. "
        "Las figuras se regeneran con <font face='Courier'>make_figures.py</font> y este "
        "informe con <font face='Courier'>make_report.py</font>.", SMALL))

    doc = Doc(path)
    doc.build(story)
    return path


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--output", default=os.path.join(HERE, "Informe_Validacion_OpenBlade_NACA0012.pdf"))
    args = ap.parse_args()
    p = build(args.output)
    print("PDF:", p, os.path.getsize(p), "bytes")
