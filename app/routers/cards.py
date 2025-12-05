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
AVATAR_PATH = os.path.join(ASSETS_DIR, "avatar.png")
TEXT_MARGIN = 4 * mm
MAX_TEXT_WIDTH = CARD_WIDTH - (2 * TEXT_MARGIN)

# --- UTILIDADES ---

def generate_qr_image(data: str):
    qr = qrcode.QRCode(version=1, box_size=10, border=0)
    qr.add_data(data)
    qr.make(fit=True)
    return qr.make_image(fill_color="black", back_color="white")

def split_text_balanced(text):
    words = text.split()
    if len(words) <= 1: return text, ""
    mid = math.ceil(len(words) / 2)
    return " ".join(words[:mid]), " ".join(words[mid:])

def draw_card(c: canvas.Canvas, person, is_employee=False):
    """
    Dibuja un carnet genérico.
    person: puede ser modelo Student o Employee
    """
    # 1. Fondo
    if os.path.exists(BG_PATH):
        c.drawImage(BG_PATH, 0, 0, width=CARD_WIDTH, height=CARD_HEIGHT)
    else:
        c.setFillColorRGB(1, 1, 1)
        c.rect(0, 0, CARD_WIDTH, CARD_HEIGHT, fill=1, stroke=1)

    # 2. Foto (Circular)
    photo_size = 30 * mm
    photo_y = 43 * mm
    photo_x = (CARD_WIDTH - photo_size) / 2
    radius = photo_size / 2
    # LÓGICA DE SELECCIÓN DE IMAGEN
    image_to_draw = None

    # 1. Intentar buscar foto personal
    if person.photo_path:
        sys_path = person.photo_path.lstrip("/")
        if os.path.exists(f"app{person.photo_path}"):
            image_to_draw = f"app{person.photo_path}"
        elif os.path.exists(sys_path):
            image_to_draw = sys_path
    
    # 2. Si no se encontró foto personal, usar Avatar Genérico
    if not image_to_draw and os.path.exists(AVATAR_PATH):
        image_to_draw = AVATAR_PATH
    
    c.saveState()
    path = c.beginPath()
    path.circle(photo_x + radius, photo_y + radius, radius) 
    c.clipPath(path, stroke=0, fill=0)
    
    if image_to_draw:
        try:
            c.drawImage(image_to_draw, photo_x, photo_y, width=photo_size, height=photo_size, mask=None) 
        except:
            c.setFillColorRGB(0.9, 0.9, 0.9)
            c.rect(photo_x, photo_y, photo_size, photo_size, fill=1)
    else:
        c.setFillColorRGB(0.9, 0.9, 0.9)
        c.rect(photo_x, photo_y, photo_size, photo_size, fill=1)
    c.restoreState()
    
    # Borde foto
    c.setStrokeColorRGB(0.2, 0.2, 0.2)
    c.setLineWidth(0.5)
    c.circle(photo_x + radius, photo_y + radius, radius, stroke=1, fill=0)

    # 3. Nombre
    c.setFillColorRGB(0, 0, 0)
    name_y = 36 * mm
    full_name = person.full_name.upper()
    font_name = "Helvetica-Bold"
    font_size = 12
    
    if stringWidth(full_name, font_name, font_size) > MAX_TEXT_WIDTH:
        font_size = 10
        if stringWidth(full_name, font_name, font_size) > MAX_TEXT_WIDTH:
            l1, l2 = split_text_balanced(full_name)
            c.setFont(font_name, 11)
            c.drawCentredString(CARD_WIDTH/2, name_y + 2*mm, l1)
            c.drawCentredString(CARD_WIDTH/2, name_y - 2*mm, l2)
        else:
            c.setFont(font_name, font_size)
            c.drawCentredString(CARD_WIDTH/2, name_y, full_name)
    else:
        c.setFont(font_name, font_size)
        c.drawCentredString(CARD_WIDTH/2, name_y, full_name)

    # 4. Datos Variables (Estudiante vs Empleado)
    c.setFont("Helvetica", 10)
    info_y = 30 * mm
    
    if is_employee:
        # EMPLEADO
        if person.position:
            c.drawCentredString(CARD_WIDTH/2, info_y + 4*mm, person.position.upper())
        c.setFont("Helvetica", 9)
        c.drawCentredString(CARD_WIDTH/2, info_y, f"C.C.: {person.doc_id}")
        qr_data = person.doc_id
    else:
        # ESTUDIANTE
        # Curso omitido según diseño anterior, o se puede poner si se desea
        # c.drawCentredString(CARD_WIDTH/2, info_y + 4*mm, person.course) 
        c.setFont("Helvetica", 9)
        c.drawCentredString(CARD_WIDTH/2, info_y, f"ID: {person.student_id}")
        qr_data = person.student_id

    # 5. QR Firmado
    secure_qr = auth.sign_qr_content(qr_data)
    qr_img = generate_qr_image(secure_qr)
    
    qr_size = 26 * mm
    qr_x = (CARD_WIDTH - qr_size) / 2
    
    side_im_data = io.BytesIO()
    qr_img.save(side_im_data, format='PNG')
    side_im_data.seek(0)
    c.drawImage(ImageReader(side_im_data), qr_x, 3*mm, width=qr_size, height=qr_size)

