# Runbook: actualizar School Guard en producción

Actualización de una instalación existente en `192.168.3.5`. **No es un despliegue inicial**: no crear usuarios del sistema, venv, base de datos ni administrador. El servicio y la base ya existen.

- Código: clon Git en `/var/www/school_guard`.
- Servicio: `schoolguard.service` (systemd), usuario `www-data`, Gunicorn con `UvicornWorker` en `127.0.0.1:8001`, 4 workers.
- Entorno virtual: `/var/www/school_guard/venv` (no `.venv`).
- Base: MySQL 8 con Alembic. Migraciones posibles: `0002_security_and_audit` y `0003_photo_paths`.
- Los carnets v1 ya impresos siguen válidos: no se rota `QR_SECRET_KEY_CURRENT`.
- Fuera de alcance: rotación de secretos, edición/untracking de `.env`, purga de historial, cambios de Nginx/TLS y reimpresión masiva v2.

## Estado observado (2026-10-27)

- Servicio activo desde el 2026-10-25, 4 workers de Gunicorn, ~469 MB de RAM; servidor con 7.8 GB de RAM y 58 GB libres.
- `/healthz` responde **404**: la versión desplegada es anterior a la ruta de salud. El baseline previo al despliegue se toma con `/login`.
- El repo pertenece al usuario de despliegue (no a `www-data`): ejecutar Git como el dueño, no con `sudo -u www-data`.
- MySQL escucha en `3306` y Nginx en `80/443`.
- `BACKUP_DIR=/home/joanvup/backups/school_guard` y `MYSQL_CNF=/home/joanvup/school-guard/mysql-backup.cnf`.

## 0. Descubrir la instalación real (solo lectura)

```bash
UNIT=schoolguard.service
APP_DIR=/var/www/school_guard
BACKUP_DIR=/home/joanvup/backups/school_guard
MYSQL_CNF=/home/joanvup/school-guard/mysql-backup.cnf

sudo systemctl cat "$UNIT"
APP_USER=$(sudo systemctl cat "$UNIT" | grep '^User=' | cut -d= -f2)
APP_USER=${APP_USER:-www-data}
EXEC_LINE=$(sudo systemctl cat "$UNIT" | grep '^ExecStart=' | cut -d= -f2-)
VENV=$(printf '%s' "$EXEC_LINE" | awk '{print $1}' | sed 's#/bin/.*##')
VENV=${VENV:-$APP_DIR/venv}
APP_PORT=$(printf '%s' "$EXEC_LINE" | grep -oE '(-b|--bind) [^ ]+:[0-9]+' | grep -oE '[0-9]+$')
APP_PORT=${APP_PORT:-8001}
REPO_OWNER=$(stat -c '%U' "$APP_DIR/.git")
VENV_OWNER=$(stat -c '%U' "$VENV")
DOMAIN=salidas.colegiobilingue.edu.co   # confirmar en la salida de Nginx
echo "user=$APP_USER venv=$VENV port=$APP_PORT repo_owner=$REPO_OWNER venv_owner=$VENV_OWNER"
```

Si la unidad no existe o `$APP_DIR` no es el `WorkingDirectory`, usar los valores reales y no continuar con los de ejemplo. Git debe ejecutarse como `$REPO_OWNER` (normalmente el usuario de despliegue); `sudo -u www-data git` falla por `dubious ownership`.

Identificar el vhost correcto entre las aplicaciones del servidor:

```bash
sudo nginx -T 2>/dev/null | grep -nE 'server_name|proxy_pass http://127.0.0.1:8001' | head -40
# Confirmar DOMAIN con el server_name del bloque que proxifica a 8001.
```

```bash
sudo systemctl status "$UNIT" --no-pager | head -15
curl -sS -o /dev/null -w 'healthz=%{http_code}\n' "http://127.0.0.1:$APP_PORT/healthz"
curl -sS -o /dev/null -w 'login=%{http_code}\n' "http://127.0.0.1:$APP_PORT/login"
sudo ss -ltnp | grep -E ":$APP_PORT\b"
sudo ss -ltnp | grep -E ':(80|443|3306)\b'
df -h "$APP_DIR" "$BACKUP_DIR"
free -m
stat -c '%U:%G %a %n' "$APP_DIR" "$APP_DIR/.git" "$VENV" "$APP_DIR/.env"
sudo -u "$APP_USER" test -r "$APP_DIR/.env" && echo ".env legible por $APP_USER"
sudo -u "$APP_USER" test -w "$APP_DIR/app/data" && echo "app/data escribible por $APP_USER"
```

