# EnvioBot Full 📦

SaaS complementario para vendedores de **MercadoLibre Argentina** que utilizan **Mercado Envíos Full**.
Monitorea inventario en bodega, calcula la rotación y velocidad de venta diaria ($VPD$) y proyecta la **fecha estimada de quiebre de stock** con alertas anticipadas para preparar despachos con tiempo suficiente ($X$ días de antelación).

---

## 🛠️ Stack Tecnológico

* **Frontend:** HTML5, CSS3 y JavaScript Vanilla (sin frameworks pesados), con el mismo diseño, paleta y modo alto contraste de `enviobot.com.ar/app`.
* **Backend:** Python Flask (API REST) + Flask-JWT-Extended + PyMySQL + Requests.
* **Base de Datos:** MySQL / MariaDB (`enviobot_full`).
* **Sincronización:** `worker.py` ejecutado periódicamente vía Cron en servidor Linux (DonWeb VPS).

---

## 📂 Estructura del Proyecto

```text
enviobot-full/
├── backend/
│   ├── app.py               # API REST principal (Auth, OAuth MeLi, Items, Settings)
│   ├── worker.py            # Motor de sincronización y cálculo de quiebre de stock
│   ├── schema.sql           # Esquema de base de datos MySQL
│   ├── requirements.txt     # Dependencias Python
│   └── .env.example         # Variables de entorno
├── frontend/
│   ├── index.html           # Panel de control con semáforo y calculadora
│   ├── login.html           # Inicio de sesión
│   ├── css/
│   │   └── style.css        # Paleta oscura #111318 + acento ámbar #f5a623 + modo claro
│   └── js/
│       ├── app.js           # Lógica interactiva de tabla, cálculo y filtros
│       └── theme.js         # Selector de tema oscuro / claro sin parpadeo
└── README.md
```

---

## 🚀 Puesta en Marcha Local

### 1. Requisitos previos
* Python 3.9+
* Servidor MySQL local (XAMPP, Docker o nativo)

### 2. Configurar Base de Datos
Importá el esquema en tu MySQL local:
```bash
mysql -u root -p < backend/schema.sql
```

### 3. Configurar Backend
```bash
cd backend
python -m venv venv
# En Windows:
.\venv\Scripts\activate
# En Linux/Mac:
source venv/bin/activate

pip install -r requirements.txt
cp .env.example .env
```
Editá `.env` con tus credenciales de base de datos y de la aplicación de MercadoLibre.

### 4. Iniciar Servidor
```bash
python app.py
```
Abrí tu navegador en `http://localhost:5001`.

> **Nota:** Si abrís `frontend/index.html` directamente haciendo doble clic (sin backend corriendo), el panel cargará automáticamente un dataset de demostración interactivo para que puedas probar los filtros, el semáforo y la calculadora de inmediato.

---

## ⏱️ Configuración del Cron en DonWeb VPS

Para que el sistema analice los saldos de stock de todos los clientes cada 4 horas automáticamente, programá en el crontab del servidor Linux:

```bash
crontab -e
```
Agregá la línea:
```cron
0 */4 * * * /var/www/enviobot-full/backend/venv/bin/python /var/www/enviobot-full/backend/worker.py >> /var/log/enviobot_full.log 2>&1
```

---

## 📐 Modelo de Pronóstico de Quiebre

1. **Venta Promedio Diaria Ponderada ($VPD$):**
   $$\text{VPD} = 0.50 \times \left(\frac{\text{Ventas 7d}}{7}\right) + 0.35 \times \left(\frac{\text{Ventas 15d}}{15}\right) + 0.15 \times \left(\frac{\text{Ventas 30d}}{30}\right)$$

2. **Días de Cobertura Restantes:**
   $$\text{Días Restantes} = \frac{\text{Stock Disponible en Full}}{\text{VPD}}$$

3. **Disparo de Alertas:**
   * **🔴 Riesgo Crítico:** $\text{Días Restantes} \le \text{Lead Time}$ (Ya no llegás a reponer sin quebrar).
   * **🟡 Preparar Envío:** $\text{Días Restantes} \le (\text{Lead Time} + \text{Buffer})$ (**MOMENTO EXACTO DE ACCIÓN**).
   * **🟢 Óptimo:** $\text{Días Restantes} > (\text{Lead Time} + \text{Buffer})$.
