-- Migración 005 de EnvioBot Full: foto diaria del índice de quiebres.
-- Tabla nueva indice_quiebres: una fila por cuenta y día con cuántos productos se quedan sin stock en las próximas 3 semanas
-- (los que todavía se evitan actuando hoy y los que ya no) y el porcentaje de venta que se perdería. Sirve para ver si mejoramos.
-- NO aplicar con el servicio prendido. Orden: apagar enviobot-full, respaldo, aplicar, prender, verificar.
-- Se puede correr dos veces sin efecto. Sin esta migración el panel igual funciona: simplemente no guarda el historial.
SET SESSION lock_wait_timeout = 10;

CREATE TABLE IF NOT EXISTS indice_quiebres (
    user_id INT NOT NULL,
    day DATE NOT NULL,
    productos INT NOT NULL DEFAULT 0,
    sin_quiebre INT NOT NULL DEFAULT 0,
    evitables INT NOT NULL DEFAULT 0,
    inevitables INT NOT NULL DEFAULT 0,
    perdida_evitable_pct DECIMAL(5,1) NOT NULL DEFAULT 0,
    perdida_inevitable_pct DECIMAL(5,1) NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, day)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
