-- Migración 003 de EnvioBot Full: qué avisos recibe cada destinatario de la agenda de envíos.
-- Columna alert_recipients.avisos: NULL = todos (como hasta ahora), '' = ninguno, 'a,b' = solo esos.
-- NO aplicar con el servicio prendido. Orden: apagar enviobot-full, respaldo, aplicar, prender, verificar.
-- Se puede correr dos veces sin efecto. Sin esta migración todos reciben todos los avisos, como siempre.
SET SESSION lock_wait_timeout = 10;

SET @sql = IF((SELECT COUNT(*) FROM information_schema.COLUMNS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'alert_recipients' AND COLUMN_NAME = 'avisos') = 0,
    'ALTER TABLE alert_recipients ADD COLUMN avisos VARCHAR(255) NULL',
    'SELECT 1');
PREPARE s FROM @sql; EXECUTE s; DEALLOCATE PREPARE s;
