# -*- coding: utf-8 -*-
import io
import re
import numpy as np
import pandas as pd
import streamlit as st

# ==========================
# Helpers UI (subtítulo con "i")
# ==========================
def section_header(title: str, help_text: str):
    left, right = st.columns([1, 0.06])
    with left:
        st.subheader(title)
    with right:
        if hasattr(st, "popover"):
            with st.popover("ℹ️"):
                st.markdown(help_text)
        else:
            with st.expander("ℹ️"):
                st.markdown(help_text)

def chart_header(title: str, help_text: str):
    left, right = st.columns([1, 0.06])
    with left:
        st.subheader(title)
    with right:
        if hasattr(st, "popover"):
            with st.popover("ℹ️"):
                st.markdown(help_text)
        else:
            with st.expander("ℹ️"):
                st.markdown(help_text)

# ==========================
# Mapeo automático de columnas
# ==========================
_SYNONYMS = {
    "party": [
        "proveedor", "supplier", "vendor", "razon social", "razón social",
        "cliente", "customer", "customername", "nombrecliente", "customer name",
        "partner", "tercero"
    ],
    "invoice": [
        "n° factura", "nº factura", "no factura", "numero factura", "nro factura",
        "invoice", "invoice number", "invoicenumber", "numfactura", "factura",
        "doc", "documento", "comprobante"
    ],
    "date": [
        "fecha", "fecha emision", "fecha emisión", "invoice date", "invoicedate",
        "fecha factura", "f.emision", "f emision", "fechaemision", "fecha emision"
    ],
    "amount": [
        "monto", "valor", "subtotal", "amount", "base", "neto", "importe"
    ],
    "tax": [
        "iva", "tax", "impuesto", "vat"
    ],
    "total": [
        "total", "total factura", "monto total", "grand total", "importe total"
    ],
}

def _norm_colname(s: str) -> str:
    s = s.strip().lower()
    s = re.sub(r"[_\-\.\s]+", " ", s)
    s = (s.replace("á", "a").replace("é", "e").replace("í", "i")
           .replace("ó", "o").replace("ú", "u").replace("ñ", "n"))
    return s

def _find_first(cols_norm, keys):
    for c, n in cols_norm.items():
        for k in keys:
            if n == k or n.endswith(" "+k) or k in n:
                return c
    return None

def auto_map_columns(df: pd.DataFrame):
    cols_norm = {c: _norm_colname(c) for c in df.columns}
    party_col   = _find_first(cols_norm, _SYNONYMS["party"])
    invoice_col = _find_first(cols_norm, _SYNONYMS["invoice"])
    date_col    = _find_first(cols_norm, _SYNONYMS["date"])
    amount_col  = _find_first(cols_norm, _SYNONYMS["amount"])
    tax_col     = _find_first(cols_norm, _SYNONYMS["tax"])
    total_col   = _find_first(cols_norm, _SYNONYMS["total"])

    # Si no hay total, derivarlo si existen amount e impuesto
    if total_col is None and amount_col is not None and tax_col is not None:
        try:
            df["__TotalDerived"] = pd.to_numeric(df[amount_col], errors="coerce") + pd.to_numeric(df[tax_col], errors="coerce")
            total_col = "__TotalDerived"
        except Exception:
            pass

    label = "Proveedor/Cliente"
    if party_col:
        nn = _norm_colname(party_col)
        if any(k in nn for k in ["proveedor", "supplier", "vendor"]):
            label = "Proveedor"
        elif any(k in nn for k in ["cliente", "customer"]):
            label = "Cliente"

    cols = dict(
        party=party_col,
        invoice=invoice_col,
        date=date_col,
        amount=amount_col,
        tax=tax_col,
        total=total_col,
        label=label,
    )
    return df, cols

# ==========================
# Carga de archivo
# ==========================
def load_file(uploaded):
    if uploaded is None:
        return None
    name = uploaded.name.lower()
    try:
        if name.endswith(".csv"):
            df = pd.read_csv(uploaded, encoding="utf-8-sig")
        elif name.endswith(".xlsx") or name.endswith(".xls"):
            df = pd.read_excel(uploaded)
        else:
            st.error("Formato no soportado. Sube CSV o Excel.")
            return None
        return df
    except Exception as e:
        st.error(f"No se pudo leer el archivo: {e}")
        return None

