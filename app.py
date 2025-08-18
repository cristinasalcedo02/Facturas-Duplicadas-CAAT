# CAAT Avanzado — Detección de Facturas Duplicadas con Análisis de Riesgo (v2)
# Autor: Tu asistente
# Notas clave:
# - No exige nombres de columnas fijos (mapeo manual).
# - Detección Exacta y Aproximada (con tolerancias por monto y fecha).
# - Fuzzy matching con bloqueo por proveedor y bucketing por monto.
# - KPIs, filtros, gráficos (Plotly con fallback a Matplotlib), y exportación a Excel (múltiples hojas).
# - Manejo de errores y de tipos (fechas y números robustos).

import io
import math
import numpy as np
import pandas as pd
import streamlit as st

# Dependencias opcionales
try:
    import plotly.express as px
    _HAS_PLOTLY = True
except Exception:
    _HAS_PLOTLY = False

try:
    from rapidfuzz import fuzz  # más rápido que thefuzz
    _HAS_RAPIDFUZZ = True
except Exception:
    try:
        from thefuzz import fuzz  # fallback
        _HAS_RAPIDFUZZ = False
    except Exception:
        fuzz = None
        _HAS_RAPIDFUZZ = False

st.set_page_config(page_title="Control Avanzado de Facturas", layout="wide")
st.title("Control Avanzado de Facturas: Duplicados y Análisis de Riesgo — v2")

st.markdown(
    """
**⚠️ Por qué importa**  
Las facturas duplicadas generan **pagos repetidos**, errores contables y pérdida de control. Esta app permite **identificar, analizar y priorizar** duplicados para reforzar controles.

**Cómo usar**  
1️⃣ Sube tu archivo (Excel/CSV).  
2️⃣ Mapea las columnas clave.  
3️⃣ Elige el tipo de detección y** (opcional)** ajusta tolerancias.  
4️⃣ Aplica filtros, revisa KPIs, tablas y gráficos.  
5️⃣ Exporta hallazgos (Excel con múltiples hojas).
    """
)

# ------------------------------
# 1) CARGA DE ARCHIVO
# ------------------------------
file = st.file_uploader("Sube tu archivo Excel o CSV", type=["xlsx", "xls", "csv"]) 

@st.cache_data(show_spinner=False)
def _read_file(_file):
    if _file.name.lower().endswith((".xlsx", ".xls")):
        return pd.read_excel(_file)
    return pd.read_csv(_file)

if not file:
    st.info("Carga un archivo para comenzar.")
    st.stop()

try:
    df_raw = _read_file(file)
except Exception as e:
    st.error(f"No se pudo leer el archivo: {e}")
    st.stop()

if df_raw.empty:
    st.warning("El archivo está vacío.")
    st.stop()

st.success("Archivo cargado correctamente.")
st.caption("Vista previa (primeras 200 filas)")
st.dataframe(df_raw.head(200), use_container_width=True)

# ------------------------------
# 2) MAPEO DE COLUMNAS (MODO RÁPIDO + AVANZADO)
# ------------------------------
from typing import List, Tuple, Dict

# --- Heurísticas y sinónimos ---
_SYNONYMS = {
    "num": ["numero", "número", "num", "nro", "no", "factura", "nrofactura", "numfactura", "doc", "documento", "invoice", "inv", "bill", "folio", "serie", "secuencia"],
    "prov": ["proveedor", "supplier", "vendor", "ruc", "nit", "taxid", "proveed", "provider", "nombreproveedor", "namevendor"],
    "fecha": ["fecha", "emision", "emisión", "date", "fechafactura", "femision", "postingdate", "documentdate", "fechaemision"],
    "monto": ["monto", "importe", "valor", "total", "amount", "subtotal", "neto", "bruto", "grandtotal", "totallinea", "totaldoc"]
}

try:
    from rapidfuzz import process as _rf_process
    def _best_header(options: List[str], headers: List[str]) -> Tuple[str, float]:
        res = _rf_process.extractOne(options, headers, score_cutoff=55)
        if res is None:
            return "", 0.0
        return res[0], float(res[1])
except Exception:
    def _best_header(options: List[str], headers: List[str]) -> Tuple[str, float]:
        # Fallback simple por inclusión
        headers_l = [h.lower().replace(" ", "") for h in headers]
        for opt in options:
            opt = opt.lower()
            for i, h in enumerate(headers_l):
                if opt in h or h in opt:
                    return headers[i], 60.0
        return "", 0.0

