-- Migración 009 de EnvioBot Full: lo que permite la cita de cada colecta de Mercado Libre.
-- Columnas nuevas en inbound_shipments (todas admiten vacío): total_declarado (unidades declaradas al agendar, se guarda una sola
-- vez), cita_min y cita_max (rango que el usuario corrige a mano si Mercado Libre muestra otro). Sin ellas el panel funciona igual:
-- estima el rango con lo cargado.
-- NO aplicar con el servicio prendido. Orden: apagar enviobot-full, respaldo, aplicar, prender, verificar.
-- Se puede correr dos veces sin efecto.
SET SESSION lock_wait_timeout = 10;

SET @sql = IF((SELECT COUNT(*) FROM information_schema.COLUMNS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'inbound_shipments' AND COLUMN_NAME = 'total_declarado') = 0,
    'ALTER TABLE inbound_shipments ADD COLUMN total_declarado INT NULL',
    'SELECT 1');
PREPARE s FROM @sql; EXECUTE s; DEALLOCATE PREPARE s;

SET @sql = IF((SELECT COUNT(*) FROM information_schema.COLUMNS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'inbound_shipments' AND COLUMN_NAME = 'cita_min') = 0,
    'ALTER TABLE inbound_shipments ADD COLUMN cita_min INT NULL',
    'SELECT 1');
PREPARE s FROM @sql; EXECUTE s; DEALLOCATE PREPARE s;

SET @sql = IF((SELECT COUNT(*) FROM information_schema.COLUMNS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'inbound_shipments' AND COLUMN_NAME = 'cita_max') = 0,
    'ALTER TABLE inbound_shipments ADD COLUMN cita_max INT NULL',
    'SELECT 1');
PREPARE s FROM @sql; EXECUTE s; DEALLOCATE PREPARE s;
