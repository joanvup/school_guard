# Runbook: actualizar School Guard en producción

Actualización de una instalación existente en `192.168.3.5`. **No es un despliegue inicial**: no crear usuarios del sistema, venv, base de datos ni administrador. El servicio y la base ya existen.

- Código: clon Git en `/var/www/school_guard`.
- Servicio: `schoolguard.service` (systemd), Uvicorn en `127.0.0.1:8001`, Nginx con TLS y DNS interno.
- Base: MySQL 8 con Alembic. Migraciones posibles: `0002_security_and_audit` y `0003_photo_paths`.
- Los carnets v1 ya impresos siguen válidos: no se rota `QR_SECRET_KEY_CURRENT`.
- Fuera de alcance: rotación de secretos, edición/untracking de `.env`, purga de historial, cambios de Nginx/TLS y reimpresión masiva v2.

## 0. Descubrir la instalación real (solo lectura)

```bash
UNIT=schoolguard.service
APP_DIR=/var/www/school_guard
BACKUP_DIR=/var/backups/school_guard
MYSQL_CNF=/etc/school-guard/mysql-backup.cnf

sudo systemctl cat "$UNIT"
APP_USER=$(sudo systemctl cat "$UNIT" | grep '^User=' | cut -d= -f2)
APP_USER=${APP_USER:-schoolguard}
EXEC_LINE=$(sudo systemctl cat "$UNIT" | grep '^ExecStart=' | cut -d= -f2-)
VENV=$(printf '%s' "$EXEC_LINE" | grep -oE '/[^ ]*\.venv' | head -1)
VENV=${VENV:-$APP_DIR/.venv}
APP_PORT=$(printf '%s' "$EXEC_LINE" | grep -oE -- '--port [0-9]+' | awk '{print $2}')
APP_PORT=${APP_PORT:-8001}
echo "user=$APP_USER venv=$VENV port=$APP_PORT"
```

Si la unidad no existe o `$APP_DIR` no es el `WorkingDirectory`, usar los valores reales y no continuar con los de ejemplo.

Identificar el vhost correcto entre las aplicaciones del servidor:

```bash
sudo nginx -T 2>/dev/null | grep -B5 -A30 "127.0.0.1:$APP_PORT" | grep -E 'server_name|proxy_pass' | head -20
DOMAIN=<dominio-interno>   # elegir el server_name del vhost que apunta a APP_PORT
```

```bash
sudo systemctl status "$UNIT" --no-pager | head -15
curl -fsS "http://127.0.0.1:$APP_PORT/healthz"; echo
sudo ss -ltnp | grep -E ":$APP_PORT\b"
sudo ss -ltnp | grep -E ':(80|443|3306)\b'
df -h "$APP_DIR" /var/backups
free -m
sudo -u "$APP_USER" test -r "$APP_DIR/.env" && echo ".env legible por $APP_USER"
```

Git, SHA objetivo y revisión Alembic:

```bash
cd "$APP_DIR"
sudo -u "$APP_USER" git fetch origin
sudo -u "$APP_USER" git log -1 --oneline origin/main
TARGET=$(sudo -u "$APP_USER" git rev-parse origin/main)
echo "TARGET=$TARGET"
sudo -u "$APP_USER" git rev-parse HEAD
sudo -u "$APP_USER" git status --short
sudo -u "$APP_USER" git ls-files --error-unmatch .env && echo "AVISO: .env versionado"
sudo -u "$APP_USER" git cat-file -t "$TARGET"
sudo -u "$APP_USER" "$VENV/bin/alembic" current
sudo -u "$APP_USER" "$VENV/bin/alembic" heads
```

Fijar `TARGET` al SHA de `origin/main` que se va a desplegar y confirmar CI verde. Si `main` avanzó después de este documento, revisar el diff antes de usarlo. No usar `git clean`, `git reset --hard` ni descartar cambios.

Estado real de la base sin imprimir credenciales:

