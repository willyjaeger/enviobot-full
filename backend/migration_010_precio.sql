-- Migración 010 de EnvioBot Full: precio de venta de cada publicación (full_items.price).
-- Lo trae el worker de Mercado Libre en cada sincronización. Sirve para el reloj de la plata que se perdió por quedarse sin stock.
-- Columna nueva que admite vacío: no cambia datos existentes. Sin la columna el panel funciona igual y el reloj avisa que falta el precio.
-- NO aplicar con el servicio prendido. Orden: apagar enviobot-full, respaldo, aplicar, prender, verificar.
-- Se puede correr dos veces sin efecto.
SET SESSION lock_wait_timeout = 10;

SET @sql = IF((SELECT COUNT(*) FROM information_schema.COLUMNS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'full_items' AND COLUMN_NAME = 'price') = 0,
    'ALTER TABLE full_items ADD COLUMN price DECIMAL(14,2) NULL',
    'SELECT 1');
PREPARE s FROM @sql; EXECUTE s; DEALLOCATE PREPARE s;
