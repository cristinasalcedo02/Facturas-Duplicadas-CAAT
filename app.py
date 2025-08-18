# CAAT Avanzado — Detección de Facturas Duplicadas con Análisis de Riesgo
# Autor: Grupo A

import io
import re
import unicodedata
import numpy as np
import pandas as pd
import streamlit as st

# ── Gráficos (Plotly opcional) ────────────────────────────────────────────────
try:
    import plotly.express as px
    _HAS_PLOTLY = True
except Exception:
    _HAS_PLOTLY = False

# ── Fuzzy matching (rapidfuzz > thefuzz > none) ──────────────────────────────
try:
    from rapidfuzz import fuzz
    _FUZZ_OK = True
except Exception:
    try:
        from thefuzz import fuzz
        _FUZZ_OK = True
    except Exception:
        fuzz = None
        _FUZZ_OK = False

# ── PDF (opcional: reportlab) ────────────────────────────────────────────────
try:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    _HAS_PDF = True
except Exception:
    _HAS_PDF = False

st.set_page_config(page_title="Control Avanzado de Facturas", layout="wide")
st.title("Control Avanzado de Facturas: Duplicados y Análisis de Riesgo")

st.markdown(
    """
**⚠️ ¿Por qué es importante?**  
Las facturas duplicadas generan **pagos repetidos**, errores contables y pérdida de control. Esta app permite **identificar, analizar y priorizar** duplicados para reforzar controles.

**¿Cómo usar?**  
1) Sube tu archivo (Excel/CSV).  
2) Confirma el mapeo sugerido o pulsa **Editar mapeo** si necesitas corregir.  
3) Elige **Exacto** o **Aproximado**.  
4) (Opcional) Ajusta parámetros en **⚙️ Configuración avanzada**.  
5) Revisa **KPIs**, tabla y gráficas.  
6) **Exporta** resultados a Excel o PDF.
""")

# =============================================================================
# 1) CARGA DE ARCHIVO (con selector de hoja y opción "todas")
# =============================================================================
file = st.file_uploader("Sube tu archivo Excel o CSV", type=["xlsx", "xls", "csv"])

def _hash_bytes(b: bytes) -> int:
    # hash simple para cache
    return hash(b) & 0xFFFFFFFF

@st.cache_data(show_spinner=False)
def _read_csv(file_bytes: bytes) -> pd.DataFrame:
    return pd.read_csv(io.BytesIO(file_bytes))

@st.cache_data(show_spinner=False)
def _read_excel_sheet(file_bytes: bytes, sheet_name: str) -> pd.DataFrame:
    return pd.read_excel(io.BytesIO(file_bytes), sheet_name=sheet_name)

@st.cache_data(show_spinner=False)
def _list_sheets(file_bytes: bytes):
    xl = pd.ExcelFile(io.BytesIO(file_bytes))
    return xl.sheet_names

@st.cache_data(show_spinner=False)
def _read_excel_all(file_bytes: bytes) -> pd.DataFrame:
    xl = pd.ExcelFile(io.BytesIO(file_bytes))
    frames = []
    for sh in xl.sheet_names:
        df = xl.parse(sh)
        df["__hoja__"] = sh
        frames.append(df)
    return pd.concat(frames, ignore_index=True, sort=False)

if not file:
    st.info("Carga un archivo para comenzar.")
    st.stop()

try:
    bytes_data = file.getvalue()
    is_excel = file.name.lower().endswith((".xlsx", ".xls"))
    df_raw = None
    hoja_info = ""

    if is_excel:
        sheets = _list_sheets(bytes_data)
        st.caption("Tu archivo tiene varias hojas.")
        mode = st.radio("¿Qué hojas deseas analizar?", ["Elegir una", "Todas (unir)"], horizontal=True)
        if mode == "Elegir una":
            sel = st.selectbox("Selecciona la hoja", sheets, index=0)
            df_raw = _read_excel_sheet(bytes_data, sel)
            hoja_info = f" — Hoja seleccionada: **{sel}**"
        else:
            df_raw = _read_excel_all(bytes_data)
            hoja_info = " — Hojas: **todas (unidas)**"
    else:
        df_raw = _read_csv(bytes_data)
        hoja_info = " — Archivo CSV"
