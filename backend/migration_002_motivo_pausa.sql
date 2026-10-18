-- Migración 002 de EnvioBot Full: motivo de pausa de cada publicación (sub_status de MercadoLibre).
-- Sirve para distinguir "pausada porque se quedó sin stock" (hay que avisar) de "la pausé yo" (no).
-- NO aplicar con el servicio prendido. Orden: apagar enviobot-full, respaldo de la base,
-- aplicar esto, prender, verificar. Se puede correr dos veces sin efecto.
SET SESSION lock_wait_timeout = 10;

SET @sql = IF((SELECT COUNT(*) FROM information_schema.COLUMNS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'full_items' AND COLUMN_NAME = 'sub_status') = 0,
    'ALTER TABLE full_items ADD COLUMN sub_status VARCHAR(100) NULL AFTER status',
    'SELECT 1');
PREPARE s FROM @sql; EXECUTE s; DEALLOCATE PREPARE s;
