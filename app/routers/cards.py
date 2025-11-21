from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.orm import Session
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase.pdfmetrics import stringWidth
import qrcode
import io
import os
import zipfile
import math
from .. import database, models, deps, auth

router = APIRouter(
    prefix="/cards",
    tags=["Cards & QR"],
    dependencies=[Depends(deps.require_admin)]
)

# --- CONFIGURACIÓN ---
CARD_WIDTH = 54 * mm
CARD_HEIGHT = 85 * mm
ASSETS_DIR = "app/static/assets"
BG_PATH = os.path.join(ASSETS_DIR, "carnet_bg.png")

# Margen lateral de seguridad para textos (4mm a cada lado)
TEXT_MARGIN = 4 * mm
MAX_TEXT_WIDTH = CARD_WIDTH - (2 * TEXT_MARGIN)

# --- UTILIDADES ---

def generate_qr_image(data: str):
    """Genera una imagen QR en memoria"""
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=10,
        border=0, # Sin borde blanco extra, lo manejamos nosotros
    )
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    return img

def split_text_balanced(text):
    """Divide un texto en dos partes lo más equilibradas posible por palabras"""
    words = text.split()
    if len(words) == 1:
        return text, ""
    
    mid = math.ceil(len(words) / 2)
    line1 = " ".join(words[:mid])
    line2 = " ".join(words[mid:])
    return line1, line2

def draw_student_card(c: canvas.Canvas, student: models.Student):
    """Dibuja un solo carnet en el canvas actual"""
    
    # 1. Fondo
    if os.path.exists(BG_PATH):
        c.drawImage(BG_PATH, 0, 0, width=CARD_WIDTH, height=CARD_HEIGHT)
    else:
        c.setFillColorRGB(1, 1, 1)
        c.rect(0, 0, CARD_WIDTH, CARD_HEIGHT, fill=1)
        c.setStrokeColorRGB(0, 0, 0)
        c.rect(1, 1, CARD_WIDTH-2, CARD_HEIGHT-2, stroke=1, fill=0)

    # 2. Foto del Estudiante (Circular y "Fill")
    # Geometría
    photo_size = 28 * mm  # Un poco más grande para que se vea bien
    photo_y = 43 * mm     # Posición vertical
    photo_x = (CARD_WIDTH - photo_size) / 2
    radius = photo_size / 2
    center_x = photo_x + radius
    center_y = photo_y + radius

    photo_path = None
    if student.photo_path:
        sys_path = student.photo_path.lstrip("/")
        if os.path.exists(f"app{student.photo_path}"):
            photo_path = f"app{student.photo_path}"
        elif os.path.exists(sys_path):
             photo_path = sys_path
    
    # Guardamos el estado del canvas para aplicar el recorte (clipping)
    c.saveState()
    
    # Crear ruta circular para recortar
    path = c.beginPath()
    path.circle(center_x, center_y, radius) 
    c.clipPath(path, stroke=0, fill=0)
    
    if photo_path:
        # Dibujamos la imagen ocupando todo el cuadrado que envuelve al círculo
        # preserveAspectRatio=False fuerza a llenar el cuadro (y por ende el círculo)
        try:
            c.drawImage(photo_path, photo_x, photo_y, width=photo_size, height=photo_size, mask=None)
        except Exception:
            # Fallback si la imagen falla
            c.setFillColorRGB(0.8, 0.8, 0.8)
            c.rect(photo_x, photo_y, photo_size, photo_size, fill=1)
    else:
        # Avatar por defecto (Gris)
        c.setFillColorRGB(255, 255, 255)
        c.rect(photo_x, photo_y, photo_size, photo_size, fill=1)
        
    # Restaurar estado (quitar recorte para el resto de elementos)
    c.restoreState()

    # Opcional: Dibujar un borde fino alrededor de la foto circular para mejor acabado
    c.setStrokeColorRGB(0, 0, 0) # Gris oscuro
    c.setLineWidth(0.5)
    c.circle(center_x, center_y, radius, stroke=1, fill=0)

    # 3. Nombre Inteligente (Ajuste de línea y tamaño)
    c.setFillColorRGB(0, 0, 0)
    name_y_start = 36 * mm # Debajo de la foto
    
    font_name = "Helvetica-Bold"
    font_size = 12
    line_height = 4.5 * mm
    
    full_name = student.full_name.upper() # Nombre en mayúsculas se ve mejor
    
    # Estrategia 1: Una línea tamaño 12
    if stringWidth(full_name, font_name, font_size) <= MAX_TEXT_WIDTH:
        c.setFont(font_name, font_size)
        c.drawCentredString(CARD_WIDTH / 2, name_y_start, full_name)
    else:
        # Estrategia 2: Una línea tamaño 10
        font_size = 10
        if stringWidth(full_name, font_name, font_size) <= MAX_TEXT_WIDTH:
            c.setFont(font_name, font_size)
            c.drawCentredString(CARD_WIDTH / 2, name_y_start, full_name)
        else:
            # Estrategia 3: Dos líneas tamaño 11
            line1, line2 = split_text_balanced(full_name)
            font_size = 11
            
            # Si alguna línea aun es muy ancha, bajamos a 9
            w1 = stringWidth(line1, font_name, font_size)
            w2 = stringWidth(line2, font_name, font_size)
            
            if w1 > MAX_TEXT_WIDTH or w2 > MAX_TEXT_WIDTH:
                font_size = 9
            
            c.setFont(font_name, font_size)
            c.drawCentredString(CARD_WIDTH / 2, name_y_start + (line_height * 0.5), line1)
            c.drawCentredString(CARD_WIDTH / 2, name_y_start - (line_height * 0.5), line2)

    # 4. ID (Texto pequeño debajo del nombre)
    c.setFont("Helvetica", 9)
    # Ajustamos la Y dependiendo de si el nombre ocupó mucho espacio, 
    # pero para mantener diseño fijo, lo ponemos en zona segura.
    id_y = 30 * mm 
    c.drawCentredString(CARD_WIDTH / 2, id_y, f"ID: {student.student_id}")

    # 5. Código QR (Grande abajo)
    secure_qr_content = auth.sign_qr_content(student.student_id)
    qr_img = generate_qr_image(secure_qr_content) # Usamos el contenido firmado
    qr_size = 26 * mm # Tamaño generoso
    qr_x = (CARD_WIDTH - qr_size) / 2
    qr_y = 3 * mm # Margen inferior mínimo
    
    # Crear fondo blanco detrás del QR por si el fondo del carnet es oscuro
    c.setFillColorRGB(1, 1, 1)
    c.rect(qr_x - 1*mm, qr_y - 1*mm, qr_size + 2*mm, qr_size + 2*mm, fill=1, stroke=0)

    side_im_data = io.BytesIO()
    qr_img.save(side_im_data, format='PNG')
    side_im_data.seek(0)
    c.drawImage(ImageReader(side_im_data), qr_x, qr_y, width=qr_size, height=qr_size)

