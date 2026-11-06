import os
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image, Table, TableStyle, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

def _cifra(valor, formato, unidad=""):
    return format(valor, formato) + unidad if isinstance(valor, (int, float)) else "desconocido"


def _tabla_ficha(ficha):
    """Lo que identifica el calculo: de donde salio y con que."""
    ejecucion = ficha.get("ejecucion") or {}
    programa = ficha.get("programa") or {}
    versiones = ficha.get("versiones") or {}
    malla = ficha.get("checkmesh") or {}
    filas = [["Dato", "Valor"],
             ["Programa (commit)", (programa.get("commit") or "desconocido")[:12]
              + (" con cambios sin guardar" if programa.get("modificados") else "")],
             ["sha256 de la malla", ((ficha.get("archivos") or {}).get("mesh.msh") or "")[:24]],
             ["Malla", (ficha.get("malla") or {}).get("mallador")
              or f"gmsh {versiones.get('gmsh')} / gmshairfoil2d {versiones.get('gmshairfoil2d')}"],
             ["OpenFOAM", ejecucion.get("openfoam_build") or "desconocido"],
             ["Máquina / procesos", f"{ejecucion.get('maquina')} / {ejecucion.get('procesos')}"]]
    abertura = (ficha.get("malla") or {}).get("abertura_borde_salida")
    if abertura is not None:
        filas.append(["Abertura del borde de salida",
                      f"{100 * abertura:.2f} % de la cuerda, cerrada en la malla"])
    if malla:
        filas += [["Celdas", str(malla.get("celdas"))],
                  ["No ortogonalidad máx", _cifra(malla.get("no_ortogonalidad_max"), ".1f", "°")],
                  ["Sesgo máx", _cifra(malla.get("sesgo_max"), ".2f")]]
    return filas


def generate_pdf_report(filename, params, analysis, images, ficha=None):
    """Informe de una corrida. `analysis` es lo que devuelve core.verdict.analyze_case."""
    doc = SimpleDocTemplate(filename, pagesize=letter)
    styles = getSampleStyleSheet()
    title_style = styles['Heading1']
    subtitle_style = styles['Heading2']
    normal_style = styles['Normal']
    
    elements = []
    
    # Title
    elements.append(Paragraph("OpenBlade 2D - Informe de Simulación CFD", title_style))
    elements.append(Spacer(1, 12))

    # El veredicto va primero: ningun coeficiente se lee sin el.
    verdict = analysis["verdict"]
    estado = verdict["state"]
    color = {"CONVERGIDO": "#1b5e20", "DIVERGIDO": "#b71c1c"}.get(estado, "#b26a00")
    elements.append(Paragraph("Veredicto", subtitle_style))
    elements.append(Paragraph(f'<font color="{color}"><b>{estado}</b></font>: '
                              f'{verdict["reason"]}', normal_style))
    if estado != "CONVERGIDO":
        elements.append(Paragraph(f'<font color="{color}">Estos coeficientes no son un '
                                  'resultado válido de la simulación.</font>', normal_style))
    aviso = analysis.get("yplus_notice")
    if aviso:
        elements.append(Spacer(1, 6))
        elements.append(Paragraph(aviso["text"], normal_style))
    from core.surface import surface_text
    sup = surface_text(analysis.get("superficie"), verdict.get("cd"))
    if sup:
        elements.append(Spacer(1, 6))
        elements.append(Paragraph(sup[0].upper() + sup[1:] + ".", normal_style))
    elements.append(Spacer(1, 12))

    if ficha:
        elements.append(Paragraph("Ficha del caso", subtitle_style))
        t_ficha = Table(_tabla_ficha(ficha))
        t_ficha.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.grey),
            ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
            ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
            ('GRID', (0,0), (-1,-1), 0.5, colors.black)
        ]))
        elements.append(t_ficha)
        elements.append(Spacer(1, 12))
    
    # Parameters
    elements.append(Paragraph("Parámetros de la Simulación", subtitle_style))
    param_data = [["Parámetro", "Valor"]]
    for k, v in params.items():
        param_data.append([str(k), str(v)])
    
    if len(param_data) > 1:
        t = Table(param_data)
        t.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.grey),
            ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
            ('ALIGN', (0,0), (-1,-1), 'CENTER'),
            ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
            ('BOTTOMPADDING', (0,0), (-1,0), 12),
            ('BACKGROUND', (0,1), (-1,-1), colors.beige),
            ('GRID', (0,0), (-1,-1), 1, colors.black)
        ]))
        elements.append(t)
    elements.append(Spacer(1, 12))
    
    # Results Table
    elements.append(Paragraph("Resultados Finales", subtitle_style))
    res_data = [["Coeficiente", "Media", "± Amplitud"]]
    if verdict["cl"] is not None and estado != "DIVERGIDO":
        for nombre, media, amplitud, decimales in (
                ("Cl", verdict["cl"], verdict["cl_amp"], 4),
                ("Cd", verdict["cd"], verdict["cd_amp"], 5),
                ("Cm", verdict["cm"], verdict["cm_amp"], 4)):
            res_data.append([nombre, f"{media:.{decimales}f}", f"{amplitud:.{decimales}f}"])
    else:
        res_data.append(["Sin coeficientes válidos", "", ""])
    if verdict["window"]:
        ventana = "del último 25 % del tiempo" if verdict["transient"] else (
            f"de las últimas {verdict['window']} de {verdict['n_rows']} iteraciones")
        elements.append(Paragraph(f"Media {ventana}.", normal_style))
        elements.append(Spacer(1, 6))

    t_res = Table(res_data)
    t_res.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.darkblue),
        ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('BOTTOMPADDING', (0,0), (-1,0), 12),
        ('BACKGROUND', (0,1), (-1,-1), colors.aliceblue),
        ('GRID', (0,0), (-1,-1), 1, colors.black)
    ]))
    elements.append(t_res)
    elements.append(Spacer(1, 12))
    
    # Images
    for img_title, img_path in images.items():
        if os.path.exists(img_path):
            elements.append(Paragraph(img_title, subtitle_style))
            elements.append(Spacer(1, 6))
            # Escalar imagen para que encaje
            img = Image(img_path)
            # Default width is around 6 inches (432 points) for letter margins
            available_width = 450
            if img.drawWidth > available_width:
                aspect = img.drawHeight / img.drawWidth
                img.drawWidth = available_width
                img.drawHeight = available_width * aspect
            elements.append(img)
            elements.append(Spacer(1, 12))
            
    doc.build(elements)