except Exception as e:
    st.error(f"No se pudo leer el archivo: {e}")
    st.stop()

if df_raw is None or df_raw.empty:
    st.warning("El archivo está vacío.")
    st.stop()

st.success("Archivo cargado correctamente.")
N_PREVIEW = 30
st.caption(f"Vista previa (primeras {N_PREVIEW} filas){hoja_info}")
st.dataframe(df_raw.head(N_PREVIEW), use_container_width=True)

# =============================================================================
# 2) MAPEO — AUTODETECCIÓN + CONFIRMAR/EDITAR (con combinar)
# =============================================================================
def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s))
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return re.sub(r"[^0-9a-z]", "", s.lower())

_SYNONYMS = {
    "num":   ["numero","número","num","nro","no","factura","invoice","folio","serie","secuencia","documento","doc"],
    "prov":  ["proveedor","supplier","vendor","ruc","nit","taxid","nombreproveedor","provider","parte","counterparty"],
    "fecha": ["fecha","emision","emisión","date","fechafactura","postingdate","documentdate","fechaemision"],
    "monto": ["monto","importe","valor","total","amount","subtotal","grandtotal","neto","bruto","totallinea","totaldoc"],
    "moneda": ["moneda","currency","divisa"],
    "empresa": ["empresa","compania","compañia","company","sociedad","entidad","filial"]
}

cols = df_raw.columns.tolist()

def _best_by_name(keys, headers):
    keys = [_norm(k) for k in keys]
    for h in headers:
        hn = _norm(h)
        if any(k in hn or hn in k for k in keys):
            return h
    return None

def _best_date(headers):
    scores = {c: pd.to_datetime(df_raw[c], errors="coerce").notna().mean() for c in headers}
    return max(scores, key=scores.get)

def _best_numeric(headers):
    scores = {c: pd.to_numeric(df_raw[c], errors="coerce").notna().mean() for c in headers}
    return max(scores, key=scores.get)

h_num    = _best_by_name(_SYNONYMS["num"], cols)    or cols[0]
h_prov   = _best_by_name(_SYNONYMS["prov"], cols)   or (cols[1] if len(cols) > 1 else cols[0])
h_fecha  = _best_by_name(_SYNONYMS["fecha"], cols)  or _best_date(cols)
h_monto  = _best_by_name(_SYNONYMS["monto"], cols)  or _best_numeric(cols)

_defaults = {"num": h_num, "prov": h_prov, "fecha": h_fecha, "monto": h_monto}

if "edit_mapping" not in st.session_state:
    st.session_state.edit_mapping = False

st.subheader("Mapeo de columnas")
st.write("Revisé tu archivo y esto es lo que **detecté automáticamente**:")

cA, cB, cC, cD = st.columns(4)
cA.metric("Nº de factura", _defaults["num"])
cB.metric("Proveedor", _defaults["prov"])
cC.metric("Fecha", _defaults["fecha"])
cD.metric("Monto", _defaults["monto"])

b1, b2 = st.columns([1,1])
usar   = b1.button("✅ Usar mapeo sugerido", type="primary", use_container_width=True)
editar = b2.button(("✏️ Editar mapeo" if not st.session_state.edit_mapping else "🔒 Ocultar edición"),
                   use_container_width=True)
if editar:
    st.session_state.edit_mapping = not st.session_state.edit_mapping

if usar and not st.session_state.edit_mapping:
    c_num, c_prov, c_fecha, c_monto = _defaults["num"], _defaults["prov"], _defaults["fecha"], _defaults["monto"]