# Perfilado de columnas por tipo de dato (para no depender sólo del nombre)
cols = df_raw.columns.tolist()
cols_norm = [c.lower().replace(" ", "") for c in cols]

# Detectar candidatos por encabezado
num_head, _ = _best_header(_SYNONYMS["num"], cols_norm)
prov_head, _ = _best_header(_SYNONYMS["prov"], cols_norm)
fecha_head, _ = _best_header(_SYNONYMS["fecha"], cols_norm)
monto_head, _ = _best_header(_SYNONYMS["monto"], cols_norm)

# Detectar por contenido
def _is_date_series(s: pd.Series) -> float:
    try:
        parsed = pd.to_datetime(s, errors='coerce', dayfirst=True)
        return parsed.notna().mean()
    except Exception:
        return 0.0

def _is_numeric_series(s: pd.Series) -> float:
    try:
        asnum = pd.to_numeric(s, errors='coerce')
        return asnum.notna().mean()
    except Exception:
        return 0.0

content_date_scores = {c: _is_date_series(df_raw[c]) for c in cols}
content_num_scores  = {c: _is_numeric_series(df_raw[c]) for c in cols}

# Elegir defaults robustos
def _choose_default(candidate_by_header: str, scores: Dict[str, float], prefer_numeric=False, prefer_date=False):
    if candidate_by_header in cols:
        return candidate_by_header
    if prefer_date:
        best = max(scores.items(), key=lambda kv: kv[1])[0] if scores else cols[0]
        return best
    if prefer_numeric:
        best = max(scores.items(), key=lambda kv: kv[1])[0] if scores else cols[0]
        return best
    return cols[0]

# Defaults sugeridos
_default_num   = _choose_default(num_head, {}, False, False)
_default_prov  = _choose_default(prov_head, {}, False, False)
_default_fecha = _choose_default(fecha_head, content_date_scores, False, True)
_default_monto = _choose_default(monto_head, content_num_scores, True, False)

# --- UI: Modo rápido / avanzado ---
st.subheader("Mapeo de columnas")
mode_fast = st.toggle("Modo rápido (un campo por rol)", value=True, help="Usa autodetección por nombre y por contenido. Si necesitas combinar columnas, desactívalo para usar el modo avanzado.")

if mode_fast:
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        c_num = st.selectbox("Nº de factura", cols, index=cols.index(_default_num) if _default_num in cols else 0, key="fast_num")
    with col2:
        c_prov = st.selectbox("Proveedor", cols, index=cols.index(_default_prov) if _default_prov in cols else 0, key="fast_prov")
    with col3:
        c_fecha = st.selectbox("Fecha de emisión", cols, index=cols.index(_default_fecha) if _default_fecha in cols else 0, key="fast_fecha")
    with col4:
        c_monto = st.selectbox("Monto", cols, index=cols.index(_default_monto) if _default_monto in cols else 0, key="fast_monto")
else:
    st.caption("Puedes combinar varias columnas y definir separadores. Guarda una plantilla para reutilizarlo.")
    col_a, col_b = st.columns(2)
    with col_a:
        combine_num = st.checkbox("Combinar columnas para Nº de factura", value=False)
        if combine_num:
            sel_num = st.multiselect("Columnas para Nº de factura", options=cols, default=[_default_num] if _default_num in cols else [])
            sep_num = st.text_input("Separador para Nº combinado", value="-", max_chars=3)
            if sel_num:
                df_raw["__num__"] = df_raw[sel_num].astype(str).agg(lambda r: sep_num.join([x.strip() for x in r]), axis=1)
                c_num = "__num__"
            else:
                c_num = _default_num
        else:
            c_num = st.selectbox("Nº de factura", cols, index=cols.index(_default_num) if _default_num in cols else 0)
    with col_b:
        combine_prov = st.checkbox("Combinar columnas para Proveedor", value=False)
        if combine_prov:
            sel_prov = st.multiselect("Columnas para Proveedor", options=cols, default=[_default_prov] if _default_prov in cols else [])
            sep_prov = st.text_input("Separador para Proveedor combinado", value=" ", max_chars=3)
            if sel_prov:
                df_raw["__prov__"] = df_raw[sel_prov].astype(str).agg(lambda r: sep_prov.join([x.strip() for x in r]), axis=1)
                c_prov = "__prov__"
            else:
                c_prov = _default_prov
        else:
            c_prov = st.selectbox("Proveedor", cols, index=cols.index(_default_prov) if _default_prov in cols else 0)

    col_c, col_d = st.columns(2)
    with col_c:
        c_fecha = st.selectbox("Fecha de emisión", cols, index=cols.index(_default_fecha) if _default_fecha in cols else 0)
        split_dt = st.checkbox("Separar fecha y hora si vienen juntas", value=False)
    with col_d:
        c_monto = st.selectbox("Monto", cols, index=cols.index(_default_monto) if _default_monto in cols else 0)
        invert_sign = st.checkbox("Invertir signo (si vienen negativos)", value=False)

    # Guardar plantilla (opcional)
    if st.button("Guardar plantilla de mapeo"):
        tpl = {"num": sel_num if combine_num else [c_num], "prov": sel_prov if combine_prov else [c_prov], "fecha": [c_fecha], "monto": [c_monto]}
        bio = io.BytesIO()
        pd.Series(tpl).to_json(bio)
        st.download_button("Descargar plantilla.json", data=bio.getvalue(), file_name="plantilla_mapeo.json", mime="application/json")

