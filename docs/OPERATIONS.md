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