else:
    if st.session_state.edit_mapping:
        e1, e2, e3, e4 = st.columns(4)
        with e1: c_num   = st.selectbox("Nº de factura", cols, index=cols.index(_defaults["num"]))
        with e2: c_prov  = st.selectbox("Proveedor",   cols, index=cols.index(_defaults["prov"]))
        with e3: c_fecha = st.selectbox("Fecha de emisión", cols, index=cols.index(_defaults["fecha"]))
        with e4: c_monto = st.selectbox("Monto", cols, index=cols.index(_defaults["monto"]))
        with st.expander("Opciones para combinar campos (opcional)"):
            comb_num = st.checkbox("Combinar columnas para Nº", value=False)
            if comb_num:
                sel = st.multiselect("Columnas a combinar (Nº)", options=cols, default=[c_num])
                sep = st.text_input("Separador", value="-", max_chars=3)
                if sel:
                    df_raw["__num__"] = df_raw[sel].astype(str).agg(lambda r: sep.join([x.strip() for x in r]), axis=1)
                    c_num = "__num__"
            comb_prov = st.checkbox("Combinar columnas para Proveedor", value=False)
            if comb_prov:
                selp = st.multiselect("Columnas a combinar (Proveedor)", options=cols, default=[c_prov])
                sepp = st.text_input("Separador proveedor", value=" ", max_chars=3)
                if selp:
                    df_raw["__prov__"] = df_raw[selp].astype(str).agg(lambda r: sepp.join([x.strip() for x in r]), axis=1)
                    c_prov = "__prov__"
    else:
        c_num, c_prov, c_fecha, c_monto = _defaults["num"], _defaults["prov"], _defaults["fecha"], _defaults["monto"]

# Validaciones rápidas
sel_cols = [c_num, c_prov, c_fecha, c_monto]
if len(set(sel_cols)) < len(sel_cols):
    st.error("Has seleccionado la **misma columna** para más de un rol (Nº/Proveedor/Fecha/Monto). Corrige el mapeo.")
    st.stop()
if pd.to_datetime(df_raw[c_fecha], errors='coerce').notna().mean() < 0.5:
    st.warning(f"La columna **Fecha** (`{c_fecha}`) no parece ser fecha en la mayoría de filas.")
if pd.to_numeric(df_raw[c_monto], errors='coerce').notna().mean() < 0.5:
    st.warning(f"La columna **Monto** (`{c_monto}`) no parece numérica en la mayoría de filas.")

# =============================================================================
# 3) PREPROCESAMIENTO
# =============================================================================
def _strip_accents_lower(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s))
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return s.lower().strip()

df = df_raw.copy()
df[c_prov] = df[c_prov].map(_strip_accents_lower)

# Nº de factura normalizado (alfa-numérico, sin símbolos, sin ceros a la izquierda)
df[c_num] = (df[c_num].astype(str).str.lower()
             .str.replace(r"[^0-9a-z]", "", regex=True)
             .str.lstrip("0"))

df[c_fecha] = pd.to_datetime(df[c_fecha], errors="coerce")
df[c_monto] = pd.to_numeric(df[c_monto], errors="coerce")

# Columnas opcionales Moneda/Empresa (si existen)
def _opt_col(df, synonyms_key):
    cols_l = [c.lower() for c in df.columns]
    for cand in _SYNONYMS[synonyms_key]:
        if cand in cols_l:
            col = df.columns[cols_l.index(cand)]
            df[col] = df[col].astype(str).str.strip().str.lower()
            return col
    return None

_moneda_col  = _opt_col(df, "moneda")
_empresa_col = _opt_col(df, "empresa")

# Filas válidas base
key_mask = df[[c_num, c_prov, c_monto]].notna().all(axis=1)
df = df.loc[key_mask].reset_index(drop=True)
if df.empty:
    st.error("No hay registros válidos tras el preprocesamiento.")
    st.stop()

st.success("Datos preprocesados correctamente.")

# =============================================================================
# 4) CONFIGURACIÓN DE DUPLICADOS
# =============================================================================
st.subheader("Configuración de duplicados")
modo = st.selectbox("Tipo de detección", ["Exacto", "Aproximado"], index=0)

# Defaults
umbral_sim = 90
tol_monto  = 0.00
tol_dias   = 0
bloq_prov  = True
bloq_mes   = False

