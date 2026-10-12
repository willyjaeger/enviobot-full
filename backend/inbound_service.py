"""
inbound_service.py - Módulo de Colectas y Envíos Inbound a Mercado Libre Full
Maneja la generación de remitos oficiales imprimibles, cálculo de bultos y sincronización con MeLi.
"""

from datetime import datetime
import json
import html

def generate_barcode_svg(code_text: str) -> str:
    """Genera una representación visual de código de barras limpia en SVG."""
    # Patrón decorativo / funcional visual de barras basado en el hash del texto
    bars = []
    x = 10
    h = 55
    # Starter guard
    bars.append(f'<rect x="{x}" y="0" width="3" height="{h}" fill="#111" />')
    x += 5
    bars.append(f'<rect x="{x}" y="0" width="1.5" height="{h}" fill="#111" />')
    x += 4

    for char in code_text:
        val = ord(char) % 8 + 1
        w1 = 1.5 if val % 2 == 0 else 3.5
        w2 = 3.0 if val % 3 == 0 else 1.5
        bars.append(f'<rect x="{x}" y="0" width="{w1}" height="{h}" fill="#111" />')
        x += w1 + 2
        bars.append(f'<rect x="{x}" y="0" width="{w2}" height="{h}" fill="#111" />')
        x += w2 + 3

    # End guard
    bars.append(f'<rect x="{x}" y="0" width="3" height="{h}" fill="#111" />')
    x += 5
    bars.append(f'<rect x="{x}" y="0" width="1.5" height="{h}" fill="#111" />')
    x += 10

    svg = f'<svg width="{x}" height="{h + 18}" viewBox="0 0 {x} {h + 18}" xmlns="http://www.w3.org/2000/svg">'
    svg += "".join(bars)
    svg += f'<text x="{x / 2}" y="{h + 14}" font-family="Courier, monospace" font-size="12" font-weight="700" text-anchor="middle" fill="#222">{html.escape(code_text)}</text>'
    svg += '</svg>'
    return svg