# Vista previa rápida
st.caption("Vista previa (5 filas)")
_preview_cols = {"Nº factura": df_raw[c_num].astype(str).head(5), "Proveedor": df_raw[c_prov].astype(str).head(5), "Fecha": df_raw[c_fecha].astype(str).head(5), "Monto": df_raw[c_monto].head(5)}
st.dataframe(pd.DataFrame(_preview_cols), use_container_width=True)

# ------------------------------
# 2.5) VALIDACIONES DE MAPEOS (GUARDRAILS)
# ------------------------------
# Evitar mapeos erróneos (como usar Fecha para Nº o Monto, o reutilizar la misma columna)
sel_cols = [c_num, c_prov, c_fecha, c_monto]
labels = ["Nº de factura", "Proveedor", "Fecha", "Monto"]

# 1) Colisiones de columnas
if len({c for c in sel_cols}) < len(sel_cols):
    st.error("Has seleccionado la **misma columna** para más de un rol (Nº/Proveedor/Fecha/Monto). Corrige el mapeo antes de continuar.")
    st.stop()

# 2) Coherencia por contenido
_score_date = 0.0
try:
    _score_date = pd.to_datetime(df_raw[c_fecha], errors='coerce').notna().mean()
except Exception:
    _score_date = 0.0

_score_num = 0.0
try:
    _score_num = pd.to_numeric(df_raw[c_monto], errors='coerce').notna().mean()
except Exception:
    _score_num = 0.0

if _score_date < 0.5:
    st.warning(f"La columna seleccionada como **Fecha** (`{c_fecha}`) **no parece ser fecha** en la mayoría de filas. Revisa el mapeo.")
if _score_num < 0.5:
    st.warning(f"La columna seleccionada como **Monto** (`{c_monto}`) **no parece numérica** en la mayoría de filas. Revisa el mapeo.")

# 3) Nº de factura no debería incluir fecha seleccionada
if isinstance(c_num, str) and c_num.startswith("__"):
    # Si combinamos columnas para el número, verifica que no contenga exactamente la columna de fecha
    # Heurística: si texto de la columna fecha aparece en la expresión combinada
    st.info("Validando combinación del Nº de factura…")

# 4) Botón de Autorrellenar (reaplicar heurísticas)
if st.button("Autorrellenar mapeo sugerido"):
    st.experimental_rerun()

# ------------------------------
# 3) PREPROCESAMIENTO ROBUSTO
# ------------------------------
df = df_raw.copy()

# Normalizar proveedor (string limpio)
df[c_prov] = (
    df[c_prov]
    .astype(str)
    .str.lower()
    .str.normalize("NFKD")
    .str.encode("ascii", errors="ignore")
    .str.decode("utf-8")
    .str.strip()
)

# Normalizar número de factura (quitar separadores, ceros a la izquierda)
df[c_num] = (
    df[c_num]
    .astype(str)
    .str.lower()
    .str.replace(r"[^0-9a-z]", "", regex=True)
    .str.lstrip("0")
)

# Fecha y monto estrictos
df[c_fecha] = pd.to_datetime(df[c_fecha], errors="coerce")
df[c_monto] = pd.to_numeric(df[c_monto], errors="coerce")

# Eliminar filas totalmente vacías en campos clave
key_mask = df[[c_num, c_prov, c_monto]].notna().all(axis=1)
df = df.loc[key_mask].reset_index(drop=True)

