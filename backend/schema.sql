-- =====================================================================
-- Esquema de Base de Datos: EnvioBot Full (SaaS Independiente)
-- Compatible con MySQL 5.7+ / 8.0+ y MariaDB (DonWeb VPS)
-- =====================================================================

CREATE DATABASE IF NOT EXISTS enviobot_full CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE enviobot_full;

-- 1. Usuarios y suscripciones
CREATE TABLE IF NOT EXISTS users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    email VARCHAR(255) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    full_name VARCHAR(150) NOT NULL,
    phone VARCHAR(50) NULL,
    business_name VARCHAR(150) NULL,
    plan_tier ENUM('trial', 'pro', 'enterprise') NOT NULL DEFAULT 'trial',
    trial_ends_at TIMESTAMP NOT NULL DEFAULT (CURRENT_TIMESTAMP + INTERVAL 14 DAY),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 2. Credenciales OAuth de MercadoLibre (un registro por usuario)
CREATE TABLE IF NOT EXISTS ml_credentials (
    user_id INT PRIMARY KEY,
    meli_user_id BIGINT NOT NULL,
    nickname VARCHAR(100) NULL,
    access_token VARCHAR(500) NOT NULL,
    refresh_token VARCHAR(500) NOT NULL,
    expires_at TIMESTAMP NOT NULL,
    last_sync_at TIMESTAMP NULL,
    sync_status ENUM('idle', 'syncing', 'error') NOT NULL DEFAULT 'idle',
    last_error VARCHAR(255) NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 3. Parámetros globales de stock y alertas por usuario
CREATE TABLE IF NOT EXISTS user_settings (
    user_id INT PRIMARY KEY,
    default_lead_time_days INT NOT NULL DEFAULT 7,      -- Tiempo de fabricación/preparación + turno en Full
    default_safety_stock_days INT NOT NULL DEFAULT 3,   -- Colchón de seguridad para imprevistos
    target_coverage_days INT NOT NULL DEFAULT 30,       -- Cuántos días de stock busca tener cubierto
    notify_email BOOLEAN NOT NULL DEFAULT TRUE,
    alert_email VARCHAR(255) NULL,
    notify_whatsapp BOOLEAN NOT NULL DEFAULT FALSE,
    whatsapp_phone VARCHAR(50) NULL,
    brand_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    brand_name VARCHAR(150) NULL,
    brand_logo_url MEDIUMTEXT NULL,
    brand_primary_color VARCHAR(25) NULL,
    brand_show_powered_by BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 4. Catálogo de publicaciones con presencia en Mercado Envíos Full
CREATE TABLE IF NOT EXISTS full_items (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    ml_credential_id INT NULL,
    item_id VARCHAR(50) NOT NULL,                      -- MLA123456789
    variation_id VARCHAR(50) NOT NULL DEFAULT '',
    variation_name VARCHAR(150) NULL,                  -- ej: Color: Negro / Talle: 42
    inventory_id VARCHAR(50) NULL,                     -- Inventory ID de MeLi en bodega Full
    sku VARCHAR(100) NULL,
    title VARCHAR(255) NOT NULL,
    thumbnail VARCHAR(350) NULL,
    permalink VARCHAR(500) NULL,
    listing_type_id VARCHAR(50) NULL,                  -- gold_special (Clásica), gold_pro (Premium)
    is_catalog BOOLEAN NOT NULL DEFAULT FALSE,         -- true si compite en Catálogo / Buy Box
    status VARCHAR(30) NOT NULL DEFAULT 'active',      -- active, paused, closed
    current_stock_full INT NOT NULL DEFAULT 0,         -- Stock APTO disponible en depósito de MeLi
    not_available_stock_full INT NOT NULL DEFAULT 0,    -- Stock retenido/dañado en depósito de MeLi
    lead_time_override INT NULL,                       -- Tiempo de preparación específico para este SKU
    safety_stock_override INT NULL,                    -- Buffer específico para este SKU
    is_monitored BOOLEAN NOT NULL DEFAULT TRUE,
    last_synced_at TIMESTAMP NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_user_item_var (user_id, item_id, variation_id),
    INDEX idx_user_sku (user_id, sku),
    INDEX idx_user_inv (user_id, inventory_id),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 5. Pronósticos y Semáforo de Quiebre de Stock
CREATE TABLE IF NOT EXISTS forecasts (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    item_id VARCHAR(50) NOT NULL,
    variation_id VARCHAR(50) NOT NULL DEFAULT '',
    sales_last_7d INT NOT NULL DEFAULT 0,
    sales_last_15d INT NOT NULL DEFAULT 0,
    sales_last_30d INT NOT NULL DEFAULT 0,
    vpd_weighted DECIMAL(8,2) NOT NULL DEFAULT 0.00,    -- Ventas promedio diarias ponderadas
    days_left DECIMAL(8,1) NOT NULL DEFAULT 0.0,        -- Días de inventario restantes
    stockout_date DATE NULL,                            -- Fecha estimada de quiebre
    reorder_deadline_date DATE NULL,                    -- Fecha límite para preparar y enviar mercadería
    suggested_restock_units INT NOT NULL DEFAULT 0,     -- Cantidad de unidades a mandar a Full
    status ENUM('ok', 'warning', 'critical', 'out_of_stock') NOT NULL DEFAULT 'ok',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_user_forecast (user_id, item_id, variation_id),
    INDEX idx_user_status (user_id, status),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 6. Historial de alertas emitidas (para control y no repetir notificaciones en el mismo día)
CREATE TABLE IF NOT EXISTS alert_logs (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    item_id VARCHAR(50) NOT NULL,
    alert_type ENUM('warning', 'critical', 'out_of_stock') NOT NULL,
    message VARCHAR(255) NOT NULL,
    channel ENUM('email', 'whatsapp', 'panel') NOT NULL,
    sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_user_sent (user_id, sent_at),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 7. Depósitos y Nodos Logísticos (MeLi Full, Córdoba, Rosario, Mar del Plata, etc.)
CREATE TABLE IF NOT EXISTS warehouses (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    code VARCHAR(50) NOT NULL,                          -- ej: 'meli_full', 'cordoba', 'rosario', 'mdp'
    name VARCHAR(100) NOT NULL,                         -- "Mercado Envíos Full", "Depósito Córdoba"
    city VARCHAR(100) NULL,                             -- "Buenos Aires", "Córdoba", "Rosario"
    province VARCHAR(100) NULL,
    type ENUM('meli_full', 'hub_regional', 'central_origen') NOT NULL DEFAULT 'hub_regional',
    transit_days INT NOT NULL DEFAULT 3,                -- Demora del flete/camión hacia este depósito
    target_stock_days INT NOT NULL DEFAULT 30,          -- Días de stock teórico a mantener
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_user_wh_code (user_id, code),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 8. Stock físico y parámetros específicos por depósito
CREATE TABLE IF NOT EXISTS warehouse_stock (
    id INT AUTO_INCREMENT PRIMARY KEY,
    warehouse_id INT NOT NULL,
    item_id VARCHAR(50) NOT NULL,                       -- MLA o SKU
    sku VARCHAR(100) NULL,
    current_stock INT NOT NULL DEFAULT 0,
    transit_days_override INT NULL,                     -- Demora flete específica para este SKU en este depósito
    target_days_override INT NULL,                      -- Días de stock teórico específicos
    sales_velocity_vpd DECIMAL(8,2) DEFAULT 0.00,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_wh_item (warehouse_id, item_id),
    FOREIGN KEY (warehouse_id) REFERENCES warehouses(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 9. Destinatarios de Alertas de WhatsApp Multiusuario (Monetizable por Plan)
CREATE TABLE IF NOT EXISTS alert_recipients (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    name VARCHAR(100) NOT NULL,                         -- "Guillermo (Dueño)", "Marcos (Depósito)"
    phone VARCHAR(50) NOT NULL,                         -- "+54 9 11 5555-0001"
    role ENUM('admin', 'deposito', 'flete') NOT NULL DEFAULT 'admin',
    warehouse_filter VARCHAR(50) NOT NULL DEFAULT 'all',-- 'all', 'meli_full', 'cordoba', 'rosario'
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_user_active (user_id, is_active),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

-- 10. Módulo de Colectas y Envíos Inbound a Mercado Libre Full (Módulo Pago)
CREATE TABLE IF NOT EXISTS inbound_shipments (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    ml_credential_id INT NULL,
    shipment_code VARCHAR(50) NOT NULL UNIQUE,          -- ej: COL-FULL-20261012-001
    destination_warehouse VARCHAR(50) NOT NULL DEFAULT 'meli_full',
    destination_name VARCHAR(150) NOT NULL DEFAULT 'Mercado Envíos Full (Villa Celina)',
    status ENUM('draft', 'scheduled', 'in_transit', 'delivered', 'cancelled') NOT NULL DEFAULT 'scheduled',
    target_coverage_days INT NOT NULL DEFAULT 30,
    lead_time_days INT NOT NULL DEFAULT 2,
    transit_days INT NOT NULL DEFAULT 3,
    total_items INT NOT NULL DEFAULT 0,
    total_units INT NOT NULL DEFAULT 0,
    total_boxes INT NOT NULL DEFAULT 1,
    packaging_type VARCHAR(50) NOT NULL DEFAULT 'cajas_master', -- 'cajas_master', 'bultos_sueltos', 'pallet'
    carrier_notes TEXT NULL,
    pickup_date DATE NULL,
    estimated_arrival_date DATE NULL,
    meli_inbound_id VARCHAR(100) NULL,
    meli_inbound_status VARCHAR(50) NULL,
    meli_sync_payload TEXT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_user_shipments (user_id, status),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS inbound_shipment_items (
    id INT AUTO_INCREMENT PRIMARY KEY,
    shipment_id INT NOT NULL,
    item_id VARCHAR(50) NOT NULL,
    inventory_id VARCHAR(50) NULL,
    variation_id VARCHAR(50) NULL,
    variation_name VARCHAR(150) NULL,
    sku VARCHAR(100) NULL,
    title VARCHAR(255) NOT NULL,
    current_full_stock INT NOT NULL DEFAULT 0,
    vpd DECIMAL(10,2) NOT NULL DEFAULT 0,
    suggested_units INT NOT NULL DEFAULT 0,
    units_to_send INT NOT NULL DEFAULT 0,
    units_per_box INT NOT NULL DEFAULT 0,
    box_count INT NOT NULL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_shipment_items (shipment_id),
    FOREIGN KEY (shipment_id) REFERENCES inbound_shipments(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