if modo == "Aproximado":
    with st.expander("⚙️ Configuración avanzada"):
        umbral_sim = st.slider(
            "Coincidencia mínima del Nº (0–100)",
            70, 100, 90,
            help="Porcentaje mínimo de parecido entre números de factura. "
                 "Más alto = más estricto; más bajo = más flexible."
        )
        colA, colB = st.columns(2)
        with colA:
            tol_monto = st.number_input(
                "Tolerancia de monto (misma moneda)",
                min_value=0.0, value=0.00, step=0.01,
                help="Diferencia máxima de importe permitida (ej.: 1.00 permite ±1 unidad)."
            )
        with colB:
            tol_dias  = st.number_input(
                "Tolerancia de fecha (± días)",
                min_value=0, value=0, step=1,
                help="Acepta diferencias de fecha hasta X días."
            )
        bloq_prov = st.checkbox("Comparar solo dentro del mismo proveedor", value=True,
                                help="Reduce falsos positivos y acelera el análisis.")
        bloq_mes  = st.checkbox("Bloquear por mismo mes de emisión", value=False,
                                help="Acelera en archivos grandes (más estricto).")

# =============================================================================
# 5) DETECCIÓN (Exacto + Aproximado con union-find y bloqueos opcionales)
# =============================================================================
@st.cache_data(show_spinner=False)
def detect_exact(df: pd.DataFrame, c_num: str, c_prov: str, c_monto: str, c_fecha: str,
                 moneda_col: str | None, empresa_col: str | None):
    # Agrupar por bloqueos opcionales (moneda/empresa)
    if moneda_col or empresa_col:
        keys = [k for k in [moneda_col, empresa_col] if k]
        mask = df.groupby(keys, dropna=False).apply(
            lambda g: g.duplicated(subset=[c_num, c_prov, c_monto], keep=False)
        ).reset_index(level=0, drop=True)
    else:
        mask = df.duplicated(subset=[c_num, c_prov, c_monto], keep=False)
    out = df.loc[mask].copy()
    out["_regla"] = "Exacto (número + proveedor + monto)"
    out["_cluster_id"] = out.groupby([c_num, c_prov, c_monto]).ngroup()
    out["_cluster_size"] = out.groupby("_cluster_id")["_cluster_id"].transform("size")
    return out.sort_values([c_prov, c_num, c_monto, c_fecha], na_position="last")

def _pairwise(sg: pd.DataFrame, results: list, c_num: str, c_fecha: str, c_monto: str,
              sim_thr: int, tol_monto: float, tol_dias: int):
    rows = sg[[c_num, c_fecha, c_monto, "_rowid"]].values.tolist()
    n = len(rows)
    for i in range(n):
        num_i, fec_i, mon_i, id_i = rows[i]
        for j in range(i+1, n):
            num_j, fec_j, mon_j, id_j = rows[j]
            if not (pd.notna(mon_i) and pd.notna(mon_j)):
                continue
            d_monto = abs(mon_i - mon_j)
            if d_monto > tol_monto:
                continue
            d_dias = 0
            if tol_dias > 0 and pd.notna(fec_i) and pd.notna(fec_j):
                d_dias = abs((fec_i - fec_j).days)
                if d_dias > tol_dias:
                    continue
            if not _FUZZ_OK:
                continue
            sim = fuzz.ratio(str(num_i), str(num_j))
            if sim >= sim_thr:
                results.append([int(id_i), int(id_j), int(sim), float(d_monto), int(d_dias)])

def _union_find_build(pairs_df):
    parent = {}
    def find(x):
        parent.setdefault(x, x)
        if parent[x] != x:
            parent[x] = find(parent[x])
        return parent[x]
    def union(a,b):
        pa, pb = find(a), find(b)
        if pa != pb:
            parent[pb] = pa
    for _, r in pairs_df.iterrows():
        union(r["_id1"], r["_id2"])
    roots = {}
    cluster_ids = {}
    next_id = 0
    for x in set(pairs_df["_id1"]).union(set(pairs_df["_id2"])):
        rx = find(x)
        if rx not in roots:
            roots[rx] = next_id
            next_id += 1
        cluster_ids[x] = roots[rx]
    return cluster_ids

