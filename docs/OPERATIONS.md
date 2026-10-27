# Operación

## Salud

```bash
curl -fsS http://127.0.0.1:8001/healthz
```

- `200 {"status":"ok"}`: la aplicación responde y la base contesta `SELECT 1`.
- `503 {"status":"degraded"}`: la base no está disponible. Revisar `journalctl` y la conexión MySQL.

El endpoint no expone detalles internos. Para monitoreo externo, permitir solo las IP del monitor.

## Logs y request_id

Cada respuesta incluye `X-Request-ID`. Si el cliente envía uno válido (`[A-Za-z0-9._-]{8,36}`), se conserva; si no, se genera.

Los logs son JSON con `timestamp`, `level`, `logger`, `message`, `request_id`, `method`, `path`, `status`, `duration_ms` y `user_id` cuando existe.

```bash
sudo journalctl -u school-guard -o cat | jq 'select(.level == "ERROR")'
sudo journalctl -u school-guard -o cat | jq 'select(.request_id == "abc12345")'
```

No se registran cuerpos, contraseñas, códigos QR ni nombres completos.

Los `audit_logs` guardan el mismo `request_id`, lo que permite reconstruir una operación:

```sql
SELECT created_at, actor_id, action, entity_type, entity_id, ip, request_id, details
FROM audit_logs
WHERE request_id = 'abc12345';
```

## Evidencia de intentos

```sql
-- Rechazos y duplicados del día
SELECT created_at, module, method, result, reason, operator_id, student_id, employee_id
FROM scan_attempts
WHERE created_at >= CURDATE()
ORDER BY created_at DESC;

-- Cambios administrativos recientes
SELECT created_at, actor_id, action, entity_type, entity_id, details
FROM audit_logs
WHERE created_at >= NOW() - INTERVAL 7 DAY
ORDER BY created_at DESC;
```

## Backup y restore

Los scripts usan un archivo de credenciales de MySQL, nunca contraseñas en argumentos.

```bash
export DB_NAME=school_guard
export DB_USER=school_guard
export MYSQL_CONFIG=/etc/school-guard/mysql-backup.cnf
export BACKUP_DIR=/var/backups/school_guard
./scripts/backup_db.sh
```

El respaldo se comprime, se verifica con `gzip -t` y se conserva según `RETENTION_DAYS` (14 por defecto). Copiar los archivos fuera del servidor. Respaldar también `app/data/photos`.

Restore (detener la aplicación primero):

```bash
export DB_NAME=school_guard
export DB_USER=school_guard
export MYSQL_CONFIG=/etc/school-guard/mysql-backup.cnf
export CONFIRM_RESTORE=YES
./scripts/restore_db.sh /var/backups/school_guard/school_guard_2026-10-26_020000.sql.gz
```

Probar el restore en staging antes de necesitarlo en producción.

## Tickets de almuerzo

Cada entrega tiene un `public_id` UUID. Si la impresora falla:

1. Buscar la entrega en el reporte del día.
2. Usar “Reimprimir” o `POST /lunch/tickets/{public_id}/reprint`.
3. Verificar que `printed_count` aumente y que la reimpresión quede auditada.

No se crea un segundo registro de almuerzo. Un escaneo duplicado devuelve la entrega existente.

## Desactivación y borrado

- Usuarios, estudiantes, empleados y puertas con historial se **desactivan**, no se borran.
- Una entidad inactiva no puede operar: no inicia sesión, no registra salidas y no reclama almuerzos.
- No se puede eliminar ni degradar al último administrador activo.
- Cada alta, baja, cambio de rol o cambio de autorización queda en `audit_logs`.

## Checklist de incidentes

**Base de datos caída**

1. Confirmar `/healthz` en `503`.
2. Revisar `journalctl` y conectividad MySQL.
3. No reiniciar en bucle; corregir la causa y verificar `/healthz`.

**Cámara o escáner no funciona**

1. Confirmar HTTPS y permiso de cámara en el navegador.
2. Usar la búsqueda manual de respaldo (solo comedor) o el ingreso manual autorizado.
3. Revisar que el service worker solo cachee estáticos; el escaneo es online.

