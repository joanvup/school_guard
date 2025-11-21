import os
import requests

# Configuración
LIBS = {
    "chart.min.js": "https://cdn.jsdelivr.net/npm/chart.js",
    "html5-qrcode.min.js": "https://unpkg.com/html5-qrcode/html5-qrcode.min.js"
}
OUTPUT_JS = "app/static/js"

if not os.path.exists(OUTPUT_JS):
    os.makedirs(OUTPUT_JS)

print("Descargando librerías...")

for filename, url in LIBS.items():
    print(f" - Descargando {filename}...")
    try:
        r = requests.get(url)
        if r.status_code == 200:
            with open(os.path.join(OUTPUT_JS, filename), 'wb') as f:
                f.write(r.content)
            print("   OK.")
        else:
            print(f"   ERROR: {r.status_code}")
    except Exception as e:
        print(f"   Error de conexión: {e}")

print("Descarga de JS completada.")