`healthz=404` es esperado antes de esta actualización; `login` debe responder `200` o `303`. Tras desplegar, `/healthz` debe responder `200`.

Git, SHA objetivo y revisión Alembic:

```bash
cd "$APP_DIR"
git fetch origin
git log -1 --oneline origin/main
TARGET=$(git rev-parse origin/main)
echo "TARGET=$TARGET"
git rev-parse HEAD
git status --short
git ls-files --error-unmatch .env && echo "AVISO: .env versionado"
git cat-file -t "$TARGET"
if [ -x "$VENV/bin/alembic" ]; then
  sudo -u "$VENV_OWNER" "$VENV/bin/alembic" current
  sudo -u "$VENV_OWNER" "$VENV/bin/alembic" heads
else
  echo "alembic aún no está instalado en el venv; se instalará con requirements"
fi
```

Si aparece `dubious ownership`, ejecutar Git como `$REPO_OWNER` o usar `git -c safe.directory="$APP_DIR"`; no ejecutarlo como `www-data`. Fijar `TARGET` al SHA de `origin/main` que se va a desplegar y confirmar CI verde. Si `main` avanzó después de este documento, revisar el diff antes de usarlo. No usar `git clean`, `git reset --hard` ni descartar cambios.

Estado real de la base sin imprimir credenciales:

```bash
sudo -u "$APP_USER" env PYTHONPATH="$APP_DIR" "$VENV/bin/python" - <<'PY'
from sqlalchemy import text
from app.database import SessionLocal

with SessionLocal() as db:
    tables = db.execute(text(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = DATABASE() ORDER BY table_name"
    )).scalars().all()
    print("tablas:", ", ".join(tables))
    if "alembic_version" in tables:
        print("alembic_version:", db.execute(text("SELECT version_num FROM alembic_version")).scalar())
    else:
        print("alembic_version: SIN VERSION (revisar antes de migrar)")
    print("role:", db.execute(text("""
        SELECT COLUMN_TYPE FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'users' AND COLUMN_NAME = 'role'
    """)).scalar())
    for table in ("users", "students", "employees", "doors", "exit_logs", "lunch_logs"):
        try:
            n = db.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()
        except Exception:
            db.rollback()
            n = "NO EXISTE"
        print(f"{table}: {n}")
    try:
        dup = db.execute(text("""
            SELECT 'student' AS tipo, student_id AS persona, DATE(timestamp) AS dia, COUNT(*) AS total
            FROM lunch_logs WHERE student_id IS NOT NULL
            GROUP BY student_id, DATE(timestamp) HAVING COUNT(*) > 1
            UNION ALL
            SELECT 'employee', employee_id, DATE(timestamp), COUNT(*)
            FROM lunch_logs WHERE employee_id IS NOT NULL
            GROUP BY employee_id, DATE(timestamp) HAVING COUNT(*) > 1
        """)).fetchall()
    except Exception:
        db.rollback()
        dup = "NO DISPONIBLE"
    print("duplicados_almuerzo:", dup)
    print("max_connections:", db.execute(text("SHOW VARIABLES LIKE 'max_connections'")).fetchone()[1])
    print("threads_connected:", db.execute(text("SHOW STATUS LIKE 'Threads_connected'")).fetchone()[1])
PY
```

Guardar salidas (SHA, revisión, tablas, conteos, enum, duplicados) como evidencia.

## 1. Go / No-Go

Continuar solo si todo está verde:

