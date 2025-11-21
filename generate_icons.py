from PIL import Image
import os

# Configuración
SOURCE_LOGO = "app/static/assets/logo.png"
OUTPUT_DIR = "app/static/icons"
SIZES = [(192, 192), (512, 512)]

if not os.path.exists(OUTPUT_DIR):
    os.makedirs(OUTPUT_DIR)

def generate_icons():
    if not os.path.exists(SOURCE_LOGO):
        print(f"ERROR: No encontré la imagen en {SOURCE_LOGO}")
        return

    try:
        img = Image.open(SOURCE_LOGO)
        
        # Convertir a RGB por si acaso (evita errores con PNGs raros)
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGBA")
        else:
            img = img.convert("RGB")

        print(f"Imagen base cargada: {img.size}")

        for size in SIZES:
            # Redimensionar usando algoritmo de alta calidad (LANCZOS)
            # Usamos copy() para no afectar la imagen original en el loop
            resized_img = img.copy()
            resized_img.thumbnail(size, Image.Resampling.LANCZOS)
            
            # Crear un lienzo cuadrado transparente por si la imagen no es cuadrada
            final_icon = Image.new("RGBA", size, (255, 255, 255, 0))
            
            # Pegar la imagen redimensionada en el centro
            bg_w, bg_h = final_icon.size
            img_w, img_h = resized_img.size
            offset = ((bg_w - img_w) // 2, (bg_h - img_h) // 2)
            final_icon.paste(resized_img, offset)
            
            filename = f"icon-{size[0]}x{size[1]}.png"
            final_icon.save(os.path.join(OUTPUT_DIR, filename))
            print(f"Generado: {filename}")
            
    except Exception as e:
        print(f"Error procesando imagen: {e}")

if __name__ == "__main__":
    generate_icons()