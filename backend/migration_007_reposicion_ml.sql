-- Migración 007 de EnvioBot Full: lo que Mercado Libre informa de cada producto en Full (ventas y recomendación de reposición).
-- Tabla nueva ml_reposicion: una fila por publicación con las unidades vendidas de los últimos 30 días y de las últimas
-- semanas según ML, y lo que ML recomienda reponer. Sirve para mostrar "Venta/día ML" al lado de la de EnvioBot.
-- NO aplicar con el servicio prendido. Orden: apagar enviobot-full, respaldo, aplicar, prender, verificar.
-- Se puede correr dos veces sin efecto. Sin esta migración el panel igual funciona: simplemente no muestra la columna de ML.
SET SESSION lock_wait_timeout = 10;

CREATE TABLE IF NOT EXISTS ml_reposicion (
    user_id         INT         NOT NULL,
    item_id         VARCHAR(50) NOT NULL,
    user_product_id VARCHAR(50) NULL,
    unidades_30d    INT         NULL,
    semanas         VARCHAR(120) NULL,          -- unidades por semana, de la más nueva a la más vieja: "63,178,128,107,110"
    sugerido        INT         NULL,           -- unidades que ML recomienda reponer
    urgencia        VARCHAR(30) NULL,           -- THIS_WEEK, NEXT_WEEK, IN_TWO_WEEKS, NO_URGENCY, EXCEDENT...
    stock_total     INT         NULL,
    actualizado     TIMESTAMP   NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, item_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