- Servicio activo y `/login` responde `200`/`303`. `/healthz` puede ser `404` antes de actualizar; registrarlo.
- `git status` limpio salvo `.env`; cualquier otro archivo modificado detiene el despliegue.
- `$TARGET` existe en el servidor y su CI está verde.
- `alembic heads` muestra una sola cabeza (`0003_photo_paths`) si Alembic ya está instalado.
- `alembic_version` es `0001_baseline`, `0002_security_and_audit` o `0003_photo_paths`.
  - `0003`: no hay migración pendiente.
  - `0001`/`0002`: habrá migración; backup y comprobaciones son obligatorios.
  - Sin fila/versión y con las seis tablas del baseline (`users`, `students`, `employees`, `doors`, `exit_logs`, `lunch_logs`): detenerse y confirmar el esquema. Solo entonces se podrá `alembic stamp 0001_baseline` con aprobación explícita y backup fresco. Si hay tablas extra o faltan columnas, no continuar.
- `users.role` es `enum('ADMIN','OPERATOR','LUNCH_OP')`; cualquier otra cosa detiene el despliegue.
- No hay duplicados de almuerzo. Si hay filas: exportar evidencia y detenerse para archivarlas con aprobación; no borrar automáticamente.
- `/var` con al menos 2× el tamaño de la BD + 1 GB libre; `$BACKUP_DIR` escribible.
- Puerto `$APP_PORT` ocupado solo por School Guard; el vhost de `$DOMAIN` apunta a ese puerto; HTTPS y `/sw.js` funcionan.
- `mysqldump`, `gzip`, `tar` y `curl` disponibles; personal avisado y actividad baja.

## 2. Backup verificado

Crear credenciales solo si no existen (no imprime la contraseña):

```bash
mkdir -p "$BACKUP_DIR" "$(dirname "$MYSQL_CNF")"
chmod 700 "$(dirname "$MYSQL_CNF")"
if [ ! -r "$MYSQL_CNF" ]; then
  APP_DIR="$APP_DIR" MYSQL_CNF="$MYSQL_CNF" python3 - <<'PY'
import os
from pathlib import Path
from urllib.parse import unquote, urlsplit

raw = Path(os.environ["APP_DIR"], ".env").read_text(encoding="utf-8")
line = next(l for l in raw.splitlines() if l.startswith("DATABASE_URL="))
url = urlsplit(line.split("=", 1)[1].strip())
cnf = Path(os.environ["MYSQL_CNF"])
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

El archivo de credenciales queda en `$MYSQL_CNF` con permisos `600`. Exportar los cuatro valores mostrados y respaldar configuración, base y fotos:

```bash
export DB_NAME=<valor> DB_USER=<valor> DB_HOST=<valor> DB_PORT=<valor>
export MYSQL_CONFIG="$MYSQL_CNF" BACKUP_DIR

ENV_SHA=$(sha256sum "$APP_DIR/.env" | awk '{print $1}')
cp -p "$APP_DIR/.env" "$BACKUP_DIR/env_$(date +%F_%H%M).bak"
chmod 600 "$BACKUP_DIR"/env_*.bak

DUMP="$BACKUP_DIR/${DB_NAME}_$(date +%F_%H%M%S).sql.gz"
if [ -x "$APP_DIR/scripts/backup_db.sh" ]; then
  sudo env DB_NAME="$DB_NAME" DB_USER="$DB_USER" DB_HOST="$DB_HOST" DB_PORT="$DB_PORT" \
    MYSQL_CONFIG="$MYSQL_CNF" BACKUP_DIR="$BACKUP_DIR" "$APP_DIR/scripts/backup_db.sh"
  DUMP=$(ls -t "$BACKUP_DIR/${DB_NAME}"_*.sql.gz | head -1)
else
  sudo sh -c "mysqldump --defaults-extra-file='$MYSQL_CNF' --host='$DB_HOST' --port='$DB_PORT' \
    --user='$DB_USER' --single-transaction --quick --routines --triggers \
    --default-character-set=utf8mb4 '$DB_NAME' | gzip -c > '$DUMP'"
fi
gzip -t "$DUMP" && zcat "$DUMP" | tail -2   # debe incluir "-- Dump completed"