@st.cache_data(show_spinner=False)
def detect_approx(df: pd.DataFrame,
                  c_num: str, c_prov: str, c_fecha: str, c_monto: str,
                  sim_thr: int, tol_monto: float, tol_dias: int,
                  bloquear_por_proveedor: bool, bloquear_por_mes: bool,
                  moneda_col: str | None, empresa_col: str | None):
    if not _FUZZ_OK:
        return pd.DataFrame(columns=df.columns.tolist() + ["_match_id","_sim","_regla","_dmonto","_ddias","_cluster_id","_cluster_size"])

    # Base con bloqueos opcionales
    keep_cols = [c_num, c_prov, c_fecha, c_monto]
    if moneda_col:  keep_cols.append(moneda_col)
    if empresa_col: keep_cols.append(empresa_col)
    work = df[keep_cols].copy()
    work["_rowid"] = np.arange(len(work))

    # keys de agrupación (blocking)
    keys = []
    if bloquear_por_proveedor: keys.append(c_prov)
    if moneda_col:  keys.append(moneda_col)
    if empresa_col: keys.append(empresa_col)

    groups = [work] if not keys else [g for _, g in work.groupby(keys, dropna=False)]
    results = []  # (id1, id2, sim, dmonto, ddias)

    for g in groups:
        subgroups = [g]
        if bloquear_por_mes and g[c_fecha].notna().any():
            subgroups = [sg for _, sg in g.groupby(g[c_fecha].dt.to_period("M"))]

        for sg in subgroups:
            if sg.empty or len(sg) < 2:
                continue
            # Bucketing por monto para rendimiento
            if tol_monto > 0:
                bin_size = max(tol_monto, 1.0)
                bins = np.floor(sg[c_monto].fillna(0) / bin_size)
                for _, bg in sg.groupby(bins):
                    _pairwise(bg, results, c_num, c_fecha, c_monto, sim_thr, tol_monto, tol_dias)
            else:
                _pairwise(sg, results, c_num, c_fecha, c_monto, sim_thr, tol_monto, tol_dias)

    if not results:
        return pd.DataFrame(columns=df.columns.tolist() + ["_match_id","_sim","_regla","_dmonto","_ddias","_cluster_id","_cluster_size"])

    pairs = pd.DataFrame(results, columns=["_id1","_id2","_sim","_dmonto","_ddias"])

    # Union-Find para clústeres
    cluster_map = _union_find_build(pairs)
    cluster_df = pd.DataFrame({"_rowid": list(cluster_map.keys()), "_cluster_id": list(cluster_map.values())})

    # Mejor match por fila (máxima similitud) para explicar "Por_que"
    a = pairs.rename(columns={"_id1":"rowid"})[["rowid","_sim","_dmonto","_ddias"]]
    b = pairs.rename(columns={"_id2":"rowid"})[["rowid","_sim","_dmonto","_ddias"]]
    pairs_l = pd.concat([a,b], ignore_index=True)
    best = pairs_l.sort_values("_sim", ascending=False).drop_duplicates("rowid", keep="first")
    best = best.rename(columns={"rowid":"_rowid"})

    out = work.merge(best, on="_rowid", how="inner").merge(cluster_df, on="_rowid", how="left")
    out["_regla"] = "Aproximado (fuzzy + tolerancias)"
    out["_cluster_size"] = out.groupby("_cluster_id")["_cluster_id"].transform("size")

    merged = df.reset_index(drop=True).merge(
        out[["_rowid","_sim","_dmonto","_ddias","_cluster_id","_cluster_size","_regla"]],
        left_index=True, right_on="_rowid", how="left"
    ).drop(columns=["_rowid"])
    merged = merged[merged["_cluster_id"].notna()].copy()
    if c_fecha in merged:
        merged = merged.sort_values([c_prov, c_num, c_monto, c_fecha], na_position="last")
    return merged

# Ejecutar
if modo == "Exacto":
    df_dups = detect_exact(df, c_num, c_prov, c_monto, c_fecha, _moneda_col, _empresa_col)
else:
    df_dups = detect_approx(df, c_num, c_prov, c_fecha, c_monto,
                            umbral_sim, tol_monto, tol_dias,
                            bloq_prov, bloq_mes, _moneda_col, _empresa_col)

