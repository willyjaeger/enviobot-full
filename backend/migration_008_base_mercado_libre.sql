-- Migración 008 de EnvioBot Full: la "base" de cada colecta, o sea lo que Mercado Libre tiene (el último PDF cargado).
-- Columna nueva inbound_shipments.ml_base (JSON en texto). Sirve para que todas las computadoras de la cuenta vean la misma
-- hoja de cambios para hacer en Mercado Libre. Sin la columna el panel funciona igual: la hoja se arma con lo guardado.
-- NO aplicar con el servicio prendido. Orden: apagar enviobot-full, respaldo, aplicar, prender, verificar.
-- Se puede correr dos veces sin efecto.
SET SESSION lock_wait_timeout = 10;

SET @sql = IF((SELECT COUNT(*) FROM information_schema.COLUMNS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'inbound_shipments' AND COLUMN_NAME = 'ml_base') = 0,
    'ALTER TABLE inbound_shipments ADD COLUMN ml_base MEDIUMTEXT NULL',
    'SELECT 1');
PREPARE s FROM @sql; EXECUTE s; DEALLOCATE PREPARE s;
