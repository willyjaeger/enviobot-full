-- ====================================================================
-- MIGRACIÓN DE CONTROL DE CLIENTES Y SUSCRIPCIÓN - ENVIOBOT FULL
-- ====================================================================
-- Esta migración añade los campos para el control administrativo manual:
-- 1. `is_blocked`: permite bloquear un cliente totalmente.
-- 2. `admin_notes`: observaciones internas (pagos, extensiones, notas).
-- 3. Reseteo de asignaciones automáticas heredadas.
-- ====================================================================

-- 1. Agregar columnas a la tabla de usuarios
ALTER TABLE users ADD COLUMN IF NOT EXISTS is_blocked TINYINT(1) DEFAULT 0;
ALTER TABLE users ADD COLUMN IF NOT EXISTS admin_notes TEXT NULL;

-- 2. Agregar columnas a la tabla de asignación de features (usada por admin.enviobot.com.ar)
ALTER TABLE user_features ADD COLUMN IF NOT EXISTS is_blocked TINYINT(1) DEFAULT 0;
ALTER TABLE user_features ADD COLUMN IF NOT EXISTS admin_notes TEXT NULL;

-- 3. Asegurar que exista la feature 'enviobot_full' en el catálogo central
INSERT INTO features (feature_code, feature_name, description, is_active)
SELECT 'enviobot_full', 'EnvioBot Full', 'Control de stock Full y reposición', 1
WHERE NOT EXISTS (SELECT 1 FROM features WHERE feature_code = 'enviobot_full');

-- ====================================================================
-- INSTRUCCIONES PARA DESVINCULAR A GUILLERMO Y PROBAR COMO CLIENTE NUEVO:
-- ====================================================================
-- Ejecutar la siguiente consulta para quitarle el acceso Full a Guillermo.
-- Al ingresar a EnvioBot Full, el sistema lo tratará como usuario sin suscripción
-- y le solicitará registrarse o activar explícitamente sus 30 días de prueba.

DELETE FROM user_features 
WHERE user_id = (SELECT id FROM users WHERE email = 'guillermo.jaeger@gmail.com' LIMIT 1)
  AND feature_id = (SELECT id FROM features WHERE feature_code = 'enviobot_full' LIMIT 1);

-- ====================================================================
-- PARA QUITAR LA HERENCIA AUTOMÁTICA EN admin.enviobot.com.ar:
-- ====================================================================
-- En la pantalla "Funcionalidades por cliente":
-- 1. Desmarcar la casilla superior "Por defecto" en la columna de EnvioBot Full.
-- 2. Con eso, ningún usuario nuevo ni secundario recibirá Full automáticamente.
-- 3. Solo quienes hagan clic en "Activar 30 días" o quienes vos tildes manualmente
--    tendrán acceso.