```bash
sudo -u "$APP_USER" env PYTHONPATH="$APP_DIR" "$VENV/bin/python" - <<'PY'
from sqlalchemy import text
from app.database import SessionLocal

with SessionLocal() as db:
    try:
        rev = db.execute(text("SELECT version_num FROM alembic_version")).scalar()
    except Exception:
        db.rollback()
        rev = None
    print("alembic_version:", rev or "SIN VERSION (detenerse y revisar)")
    print("role:", db.execute(text("""
        SELECT COLUMN_TYPE FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'users' AND COLUMN_NAME = 'role'
    """)).scalar())
    for table in ("users", "students", "employees", "doors", "exit_logs", "lunch_logs"):
        print(f"{table}:", db.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar())
    dup = db.execute(text("""
        SELECT 'student' AS tipo, student_id AS persona, DATE(timestamp) AS dia, COUNT(*) AS total
        FROM lunch_logs WHERE student_id IS NOT NULL
        GROUP BY student_id, DATE(timestamp) HAVING COUNT(*) > 1
        UNION ALL
        SELECT 'employee', employee_id, DATE(timestamp), COUNT(*)
        FROM lunch_logs WHERE employee_id IS NOT NULL
        GROUP BY employee_id, DATE(timestamp) HAVING COUNT(*) > 1
    """)).fetchall()
    print("duplicados_almuerzo:", dup)
    print("max_connections:", db.execute(text("SHOW VARIABLES LIKE 'max_connections'")).fetchone()[1])
    print("threads_connected:", db.execute(text("SHOW STATUS LIKE 'Threads_connected'")).fetchone()[1])
PY
```

Guardar salidas (SHA, revisión, conteos, enum, duplicados) como evidencia.

## 1. Go / No-Go

Continuar solo si todo está verde:

- Servicio activo y `/healthz` responde `200 {"status":"ok"}`.
- `git status` limpio salvo `.env`; cualquier otro archivo modificado detiene el despliegue.
- `$TARGET` existe en el servidor y su CI está verde.
- `alembic heads` muestra una sola cabeza (`0003_photo_paths`).
- `alembic_version` es `0001_baseline`, `0002_security_and_audit` o `0003_photo_paths`.
  - `0003`: no hay migración pendiente.
  - `0001`/`0002`: habrá migración; backup y comprobaciones son obligatorios.
  - Sin fila/versión y con tablas existentes: detenerse. Solo tras verificar que el esquema coincide con `0001` se podrá `alembic stamp 0001_baseline` con aprobación explícita y backup fresco.
- `users.role` es `enum('ADMIN','OPERATOR','LUNCH_OP')`; cualquier otra cosa detiene el despliegue.
- No hay duplicados de almuerzo. Si hay filas: exportar evidencia y detenerse para archivarlas con aprobación; no borrar automáticamente.
- `/var` con al menos 2× el tamaño de la BD + 1 GB libre; `/var/backups` escribible.
- Puerto `$APP_PORT` ocupado solo por School Guard; el vhost de `$DOMAIN` apunta a ese puerto; HTTPS y `/sw.js` funcionan.
- `mysqldump`, `gzip`, `tar` y `curl` disponibles; personal avisado y actividad baja.

## 2. Backup verificado

Crear credenciales solo si no existen (no imprime la contraseña):

```bash
sudo install -d -m 700 -o root -g root /etc/school-guard
if [ ! -r "$MYSQL_CNF" ]; then
  sudo env APP_DIR="$APP_DIR" "$VENV/bin/python" - <<'PY'
import os
from pathlib import Path
from urllib.parse import unquote, urlsplit

raw = Path(os.environ["APP_DIR"], ".env").read_text(encoding="utf-8")
line = next(l for l in raw.splitlines() if l.startswith("DATABASE_URL="))
url = urlsplit(line.split("=", 1)[1].strip())
cnf = Path("/etc/school-guard/mysql-backup.cnf")
cnf.write_text(
    "[client]\n"
    f"user={unquote(url.username or '')}\n"
    f"password={unquote(url.password or '')}\n"
    f"host={url.hostname or '127.0.0.1'}\n"
    f"port={url.port or 3306}\n",
    encoding="utf-8",
)
cnf.chmod(0o600)
print(f"DB_USER={unquote(url.username or '')}")
print(f"DB_NAME={url.path.lstrip('/')}")
print(f"DB_HOST={url.hostname or '127.0.0.1'}")
print(f"DB_PORT={url.port or 3306}")
PY
fi
```

Exportar los cuatro valores mostrados y respaldar configuración, base y fotos:

```bash
export DB_NAME=<valor> DB_USER=<valor> DB_HOST=<valor> DB_PORT=<valor>
export MYSQL_CONFIG="$MYSQL_CNF" BACKUP_DIR=/var/backups/school_guard

ENV_SHA=$(sudo sha256sum "$APP_DIR/.env" | awk '{print $1}')
sudo cp -p "$APP_DIR/.env" "$BACKUP_DIR/env_$(date +%F_%H%M).bak"
sudo chmod 600 "$BACKUP_DIR"/env_*.bak

sudo env DB_NAME="$DB_NAME" DB_USER="$DB_USER" DB_HOST="$DB_HOST" DB_PORT="$DB_PORT" \
  MYSQL_CONFIG="$MYSQL_CNF" BACKUP_DIR="$BACKUP_DIR" "$APP_DIR/scripts/backup_db.sh"

DUMP=$(ls -t "$BACKUP_DIR/${DB_NAME}"_*.sql.gz | head -1)
gzip -t "$DUMP" && zcat "$DUMP" | tail -2   # debe incluir "-- Dump completed"

PHOTOS_DIR=$(sudo grep -E '^MEDIA_PHOTOS_DIR=' "$APP_DIR/.env" | cut -d= -f2-)
PHOTOS_DIR=${PHOTOS_DIR:-app/data/photos}
case "$PHOTOS_DIR" in /*) : ;; *) PHOTOS_DIR="$APP_DIR/$PHOTOS_DIR" ;; esac
PHOTOS_TGZ="$BACKUP_DIR/photos_$(date +%F_%H%M).tgz"
sudo tar -C / -czf "$PHOTOS_TGZ" "${PHOTOS_DIR#/}"
echo "fotos en backup: $(sudo tar -tzf "$PHOTOS_TGZ" | wc -l)"
echo "fotos en disco:  $(sudo find "$PHOTOS_DIR" -type f | wc -l)"
```

Copiar `$DUMP`, `$PHOTOS_TGZ` y el backup de `.env` fuera del servidor.

Restore verificado: crear una base temporal, importar el dump y comparar conteos. Si el usuario de backup no puede crear bases, pedir al DBA que lo haga. No continuar sin una restauración verificada (de esta ventana o de las últimas 24 h).

```bash
SCRATCH=${DB_NAME}_restore_check
mysql --defaults-extra-file="$MYSQL_CNF" -e "CREATE DATABASE $SCRATCH CHARACTER SET utf8mb4"
gzip -dc "$DUMP" | mysql --defaults-extra-file="$MYSQL_CNF" "$SCRATCH"
mysql --defaults-extra-file="$MYSQL_CNF" -e "SELECT COUNT(*) FROM $SCRATCH.users; SELECT COUNT(*) FROM $SCRATCH.lunch_logs;"
mysql --defaults-extra-file="$MYSQL_CNF" -e "DROP DATABASE $SCRATCH"
```

## 3. Proteger `.env` y revisar el diff

```bash
cd "$APP_DIR"
OLD=$(sudo -u "$APP_USER" git rev-parse HEAD)
sudo -u "$APP_USER" git diff --stat "$OLD" "$TARGET"
sudo -u "$APP_USER" git diff "$OLD" "$TARGET" -- .env.template app/config.py requirements.txt requirements-dev.txt
```

Si el diff exige variables nuevas ausentes en `.env`, detenerse y consultar: no se edita `.env` en esta ventana.

`.env` está versionado; impedir que el checkout lo sobrescriba:

```bash
TRACKED=no
sudo -u "$APP_USER" git ls-files --error-unmatch .env >/dev/null 2>&1 && TRACKED=yes
if [ "$TRACKED" = yes ]; then
  sudo -u "$APP_USER" git update-index --skip-worktree .env
fi
```

## 4. Ventana de actualización

```bash
sudo systemctl stop "$UNIT"
```

Si el servicio no queda inactivo, no continuar.

```bash
sudo -u "$APP_USER" git checkout --detach "$TARGET"
if [ "$TRACKED" = yes ]; then
  sudo -u "$APP_USER" git update-index --no-skip-worktree .env
fi
sudo -u "$APP_USER" git rev-parse HEAD          # debe ser $TARGET
NEW_ENV_SHA=$(sudo sha256sum "$APP_DIR/.env" | awk '{print $1}')
[ "$NEW_ENV_SHA" = "$ENV_SHA" ] || {
  echo "ABORTAR: .env cambió durante el checkout";
  sudo cp -p "$(ls -t "$BACKUP_DIR"/env_*.bak | head -1)" "$APP_DIR/.env";
  sudo chown "$APP_USER:$APP_USER" "$APP_DIR/.env";
}
```

Dependencias (no hay build de frontend):

```bash
sudo -u "$APP_USER" "$VENV/bin/pip" install -r "$APP_DIR/requirements.txt"
sudo -u "$APP_USER" "$VENV/bin/pip" check
```

Migración:

```bash
cd "$APP_DIR"
# Solo si el paso 1 confirmó que no existía alembic_version y el esquema coincide con 0001:
# sudo -u "$APP_USER" "$VENV/bin/alembic" stamp 0001_baseline
sudo -u "$APP_USER" "$VENV/bin/alembic" upgrade head
sudo -u "$APP_USER" "$VENV/bin/alembic" current   # 0003_photo_paths (head)
sudo -u "$APP_USER" "$VENV/bin/alembic" check     # sin deriva
```

Arranque y primeras señales:

```bash
sudo systemctl start "$UNIT"
sleep 2
sudo systemctl status "$UNIT" --no-pager | head -15
curl -fsS "http://127.0.0.1:$APP_PORT/healthz"; echo
sudo journalctl -u "$UNIT" --since '-5 min' -o cat | tail -40
```

Si `/healthz` no devuelve 200, el servicio reinicia en bucle o hay errores en logs: ir a Rollback.

## 5. Verificación y smoke

Infraestructura:

```bash
curl -fsSI "https://$DOMAIN/healthz"
curl -fsSI "https://$DOMAIN/sw.js" | grep -Ei 'service-worker-allowed|cache-control'
cd "$APP_DIR" && sudo -u "$APP_USER" "$VENV/bin/alembic" current
```

Navegador y funcional (portería y comedor):

- Login de `admin`, operador de portería y operador de comedor.
- Escaneo real con carnet v1 y v2: salida registrada, `exit_logs`/`scan_attempts` con `success` y auditoría.
- Segundo escaneo dentro del cooldown: `409`, aviso y `scan_attempts.result="duplicate"`.
- QR falsificado: `403`, `scan_attempts.result="invalid_signature"`.
- Almuerzo: ticket impreso y reimpresión desde reportes (`printed_count` incrementa; la ventana emergente no bloquea la pestaña).
- Exportaciones XLSX de salidas y almuerzos; paginación de reportes y dashboards.
- Fotos en `/media/` cargan; `/static/photos` responde 404.
- PWA: `/sw.js` con scope raíz, iconos 200, sin errores CSP ni peticiones externas.
- Cámara y lector RFID probados en los equipos reales (HTTPS).
- Conteos posteriores: `exit_logs` y `lunch_logs` mayores o iguales al baseline; duplicados en cero.

## 6. Rollback

Criterio: falla un flujo crítico (login, salida, almuerzo, impresión) o `/healthz` no se recupera. Restaurar backup y volver al código anterior; no usar `alembic downgrade` (0002 elimina auditoría y columnas).

```bash
sudo systemctl stop "$UNIT"
sudo env CONFIRM_RESTORE=YES DB_NAME="$DB_NAME" DB_USER="$DB_USER" DB_HOST="$DB_HOST" \
  DB_PORT="$DB_PORT" MYSQL_CONFIG="$MYSQL_CNF" "$APP_DIR/scripts/restore_db.sh" "$DUMP"

# Solo si se detectó corrupción de fotos:
sudo tar -C / -xzf "$PHOTOS_TGZ"

# Si .env cambió:
sudo cp -p "$(ls -t "$BACKUP_DIR"/env_*.bak | head -1)" "$APP_DIR/.env"
sudo chown "$APP_USER:$APP_USER" "$APP_DIR/.env"

sudo -u "$APP_USER" git checkout --detach "$OLD"
sudo -u "$APP_USER" "$VENV/bin/pip" install -r "$APP_DIR/requirements.txt"
sudo systemctl start "$UNIT"
curl -fsS "http://127.0.0.1:$APP_PORT/healthz"
```

Si el restore falla, mantener el servicio detenido y escalar; no arrancar código nuevo contra una base a medio restaurar. El restore descarta las filas creadas después del backup (incluido el smoke).

## 7. Cierre y evidencia

- Registrar en los issues #1/#2: SHA anterior y nuevo, nombre/hora de `$DUMP`, `$PHOTOS_TGZ` y backup de `.env`, revisión Alembic final, enum, duplicados, conteos antes/después y resultado del smoke.
- Confirmar copia de backups fuera del servidor y retención de 14 días.
- Avisar reapertura y monitorear 24 h (`journalctl`, `/healthz`, 5xx).
- Fuera de esta ventana: rotación de secretos, `.env` untracking/purga, reimpresión masiva v2 y retiro de `QR_SECRET_KEY_PREVIOUS` (~30 días).

## Riesgos de convivencia con otras apps

- Colisión de `$APP_PORT`: el paso 0 lo detecta; usar el puerto del unit, no el de la documentación antigua.
- RAM/CPU: 4 workers de Uvicorn comparten host; revisar `free -m` antes y después.
- MySQL compartido: vigilar `Threads_connected`/`max_connections`; 4 workers pueden abrir hasta ~60 conexiones en pico.
- Nginx compartido: no se recarga ni se edita; si hubiera que hacerlo, `nginx -t` antes de `reload`.
- Migración con locks: 0002 altera tablas; ejecutar con actividad baja y vigilar `SHOW PROCESSLIST`.
- `.env` versionado: `skip-worktree` y comparación de hash evitan pisar la configuración de producción.
- Propietario del repo/venv: ejecutar Git y pip como el usuario del servicio para no dejar archivos de root.