# =============================================================================
# 5.1) Explicación del match + Score de riesgo + Etiquetas + Leyenda colores
# =============================================================================
if not df_dups.empty:
    # Columna Por_que
    if modo == "Exacto":
        df_dups["Por_que"] = "Coincidencia exacta (número + proveedor + monto)"
    else:
        def _pq(row):
            partes = []
            sim_val = row.get("_sim", None)
            if isinstance(sim_val, (int, float, np.number)) and pd.notna(sim_val):
                partes.append(f"sim≈{int(sim_val)}%")
            else:
                partes.append("coincidencia aproximada")
            if "_dmonto" in df_dups.columns and tol_monto > 0 and pd.notna(row.get("_dmonto")):
                partes.append(f"Δmonto={float(row['_dmonto']):.2f}")
            if "_ddias" in df_dups.columns and tol_dias > 0 and pd.notna(row.get("_ddias")):
                partes.append(f"Δdías={int(row['_ddias'])}")
            llaves = []
            if bloq_prov: llaves.append("mismo proveedor")
            if bloq_mes:  llaves.append("mismo mes")
            if _moneda_col:  llaves.append("misma moneda")
            if _empresa_col: llaves.append("misma empresa")
            if llaves:
                partes.append(", ".join(llaves))
            if "_cluster_size" in df_dups.columns and pd.notna(row.get("_cluster_size")):
                partes.append(f"clúster={int(row['_cluster_size'])}")
            return ", ".join(partes)
        df_dups["Por_que"] = df_dups.apply(_pq, axis=1)

    # Score de riesgo y nivel
    z = (df_dups[c_monto] - df_dups[c_monto].mean())
    denom = df_dups[c_monto].std(ddof=0)
    z = z / (denom if denom and not np.isclose(denom, 0.0) else 1.0)
    df_dups["_freq_proveedor"] = df_dups.groupby(c_prov)[c_prov].transform("count")
    df_dups["_riesgo"] = z.fillna(0) + (df_dups["_freq_proveedor"] /
                                        max(df_dups["_freq_proveedor"].max(), 1))

    if len(df_dups) >= 3:
        q_low, q_high = df_dups["_riesgo"].quantile([0.33, 0.66]).tolist()
    else:
        q_low, q_high = df_dups["_riesgo"].min(), df_dups["_riesgo"].max()

    def _nivel_riesgo(s):
        if s >= q_high: return "Alto"
        if s >= q_low:  return "Medio"
        return "Bajo"

    df_dups["Nivel_riesgo"] = df_dups["_riesgo"].apply(_nivel_riesgo)

# Leyenda de colores (app)
st.markdown(
    """
**Leyenda de colores – Nivel de riesgo**  
<span style="background-color:#ff4d4f; color:white; padding:3px 8px; border-radius:6px;">Alto</span>
<span style="background-color:#faad14; color:black; padding:3px 8px; border-radius:6px; margin-left:8px;">Medio</span>
<span style="background-color:#52c41a; color:white; padding:3px 8px; border-radius:6px; margin-left:8px;">Bajo</span>
""",
    unsafe_allow_html=True
)

# =============================================================================
# 6) FILTROS (Proveedor, Monto, Fecha)
# =============================================================================
st.subheader("Filtros de análisis")
if df_dups.empty:
    st.info("No se encontraron duplicados con las reglas actuales.")
else:
    prods = sorted(df[c_prov].dropna().unique().tolist())
    f_prov = st.multiselect("Proveedor", options=prods, default=prods)

    vmin = float(np.nanmin(df[c_monto].values)) if df[c_monto].notna().any() else 0.0
    vmax = float(np.nanmax(df[c_monto].values)) if df[c_monto].notna().any() else 1.0
    f_min, f_max = st.slider("Rango de monto", vmin, vmax, (vmin, vmax))

    # Filtro por fecha (si existen fechas)
    if df_dups[c_fecha].notna().any():
        dmin = pd.to_datetime(df_dups[c_fecha].min()).date()
        dmax = pd.to_datetime(df_dups[c_fecha].max()).date()
        f_dates = st.date_input("Rango de fecha", value=(dmin, dmax))
        if isinstance(f_dates, tuple) and len(f_dates) == 2:
            f_start, f_end = f_dates
        else:
            f_start, f_end = dmin, dmax
        mask_date = df_dups[c_fecha].dt.date.between(f_start, f_end)
    else:
        mask_date = True

    df_dups = df_dups[
        df_dups[c_prov].isin(f_prov) &
        df_dups[c_monto].between(f_min, f_max) &
        mask_date
    ]