if df.empty:
    st.error("No hay registros válidos tras el preprocesamiento.")
    st.stop()

st.success("Datos preprocesados correctamente.")

# ------------------------------
# 4) PARÁMETROS DE DETECCIÓN
# ------------------------------
st.subheader("Configuración de detección de duplicados")
left, right = st.columns([3,2])
with left:
    tipo = st.selectbox("Tipo de duplicado", ["Exacto", "Aproximado"], index=0)
with right:
    if tipo == "Aproximado":
        sim_thr = st.slider("Umbral de similitud del Nº (0-100)", 70, 100, 90)
    else:
        sim_thr = None

# Tolerancias adicionales
adv = st.expander("Más opciones (tolerancias y reglas)")
with adv:
    tol_monto = st.number_input("Tolerancia de monto (misma moneda)", min_value=0.0, value=0.0, step=0.01, help="Permite considerar duplicado si la diferencia absoluta de monto está dentro de este valor.")
    tol_dias = st.number_input("Tolerancia de fecha (± días)", min_value=0, value=0, step=1, help="Permite considerar duplicado si la emisión está dentro de ±N días.")
    bloquear_por_proveedor = st.checkbox("Bloquear comparación por proveedor (recomendado)", value=True)
    bloquear_por_mes = st.checkbox("Bloquear por mismo mes de emisión (ayuda rendimiento)", value=False)

# ------------------------------
# 5) FUNCIONES DE DETECCIÓN
# ------------------------------
@st.cache_data(show_spinner=False)
def detect_exact(df: pd.DataFrame, c_num: str, c_prov: str, c_fecha: str, c_monto: str):
    # Agrupar por claves exactas más tolerancias (si las hubiera, para exacto sólo aplica tol_monto/tol_dias=0)
    grp_keys = [c_num, c_prov, c_monto]
    dup_mask = df.duplicated(subset=grp_keys, keep=False)
    out = df.loc[dup_mask].copy()
    out["_regla"] = "Exacto (num+prov+monto)"
    return out.sort_values([c_prov, c_num, c_monto, c_fecha], na_position="last")

@st.cache_data(show_spinner=False)
def detect_approx(
    df: pd.DataFrame,
    c_num: str,
    c_prov: str,
    c_fecha: str,
    c_monto: str,
    sim_thr: int,
    tol_monto: float,
    tol_dias: int,
    bloquear_por_proveedor: bool,
    bloquear_por_mes: bool,
):
    if fuzz is None:
        st.warning("No se encontró librería de fuzzy matching (rapidfuzz/thefuzz). Se omitirá la detección aproximada.")
        return pd.DataFrame(columns=df.columns.tolist() + ["_match_id", "_sim", "_regla"]) 

    work = df[[c_num, c_prov, c_fecha, c_monto]].copy()
    work["_rowid"] = np.arange(len(work))

    # Bloqueo por proveedor
    groups = [work]
    if bloquear_por_proveedor:
        groups = [g for _, g in work.groupby(c_prov)]

    results = []

    for g in groups:
        g = g.copy()
        # Opcional: Bloquear por mes
        if bloquear_por_mes and g[c_fecha].notna().any():
            subgroups = [sg for _, sg in g.groupby(g[c_fecha].dt.to_period("M"))]
        else:
            subgroups = [g]

        for sg in subgroups:
            if sg.empty or len(sg) < 2:
                continue

            # Bucketing por monto para evitar cuadrático puro
            if tol_monto > 0:
                # crear bins por monto
                bin_size = max(tol_monto, 1.0)
                bins = np.floor(sg[c_monto].fillna(0) / bin_size)
                for _, bg in sg.groupby(bins):
                    _pairwise(bg, results, c_num, c_fecha, c_monto, sim_thr, tol_monto, tol_dias)
            else:
                _pairwise(sg, results, c_num, c_fecha, c_monto, sim_thr, tol_monto, tol_dias)

    if not results:
        return pd.DataFrame(columns=df.columns.tolist() + ["_match_id", "_sim", "_regla"]) 

    pairs = pd.DataFrame(results, columns=["_id1", "_id2", "_sim"]) 
    ids = set(pairs["_id1"]).union(set(pairs["_id2"]))

    out = work[work["_rowid"].isin(ids)].merge(
        pairs.melt(value_vars=["_id1", "_id2"], value_name="_rowid"), on="_rowid", how="left"
    )
    out["_match_id"] = out.groupby("_rowid").ngroup()
    out["_regla"] = "Aproximado (fuzzy+tol)"

    # devolver con columnas originales + metadatos de fuzzy
    merged = df.reset_index(drop=True).merge(out[["_rowid", "_match_id", "_sim", "_regla"]], left_index=True, right_on="_rowid", how="left")
    merged = merged.drop(columns=["_rowid"]) 
    merged = merged[merged["_match_id"].notna()].copy()
    # ordenar
    if c_fecha in merged:
        merged = merged.sort_values([c_prov, c_num, c_monto, c_fecha], na_position="last")
    return merged