# ==========================
# Reglas de duplicados (flexibles)
# ==========================
def compute_duplicates_flexible(df: pd.DataFrame, PARTY_COL, INVOICE_COL, DATE_COL, TOTAL_COL):
    """Devuelve:
    - d_all, d_extra: máscaras booleanas
    - total, dup_exceso, pct
    - regla_usada: texto de la regla aplicada
    - keys: lista de columnas usadas como llave
    """
    # Tipos
    if DATE_COL and DATE_COL in df.columns:
        df[DATE_COL] = pd.to_datetime(df[DATE_COL], errors="coerce")
    if TOTAL_COL and TOTAL_COL in df.columns:
        df[TOTAL_COL] = pd.to_numeric(df[TOTAL_COL], errors="coerce")

    # Prioridad de llaves según disponibilidad
    candidates = []
    if PARTY_COL and INVOICE_COL and TOTAL_COL:
        candidates.append((["party+invoice+total", [PARTY_COL, INVOICE_COL, TOTAL_COL]]))
    if PARTY_COL and INVOICE_COL:
        candidates.append((["party+invoice", [PARTY_COL, INVOICE_COL]]))
    if PARTY_COL and DATE_COL and TOTAL_COL:
        candidates.append((["party+date+total", [PARTY_COL, DATE_COL, TOTAL_COL]]))
    if INVOICE_COL:
        candidates.append((["invoice", [INVOICE_COL]]))
    if PARTY_COL and TOTAL_COL:
        candidates.append((["party+total", [PARTY_COL, TOTAL_COL]]))

    if not candidates:
        return (pd.Series(False, index=df.index),
                pd.Series(False, index=df.index),
                int(len(df)), 0, 0.0, "sin-regla", [])

    # Toma la primera llave disponible
    regla_tag, keys = candidates[0]
    # Cálculo
    d_all = df.duplicated(subset=keys, keep=False)
    d_extra = df.duplicated(subset=keys, keep="first")

    # Etiqueta de regla legible
    regla_map = {
        "party+invoice+total": "Exacto (Parte+Número+Total)",
        "party+invoice": "Exacto (Parte+Número)",
        "party+date+total": "Combo (Parte+Fecha+Total)",
        "invoice": "Número global repetido",
        "party+total": "Parte+Total repetidos"
    }
    df["_regla"] = np.where(d_all, regla_map.get(regla_tag, regla_tag), "")

    total = int(len(df))
    dup_exceso = int(d_extra.sum())
    pct = (dup_exceso / total) if total else 0.0
    return d_all, d_extra, total, dup_exceso, pct, regla_map.get(regla_tag, regla_tag), keys

# ==========================
# Exportar Excel con Hallazgos
# ==========================
def export_to_excel(df_base: pd.DataFrame, df_tabla: pd.DataFrame, alerts=None, concl=None, recs=None) -> bytes:
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        # Base
        df_base.to_excel(writer, index=False, sheet_name="Base")
        # Tabla de duplicados
        df_tabla.to_excel(writer, index=False, sheet_name="Duplicados")
        # Hallazgos
        def _pad(lst, n):
            return (lst or []) + [""] * (n - len(lst or []))
        m = max(1, len(alerts or []), len(concl or []), len(recs or []))
        hallazgos = pd.DataFrame({
            "Alertas": _pad(alerts, m),
            "Conclusiones": _pad(concl, m),
            "Recomendaciones": _pad(recs, m)
        })
        hallazgos.to_excel(writer, index=False, sheet_name="Hallazgos")
    output.seek(0)
    return output.read()

# ==========================
# APP
# ==========================
st.set_page_config(page_title="Detección de Facturas Duplicadas", layout="wide")
st.title("Detección de facturas duplicadas")