# =============================================================================
# 7) KPIs + TABLA
# =============================================================================
st.subheader("Indicadores clave")
N = len(df)
D = len(df_dups)
porc = round((D / N) * 100, 2) if N else 0.0
monto_dup = float(df_dups[c_monto].sum()) if not df_dups.empty else 0.0
col1, col2, col3, col4 = st.columns(4)
col1.metric("Total Facturas", f"{N:,}")
col2.metric("Duplicados", f"{D:,}")
col3.metric("% Duplicados", f"{porc}%")
col4.metric("Monto Total Duplicados", f"$ {monto_dup:,.2f}")

st.subheader("Tabla de facturas potencialmente duplicadas")
st.dataframe(df_dups, use_container_width=True)

# =============================================================================
# 8) VISUALIZACIONES
# =============================================================================
st.subheader("Visualizaciones")
if not df_dups.empty:
    # Monto duplicado por proveedor
    prov_agg = df_dups.groupby(c_prov, dropna=False)[c_monto].sum().reset_index()
    if _HAS_PLOTLY:
        fig1 = px.bar(prov_agg, x=c_prov, y=c_monto, title="Monto duplicado por proveedor")
        st.plotly_chart(fig1, use_container_width=True)
    else:
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots()
        ax.bar(prov_agg[c_prov].astype(str), prov_agg[c_monto])
        ax.set_title("Monto duplicado por proveedor"); ax.set_xlabel("Proveedor"); ax.set_ylabel("Monto")
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

# =============================================================================
# 9) PRIORIZACIÓN DE RIESGO
# =============================================================================
st.subheader("Priorización de riesgo")
if not df_dups.empty:
    topn = st.slider("Mostrar Top-N por riesgo", 5, min(50, max(5, len(df_dups))), 10)
    cols_show = [c for c in [c_num, c_prov, c_monto, c_fecha, "__hoja__", "_riesgo", "Nivel_riesgo", "Por_que", "_cluster_id", "_cluster_size"] if c in df_dups.columns]
    st.dataframe(
        df_dups.sort_values("_riesgo", ascending=False)[cols_show].head(topn),
        use_container_width=True
    )

# =============================================================================
# 10) EXPORTACIÓN (Excel + PDF con leyenda de colores)
# =============================================================================
st.subheader("Exportar resultados")
if df_dups.empty:
    st.warning("No hay duplicados para exportar.")