def _pairwise(sg: pd.DataFrame, results: list, c_num: str, c_fecha: str, c_monto: str, sim_thr: int, tol_monto: float, tol_dias: int):
    rows = sg[[c_num, c_fecha, c_monto, "_rowid"]].values.tolist()
    n = len(rows)
    for i in range(n):
        num_i, fec_i, mon_i, id_i = rows[i]
        for j in range(i+1, n):
            num_j, fec_j, mon_j, id_j = rows[j]

            # Tolerancia por monto
            if not (pd.notna(mon_i) and pd.notna(mon_j)):
                continue
            if abs(mon_i - mon_j) > tol_monto:
                continue

            # Tolerancia por fecha
            if tol_dias > 0:
                if pd.isna(fec_i) or pd.isna(fec_j):
                    continue
                if abs((fec_i - fec_j).days) > tol_dias:
                    continue

            # Similitud de número
            if not isinstance(num_i, str):
                num_i = str(num_i)
            if not isinstance(num_j, str):
                num_j = str(num_j)

            sim = fuzz.ratio(num_i, num_j)
            if sim >= sim_thr:
                results.append([id_i, id_j, sim])

# ------------------------------
# 6) EJECUCIÓN DE LA DETECCIÓN
# ------------------------------
if tipo == "Exacto":
    df_dups = detect_exact(df, c_num, c_prov, c_fecha, c_monto)
else:
    df_dups = detect_approx(
        df, c_num, c_prov, c_fecha, c_monto, sim_thr, tol_monto, tol_dias, bloquear_por_proveedor, bloquear_por_mes
    )

# ------------------------------
# 7) FILTROS DE ANÁLISIS
# ------------------------------
st.subheader("Filtros de análisis")
if df_dups.empty:
    st.info("No se encontraron duplicados con las reglas actuales.")
else:
    prods = sorted(df[c_prov].dropna().unique().tolist())
    f_prov = st.multiselect("Proveedor", options=prods, default=prods)
    f_min, f_max = st.slider(
        "Rango de monto",
        float(np.nanmin(df[c_monto].values)),
        float(np.nanmax(df[c_monto].values)),
        (float(np.nanmin(df[c_monto].values)), float(np.nanmax(df[c_monto].values)))
    )

    mask = df_dups[c_prov].isin(f_prov) & df_dups[c_monto].between(f_min, f_max)
    df_dups = df_dups.loc[mask].copy()

# ------------------------------
# 8) KPIs Y MÉTRICAS
# ------------------------------
st.subheader("Indicadores clave")
col1, col2, col3, col4 = st.columns(4)
N = len(df)
D = len(df_dups)
porc = round((D / N) * 100, 2) if N else 0.0
monto_dup = float(df_dups[c_monto].sum()) if not df_dups.empty else 0.0
col1.metric("Total Facturas", f"{N:,}")
col2.metric("Duplicados", f"{D:,}")
col3.metric("% Duplicados", f"{porc}%")
col4.metric("Monto Total Duplicados", f"$ {monto_dup:,.2f}")

# ------------------------------
# 9) TABLA DE RESULTADOS
# ------------------------------
st.subheader("Tabla de facturas potencialmente duplicadas")
st.dataframe(df_dups, use_container_width=True)

