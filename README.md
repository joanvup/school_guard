<div align="center">
  <img src="app/static/assets/logo.png" alt="School Guard Logo" width="160">
  <h1>School Guard 🛡️</h1>
  <p>
    <strong>Sistema Integral de Control de Salidas Peatonales Escolares</strong>
  </p>
  <p>
    <a href="https://fastapi.tiangolo.com/">
        <img src="https://img.shields.io/badge/FastAPI-005571?style=for-the-badge&logo=fastapi" alt="FastAPI">
    </a>
    <a href="https://www.python.org/">
        <img src="https://img.shields.io/badge/Python-3.10+-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python">
    </a>
    <a href="https://tailwindcss.com/">
        <img src="https://img.shields.io/badge/Tailwind_CSS-38B2AC?style=for-the-badge&logo=tailwind-css&logoColor=white" alt="Tailwind">
    </a>
    <a href="https://www.mysql.com/">
        <img src="https://img.shields.io/badge/MySQL-000000?style=for-the-badge&logo=mysql&logoColor=white" alt="MySQL">
    </a>
  </p>
</div>

---

## 📖 Descripción

**School Guard** es una Aplicación Web Progresiva (PWA) diseñada para gestionar, controlar y auditar la salida de estudiantes en instituciones educativas. 

El sistema reemplaza los listados en papel por un escáner QR digital seguro, capaz de validar en tiempo real si un estudiante está autorizado para retirarse, registrando la hora exacta, la puerta de salida y el operador responsable. Cuenta con medidas de seguridad criptográfica para evitar la falsificación de carnets.

## ✨ Características Principales

### 📱 Operación y Seguridad
*   **Escáner QR Web/Móvil:** Uso de la cámara del dispositivo para lectura rápida.
*   **Validación Criptográfica (HMAC):** Los códigos QR están firmados digitalmente para evitar falsificaciones o generación de códigos por terceros.
*   **Anti-Passback (Cooldown):** Bloqueo temporal para evitar que un mismo carnet sea escaneado dos veces consecutivas en un periodo corto.
*   **PWA Instalable:** Funciona como app nativa en Android/iOS (Icono en escritorio, pantalla completa).

### 🏫 Gestión Administrativa
*   **Dashboard en Tiempo Real:** Gráficas de salidas por curso, hora pico y estadísticas por puerta.
*   **Gestión de Estudiantes:** CRUD completo con fotos.
*   **Carga Masiva:** Importación de estudiantes desde Excel y fotos desde archivos ZIP.
*   **Generador de Carnets:** Motor PDF integrado para generar carnets listos para imprimir (5.4x8.5cm) y descarga de QRs.

### 👥 Roles y Accesos
*   **Administrador:** Acceso total al sistema, gestión de usuarios y configuraciones.
*   **Operador (Vigilante):** Acceso restringido únicamente al escáner y dashboard básico.

---

## 🛠️ Estructura del Proyecto

El proyecto sigue una arquitectura modular basada en FastAPI:

```text
school_guard/
├── app/
│   ├── routers/       # Endpoints de la API (Auth, Dashboard, Scan, etc.)
│   ├── static/        # Assets (CSS compilado, JS local, Fotos, Iconos)
│   ├── templates/     # Vistas HTML (Jinja2)
│   ├── auth.py        # Lógica de JWT y Firmas HMAC
│   ├── database.py    # Conexión MySQL (SQLAlchemy)
│   ├── models.py      # Modelos de Base de Datos
│   └── main.py        # Punto de entrada
├── .env               # Variables de entorno (NO SUBIR AL REPO)
├── requirements.txt   # Dependencias Python
└── README.md          # Documentación

```

## 🚀 Instalación y Despliegue

### Prerrequisitos
*   Python 3.10 o superior.
*   MySQL Server.
*   Entorno Linux (Recomendado para producción) o Windows.

### 1. Clonar el repositorio
```bash
git clone https://github.com/joanvup/school_guard.git
cd school_guard
```
### 2. Configurar Entorno Virtual
```bash
python -m venv venv
```

# Windows
```bash
.\venv\Scripts\activate
```
# Linux/Mac
```bash
source venv/bin/activate
```

### 3. Instalar Dependencias
```bash
pip install -r requirements.txt
```

### 4. Configuración (.env)
Crea un archivo .env en la raíz del proyecto con las siguientes variables:

```ini
# Base de Datos
DATABASE_URL=mysql+pymysql://usuario:password@localhost:3306/nombre_db

# Seguridad (JWT) - Generar clave segura
SECRET_KEY=tu_clave_super_secreta_para_jwt
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=120

# Seguridad (Firma QR) - CRÍTICO: Si cambia, los carnets impresos dejan de funcionar
QR_SECRET_KEY=clave_secreta_para_firmar_qrs_no_cambiar
```
### 5. Preparación de Assets
El proyecto está configurado para no depender de CDNs externos en producción.
## Descargar librerías JS (Chart.js, HTML5-QR)
```bash
python download_libs.py
```
## Generar iconos de la App (PWA) basados en el logo
```bash
python generate_icons.py
```
### 6. Inicializar Base de Datos
Este script crea las tablas y el usuario administrador por defecto.
```bash
python init_db.py
```

Credenciales por defecto:
User: admin
Pass: admin123

### 7. Ejecutar (Modo Desarrollo)
```bash
uvicorn app.main:app --reload
```

## 🌐 Despliegue en Producción (Ubuntu + Nginx)

Para un entorno productivo robusto se recomienda usar **Gunicorn** detrás de un proxy inverso **Nginx**.

### 1. Configurar Servicio (Systemd)
Crear un servicio para mantener la app corriendo en el puerto 8001.

### 2. Configuración de Nginx
Bloque de servidor recomendado para manejar estáticos y proxy reverso:

```nginx
server {
    listen 80;
    server_name salidas.tucuelegio.edu.co;

    # Aumentar límite para subida de fotos/zip
    client_max_body_size 50M;

    location / {
        proxy_pass http://127.0.0.1:8001;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }

    # Servir archivos estáticos directamente (Optimización)
    location /static/ {
        alias /var/www/school-guard/app/static/;
        expires 30d;
    }
}
```
### 3. Certificado SSL (HTTPS)
⚠️ Importante: Es obligatorio configurar HTTPS (usando Certbot/Let's Encrypt) para que los navegadores móviles permitan el acceso a la cámara para escanear los códigos QR.

---

### Parte 3: Seguridad y Licencia

## 🔒 Seguridad del Código QR

Para prevenir vulnerabilidades donde un estudiante genera un código QR falso usando solo su número de identificación, el sistema implementa **HMAC-SHA256**.

1.  **Generación:** Al crear el carnet, se genera un string compuesto: `ID_ESTUDIANTE` + `.` + `FIRMA`.
2.  **Firma:** La firma se calcula criptográficamente usando la variable `QR_SECRET_KEY` (solo conocida por el servidor).
3.  **Verificación:** Al escanear, el servidor recalcula la firma del ID recibido. Si no coincide con la firma del QR, el acceso es denegado inmediatamente como **"Falsificado"**.

Esto garantiza que solo los códigos QR generados legítimamente por la plataforma sean válidos.

---

## 📄 Licencia

Propiedad de **Fundación Colegio Bilingüe**.
Desarrollado para uso interno institucional. Prohibida su distribución o comercialización sin autorización expresa.