# Guía de Importación y Edición en CorelDRAW — EnvioBot Full

Esta guía detalla cómo abrir, editar y exportar los archivos vectoriales oficiales de **EnvioBot Full** en **CorelDRAW** (compatible con CorelDRAW X7, 2018, 2020, 2022, 2024 y versiones superiores).

---

## 📁 Archivos Disponibles en `/docs`

| Archivo | Contenido | Propósito |
|---|---|---|
| `whatsapp-profile-enviobot-full-corel.svg` | Fondo negro 1024×1024 + Cajita centrada | **Avatar oficial para WhatsApp Business** (listo para editar o exportar). |
| `icon-cajita-enviobot-corel.svg` | Cajita aislada con curvas Bézier estándar | Icono suelto para usar en folletos, membretes o packaging. |
| `logo-enviobot-full-corel.svg` | Cajita + Wordmark *"EnvioBot Full"* | Logotipo horizontal institucional para web, banners y papelería. |
| `icon-cajita-enviobot.svg` | SVG web estándar (24×24 viewBox) | Fuente de verdad para desarrollo web y apps. |

---

## 🚀 Pasos para Importar en CorelDRAW

### 1. Abrir o Importar en un documento nuevo
1. Abre CorelDRAW y crea un documento nuevo (o abre uno existente).
2. Ve a **Archivo > Importar** (o presiona `Ctrl + I`).
3. Busca la carpeta del proyecto:
   ```
   C:\Proyecto\Enviobot Full\docs\
   ```
4. Selecciona `whatsapp-profile-enviobot-full-corel.svg` (o el archivo que desees).
5. Haz clic en **Importar** y colócalo en el espacio de trabajo.

### 2. Desagrupar y Convertir a Curvas (`Ctrl + Q`)
Los archivos ya vienen con las curvas Bézier calculadas con precisión matemática para CorelDRAW.
- Para editar los trazos de forma independiente:
  1. Selecciona el objeto importado.
  2. Presiona `Ctrl + U` (Desagrupar).
  3. Ahora tienes por separado:
     - El **Fondo negro** (rectángulo de 1024×1024 px).
     - El **Contorno exterior de la cajita** (con las 6 esquinas redondeadas $R=2.5$).
     - La **Arista superior** (pliegue de la tapa).
     - La **Arista frontal** (eje vertical).

---

## 🎨 Modificar Colores y Trazos en CorelDRAW

### Cambiar el color de la Cajita
1. Selecciona las 3 partes de la cajita.
2. Haz clic derecho sobre el color que desees en la paleta de colores lateral:
   - **Naranja oficial:** `#f5a623` (RGB: 245, 166, 35)
   - **Blanco:** `#ffffff` (para versiones monocromáticas)
   - **Amarillo dorado:** `#f7b238`

### Cambiar el grosor del trazo
1. Selecciona el trazado.
2. Presiona `F12` (Pluma de contorno).
3. Ajusta el grosor según la escala que estés usando. Asegúrate de tener activada la opción:
   - **Esquinas redondeadas**
   - **Extremos redondeados**
   - **"Detrás del relleno" / "Escalar con objeto"** (muy recomendado si vas a achicar o agrandar el logo).

---

## 📲 Exportar para WhatsApp Business

Si realizaste cambios en CorelDRAW y quieres exportar una imagen lista para subir a WhatsApp:

1. Selecciona el fondo negro junto con la cajita.
2. Ve a **Archivo > Exportar** (o presiona `Ctrl + E`).
3. Elige formato **PNG - Portable Network Graphics**.
4. En el diálogo de exportación de CorelDRAW:
   - **Ancho:** `1024 px` (o `500 px`)
   - **Alto:** `1024 px` (o `500 px`)
   - **Modo de color:** RGB (24 bits)
   - **Resolución:** `72 dpi` (o `300 dpi`)
   - **Fondo transparente:** Desactivado (debe quedar con fondo negro sólido `#000000`).
5. Haz clic en **Aceptar**.

> **Nota:** WhatsApp Business recorta automáticamente las fotos de perfil en círculo. La cajita ya está calculada exactamente con el tamaño y margen necesarios para que al aplicar el círculo nunca toque los bordes y quede perfectamente centrada.
