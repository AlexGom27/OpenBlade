import os
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image, Table, TableStyle, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

def generate_pdf_report(filename, params, results, images):
    doc = SimpleDocTemplate(filename, pagesize=letter)
    styles = getSampleStyleSheet()
    title_style = styles['Heading1']
    subtitle_style = styles['Heading2']
    normal_style = styles['Normal']
    
    elements = []
    
    # Title
    elements.append(Paragraph("OpenBlade 2D - Informe de Simulación CFD", title_style))
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
    res_data = [["Coeficiente", "Valor"]]
    for k, v in results.items():
        res_data.append([str(k), f"{v:.4f}" if isinstance(v, float) else str(v)])
        
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
