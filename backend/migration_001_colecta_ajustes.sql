-- Migración 001 de EnvioBot Full: ajustes de colecta, estado del galpón e historial de stock.
-- NO aplicar con el servicio prendido. Orden: apagar enviobot-full, respaldo de la base,
-- aplicar esto, prender, verificar. MySQL 8.4 no acepta IF NOT EXISTS al agregar columnas, por eso cada
-- cambio mira primero el estado (information_schema) y solo entonces altera. Se puede correr
-- dos veces sin efecto. Usar lock_wait_timeout corto.
SET SESSION lock_wait_timeout = 10;

-- 1) Umbral de sobrestock editable por cliente (multiplo del objetivo de cobertura).
SET @sql = IF((SELECT COUNT(*) FROM information_schema.COLUMNS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'user_settings' AND COLUMN_NAME = 'sobrestock_factor') = 0,
    'ALTER TABLE user_settings ADD COLUMN sobrestock_factor DECIMAL(4,2) NOT NULL DEFAULT 1.50',
    'SELECT 1');
PREPARE s FROM @sql; EXECUTE s; DEALLOCATE PREPARE s;

-- 2) Hora limite para modificar la colecta (dia anterior al retiro), por deposito. Hora de Buenos Aires.
SET @sql = IF((SELECT COUNT(*) FROM information_schema.COLUMNS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'warehouses' AND COLUMN_NAME = 'edit_cutoff_time') = 0,
    'ALTER TABLE warehouses ADD COLUMN edit_cutoff_time TIME NOT NULL DEFAULT ''09:44:00''',
    'SELECT 1');
PREPARE s FROM @sql; EXECUTE s; DEALLOCATE PREPARE s;

-- 3) Estado del galpon por producto de la colecta: to_buy / packing / boxed.
SET @sql = IF((SELECT COUNT(*) FROM information_schema.COLUMNS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'inbound_shipment_items' AND COLUMN_NAME = 'prep_status') = 0,
    'ALTER TABLE inbound_shipment_items ADD COLUMN prep_status VARCHAR(20) NOT NULL DEFAULT ''to_buy''',
    'SELECT 1');
PREPARE s FROM @sql; EXECUTE s; DEALLOCATE PREPARE s;

-- 4) Foto diaria del stock en Full, para saber cuantos dias estuvo un producto sin stock.
--    Una fila por producto y dia; un dia cuenta como "sin stock" si el maximo del dia fue 0.
CREATE TABLE IF NOT EXISTS stock_daily (
    user_id      INT          NOT NULL,
    item_id      VARCHAR(50)  NOT NULL,
    variation_id VARCHAR(50)  NOT NULL DEFAULT '',
    day          DATE         NOT NULL,
    stock_min    INT          NOT NULL,
    stock_max    INT          NOT NULL,
    PRIMARY KEY (user_id, item_id, variation_id, day)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