# --- Sección: Carga y mapeo ---
section_header("Mapeo de columnas", """
**Objetivo:** Seleccionar las columnas que usa el análisis como *Parte* (Proveedor/Cliente), *Número de factura*, *Fecha* y *Total*.
**Cómo funciona:**
1) La app intenta mapear automáticamente nombres comunes (ej. 'razón social', 'invoice', 'fecha', 'total').
2) Puedes ajustar manualmente con los selectores.
**Sugerencia:** Para mejores resultados, completa al menos una de estas combinaciones:
- Parte + Número (exacto).
- Parte + Fecha + Total (combo).
- Sólo Número (si los números son únicos globalmente).
""")

uploaded = st.file_uploader("Sube un archivo CSV o Excel", type=["csv", "xlsx", "xls"])
df = load_file(uploaded)

if df is not None and len(df):
    df, cols = auto_map_columns(df)

    all_cols = ["(ninguna)"] + list(df.columns)

    PARTY_COL = st.selectbox("Columna Parte (Proveedor/Cliente)", all_cols,
                             index=all_cols.index(cols.get("party")) if cols.get("party") in all_cols else 0)
    INVOICE_COL = st.selectbox("Columna Número de Factura", all_cols,
                               index=all_cols.index(cols.get("invoice")) if cols.get("invoice") in all_cols else 0)
    DATE_COL = st.selectbox("Columna Fecha", all_cols,
                            index=all_cols.index(cols.get("date")) if cols.get("date") in all_cols else 0)
    TOTAL_COL = st.selectbox("Columna Total / Monto", all_cols,
                             index=all_cols.index(cols.get("total")) if cols.get("total") in all_cols else 0)

    PARTY_COL   = None if PARTY_COL == "(ninguna)" else PARTY_COL
    INVOICE_COL = None if INVOICE_COL == "(ninguna)" else INVOICE_COL
    DATE_COL    = None if DATE_COL == "(ninguna)" else DATE_COL
    TOTAL_COL   = None if TOTAL_COL == "(ninguna)" else TOTAL_COL

    entity_label = "Proveedor/Cliente"
    if PARTY_COL:
        nn = PARTY_COL.strip().lower()
        if any(k in nn for k in ["proveedor", "supplier", "vendor"]):
            entity_label = "Proveedor"
        elif any(k in nn for k in ["cliente", "customer"]):
            entity_label = "Cliente"

    # Mostrar mapeo
    c1, c2, c3, c4 = st.columns(4)
    with c1: st.markdown(f"**Parte:** `{PARTY_COL or '—'}`")
    with c2: st.markdown(f"**Número:** `{INVOICE_COL or '—'}`")
    with c3: st.markdown(f"**Fecha:** `{DATE_COL or '—'}`")
    with c4: st.markdown(f"**Total:** `{TOTAL_COL or '—'}`")
    st.divider()

    # Validación mínima
    if not any([ (PARTY_COL and INVOICE_COL),
                 (PARTY_COL and DATE_COL and TOTAL_COL),
                 (INVOICE_COL) ]):
        st.warning("Selecciona al menos: Parte+Número, o Parte+Fecha+Total, o Número solo, para detectar duplicados.")
        st.stop()

    # --- Cálculo duplicados (flex) ---
    d_all, d_extra, total, dup_exceso, pct, regla_usada, keys = compute_duplicates_flexible(
        df.copy(), PARTY_COL, INVOICE_COL, DATE_COL, TOTAL_COL
    )

    # --- Indicadores ---
    section_header("Indicadores clave", f"""
**Qué ves aquí:** KPIs del archivo cargado con la regla: **{regla_usada}**.
- *Total Facturas*: filas del dataset.
- *Duplicadas*: **excedentes** (copias sobre el original) según la regla aplicada.
- *% Duplicados*: excedentes / total.
- *Monto Total Duplicados*: suma del **Total** de las copias (si hay columna Total).
**Uso:** Priorización rápida del riesgo de facturación duplicada.
""")

    # Monto total duplicado (excedentes)
    monto_total_dup = 0.0
    if TOTAL_COL:
        try:
            monto_total_dup = float(pd.to_numeric(df.loc[d_extra, TOTAL_COL], errors="coerce").fillna(0).sum())
        except Exception:
            monto_total_dup = 0.0

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Total Facturas", f"{total}")
    k2.metric("Duplicadas (excedentes)", f"{dup_exceso}")
    k3.metric("% Duplicados", f"{(pct*100):.1f}%")
    k4.metric("Monto Total Duplicados", f"${monto_total_dup:,.2f}" if TOTAL_COL else "—")

    # --- Tabla duplicados (todos los involucrados) ---
    section_header("Tabla de facturas potencialmente duplicadas", """
**Cómo usar:** Filtra y ordena para revisar grupos marcados por la columna `_regla`.
- *Exacto (Parte+Número [+Total])*: coincidencia estricta.
- *Combo (Parte+Fecha+Total)*: posible duplicado sin mismo número.
**Sugerencia:** Agrega comentarios en tu base para documentar falsos positivos.
""")

    df_tabla = df.loc[d_all].copy()
    if df_tabla.empty:
        st.success("No se encontraron registros potencialmente duplicados con la configuración actual.")
    else:
        st.dataframe(df_tabla, use_container_width=True)

    # --- Gráficos ---
    if PARTY_COL and not df.loc[d_extra].empty:
        try:
            by_party = df.loc[d_extra].groupby(PARTY_COL)[TOTAL_COL].sum().sort_values(ascending=False).head(20) if TOTAL_COL else None
            chart_header(f"Monto duplicado por {entity_label}", f"""
**Cómo leer:**
- Eje X: {entity_label}.
- Eje Y: suma de montos **duplicados (excedentes)**.
**Uso:** identifica qué {entity_label.lower()} concentran mayor monto duplicado.
""")
            if by_party is not None and not by_party.empty:
                st.bar_chart(by_party)
            else:
                st.info("No hay datos suficientes (se requiere columna Total y duplicados detectados).")
        except Exception:
            st.info("No fue posible generar el gráfico por estructura de datos.")

        try:
            count_party = df.loc[d_extra].groupby(PARTY_COL)[INVOICE_COL].count().sort_values(ascending=False).head(20) if INVOICE_COL else None
            chart_header(f"{entity_label} con más duplicados", f"""
**Cómo leer:**
- Barras ordenadas por cantidad de **copias** detectadas.
**Uso:** ayuda a priorizar revisiones por volumen de duplicados.
""")
            if count_party is not None and not count_party.empty:
                st.bar_chart(count_party)
            else:
                st.info("No hay datos suficientes (se requiere columna Número y duplicados detectados).")
        except Exception:
            st.info("No fue posible generar el gráfico por estructura de datos.")
    else:
        chart_header("Gráficos de duplicados", """
**Nota:** Para mostrar gráficos, se requiere seleccionar la columna de Parte y tener duplicados detectados.
""")
        st.info("Configura la columna de Parte y asegúrate de que existan duplicados para ver los gráficos.")

    # --- Exportar a Excel ---
    section_header("Exportar resultados", """
**Qué incluye el archivo Excel:**
- Hoja **Base**: tu dataset original.
- Hoja **Duplicados**: registros marcados por la regla aplicada.
- Hoja **Hallazgos**: *Alertas, Conclusiones y Recomendaciones*.
**Uso sugerido en tu informe:** Incluye la hoja Hallazgos para justificar la metodología y decisiones.
""")
    with st.expander("📤 Exportar a Excel"):
        alerts = [f"Se detectaron duplicados bajo la regla: {regla_usada}."]
        concl  = [f"Duplicados excedentes: {dup_exceso} de {total} registros ({pct*100:.1f}%)."]
        recs   = ["Implementar validaciones al cargar datos y normalizar números de factura."]
        if st.button("Descargar Excel con resultados", type="primary"):
            data = export_to_excel(df, df_tabla, alerts, concl, recs)
            st.download_button("Guardar archivo", data=data, file_name="resultados_duplicados.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
else:
    st.info("Sube un archivo CSV/XLSX para iniciar el análisis.")
