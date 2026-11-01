-- Migración 006 de EnvioBot Full: historial de ventas para calcular el ritmo de venta limpio (demanda.py).
-- Dos tablas nuevas, solo unidades vendidas (sin compradores ni órdenes sueltas):
--   ventas_diarias: unidades por publicación y día, últimos 120 días (después se juntan en semanas y se borra el detalle).
--   ventas_semanales: unidades por publicación y semana (lunes), hasta 2 años; sirve para la estacionalidad.
-- NO aplicar con el servicio prendido. Orden: apagar enviobot-full, respaldo, aplicar, prender, verificar.
-- Se puede correr dos veces sin efecto. Sin esta migración el panel igual funciona con el cálculo de siempre.
SET SESSION lock_wait_timeout = 10;

CREATE TABLE IF NOT EXISTS ventas_diarias (
    user_id      INT         NOT NULL,
    item_id      VARCHAR(50) NOT NULL,
    variation_id VARCHAR(50) NOT NULL DEFAULT '',
    day          DATE        NOT NULL,
    unidades     INT         NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, item_id, variation_id, day)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS ventas_semanales (
    user_id      INT         NOT NULL,
    item_id      VARCHAR(50) NOT NULL,
    variation_id VARCHAR(50) NOT NULL DEFAULT '',
    semana       DATE        NOT NULL,
    unidades     INT         NOT NULL DEFAULT 0,
    dias_sin_stock TINYINT   NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, item_id, variation_id, semana)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
