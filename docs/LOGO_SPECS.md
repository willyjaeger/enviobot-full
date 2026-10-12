# EnvioBot Full — Especificaciones del logo

El logo oficial de **EnvioBot Full** se compone de un **icono SVG de cajita isométrica (24×24, solo trazo con esquinas redondeadas R=2.5) + wordmark "EnvioBot Full"** en texto.
No hay PNG ni otro archivo de marca para interfaces web: la fuente de verdad es el SVG vectorial.

---

## Icono Oficial (SVG, copiar tal cual)

```svg
<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#f5a623" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" xmlns="http://www.w3.org/2000/svg">
  <!-- Contorno exterior con esquinas redondeadas R=2.5 (mismo estilo que EnvioBot Pedidos) -->
  <path d="M 13.21 2.97 L 19.71 6.59 A 2.50 2.50 0 0 1 21.00 8.77 L 21.00 15.23 A 2.50 2.50 0 0 1 19.71 17.41 L 13.21 21.03 A 2.50 2.50 0 0 1 10.79 21.03 L 4.29 17.41 A 2.50 2.50 0 0 1 3.00 15.23 L 3.00 8.77 A 2.50 2.50 0 0 1 4.29 6.59 L 10.79 2.97 A 2.50 2.50 0 0 1 13.21 2.97 Z"></path>
  <!-- Aristas interiores de la caja isométrica -->
  <polyline points="3.4 7.1 12 12 20.6 7.1"></polyline>
  <line x1="12" y1="21.1" x2="12" y2="12"></line>
</svg>
```

Archivos maestros:
- `docs/icon-cajita-enviobot.svg` (Web / SVG estándar)
- `docs/icon-cajita-enviobot-corel.svg` (Variante optimizada para CorelDRAW con curvas Bézier estándar)
- `docs/whatsapp-profile-enviobot-full-corel.svg` (Variante fondo negro 1024×1024 para WhatsApp Business)
- `docs/logo-enviobot-full-corel.svg` (Logotipo institucional completo)

### Propiedades Técnicas del Icono

| Propiedad | Valor |
|---|---|
| **viewBox** | `0 0 24 24` |
| **Relleno** | `none` (solo contorno lineal) |
| **Color de trazo** | `#f5a623` (naranja dorado oficial) |
| **Grosor de trazo** | `1.8` (o `1.7` sobre escala 24 px) |
| **Terminaciones / uniones** | `stroke-linecap="round"` / `stroke-linejoin="round"` |
| **Radio de esquinas** | `R = 2.5` (curvatura suave armonizada con el icono de EnvioBot Pedidos) |
| **Elementos** | Contorno exterior (path hexagonal redondeado de 6 esquinas), pliegue superior (polyline 3 puntos), eje frontal (line vertical centrada) |

---

## Wordmark (texto "EnvioBot Full")

Estructura institucional del texto:

| Propiedad | Valor |
|---|---|
| **Texto** | `EnvioBot Full` (E, B y F mayúsculas, espacio antes de Full) |
| **Fuente** | `-apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif` (alternativa: `Inter`) |
| **Peso tipográfico** | `800` (Extra Bold) |
| **Tamaño** | `19px` en topbar / dashboard (`20px` en login y landing) |
| **Letter-spacing** | `-0.2px` |
| **Color "EnvioBot"** | `#e8e9ed` (sobre fondos oscuros) / `#1a1c22` (modo claro) |
| **Color "Full"** | `#f5a623` (`var(--accent)`) |
| **Disposición** | Icono a la izquierda (`22px` a `24px`), `gap: 10px`, alineado verticalmente al centro |

### Implementación en HTML / CSS

```html
<a href="#" class="logo-wrap">
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#f5a623" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
        <path d="M 13.21 2.97 L 19.71 6.59 A 2.50 2.50 0 0 1 21.00 8.77 L 21.00 15.23 A 2.50 2.50 0 0 1 19.71 17.41 L 13.21 21.03 A 2.50 2.50 0 0 1 10.79 21.03 L 4.29 17.41 A 2.50 2.50 0 0 1 3.00 15.23 L 3.00 8.77 A 2.50 2.50 0 0 1 4.29 6.59 L 10.79 2.97 A 2.50 2.50 0 0 1 13.21 2.97 Z"></path>
        <polyline points="3.4 7.1 12 12 20.6 7.1"></polyline>
        <line x1="12" y1="21.1" x2="12" y2="12"></line>
    </svg>
    <span style="font-weight: 800; font-size: 19px; letter-spacing: -0.2px; color: var(--text);">EnvioBot <span style="color: var(--accent);">Full</span></span>
</a>
```

---

## Paleta de Colores Corporativa

| Token CSS | Hex | Uso |
|---|---|---|
| `--accent` | `#f5a623` | Trazo de la cajita, palabra "Full", botones de acción primaria |
| `--accent-d` | `#c97f10` | Hover activo y variantes de acento |
| `--bg` | `#111318` | Fondo principal oscuro del panel |
| `--surface` | `#1c1e26` | Fondo de cards, navbar y contenedor de logo |
| `--surf2` | `#252830` | Superficies terciarias y selectores anidados |
| `--text` | `#e8e9ed` | Texto principal ("EnvioBot", títulos) |
| `--text2` | `#8a8d9a` | Texto secundario y subtítulos |
| `--border` | `rgba(255, 255, 255, 0.07)` | Delimitadores sutiles de interfaz |

---

## Tamaños Recomendados por Aplicación

| Uso | Tamaño | Formato |
|---|---|---|
| **Topbar / Navbar** | 22–24 px | SVG en línea |
| **Botones / Acciones** | 16–20 px | SVG en línea |
| **Favicon de Navegador** | 16–32 px | SVG data-uri o PNG |
| **Icono de Escritorio Windows** | 16, 32, 48, 64, 128, 256 px | `icon.ico` multi-resolución |
| **WhatsApp Business Profile** | 1024×1024 px (centrado) | `docs/whatsapp-profile-enviobot-full.png` o `.svg` |
| **Portadas y Cartelería** | 100 mm a 500 mm | SVG CorelDRAW (`docs/*-corel.svg`) |

---

## Ecosistema de Marca (EnvioBot Pedidos vs EnvioBot Full)

La identidad visual de **EnvioBot** se estructura bajo una misma familia gráfica:

1. **EnvioBot Pedidos** *(antes EnvioBot)*:
   - **Icono:** Impresora térmica con rollo de etiquetas (contorno lineal `#f5a623`, trazo 1.7, esquinas redondeadas `rx="2.5"`).
   - **Propósito:** Gestión y despacho de pedidos locales y etiquetas térmicas.
2. **EnvioBot Full**:
   - **Icono:** Cajita de cartón isométrica (contorno lineal `#f5a623`, trazo 1.8, esquinas redondeadas `R=2.5`).
   - **Propósito:** Monitoreo y reposición de inventario en bodegas de Mercado Envíos Full.

Ambos iconos comparten el mismo grosor visual, color `#f5a623`, redondeo armónico y estilo outline sobre fondos oscuros.