**Impresora térmica falla**

1. Reimprimir desde el ticket o el reporte del día.
2. Si el navegador bloquea la impresión automática, usar el botón explícito.
3. Si se superan 3 reimpresiones, revisar el motivo y el operador en auditoría.

**Salida no autorizada o suplantación**

1. Localizar el intento en `scan_attempts` por fecha y operador.
2. Revisar `audit_logs` y el `request_id` asociado.
3. Si se sospecha filtración de la clave QR, coordinar rotación inmediata.

**Sospecha de filtración de secretos**

1. No publicar el contenido de `.env`.
2. Rotar `SECRET_KEY` y claves QR con el procedimiento de despliegue.
3. Coordinar la purga del historial Git y la revisión de accesos.

## Ventana de mantenimiento

Las migraciones, la rotación de secretos, los cambios de TLS y el restore real requieren ventana coordinada. Antes de tocar producción: backup verificado, responsable identificado, smoke test preparado y plan de reversión.

### Checklist pre-ventana

Ejecutar al menos 48 horas antes y repetir las verificaciones de solo lectura el mismo día. Marcar cada punto con fecha, responsable y evidencia.

#### 1. Alcance y responsables

- [ ] Fecha, hora y duración objetivo confirmadas con el colegio; modo mantenimiento en Nginx acordado.
- [ ] Responsable de la ventana y de la decisión de rollback identificados.
- [ ] Commit o tag a desplegar fijado y CI verde para ese SHA:
  ```bash
  git fetch origin
  git log -1 --oneline origin/main
  # Confirmar el run de GitHub Actions correspondiente al SHA
  ```
- [ ] Cambios congelados en `main` desde el inicio de la ventana hasta el smoke final.
- [ ] Personal operativo avisado y respaldo manual definido (listas impresas o registro en papel).

#### 2. Estado actual (solo lectura)

- [ ] `/healthz` responde `200` antes de cualquier cambio.
- [ ] Revisión actual de Alembic registrada:
  ```bash
  .venv/bin/alembic current
  .venv/bin/alembic heads   # debe haber una sola cabeza
  ```
- [ ] Conteos base de las tablas críticas para comparar después:
  ```sql
  SELECT 'users' AS tabla, COUNT(*) AS filas FROM users
  UNION ALL SELECT 'students', COUNT(*) FROM students
  UNION ALL SELECT 'employees', COUNT(*) FROM employees
  UNION ALL SELECT 'doors', COUNT(*) FROM doors
  UNION ALL SELECT 'exit_logs', COUNT(*) FROM exit_logs
  UNION ALL SELECT 'lunch_logs', COUNT(*) FROM lunch_logs;
  ```
- [ ] Baseline de errores de las últimas 24 h revisado (5xx, 403 y 409) en `journalctl` y `audit_logs`.
- [ ] Espacio libre suficiente para backup, archivos temporales y migración (`df -h`).

#### 3. Backup y restore verificado

- [ ] Backup completo ejecutado y comprimido sin errores:
  ```bash
  export DB_NAME=school_guard
  export DB_USER=school_guard
  export MYSQL_CONFIG=/etc/school-guard/mysql-backup.cnf
  export BACKUP_DIR=/var/backups/school_guard
  ./scripts/backup_db.sh
  ```
- [ ] Integridad del archivo comprobada (`gzip -t`) y copia fuera del servidor.
- [ ] `app/data/photos` respaldado por separado.
- [ ] Restore probado en staging desde ese backup y conteos coincidentes con el punto 2.
- [ ] Backup y restore documentados con nombre de archivo y hora; el restore real en producción exige `CONFIRM_RESTORE=YES`.

#### 4. Migraciones sobre copia restaurada

