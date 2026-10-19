-- Migración 004 de EnvioBot Full: mail donde cada cliente recibe los avisos de Mercado Libre sobre la colecta.
-- Columna user_settings.colecta_email: una o varias direcciones separadas por coma (NULL = no configurado).
-- Con ella el lector de mails (correo_colectas.py) sabe a qué cuenta pertenece cada mail reenviado.
-- NO aplicar con el servicio prendido. Orden: apagar enviobot-full, respaldo, aplicar, prender, verificar.
-- Se puede correr dos veces sin efecto. Sin esta migración no se puede configurar y los mails no se reparten.
SET SESSION lock_wait_timeout = 10;

SET @sql = IF((SELECT COUNT(*) FROM information_schema.COLUMNS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'user_settings' AND COLUMN_NAME = 'colecta_email') = 0,
    'ALTER TABLE user_settings ADD COLUMN colecta_email VARCHAR(255) NULL',
    'SELECT 1');
PREPARE s FROM @sql; EXECUTE s; DEALLOCATE PREPARE s;