# --- ENDPOINTS ---

@router.get("/pdf/{student_id}")
def download_single_card(student_id: str, db: Session = Depends(database.get_db)):
    student = db.query(models.Student).filter(models.Student.student_id == student_id).first()
    if not student:
        raise HTTPException(status_code=404, detail="Estudiante no encontrado")

    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=(CARD_WIDTH, CARD_HEIGHT))
    draw_student_card(c, student)
    c.showPage()
    c.save()
    buffer.seek(0)

    headers = {'Content-Disposition': f'attachment; filename="carnet_{student_id}.pdf"'}
    return Response(content=buffer.getvalue(), headers=headers, media_type='application/pdf')

@router.get("/batch/pdf")
def download_all_cards_pdf(db: Session = Depends(database.get_db)):
    students = db.query(models.Student).order_by(models.Student.course, models.Student.full_name).all()
    
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=(CARD_WIDTH, CARD_HEIGHT))
    
    for student in students:
        draw_student_card(c, student)
        c.showPage()
    
    c.save()
    buffer.seek(0)
    
    headers = {'Content-Disposition': 'attachment; filename="todos_los_carnets.pdf"'}
    return Response(content=buffer.getvalue(), headers=headers, media_type='application/pdf')

@router.get("/batch/qr-images")
def download_all_qrs_zip(db: Session = Depends(database.get_db)):
    students = db.query(models.Student).all()
    
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED, False) as zip_file:
        for student in students:
            qr_img = generate_qr_image(student.student_id)
            img_buffer = io.BytesIO()
            qr_img.save(img_buffer, format="PNG")
            img_buffer.seek(0)
            zip_file.writestr(f"{student.student_id}.png", img_buffer.getvalue())
            
    zip_buffer.seek(0)
    headers = {'Content-Disposition': 'attachment; filename="codigos_qr.zip"'}
    return Response(content=zip_buffer.getvalue(), headers=headers, media_type='application/zip')