- [ ] `alembic upgrade head` ejecutado sobre la copia restaurada sin errores.
- [ ] `alembic check` sin deriva y conteos de filas conservados.
- [ ] `alembic downgrade -1` probado en staging si el plan lo contempla; documentar las operaciones de una sola vía.
- [ ] Enum real de `users.role` verificado contra producción (issue #1):
  ```sql
  SELECT COLUMN_TYPE
  FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'users'
    AND COLUMN_NAME = 'role';
  ```
- [ ] Duplicados históricos de almuerzo detectados y archivados con aprobación explícita (issue #1):
  ```sql
  SELECT student_id, DATE(timestamp) AS dia, COUNT(*) AS total
  FROM lunch_logs
  WHERE student_id IS NOT NULL
  GROUP BY student_id, DATE(timestamp)
  HAVING COUNT(*) > 1;

  SELECT employee_id, DATE(timestamp) AS dia, COUNT(*) AS total
  FROM lunch_logs
  WHERE employee_id IS NOT NULL
  GROUP BY employee_id, DATE(timestamp)
  HAVING COUNT(*) > 1;
  ```
- [ ] Reporte de duplicados exportado y guardado junto a la evidencia de la ventana.

#### 5. Secretos y configuración

- [ ] `.env` de producción con permisos `600` y propietario del usuario del servicio.
- [ ] Variables obligatorias presentes y validadas al arranque: `APP_ENV=production`, `DATABASE_URL`, `SECRET_KEY`, `QR_SECRET_KEY_CURRENT`, `COOKIE_SECURE=true`.
- [ ] `QR_SECRET_KEY_PREVIOUS` definida durante la transición de carnets; retiro planificado tras el periodo de gracia (~30 días).
- [ ] Rotación de `SECRET_KEY` y de la contraseña de base de datos planificada con su efecto conocido: las sesiones actuales se invalidan y los usuarios deben volver a iniciar sesión.
- [ ] `.env` retirado del índice y purga del historial coordinada por separado; la rotación se hace antes de la purga y nunca se ejecuta sin force-push acordado.
- [ ] `BOOTSTRAP_ADMIN_PASSWORD` disponible solo si se requiere bootstrap (mínimo 12 caracteres); no registrar secretos en el historial del shell ni en tickets.
- [ ] Contraseña del usuario `admin` rotada o planificada tras la ventana.

#### 6. TLS, Nginx y modo mantenimiento

- [ ] HTTPS responde antes de activar `COOKIE_SECURE=true`:
  ```bash
  curl -fsSI https://salidas.example.edu.co/healthz
  curl -fsSI https://salidas.example.edu.co/sw.js
  ```
- [ ] `X-Forwarded-Proto`, `X-Request-ID` y `client_max_body_size` revisados en la configuración de Nginx.
- [ ] Página o respuesta de mantenimiento probada y reversible.
- [ ] Cámara y escaneo funcionan solo bajo HTTPS; permisos del navegador verificados en los equipos de portería y comedor.

#### 7. Hardware, impresión y carnets

- [ ] Impresora térmica con papel suficiente y página de prueba correcta.
- [ ] Lector RFID y cámara probados en los equipos que se usarán durante la ventana.
- [ ] Carnet v1 de prueba disponible; lote de reimpresión v2 planificado.
- [ ] Reimpresión desde reportes verificada en staging con el flujo actual (ventana emergente y respaldo sin autoimpresión).
- [ ] Contacto del proveedor de hardware disponible por si falla la impresora.

#### 8. Smoke y comunicación

- [ ] Smoke completo del issue #2 ensayado en staging y resultados adjuntos.
- [ ] `/healthz`, `audit_logs` y `scan_attempts` revisados tras el ensayo.
- [ ] Mensaje de inicio y fin de ventana preparado para el colegio.
- [ ] Monitoreo y acceso a logs listos durante toda la ventana.

#### 9. Go / No-Go

La ventana se cancela si falla cualquiera de estos puntos:

- Backup inexistente, corrupto o restore no verificado.
- `alembic upgrade head` o `alembic check` con errores en la copia restaurada.
- Duplicados de almuerzo sin archivar o enum de `users.role` incompatible.
- HTTPS no verificado antes de `COOKIE_SECURE=true`.
- Smoke de staging con fallos en registro de salidas, almuerzos o impresión.

Criterio de rollback: restaurar el backup verificado y volver al commit anterior. Detener la ventana si falla un flujo crítico, aunque el resto funcione.