# --- ENDPOINTS ---

@router.get("/pdf/{student_id}")
def download_student_card(student_id: str, db: Session = Depends(database.get_db)):
    student = db.query(models.Student).filter(models.Student.student_id == student_id).first()
    if not student: raise HTTPException(404, "No encontrado")
    
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=(CARD_WIDTH, CARD_HEIGHT))
    draw_card(c, student, is_employee=False)
    c.showPage()
    c.save()
    buffer.seek(0)
    return Response(content=buffer.getvalue(), headers={'Content-Disposition': f'attachment; filename="carnet_{student_id}.pdf"'}, media_type='application/pdf')

# NUEVO: Endpoint para Empleado
@router.get("/employee/pdf/{doc_id}")
def download_employee_card(doc_id: str, db: Session = Depends(database.get_db)):
    emp = db.query(models.Employee).filter(models.Employee.doc_id == doc_id).first()
    if not emp: raise HTTPException(404, "Empleado no encontrado")
    
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=(CARD_WIDTH, CARD_HEIGHT))
    draw_card(c, emp, is_employee=True)
    c.showPage()
    c.save()
    buffer.seek(0)
    return Response(content=buffer.getvalue(), headers={'Content-Disposition': f'attachment; filename="carnet_EMP_{doc_id}.pdf"'}, media_type='application/pdf')

@router.get("/batch/pdf")
def download_all_cards_pdf(db: Session = Depends(database.get_db)):
    # Solo estudiantes por defecto en el batch general
    students = db.query(models.Student).order_by(models.Student.course).all()
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=(CARD_WIDTH, CARD_HEIGHT))
    for s in students:
        draw_card(c, s, is_employee=False)
        c.showPage()
    c.save()
    buffer.seek(0)
    return Response(content=buffer.getvalue(), headers={'Content-Disposition': 'attachment; filename="todos_carnets.pdf"'}, media_type='application/pdf')

@router.get("/batch/qr-images")
def download_all_qrs_zip(db: Session = Depends(database.get_db)):
    students = db.query(models.Student).all()
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED, False) as zf:
        for s in students:
            qr = generate_qr_image(auth.sign_qr_content(s.student_id))
            ib = io.BytesIO(); qr.save(ib, format="PNG"); ib.seek(0)
            zf.writestr(f"{s.student_id}.png", ib.getvalue())
    zip_buffer.seek(0)
    return Response(content=zip_buffer.getvalue(), headers={'Content-Disposition': 'attachment; filename="qrs.zip"'}, media_type='application/zip')