PHOTOS_DIR=$(grep -E '^MEDIA_PHOTOS_DIR=' "$APP_DIR/.env" | cut -d= -f2-)
PHOTOS_DIR=${PHOTOS_DIR:-app/data/photos}
case "$PHOTOS_DIR" in /*) : ;; *) PHOTOS_DIR="$APP_DIR/$PHOTOS_DIR" ;; esac
PHOTOS_TGZ="$BACKUP_DIR/photos_$(date +%F_%H%M).tgz"
sudo tar -C / -czf "$PHOTOS_TGZ" "${PHOTOS_DIR#/}"
sudo chown "$(id -un):$(id -gn)" "$DUMP" "$PHOTOS_TGZ" "$BACKUP_DIR"/env_*.bak
echo "fotos en backup: $(sudo tar -tzf "$PHOTOS_TGZ" | wc -l)"
echo "fotos en disco:  $(sudo find "$PHOTOS_DIR" -type f | wc -l)"
```

Copiar `$DUMP`, `$PHOTOS_TGZ` y el backup de `.env` fuera del servidor.

Restore verificado: crear una base temporal, importar el dump y comparar conteos. Si el usuario de backup no puede crear bases, pedir al DBA que lo haga. No continuar sin una restauración verificada (de esta ventana o de las últimas 24 h).

```bash
SCRATCH=${DB_NAME}_restore_check
sudo mysql --defaults-extra-file="$MYSQL_CNF" -e "CREATE DATABASE $SCRATCH CHARACTER SET utf8mb4"
sudo sh -c "gzip -dc '$DUMP' | mysql --defaults-extra-file='$MYSQL_CNF' '$SCRATCH'"
sudo mysql --defaults-extra-file="$MYSQL_CNF" -e "SELECT COUNT(*) FROM $SCRATCH.users; SELECT COUNT(*) FROM $SCRATCH.lunch_logs;"
sudo mysql --defaults-extra-file="$MYSQL_CNF" -e "DROP DATABASE $SCRATCH"
```

## 3. Proteger `.env` y revisar el diff

```bash
cd "$APP_DIR"
OLD=$(git rev-parse HEAD)
git diff --stat "$OLD" "$TARGET"
git diff "$OLD" "$TARGET" -- .env.template app/config.py requirements.txt requirements-dev.txt
```

Si el diff exige variables nuevas ausentes en `.env`, detenerse y consultar: no se edita `.env` en esta ventana.

`.env` está versionado; impedir que el checkout lo sobrescriba:

```bash
TRACKED=no
git ls-files --error-unmatch .env >/dev/null 2>&1 && TRACKED=yes
if [ "$TRACKED" = yes ]; then
  git update-index --skip-worktree .env
fi
```

## 4. Ventana de actualización

```bash
sudo systemctl stop "$UNIT"
```

Si el servicio no queda inactivo, no continuar.

```bash
git checkout --detach "$TARGET"
if [ "$TRACKED" = yes ]; then
  git update-index --no-skip-worktree .env
fi
git rev-parse HEAD          # debe ser $TARGET
NEW_ENV_SHA=$(sha256sum "$APP_DIR/.env" | awk '{print $1}')
[ "$NEW_ENV_SHA" = "$ENV_SHA" ] || {
  echo "ABORTAR: .env cambió durante el checkout";
  cp -p "$(ls -t "$BACKUP_DIR"/env_*.bak | head -1)" "$APP_DIR/.env";
}
```

Dependencias (no hay build de frontend):

```bash
sudo -u "$VENV_OWNER" "$VENV/bin/pip" install -r "$APP_DIR/requirements.txt"
sudo -u "$VENV_OWNER" "$VENV/bin/pip" check
```

Migración:

```bash
cd "$APP_DIR"
# Solo si el paso 1 confirmó que no existía alembic_version y el esquema coincide con 0001:
# sudo -u "$VENV_OWNER" "$VENV/bin/alembic" stamp 0001_baseline
sudo -u "$VENV_OWNER" "$VENV/bin/alembic" upgrade head
sudo -u "$VENV_OWNER" "$VENV/bin/alembic" current   # 0003_photo_paths (head)
sudo -u "$VENV_OWNER" "$VENV/bin/alembic" check     # sin deriva
```

Asegurar que el usuario del servicio puede escribir las fotos:

```bash
test -d "$PHOTOS_DIR" && sudo chown -R "$APP_USER:$APP_USER" "$PHOTOS_DIR"
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

Infraestructura (resolver el dominio a localhost para probar el vhost sin depender del DNS):

```bash
curl -fsSI --resolve "$DOMAIN:443:127.0.0.1" "https://$DOMAIN/healthz"
curl -fsSI --resolve "$DOMAIN:443:127.0.0.1" "https://$DOMAIN/sw.js" | grep -Ei 'service-worker-allowed|cache-control'
cd "$APP_DIR" && sudo -u "$VENV_OWNER" "$VENV/bin/alembic" current
```

Si el certificado es de una CA interna no confiada por el servidor, añadir `-k` solo para esta verificación local.

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
if [ -x "$APP_DIR/scripts/restore_db.sh" ]; then
  sudo env CONFIRM_RESTORE=YES DB_NAME="$DB_NAME" DB_USER="$DB_USER" DB_HOST="$DB_HOST" \
    DB_PORT="$DB_PORT" MYSQL_CONFIG="$MYSQL_CNF" "$APP_DIR/scripts/restore_db.sh" "$DUMP"
else
  sudo sh -c "gzip -dc '$DUMP' | mysql --defaults-extra-file='$MYSQL_CNF' \
    --host='$DB_HOST' --port='$DB_PORT' --user='$DB_USER' '$DB_NAME'"
fi

# Solo si se detectó corrupción de fotos:
sudo tar -C / -xzf "$PHOTOS_TGZ"

# Si .env cambió:
cp -p "$(ls -t "$BACKUP_DIR"/env_*.bak | head -1)" "$APP_DIR/.env"

git checkout --detach "$OLD"
sudo -u "$VENV_OWNER" "$VENV/bin/pip" install -r "$APP_DIR/requirements.txt"
sudo systemctl start "$UNIT"
sudo systemctl status "$UNIT" --no-pager | head -15
curl -sS -o /dev/null -w 'login=%{http_code}\n' "http://127.0.0.1:$APP_PORT/login"
```

Tras el rollback, `/healthz` volverá a responder 404 porque el código anterior no tiene esa ruta; validar con `/login` y un escaneo. Si el restore falla, mantener el servicio detenido y escalar; no arrancar código nuevo contra una base a medio restaurar. El restore descarta las filas creadas después del backup (incluido el smoke).

## 7. Cierre y evidencia

- Registrar en los issues #1/#2: SHA anterior y nuevo, nombre/hora de `$DUMP`, `$PHOTOS_TGZ` y backup de `.env`, revisión Alembic final, enum, duplicados, conteos antes/después y resultado del smoke.
- Confirmar copia de backups fuera del servidor y retención de 14 días.
- Avisar reapertura y monitorear 24 h (`journalctl`, `/healthz`, 5xx).
- Fuera de esta ventana: rotación de secretos, `.env` untracking/purga, reimpresión masiva v2 y retiro de `QR_SECRET_KEY_PREVIOUS` (~30 días).

## Riesgos de convivencia con otras apps

- Colisión de `$APP_PORT`: el paso 0 lo detecta; usar el puerto del unit, no el de la documentación antigua.
- RAM/CPU: 4 workers de Gunicorn comparten host; revisar `free -m` antes y después.
- MySQL compartido: vigilar `Threads_connected`/`max_connections`; 4 workers pueden abrir hasta ~60 conexiones en pico.
- Nginx compartido: no se recarga ni se edita; si hubiera que hacerlo, `nginx -t` antes de `reload`.
- Migración con locks: 0002 altera tablas; ejecutar con actividad baja y vigilar `SHOW PROCESSLIST`.
- `.env` versionado: `skip-worktree` y comparación de hash evitan pisar la configuración de producción.
- Propietario del repo/venv: Git como `$REPO_OWNER` y pip/Alembic como `$VENV_OWNER`; no ejecutar Git como `www-data`.
- Código antiguo sin `/healthz`: el baseline previo y el rollback se validan con `/login`; no interpretar el 404 como caída.