else:
    # ---- Excel ----
    output_xlsx = io.BytesIO()
    with pd.ExcelWriter(output_xlsx, engine="xlsxwriter") as writer:
        df_dups.to_excel(writer, index=False, sheet_name="Duplicados")

        prov_res = (
            df_dups.groupby(c_prov, dropna=False)
            .agg(total_monto=(c_monto, "sum"), n_items=(c_prov, "size"))
            .reset_index().sort_values("total_monto", ascending=False)
        )
        prov_res.to_excel(writer, index=False, sheet_name="Resumen_Proveedor")

        # Resumen por cliente (si existe)
        cols_l = [c.lower() for c in df_dups.columns]
        cliente_col = None
        for alias in ["cliente", "customer", "client", "buyer"]:
            if alias in cols_l:
                cliente_col = df_dups.columns[cols_l.index(alias)]
                break
        if cliente_col:
            cli_res = (
                df_dups.groupby(cliente_col, dropna=False)
                .agg(total_monto=(c_monto, "sum"), n_items=(cliente_col, "size"))
                .reset_index().sort_values("total_monto", ascending=False)
            )
            cli_res.to_excel(writer, index=False, sheet_name="Resumen_Cliente")

    st.download_button(
        label="📊 Descargar Excel",
        data=output_xlsx.getvalue(),
        file_name="duplicados_avanzados.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True
    )

    # ---- PDF ----
    def _build_pdf_report(
        title: str,
        kpis: dict,
        df_dups: pd.DataFrame,
        c_num: str,
        c_prov: str,
        c_monto: str,
        c_fecha: str,
        max_rows: int = 200
    ) -> bytes:
        buf = io.BytesIO()
        doc = SimpleDocTemplate(
            buf, pagesize=A4,
            leftMargin=24, rightMargin=24, topMargin=28, bottomMargin=28
        )
        styles = getSampleStyleSheet()
        h1 = ParagraphStyle("H1", parent=styles["Heading1"], fontSize=16, spaceAfter=8)
        h2 = ParagraphStyle("H2", parent=styles["Heading2"], fontSize=12, spaceBefore=8, spaceAfter=6)
        p  = styles["Normal"]

        story = []
        story.append(Paragraph(title, h1))
        story.append(Paragraph(pd.Timestamp.now().strftime("Generado: %Y-%m-%d %H:%M"), p))
        story.append(Spacer(1, 8))

        # KPIs
        kpi_data = [["KPI", "Valor"]]
        for k, v in kpis.items():
            kpi_data.append([k, f"{v}"])
        kpi_tbl = Table(kpi_data, hAlign="LEFT")
        kpi_tbl.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#f0f0f0")),
            ("GRID", (0,0), (-1,-1), 0.25, colors.grey),
            ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
            ("ALIGN", (1,1), (1,-1), "RIGHT"),
            ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, colors.HexColor("#fbfbfb")]),
        ]))
        story.append(Paragraph("Indicadores clave", h2))
        story.append(kpi_tbl)
        story.append(Spacer(1, 12))

        # Leyenda de colores
        legend_data = [
            ["Nivel de riesgo", "Color"],
            ["Alto",  ""],
            ["Medio", ""],
            ["Bajo",  ""],
        ]
        legend_tbl = Table(legend_data, colWidths=[120, 60])
        legend_tbl.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#f0f0f0")),
            ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
            ("GRID", (0,0), (-1,-1), 0.25, colors.grey),
            ("BACKGROUND", (1,1), (1,1), colors.HexColor("#ff4d4f")),  # Alto
            ("BACKGROUND", (1,2), (1,2), colors.HexColor("#faad14")),  # Medio
            ("BACKGROUND", (1,3), (1,3), colors.HexColor("#52c41a")),  # Bajo
        ]))
        story.append(Paragraph("Leyenda de colores — Nivel de riesgo", h2))
        story.append(legend_tbl)
        story.append(Spacer(1, 12))

        # Top proveedores (15)
        if not df_dups.empty:
            prov_agg = (
                df_dups.groupby(c_prov, dropna=False)[c_monto]
                .sum().reset_index().sort_values(c_monto, ascending=False).head(15)
            )
            prov_data = [[c_prov, "Monto duplicado"]]
            for _, r in prov_agg.iterrows():
                prov_data.append([str(r[c_prov]), f"$ {float(r[c_monto]):,.2f}"])
            prov_tbl = Table(prov_data, hAlign="LEFT", colWidths=[260, 120])
            prov_tbl.setStyle(TableStyle([
                ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#e9f5ff")),
                ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
                ("GRID", (0,0), (-1,-1), 0.25, colors.grey),
                ("ALIGN", (1,1), (1,-1), "RIGHT"),
            ]))
            story.append(Paragraph("Top proveedores por monto duplicado", h2))
            story.append(prov_tbl)
            story.append(Spacer(1, 12))

        # Detalle (muestra)
        if not df_dups.empty:
            cols_show = [c_num, c_prov]
            if c_fecha in df_dups.columns:
                cols_show.append(c_fecha)
            cols_show.append(c_monto)
            for opt in ["__hoja__", "_cluster_id", "_cluster_size", "_sim", "_dmonto", "_ddias", "Por_que", "Nivel_riesgo"]:
                if opt in df_dups.columns and opt not in cols_show:
                    cols_show.append(opt)

            df_show = df_dups.loc[:, [c for c in cols_show if c in df_dups.columns]].copy()
            n_total = len(df_show)
            df_show = df_show.head(max_rows)

            head = [str(c) for c in df_show.columns]
            data = [head]
            for _, row in df_show.iterrows():
                data.append([("" if pd.isna(x) else str(x)) for x in row.tolist()])

            t = Table(data, repeatRows=1)
            t.setStyle(TableStyle([
                ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#ffeef2")),
                ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
                ("GRID", (0,0), (-1,-1), 0.25, colors.grey),
                ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, colors.HexColor("#fff9fb")]),
                ("ALIGN", (-1,1), (-1,-1), "RIGHT"),
            ]))
            story.append(Paragraph(f"Detalle de duplicados (muestra de {len(df_show):