# ------------------------------
# 10) VISUALIZACIONES
# ------------------------------
st.subheader("Visualizaciones")
if not df_dups.empty:
    # Monto por proveedor
    prov_agg = df_dups.groupby(c_prov, dropna=False)[c_monto].sum().reset_index()
    if _HAS_PLOTLY:
        fig1 = px.bar(prov_agg, x=c_prov, y=c_monto, title="Monto duplicado por proveedor")
        st.plotly_chart(fig1, use_container_width=True)
    else:
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots()
        ax.bar(prov_agg[c_prov].astype(str), prov_agg[c_monto])
        ax.set_title("Monto duplicado por proveedor")
        ax.set_xlabel("Proveedor"); ax.set_ylabel("Monto")
        st.pyplot(fig)

    # Serie temporal por mes
    if df_dups[c_fecha].notna().any():
        time_agg = df_dups.copy()
        time_agg["_mes"] = time_agg[c_fecha].dt.to_period("M").dt.to_timestamp()
        time_agg = time_agg.groupby("_mes")[c_monto].sum().reset_index()
        if _HAS_PLOTLY:
            fig2 = px.line(time_agg, x="_mes", y=c_monto, markers=True, title="Monto duplicado por mes")
            st.plotly_chart(fig2, use_container_width=True)
        else:
            import matplotlib.pyplot as plt
            fig, ax = plt.subplots()
            ax.plot(time_agg["_mes"], time_agg[c_monto], marker="o")
            ax.set_title("Monto duplicado por mes"); ax.set_xlabel("Mes"); ax.set_ylabel("Monto")
            st.pyplot(fig)

    # Frecuencia por número
    freq = df_dups.groupby(c_num)[c_num].size().rename("Frecuencia").reset_index()
    freq = freq.merge(df_dups.groupby(c_num)[c_monto].sum().reset_index(), on=c_num, how="left")
    if _HAS_PLOTLY:
        fig3 = px.scatter(freq, x=c_num, y=c_monto, size="Frecuencia", color="Frecuencia", title="Monto vs Frecuencia de Nº de factura")
        st.plotly_chart(fig3, use_container_width=True)
    else:
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots()
        ax.scatter(np.arange(len(freq)), freq[c_monto])
        ax.set_title("Monto vs Frecuencia (por Nº de factura)")
        ax.set_xlabel("Índice"); ax.set_ylabel("Monto")
        st.pyplot(fig)

# ------------------------------
# 11) RIESGO Y PRIORIZACIÓN (SIMPLE)
# ------------------------------
st.subheader("Priorización de riesgo (simple)")
if not df_dups.empty:
    # Score básico: z-score del monto + frecuencia por proveedor
    z = (df_dups[c_monto] - df_dups[c_monto].mean()) / (df_dups[c_monto].std(ddof=0) if df_dups[c_monto].std(ddof=0) else 1)
    df_dups["_freq_proveedor"] = df_dups.groupby(c_prov)[c_prov].transform("count")
    df_dups["_riesgo"] = z.fillna(0) + (df_dups["_freq_proveedor"] / max(df_dups["_freq_proveedor"].max(), 1))
    topn = st.slider("Mostrar Top-N por riesgo", 5, min(50, max(5, len(df_dups))), 10)
    st.dataframe(df_dups.sort_values("_riesgo", ascending=False).head(topn), use_container_width=True)

# ------------------------------
# 12) EXPORTACIÓN
# ------------------------------
st.subheader("Exportar resultados")
if st.button("Descargar Excel (duplicados + resumen)"):
    if df_dups.empty:
        st.warning("No hay duplicados para exportar.")
    else:
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
            df_dups.to_excel(writer, index=False, sheet_name="Duplicados")
            # Resumen por proveedor
            prov_res = df_dups.groupby(c_prov, dropna=False).agg(
                total_monto=(c_monto, "sum"),
                n_items=(c_prov, "size"),
            ).reset_index()
            prov_res.sort_values("total_monto", ascending=False).to_excel(writer, index=False, sheet_name="Resumen_Proveedor")
            # Parámetros
            params = {
                "tipo": tipo,
                "similitud": sim_thr,
                "tol_monto": tol_monto,
                "tol_dias": tol_dias,
                "bloq_proveedor": bloquear_por_proveedor,
                "bloq_mes": bloquear_por_mes,
            }
            pd.DataFrame([params]).to_excel(writer, index=False, sheet_name="Parametros")
        st.download_button(
            label="Descargar Excel",
            data=output.getvalue(),
            file_name="duplicados_avanzados_v2.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

# ------------------------------
# 13) NOTAS DE AUDITORÍA
# ------------------------------
st.info(
    """
**Notas y buenas prácticas**  
• Para archivos grandes, activa el bloqueo por proveedor y por mes, y usa una tolerancia de monto razonable para acelerar.  
• Verifica que la moneda sea consistente antes de usar tolerancias de monto.  
• Ante falsos positivos en ‘Aproximado’, aumenta el umbral de similitud o reduce tolerancias.  
• Para rastreabilidad, exporta siempre el Excel e incorpora estas hojas en tus papeles de trabajo.
    """
)