def render_remito_html(shipment: dict, items: list) -> str:
    """Genera el remito oficial de entrega a Mercado Envíos Full listo para imprimir en A4."""
    code = shipment.get("shipment_code", "COL-FULL-PENDING")
    barcode_svg = generate_barcode_svg(code)
    
    fecha_emision = datetime.now().strftime("%d/%m/%Y %H:%M")
    pickup_date = shipment.get("pickup_date") or "A coordinar"
    if hasattr(pickup_date, "strftime"):
        pickup_date = pickup_date.strftime("%d/%m/%Y")
    elif isinstance(pickup_date, str) and "-" in pickup_date:
        parts = pickup_date.split("-")
        if len(parts) == 3:
            pickup_date = f"{parts[2]}/{parts[1]}/{parts[0]}"
            
    vendedor_nombre = shipment.get("business_name") or shipment.get("full_name") or "Vendedor EnvioBot"
    cuit = shipment.get("cuit") or "No informado"
    email = shipment.get("email") or ""
    telefono = shipment.get("phone") or ""
    notas = shipment.get("carrier_notes") or "Sin observaciones particulares de transporte."
    
    total_unidades = shipment.get("total_units", 0)
    total_bultos = shipment.get("total_boxes", 1)
    packaging_type = shipment.get("packaging_type", "cajas_master")
    packaging_label = {
        "cajas_master": "Cajas Máster Rotuladas",
        "bultos_sueltos": "Bultos / Cajas Mixtas",
        "pallet": "Pallet Filmado"
    }.get(packaging_type, "Cajas Máster")

    # Filas de ítems
    rows_html = []
    box_num = 1
    for idx, it in enumerate(items, 1):
        sku = html.escape(it.get("sku") or "Sin SKU")
        inv_id = html.escape(it.get("inventory_id") or "N/A")
        title = html.escape(it.get("title") or "Producto")
        var_name = html.escape(it.get("variation_name") or "")
        var_badge = f'<span class="var-badge">{var_name}</span>' if var_name else ''
        units = it.get("units_to_send", 0)
        box_count = it.get("box_count", 1)
        units_per_box = it.get("units_per_box", 0)
        
        box_text = f"Caja {box_num}" if box_count == 1 else f"Cajas {box_num} a {box_num + box_count - 1}"
        if units_per_box > 0:
            box_text += f" ({units_per_box} un/caja)"
        box_num += box_count

        rows_html.append(f"""
        <tr>
            <td style="text-align: center; font-weight: 700;">{idx}</td>
            <td>
                <strong>{sku}</strong>
                <div style="font-size: 11px; color: #555;">MeLi Inv: <code>{inv_id}</code></div>
            </td>
            <td>
                {title} {var_badge}
            </td>
            <td style="text-align: center; font-size: 12px; color: #333;">
                {box_text}
            </td>
            <td style="text-align: right; font-weight: 800; font-size: 14px;">
                {units} un.
            </td>
            <td style="text-align: center; width: 45px;">
                <div class="check-box-square"></div>
            </td>
        </tr>
        """)

    table_rows = "".join(rows_html)

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <title>Remito Colecta Full - {code}</title>
    <style>
        @page {{
            size: A4 portrait;
            margin: 12mm 15mm;
        }}
        * {{
            box-sizing: border-box;
            -webkit-print-color-adjust: exact;
            print-color-adjust: exact;
        }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            background: #fff;
            color: #111;
            margin: 0;
            padding: 20px;
            font-size: 13px;
            line-height: 1.4;
        }}
        .no-print-bar {{
            background: #f0f4f8;
            border: 1px solid #cce;
            padding: 12px 18px;
            border-radius: 8px;
            margin-bottom: 20px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}
        .print-btn {{
            background: #ffe600;
            color: #111;
            border: 1px solid #d4c000;
            padding: 8px 18px;
            font-size: 14px;
            font-weight: 700;
            border-radius: 6px;
            cursor: pointer;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        .print-btn:hover {{
            background: #ffd000;
        }}
        .remito-card {{
            border: 2px solid #222;
            border-radius: 8px;
            padding: 18px;
        }}
        .header-grid {{
            display: grid;
            grid-template-columns: 1.2fr 1fr 1.2fr;
            gap: 15px;
            border-bottom: 2px solid #222;
            padding-bottom: 14px;
            margin-bottom: 14px;
            align-items: center;
        }}
        .logo-box h1 {{
            margin: 0;
            font-size: 22px;
            font-weight: 900;
            letter-spacing: -0.5px;
            color: #0b132b;
        }}
        .logo-box p {{
            margin: 2px 0 0;
            font-size: 11px;
            color: #555;
            font-weight: 600;
            text-transform: uppercase;
        }}
        .doc-type-box {{
            text-align: center;
            border: 1.5px solid #222;
            padding: 6px;
            border-radius: 6px;
            background: #fafafa;
        }}
        .doc-type-box .letter {{
            font-size: 24px;
            font-weight: 900;
            line-height: 1;
        }}
        .doc-type-box .type-title {{
            font-size: 11px;
            font-weight: 700;
            text-transform: uppercase;
            margin-top: 2px;
        }}
        .barcode-box {{
            text-align: right;
        }}
        .info-grid {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 15px;
            margin-bottom: 14px;
        }}
        .info-panel {{
            border: 1px solid #ccc;
            border-radius: 6px;
            padding: 10px 14px;
            background: #fbfbfb;
        }}
        .info-panel h3 {{
            margin: 0 0 6px 0;
            font-size: 12px;
            font-weight: 800;
            text-transform: uppercase;
            color: #2b3a4a;
            border-bottom: 1px solid #ddd;
            padding-bottom: 4px;
        }}
        .info-line {{
            font-size: 12px;
            margin-bottom: 3px;
        }}
        .info-line strong {{
            color: #222;
        }}
        .summary-banner {{
            background: #eef5fc;
            border: 1.5px solid #b8daff;
            border-radius: 6px;
            padding: 10px 14px;
            margin-bottom: 14px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            font-size: 13px;
        }}
        .summary-metric {{
            text-align: center;
        }}
        .summary-metric .val {{
            font-size: 18px;
            font-weight: 900;
            color: #0b132b;
        }}
        .summary-metric .lbl {{
            font-size: 11px;
            color: #555;
            text-transform: uppercase;
            font-weight: 600;
        }}
        table.items-table {{
            width: 100%;
            border-collapse: collapse;
            margin-bottom: 16px;
            font-size: 12px;
        }}
        table.items-table th {{
            background: #f0f0f0;
            border: 1px solid #aaa;
            padding: 7px 8px;
            font-size: 11px;
            font-weight: 800;
            text-transform: uppercase;
            color: #333;
        }}
        table.items-table td {{
            border: 1px solid #ccc;
            padding: 6px 8px;
            vertical-align: middle;
        }}
        .var-badge {{
            display: inline-block;
            background: #e2e8f0;
            color: #334155;
            padding: 1px 6px;
            border-radius: 4px;
            font-size: 10.5px;
            font-weight: 700;
            margin-left: 4px;
        }}
        .check-box-square {{
            width: 16px;
            height: 16px;
            border: 1.5px solid #666;
            margin: 0 auto;
            border-radius: 3px;
        }}
        .signatures-grid {{
            display: grid;
            grid-template-columns: 1fr 1fr 1fr;
            gap: 15px;
            margin-top: 25px;
            padding-top: 10px;
        }}
        .sign-box {{
            border: 1px solid #999;
            border-radius: 6px;
            padding: 10px;
            height: 100px;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
            background: #fff;
        }}
        .sign-line {{
            border-top: 1px dashed #777;
            text-align: center;
            font-size: 11px;
            font-weight: 700;
            color: #444;
            padding-top: 4px;
        }}
        .footer-notes {{
            margin-top: 14px;
            padding-top: 8px;
            border-top: 1px solid #ddd;
            font-size: 10px;
            color: #666;
            text-align: center;
        }}
        @media print {{
            .no-print-bar {{
                display: none !important;
            }}
            body {{
                padding: 0;
            }}
            .remito-card {{
                border: 1.5px solid #111;
            }}
        }}
    </style>
</head>
<body>

    <div class="no-print-bar">
        <div>
            <strong>Hoja de Despacho y Remito Oficial Full</strong> — Listo para imprimir en hoja A4 y entregar al transportista / depósito MeLi.
        </div>
        <button class="print-btn" onclick="window.print()">Imprimir Remito / Guardar PDF</button>
    </div>

    <div class="remito-card">
        <!-- Encabezado -->
        <div class="header-grid">
            <div class="logo-box">
                <h1>ENVIOBOT FULL</h1>
                <p>Logística de Entrada & Colecta</p>
                <div style="font-size: 11.5px; margin-top: 4px; color: #444;">
                    Emisión: <strong>{fecha_emision}</strong>
                </div>
            </div>

            <div class="doc-type-box">
                <div class="letter">R</div>
                <div class="type-title">Remito de Colecta Full</div>
                <div style="font-size: 10px; color: #555;">No válido como factura</div>
            </div>

            <div class="barcode-box">
                {barcode_svg}
            </div>
        </div>

        <!-- Paneles de Emisor y Destino -->
        <div class="info-grid">
            <div class="info-panel">
                <h3>1. Despachador (Vendedor)</h3>
                <div class="info-line">Razón Social: <strong>{vendedor_nombre}</strong></div>
                <div class="info-line">CUIT: <strong>{cuit}</strong></div>
                <div class="info-line">Contacto: <strong>{telefono or email}</strong></div>
                <div class="info-line">Fecha Salida / Colecta: <strong>{pickup_date}</strong></div>
            </div>

            <div class="info-panel">
                <h3>2. Depósito Receptor (Mercado Libre)</h3>
                <div class="info-line">Centro: <strong>Mercado Envíos Full (Villa Celina)</strong></div>
                <div class="info-line">Dirección: <strong>Autopista Riccheri y Av. Boulogne Sur Mer</strong></div>
                <div class="info-line">Localidad: <strong>Villa Celina, La Matanza (PBA)</strong></div>
                <div class="info-line">Tipo Operación: <strong>Inbound Replenishment / Colecta</strong></div>
            </div>
        </div>

        <!-- Resumen Métrico de Carga -->
        <div class="summary-banner">
            <div class="summary-metric">
                <div class="val">{len(items)}</div>
                <div class="lbl">SKUs Distintos</div>
            </div>
            <div class="summary-metric">
                <div class="val" style="color: #0056b3;">{total_bultos}</div>
                <div class="lbl">Total Cajas / Bultos</div>
            </div>
            <div class="summary-metric">
                <div class="val" style="color: #28a745;">{total_unidades} un.</div>
                <div class="lbl">Unidades Totales</div>
            </div>
            <div class="summary-metric">
                <div class="val" style="font-size: 14px;">{packaging_label}</div>
                <div class="lbl">Formato Embalaje</div>
            </div>
        </div>

        <!-- Observaciones de Transporte -->
        <div style="background: #fff8e1; border: 1px solid #ffe082; padding: 7px 12px; border-radius: 6px; font-size: 11.5px; margin-bottom: 12px;">
            <strong>Observaciones de Colecta / Chofer:</strong> {html.escape(notas)}
        </div>

        <!-- Tabla de Productos y Bultos -->
        <table class="items-table">
            <thead>
                <tr>
                    <th style="width: 30px; text-align: center;">#</th>
                    <th style="width: 130px;">SKU / Inv ID</th>
                    <th>Descripción de la Publicación</th>
                    <th style="width: 140px; text-align: center;">Rotulación Bulto</th>
                    <th style="width: 90px; text-align: right;">Cantidad</th>
                    <th style="width: 45px; text-align: center;" title="Control de Recepción en Depósito">Check</th>
                </tr>
            </thead>
            <tbody>
                {table_rows}
            </tbody>
        </table>

        <!-- Cuadros de Firmas -->
        <div class="signatures-grid">
            <div class="sign-box">
                <div style="font-size: 10px; color: #666;">Firma y Aclaración:</div>
                <div class="sign-line">Despachante / Emisor</div>
            </div>
            <div class="sign-box">
                <div style="font-size: 10px; color: #666;">Firma y DNI / Patente:</div>
                <div class="sign-line">Chofer / Transporte Colecta</div>
            </div>
            <div class="sign-box">
                <div style="font-size: 10px; color: #666;">Firma, Sello y Fecha:</div>
                <div class="sign-line">Receptor MeLi Full (Villa Celina)</div>
            </div>
        </div>

        <!-- Pie legal -->
        <div class="footer-notes">
            Generado automáticamente por el Módulo de Colectas de <strong>EnvioBot Full</strong> ({code}). Los bultos deben viajar identificados según la normativa de empaque de Mercado Libre Fulfillment.
        </div>
    </div>

</body>
</html>
"""
