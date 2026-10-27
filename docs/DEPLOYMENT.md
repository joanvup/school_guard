# Despliegue

Esta guía asume Linux, MySQL 8, Nginx y systemd. La aplicación corre con Uvicorn en `127.0.0.1:8001` y Nginx termina TLS.

## Arquitectura

```text
Navegador -> Nginx (TLS, :443) -> Uvicorn (127.0.0.1:8001) -> MySQL
                    |-> /static/ (assets públicos)
                    |-> /media/  (proxy: requiere sesión)
```

- `/static/` puede servirse desde disco. No contiene fotos de personas.
- `/media/` **debe** pasar por la aplicación: valida sesión y permisos.
- `/sw.js` se sirve desde la aplicación con `Service-Worker-Allowed: /`.
- `/healthz` consulta la base de datos y no requiere autenticación.

## Variables de entorno

Archivo recomendado: `/opt/school-guard/.env`, permisos `600`, propietario del usuario del servicio.

| Variable | Obligatoria | Uso |
|---|---|---|
| `APP_ENV=production` | Sí | Desactiva `/docs` y activa defaults de producción. |
| `DATABASE_URL` | Sí | `mysql+pymysql://usuario:clave@host:3306/base?charset=utf8mb4`. |
| `SECRET_KEY` | Sí | Firma JWT. Rotarla invalida todas las sesiones. |
| `QR_SECRET_KEY_CURRENT` | Sí | Firma de carnets vigente. |
| `QR_SECRET_KEY_PREVIOUS` | Durante rotación | Valida carnets impresos con la clave anterior. |
| `COOKIE_SECURE=true` | Sí con HTTPS | Cookie de sesión solo por TLS. |
| `BOOTSTRAP_ADMIN_PASSWORD` | Solo bootstrap | Se usa una vez con `init_db.py`. |
| `MEDIA_PHOTOS_DIR` | No | Default `app/data/photos`. Debe ser escribible por el servicio. |
| `LOG_LEVEL` | No | `INFO` por defecto. |
| `CSP_MODE` | No | `enforce`; usar `report-only` solo para diagnóstico. |
| `MAX_UPLOAD_MB`, `MAX_ZIP_*` | No | Límites de subidas; alinear con Nginx. |

No versionar `.env`. El repositorio aún lo contiene: su retiro, purga de historial y rotación real requieren coordinación (ver “Rotación de secretos”).

## Preparación del servidor

```bash
sudo useradd --system --home /opt/school-guard --shell /usr/sbin/nologin schoolguard
sudo mkdir -p /opt/school-guard /var/backups/school_guard
sudo chown -R schoolguard:schoolguard /opt/school-guard /var/backups/school_guard
```

Instalar el código, crear el entorno virtual e instalar dependencias:

```bash
cd /opt/school-guard
python3.11 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Crear `app/data/photos` con permisos `750` para el usuario del servicio. El backup debe cubrir la base de datos y `app/data/photos`.

## Migraciones

Antes de cada despliegue:

1. Ejecutar `scripts/backup_db.sh` y verificar el archivo.
2. Detener el servicio o entrar en ventana de mantenimiento.
3. `.venv/bin/alembic upgrade head`.
4. `.venv/bin/alembic check` (no debe detectar deriva).
5. Iniciar el servicio y ejecutar el smoke test.

El checklist completo previo a una ventana de mantenimiento está en [OPERATIONS.md](OPERATIONS.md#checklist-pre-ventana).

Si una migración falla, no continuar: restaurar el backup con `scripts/restore_db.sh` y volver al código anterior. Un `alembic downgrade` solo es aceptable si fue probado en staging.

## Servicio systemd

Copiar `deploy/school-guard.service` a `/etc/systemd/system/`, ajustar rutas y usuario, y activar:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now school-guard
sudo systemctl status school-guard
```

Logs:

```bash
sudo journalctl -u school-guard -f -o cat
```

## Nginx y TLS

Tomar `deploy/nginx.conf.example` como base. Puntos críticos:

- `proxy_set_header X-Forwarded-Proto $scheme;` para que la app detecte HTTPS y envíe HSTS.
- `proxy_set_header X-Request-ID $request_id;` para correlacionar logs.
- `client_max_body_size` mayor que `MAX_ZIP_TOTAL_MB` (por ejemplo `210m`).
- No servir `/media/` con `alias`; debe ir a la aplicación.
- Bloquear `/static/photos` explícitamente y no enlazar fotos dentro de `static`.
- TLS con Certbot/Let's Encrypt. La cámara requiere contexto seguro.

Verificación:

```bash
curl -fsS https://salidas.example.edu.co/healthz
curl -fsSI https://salidas.example.edu.co/sw.js
```

`/sw.js` debe devolver `Service-Worker-Allowed: /` y `Cache-Control: no-cache`.

## Smoke test posterior al despliegue

1. Login de administrador y de cada rol.
2. `/healthz` responde `200 {"status":"ok"}`.
3. Dashboard de salidas y de almuerzos cargan; “Cargar más” pagina.
4. Un escaneo de prueba registra salida o almuerzo y deja auditoría.
5. Exportar salidas y almuerzos genera un `.xlsx` válido.
6. El navegador no registra errores de CSP ni peticiones a dominios externos.
7. `/sw.js` se sirve desde la raíz y los iconos responden `200`.

## Rotación de secretos

Requiere ventana y coordinación explícita. Nunca ejecutar sobre producción sin backup.

1. **Contraseña de base de datos:** crear usuario/clave nuevos, actualizar `DATABASE_URL`, reiniciar y retirar el usuario anterior.
2. **`SECRET_KEY`:** generar una nueva, actualizar `.env`, reiniciar. Todas las sesiones se invalidan; los usuarios vuelven a iniciar sesión.
3. **Clave QR:** mover la actual a `QR_SECRET_KEY_PREVIOUS`, definir una nueva en `QR_SECRET_KEY_CURRENT`, reiniciar. Los carnets viejos siguen válidos mientras la anterior exista. Reimprimir carnets y retirar la clave anterior cuando termine la transición.
4. **`.env` e historial:** `git rm --cached .env`, agregar al `.gitignore`, purgar el historial con `git filter-repo` y force-push coordinado. La rotación de secretos es obligatoria aunque se purgue el historial.

No registrar claves en tickets, scripts, argumentos de línea de comandos ni historial del shell.
