import requests
import os

URL = "https://cdnjs.cloudflare.com/ajax/libs/qrcodejs/1.0.0/qrcode.min.js"
DEST = "app/static/js/qrcode.min.js"

if not os.path.exists("app/static/js"):
    os.makedirs("app/static/js")

print("Descargando qrcode.min.js...")
try:
    r = requests.get(URL)
    with open(DEST, 'wb') as f:
        f.write(r.content)
    print("¡Descarga exitosa!")
except Exception as e:
    print(f"Error: {e}")