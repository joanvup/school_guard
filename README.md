# School Guard

Aplicación web para controlar salidas peatonales y entregas de almuerzo en una institución educativa. Registra cada intento con firma QR, operador, puerta y trazabilidad, y expone tableros y reportes para portería, comedor y administración.

## Stack

- Python 3.11, FastAPI, SQLAlchemy 2 con sesiones síncronas, Alembic.
- MySQL 8 en producción; SQLite en pruebas unitarias.
- Jinja2 y JavaScript sin framework; CSS compilado localmente.
- PWA instalable con service worker que solo cachea estáticos.
- Sesiones JWT en cookie `HttpOnly`, CSRF de doble envío, roles y auditoría.

## Módulos

- **Salidas:** escaneo de carnet QR, validación de autorización, cooldown, historial con snapshots y reportes por fecha/puerta.
- **Almuerzos:** identificación por QR, RFID o búsqueda manual, un registro por persona y día, ticket térmico reimprimible y reportes.
- **Administración:** estudiantes, empleados, puertas, usuarios, carnets PDF, importaciones Excel/ZIP y fotos privadas.

## Requisitos

- Python 3.11 o superior.
- MySQL 8 (producción o pruebas de integración).
- HTTPS en producción: la cámara del navegador y la cookie `Secure` lo requieren.

## Instalación local

```bash
git clone https://github.com/joanvup/school_guard.git
cd school_guard
python -m venv .venv
```

Windows:

```bash
.venv\Scripts\activate
```

Linux/macOS:

```bash
source .venv/bin/activate
```

Instalar dependencias:

```bash
pip install -r requirements.txt -r requirements-dev.txt
```

Crear `.env` a partir de la plantilla y completar los valores:

```bash
cp .env.template .env
```

Variables obligatorias:

- `DATABASE_URL`: cadena de conexión MySQL.
- `SECRET_KEY`: clave de firma JWT, larga y aleatoria.
- `QR_SECRET_KEY_CURRENT`: clave HMAC de los carnets.
- `BOOTSTRAP_ADMIN_PASSWORD`: solo para crear el administrador inicial (mínimo 12 caracteres).

Aplicar migraciones y crear el administrador:

```bash
alembic upgrade head
python init_db.py
```

El bootstrap no usa contraseñas por defecto: si `BOOTSTRAP_ADMIN_PASSWORD` no está definida o es débil, falla.

Los iconos PWA ya están versionados. Solo es necesario regenerarlos si cambia el logo:

```bash
python scripts/generate_icons.py
```

Ejecutar en desarrollo:

```bash
uvicorn app.main:app --reload
```

La documentación interactiva de FastAPI queda en `/docs` fuera de producción.

## Roles

| Rol | Acceso |
|---|---|
| `ADMIN` | Administración completa, reportes de salidas y comedor. |
| `OPERATOR` | Portería, escaneo de salidas y sus reportes. |
| `LUNCH_OP` | Comedor, escaneo de almuerzos, tickets y sus reportes. |

Un usuario inactivo no puede iniciar sesión ni conservar una sesión válida. Cambiar contraseña o rol incrementa `token_version` e invalida tokens previos.

## Pruebas y calidad

```bash
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe -m ruff check .
.venv/Scripts/python.exe -m ruff format --check .
```

Los tests unitarios usan SQLite. Los marcados como `mysql` validan constraints y concurrencia contra MySQL 8 y se ejecutan en CI con `MYSQL_TEST_URL`; en local se omiten si no hay una base disponible.

Migraciones:

```bash
alembic upgrade head
alembic check
```

## Estructura

```text
school_guard/
├── alembic/                 # Migraciones
├── app/
│   ├── routers/             # Endpoints HTTP
│   ├── services/            # Lógica de salidas, almuerzos y auditoría
│   ├── utils/               # Fechas, medios, Excel y saneamiento de datos
│   ├── templates/           # Vistas Jinja2
│   ├── static/              # CSS, JS, iconos y assets locales
│   ├── data/photos/         # Fotos privadas de estudiantes y empleados
│   ├── config.py            # Configuración validada al arranque
│   ├── observability.py     # request_id, logs JSON y errores controlados
│   └── main.py              # Punto de entrada
├── deploy/                  # Ejemplos de Nginx y systemd
├── docs/                    # Despliegue y operación
├── scripts/                 # Iconos, backup y restore
├── tests/
└── requirements.txt
```

## Seguridad y privacidad

- Los QR se validan con HMAC-SHA256. Se aceptan carnets v1 durante la transición y v2 para nuevas impresiones.
- Las fotos no se sirven desde `/static`; se entregan autenticadas en `/media/photos/...` con `Cache-Control: private, no-store`.
- Las mutaciones requieren CSRF y método POST.
- Los formularios y tableros usan `textContent`/DOM para evitar XSS.
- Cada rechazo, duplicado y reintento deja rastro en `audit_logs` o `scan_attempts`.
- Las exportaciones Excel neutralizan fórmulas y usan memoria acotada.
- El escaneo es **online**: el service worker solo cachea estáticos y no promete operación offline.

## Despliegue y operación

- [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md): Nginx, systemd, migraciones, TLS y rotación de secretos.
- [docs/OPERATIONS.md](docs/OPERATIONS.md): salud, logs por `request_id`, backup/restore, tickets e incidentes.

## Pendientes de coordinación

- El repositorio aún versiona `.env`: retirarlo del índice, purgar el historial y rotar secretos reales requiere force-push coordinado y ventana de mantenimiento.
- Las migraciones y cambios de infraestructura en producción se ejecutan con backup previo y ventana acordada.

## Licencia

Propiedad de **Fundación Colegio Bilingüe**. Uso interno institucional; prohibida su distribución o comercialización sin autorización expresa.
