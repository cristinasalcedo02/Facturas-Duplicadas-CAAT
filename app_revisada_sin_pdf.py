# -*- coding: utf-8 -*-
import io
import re
import sys
import math
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

    # Si no hay total, intentamos derivarlo si existen amount e impuesto
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
# Reglas de duplicados
# ==========================
def compute_duplicates(df: pd.DataFrame, PARTY_COL, INVOICE_COL, DATE_COL, TOTAL_COL):
    # Aseguramos tipos
    if DATE_COL:
        df[DATE_COL] = pd.to_datetime(df[DATE_COL], errors="coerce")
    if TOTAL_COL:
        df[TOTAL_COL] = pd.to_numeric(df[TOTAL_COL], errors="coerce")
    dup_keys = [k for k in [PARTY_COL, INVOICE_COL, DATE_COL, TOTAL_COL] if k]

    # Marca todos los involucrados
    dups_all = df.duplicated(subset=dup_keys, keep=False)

    # Marca solo los excedentes
    dups_extra = df.duplicated(subset=dup_keys, keep="first")

    # Etiquetar regla principal (simple: exacto por número o combo por fecha+total)
    regla = []
    for i, row in df.iterrows():
        r = ""
        if PARTY_COL and INVOICE_COL and not pd.isna(row.get(INVOICE_COL, np.nan)):
            r = "Exacto (num+parte+monto)"
        if r == "" and PARTY_COL and DATE_COL and TOTAL_COL:
            r = "Combo (parte+fecha+total)"
        regla.append(r)
    df["_regla"] = regla

    # KPIs
    total = int(len(df))
    duplicados_exceso = int(dups_extra.sum())
    pct = (duplicados_exceso / total) if total else 0.0

    return dups_all, dups_extra, total, duplicados_exceso, pct

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

section_header("Mapeo de columnas", """
**Objetivo:** Confirmar qué columnas del archivo se usan como *Parte* (Proveedor/Cliente), *Número*, *Fecha* y *Montos*.
La app detecta nombres comunes automáticamente; puedes corregirlos si algo quedó mal.
""")

uploaded = st.file_uploader("Sube un archivo CSV o Excel", type=["csv", "xlsx", "xls"])
df = load_file(uploaded)

if df is not None and len(df):
    df, cols = auto_map_columns(df)
    PARTY_COL   = cols.get("party")   or "CustomerName"
    INVOICE_COL = cols.get("invoice") or "InvoiceNumber"
    DATE_COL    = cols.get("date")    or "InvoiceDate"
    AMOUNT_COL  = cols.get("amount")  or "Amount"
    TAX_COL     = cols.get("tax")
    TOTAL_COL   = cols.get("total")   or AMOUNT_COL
    ENTITY_LABEL = cols.get("label")  or "Proveedor/Cliente"

    # Mostrar detección
    c1, c2, c3, c4, c5 = st.columns(5)
    with c1: st.markdown(f"**Parte (Proveedor/Cliente):** `{PARTY_COL}`")
    with c2: st.markdown(f"**Número:** `{INVOICE_COL}`")
    with c3: st.markdown(f"**Fecha:** `{DATE_COL}`")
    with c4: st.markdown(f"**Monto:** `{AMOUNT_COL}`")
    with c5: st.markdown(f"**Total:** `{TOTAL_COL}`")
    st.divider()

    # Cálculo duplicados
    d_all, d_extra, total, dup_exceso, pct = compute_duplicates(df, PARTY_COL, INVOICE_COL, DATE_COL, TOTAL_COL)

    section_header("Indicadores clave", """
**Qué ves aquí:** KPIs del archivo cargado.
- *Total Facturas*: cantidad de filas del dataset.
- *Duplicadas*: **excedentes** detectados (copias sobre el original).
- *% Duplicados*: excedentes / total.
- *Monto Total Duplicados*: suma del **Total** de las copias.
""")
    # Monto total duplicado (excedentes)
    monto_total_dup = 0.0
    try:
        monto_total_dup = float(pd.to_numeric(df.loc[d_extra, TOTAL_COL], errors="coerce").fillna(0).sum())
    except Exception:
        pass

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Total Facturas", f"{total}")
    k2.metric("Duplicadas", f"{dup_exceso}")
    k3.metric("% Duplicados", f"{(pct*100):.1f}%")
    k4.metric("Monto Total Duplicados", f"${monto_total_dup:,.2f}")

    # Tabla duplicados (todas las involucradas)
    section_header("Tabla de facturas potencialmente duplicadas", """
**Cómo usar:** Filtra y ordena para revisar grupos marcados por la columna `_regla`.
- *Exacto (num+parte+monto)*: coincidencia estricta.
- *Combo (parte+fecha+total)*: posible duplicado sin mismo número.
Marca los casos válidos en *Comentarios* o *Riesgo* para tu informe.
""")
    df_tabla = df.loc[d_all].copy()
    st.dataframe(df_tabla, use_container_width=True)

    # Gráficos simples (opcional, solo si hay columnas necesarias)
    try:
        by_party = df.loc[d_extra].groupby(PARTY_COL)[TOTAL_COL].sum().sort_values(ascending=False).head(20)
        chart_header(f"Monto duplicado por {ENTITY_LABEL}", """
**Cómo leer:**
- Eje X: grupos por {ENTITY_LABEL}.
- Eje Y: suma de montos **duplicados (excedentes)**.
**Uso:** identifica qué partes concentran mayor monto duplicado.
""".replace("{ENTITY_LABEL}", ENTITY_LABEL))
        st.bar_chart(by_party)
    except Exception:
        pass

    try:
        count_party = df.loc[d_extra].groupby(PARTY_COL)[INVOICE_COL].count().sort_values(ascending=False).head(20)
        chart_header(f"{ENTITY_LABEL} con más duplicados", """
**Cómo leer:**
- Barras por {ENTITY_LABEL} ordenadas por cantidad de **copias** detectadas.
- Útil para priorizar revisiones.
""".replace("{ENTITY_LABEL}", ENTITY_LABEL))
        st.bar_chart(count_party)
    except Exception:
        pass

    # Exportar SOLO a Excel (PDF removido)
    with st.expander("📤 Exportar a Excel"):
        alerts = ["Se detectaron duplicados por número y por combinación parte+fecha+total."]
        concl  = [f"Duplicados excedentes: {dup_exceso} de {total} registros ({pct*100:.1f}%)."]
        recs   = ["Implementar reglas de validación y normalización de números de factura al cargar datos."]
        if st.button("Descargar Excel con resultados", type="primary"):
            data = export_to_excel(df, df_tabla, alerts, concl, recs)
            st.download_button("Guardar archivo", data=data, file_name="resultados_duplicados.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
else:
    st.info("Sube un archivo CSV/XLSX para iniciar el análisis.")
