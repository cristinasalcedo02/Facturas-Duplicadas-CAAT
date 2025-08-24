
# CAAT Avanzado — Detección de Facturas Duplicadas con Análisis de Riesgo
# Autor: Grupo A (versión integrada con exportación PDF y correcciones de Excel)
# ---------------------------------------------------------------------------------
# Notas:
# - Requiere: streamlit, pandas, numpy
# - Opcional (para gráficos y PDF): plotly, kaleido, matplotlib, PyPDF2, xlsxwriter/openpyxl
# - Ejecución: streamlit run app_caat_duplicados.py

import io
import re
import unicodedata
from itertools import zip_longest

import numpy as np
import pandas as pd
import streamlit as st

# ── Gráficos (Plotly opcional)
_HAS_PLOTLY = False
try:
    import plotly.express as px
    _HAS_PLOTLY = True
except Exception:
    _HAS_PLOTLY = False

# ── Fuzzy matching (rapidfuzz > thefuzz > none)
_FUZZ_OK = False
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
6) **Exporta** resultados a Excel (duplicados + resumen) y **gráficos a PDF**.
"""
)

# =============================================================================
# 1) CARGA DE ARCHIVO (por bytes para evitar caché por nombre)
# =============================================================================
file = st.file_uploader("Sube tu archivo Excel o CSV", type=["xlsx", "xls", "csv"])

@st.cache_data(show_spinner=False)
def _read_file(file_bytes: bytes, file_name: str) -> pd.DataFrame:
    bio = io.BytesIO(file_bytes)
    if file_name.lower().endswith((".xlsx", ".xls")):
        try:
            return pd.read_excel(bio, engine="openpyxl")
        except Exception:
            return pd.read_excel(bio)  # fallback al engine por defecto
    # Ajusta sep=";" si tus CSV lo requieren
    try:
        return pd.read_csv(bio)
    except Exception:
        bio.seek(0)
        return pd.read_csv(bio, sep=";")

if not file:
    st.info("Carga un archivo para comenzar.")
    st.stop()

file_bytes = file.getvalue()
try:
    df_raw = _read_file(file_bytes, file.name)
except Exception as e:
    st.error(f"No se pudo leer el archivo: {e}")
    st.stop()

if df_raw.empty:
    st.warning("El archivo está vacío.")
    st.stop()

st.success(f"Archivo cargado: **{file.name}** · **{len(file_bytes):,} bytes**")

# Vista previa corta
N_PREVIEW = 40
st.caption(f"Vista previa (primeras {N_PREVIEW} filas)")
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
    "prov_keys":  ["proveedor","supplier","vendor","ruc","nit","taxid","tercero"],
    "cli_keys":   ["cliente","customer"],
    "ter_keys":   ["tercero","third","thirdparty"],
    "fecha": ["fecha","emision","emisión","date","fechafactura","postingdate","documentdate","fechaemision"],
    "monto": ["monto","importe","valor","total","amount","subtotal","grandtotal","neto","bruto","totallinea","totaldoc"],
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

h_num   = _best_by_name(_SYNONYMS["num"], cols)   or cols[0]
h_party = (_best_by_name(_SYNONYMS["prov_keys"], cols)
           or _best_by_name(_SYNONYMS["cli_keys"], cols)
           or _best_by_name(_SYNONYMS["ter_keys"], cols)
           or (cols[1] if len(cols) > 1 else cols[0]))
h_fecha = _best_by_name(_SYNONYMS["fecha"], cols) or _best_date(cols)
h_monto = _best_by_name(_SYNONYMS["monto"], cols) or _best_numeric(cols)

def _party_label_from_header(h: str) -> str:
    # Etiqueta neutral por defecto
    return "Contraparte"

party_label = _party_label_from_header(h_party)
_defaults = {"num": h_num, "party": h_party, "fecha": h_fecha, "monto": h_monto}

if "edit_mapping" not in st.session_state:
    st.session_state.edit_mapping = False

st.subheader("Mapeo de columnas")
st.write("Revisé tu archivo y esto es lo que **detecté automáticamente**:")

cA, cB, cC, cD = st.columns(4)
cA.metric("Nº de factura", _defaults["num"])
cB.metric(party_label, _defaults["party"])
cC.metric("Fecha", _defaults["fecha"])
cD.metric("Monto", _defaults["monto"])

b1, b2 = st.columns([1,1])
usar   = b1.button("✅ Usar mapeo sugerido", type="primary", use_container_width=True)
editar = b2.button(("✏️ Editar mapeo" if not st.session_state.edit_mapping else "🔒 Ocultar edición"),
                   use_container_width=True)
if editar:
    st.session_state.edit_mapping = not st.session_state.edit_mapping

if usar and not st.session_state.edit_mapping:
    c_num, c_prov, c_fecha, c_monto = _defaults["num"], _defaults["party"], _defaults["fecha"], _defaults["monto"]
else:
    if st.session_state.edit_mapping:
        e1, e2, e3, e4 = st.columns(4)
        with e1: c_num   = st.selectbox("Nº de factura", cols, index=cols.index(_defaults["num"]))
        with e2:
            c_prov = st.selectbox(party_label, cols, index=cols.index(_defaults["party"]))
            party_label = _party_label_from_header(c_prov)
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
            comb_prov = st.checkbox(f"Combinar columnas para {party_label}", value=False)
            if comb_prov:
                selp = st.multiselect(f"Columnas a combinar ({party_label})", options=cols, default=[c_prov])
                sepp = st.text_input(f"Separador {party_label.lower()}", value=" ", max_chars=3)
                if selp:
                    df_raw["__party__"] = df_raw[selp].astype(str).agg(lambda r: sepp.join([x.strip() for x in r]), axis=1)
                    c_prov = "__party__"
    else:
        c_num, c_prov, c_fecha, c_monto = _defaults["num"], _defaults["party"], _defaults["fecha"], _defaults["monto"]

# Etiqueta visible personalizable
with st.expander("🔤 Etiqueta visible (opcional)"):
    _custom_party_label = st.text_input("Cómo quieres llamar a la columna de contraparte en la interfaz",
                                        value=party_label or "Contraparte")
    party_label = _custom_party_label.strip() or "Contraparte"

# Validaciones rápidas
sel_cols = [c_num, c_prov, c_fecha, c_monto]
if len(set(sel_cols)) < len(sel_cols):
    st.error("Has seleccionado la **misma columna** para más de un rol (Nº/Contraparte/Fecha/Monto). Corrige el mapeo.")
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

# Nº de factura normalizado
df[c_num] = (df[c_num].astype(str).str.lower()
             .str.replace(r"[^0-9a-z]", "", regex=True)
             .str.lstrip("0"))

df[c_fecha] = pd.to_datetime(df[c_fecha], errors="coerce")
df[c_monto] = pd.to_numeric(df[c_monto], errors="coerce")

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

umbral_sim = 90
tol_monto  = 0.00
tol_dias   = 0
bloq_prov  = True
bloq_mes   = False

if modo == "Aproximado":
    if not _FUZZ_OK:
        st.warning("La detección aproximada requiere rapidfuzz/thefuzz. Cambia a 'Exacto' o instala la dependencia.")
    with st.expander("⚙️ Configuración avanzada"):
        usar_simple = st.toggle("Usar selector simple de coincidencia", value=False)
        if usar_simple:
            nivel_ui = st.select_slider(
                "Exigencia de coincidencia del Nº",
                options=["Muy flexible","Flexible","Intermedia","Estricta","Muy estricta"],
                value="Estricta",
            )
            mapa = {"Muy flexible": 70, "Flexible": 78, "Intermedia": 85, "Estricta": 92, "Muy estricta": 97}
            umbral_sim = mapa[nivel_ui]
            st.caption(f"Coincidencia mínima equivalente: **{umbral_sim}%**")
        else:
            umbral_sim = st.slider("Coincidencia mínima del Nº (0–100)", 70, 100, 90)
        colA, colB = st.columns(2)
        with colA:
            tol_monto = st.number_input("Tolerancia de monto (misma moneda)", min_value=0.0, value=0.00, step=0.01)
        with colB:
            tol_dias  = st.number_input("Tolerancia de fecha (± días)", min_value=0, value=0, step=1)
        bloq_prov = st.checkbox(
            f"Buscar duplicados solo dentro de la misma {party_label.lower()} (recomendado)",
            value=True
        )
        bloq_mes  = st.checkbox("Bloquear por mismo mes de emisión", value=False)

# =============================================================================
# 5) DETECCIÓN
# =============================================================================
@st.cache_data(show_spinner=False)
def detect_exact(df: pd.DataFrame, c_num: str, c_prov: str, c_monto: str, c_fecha: str):
    # Duplicados exactos por num+contraparte+monto
    mask = df.duplicated(subset=[c_num, c_prov, c_monto], keep=False)
    out = df.loc[mask].copy()
    # Asignar un _match_id consistente por grupo
    if not out.empty:
        out["_match_id"] = out.groupby([c_num, c_prov, c_monto]).ngroup()
    else:
        out["_match_id"] = pd.Series(dtype=int)
    out["_sim"] = 100
    out["_regla"] = "Exacto (num+contraparte+monto)"
    sort_cols = [c_prov, c_num, c_monto]
    if c_fecha in out:
        sort_cols.append(c_fecha)
    return out.sort_values(sort_cols, na_position="last")

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
            if abs(mon_i - mon_j) > tol_monto:
                continue
            if tol_dias > 0 and pd.notna(fec_i) and pd.notna(fec_j):
                if abs((fec_i - fec_j).days) > tol_dias:
                    continue
            sim = fuzz.ratio(str(num_i), str(num_j))
            if sim >= sim_thr:
                results.append([id_i, id_j, sim])

@st.cache_data(show_spinner=False)
def detect_approx(df: pd.DataFrame,
                  c_num: str, c_prov: str, c_fecha: str, c_monto: str,
                  sim_thr: int, tol_monto: float, tol_dias: int,
                  bloquear_por_proveedor: bool, bloquear_por_mes: bool):
    if not _FUZZ_OK:
        return pd.DataFrame(columns=df.columns.tolist() + ["_match_id", "_sim", "_regla"])

    work = df[[c_num, c_prov, c_fecha, c_monto]].copy()
    work["_rowid"] = np.arange(len(work))

    groups = [work]
    if bloquear_por_proveedor:
        groups = [g for _, g in work.groupby(c_prov)]

    results = []
    for g in groups:
        if bloquear_por_mes and g[c_fecha].notna().any():
            subgroups = [sg for _, sg in g.groupby(g[c_fecha].dt.to_period("M"))]
        else:
            subgroups = [g]
        for sg in subgroups:
            if sg.empty or len(sg) < 2:
                continue
            if tol_monto > 0:
                bin_size = max(tol_monto, 1.0)
                bins = np.floor(sg[c_monto].fillna(0) / bin_size)
                for _, bg in sg.groupby(bins):
                    _pairwise(bg, results, c_num, c_fecha, c_monto, sim_thr, tol_monto, tol_dias)
            else:
                _pairwise(sg, results, c_num, c_fecha, c_monto, sim_thr, tol_monto, tol_dias)

    if not results:
        return pd.DataFrame(columns=df.columns.tolist() + ["_match_id", "_sim", "_regla"])

    pairs = pd.DataFrame(results, columns=["_id1", "_id2", "_sim"])
    pairs_long = pairs.melt(id_vars=["_sim"], value_vars=["_id1", "_id2"],
                            var_name="side", value_name="_rowid")

    out = work.merge(pairs_long[["_rowid", "_sim"]], on="_rowid", how="inner")
    out["_match_id"] = out.groupby("_rowid").ngroup()
    out["_regla"] = "Aproximado (fuzzy+tol)"

    merged = df.reset_index(drop=True).merge(
        out[["_rowid", "_match_id", "_sim", "_regla"]],
        left_index=True, right_on="_rowid", how="left"
    )
    merged = merged.drop(columns=["_rowid"])
    merged = merged[merged["_match_id"].notna()].copy()
    sort_cols = [c_prov, c_num, c_monto]
    if c_fecha in merged:
        sort_cols.append(c_fecha)
    return merged.sort_values(sort_cols, na_position="last")

# Ejecutar
if modo == "Exacto":
    df_dups = detect_exact(df, c_num, c_prov, c_monto, c_fecha)
else:
    df_dups = detect_approx(df, c_num, c_prov, c_fecha, c_monto,
                            umbral_sim, tol_monto, tol_dias,
                            bloq_prov, bloq_mes)

# =============================================================================
# 6) FILTROS
# =============================================================================
st.subheader("Filtros de análisis")
if df_dups.empty:
    st.info("No se encontraron duplicados con las reglas actuales.")
else:
    opciones_party = sorted(df[c_prov].dropna().unique().tolist())
    f_party = st.multiselect(party_label, options=opciones_party, default=opciones_party)

    vmin = float(np.nanmin(df[c_monto].values)) if df[c_monto].notna().any() else 0.0
    vmax = float(np.nanmax(df[c_monto].values)) if df[c_monto].notna().any() else 1.0
    f_min, f_max = st.slider("Rango de monto", vmin, vmax, (vmin, vmax))

    if df[c_fecha].notna().any():
        f_fecha_min, f_fecha_max = st.slider(
            "Rango de fechas",
            min_value=df[c_fecha].min().date(),
            max_value=df[c_fecha].max().date(),
            value=(df[c_fecha].min().date(), df[c_fecha].max().date())
        )
        df_dups = df_dups[
            (df_dups[c_prov].isin(f_party)) &
            (df_dups[c_monto].between(f_min, f_max)) &
            (df_dups[c_fecha].dt.date.between(f_fecha_min, f_fecha_max))
        ]
    else:
        df_dups = df_dups[df_dups[c_prov].isin(f_party) & df_dups[c_monto].between(f_min, f_max)]

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
plotly_figs, mpl_figs = [], []

if not df_dups.empty:
    prov_agg = df_dups.groupby(c_prov, dropna=False)[c_monto].sum().reset_index()
    if _HAS_PLOTLY:
        fig1 = px.bar(prov_agg, x=c_prov, y=c_monto, title=f"Monto duplicado por {party_label.lower()}")
        st.plotly_chart(fig1, use_container_width=True)
        plotly_figs.append(fig1)
    else:
        import matplotlib.pyplot as plt
        fig_bar, ax = plt.subplots()
        ax.bar(prov_agg[c_prov].astype(str), prov_agg[c_monto])
        ax.set_title(f"Monto duplicado por {party_label.lower()}"); ax.set_xlabel(party_label); ax.set_ylabel("Monto")
        st.pyplot(fig_bar)
        mpl_figs.append(fig_bar)

    if df_dups[c_fecha].notna().any():
        time_agg = df_dups.copy()
        time_agg["_mes"] = time_agg[c_fecha].dt.to_period("M").dt.to_timestamp()
        time_agg = time_agg.groupby("_mes")[c_monto].sum().reset_index()
        if _HAS_PLOTLY:
            fig2 = px.line(time_agg, x="_mes", y=c_monto, markers=True, title="Monto duplicado por mes")
            st.plotly_chart(fig2, use_container_width=True)
            plotly_figs.append(fig2)
        else:
            import matplotlib.pyplot as plt
            fig_line, ax = plt.subplots()
            ax.plot(time_agg["_mes"], time_agg[c_monto], marker="o")
            ax.set_title("Monto duplicado por mes"); ax.set_xlabel("Mes"); ax.set_ylabel("Monto")
            st.pyplot(fig_line)
            mpl_figs.append(fig_line)

# =============================================================================
# 9) PRIORIZACIÓN DE RIESGO + BLOQUES EN LISTA (COLORES)
# =============================================================================
st.subheader("Priorización de riesgo")

def categorizar_riesgo(valor: float) -> str:
    if valor >= 2: return "Alto"
    elif valor >= 1: return "Medio"
    else: return "Bajo"

if not df_dups.empty:
    z = (df_dups[c_monto] - df_dups[c_monto].mean()) / (df_dups[c_monto].std(ddof=0) if df_dups[c_monto].std(ddof=0) else 1)
    df_dups["_freq_party"] = df_dups.groupby(c_prov)[c_prov].transform("count")
    df_dups["_riesgo"] = z.fillna(0) + (df_dups["_freq_party"] / max(df_dups["_freq_party"].max(), 1))
    df_dups["Nivel_riesgo"] = df_dups["_riesgo"].apply(categorizar_riesgo)

    topn = st.slider("Mostrar Top-N por riesgo", 5, min(50, max(5, len(df_dups))), 10)
    st.dataframe(df_dups.sort_values("_riesgo", ascending=False).head(topn), use_container_width=True)

def construir_alertas_conclusiones(df, df_dups):
    alerts, concl, recs = [], [], []
    N, D = len(df), len(df_dups)
    porc = (D / N * 100) if N else 0.0
    monto_total = float(df[c_monto].sum()) if N else 0.0
    monto_dup = float(df_dups[c_monto].sum()) if D else 0.0

    if D == 0:
        concl.append("No se detectaron posibles duplicados con las reglas actuales.")
        recs.extend([
            "Verifica el mapeo de columnas (Nº, Contraparte, Fecha, Monto) y, si aplica, combina campos.",
            "Prueba bajar la coincidencia mínima o subir las tolerancias de monto/fecha.",
            "Amplía el filtro de 'Rango de monto' y revisa si hay múltiples monedas.",
            "Ejecuta en 'Aproximado' si hoy estás en 'Exacto'."
        ])
        return alerts, concl, recs

    if porc >= 10:  alerts.append(f"Tasa de duplicados elevada: {porc:.2f}% (≥10%).")
    elif porc >= 3: alerts.append(f"Tasa de duplicados moderada: {porc:.2f}% (≥3%).")

    if monto_total and (monto_dup / monto_total) >= 0.02:
        alerts.append("El monto duplicado supera el 2% del total facturado.")

    prov_agg = df_dups.groupby(c_prov)[c_monto].sum().sort_values(ascending=False)
    if not prov_agg.empty and monto_dup:
        top_party, top_amt = prov_agg.index[0], float(prov_agg.iloc[0])
        share = top_amt / monto_dup
        if share >= 0.5:
            alerts.append(f"Concentración: {top_party} acumula {share:.0%} del monto duplicado.")

    sizes = df_dups.groupby([c_prov, c_num]).size()
    grupos_3p = sizes[sizes >= 3]
    if not grupos_3p.empty:
        alerts.append(f"Se detectaron {len(grupos_3p)} grupo(s) de tres o más facturas con el mismo Nº y {party_label.lower()} (máx: {int(grupos_3p.max())}).")

    if (df_dups.groupby(c_num)[c_prov].nunique() >= 2).any():
        alerts.append(f"Hay números de factura repetidos en distintas {party_label.lower()}s (posible cruce o error de alta).")

    if c_fecha in df_dups and df_dups[c_fecha].notna().any():
        recientes = df_dups[df_dups[c_fecha] >= (pd.Timestamp.today().normalize() - pd.Timedelta(days=30))]
        if len(recientes) > 0:
            alerts.append(f"{len(recientes)} duplicado(s) en los últimos 30 días.")

    if c_fecha in df and df[c_fecha].isna().mean() > 0.2:
        alerts.append("Más del 20% de las facturas no tiene fecha; esto puede ocultar duplicados.")

    concl.append(f"Se identificaron {D:,} posibles duplicados ({porc:.2f}%) por un total de $ {monto_dup:,.2f}.")
    if alerts:
        concl.append("Los hallazgos muestran señales de riesgo que requieren revisión prioritaria.")

    recs.extend([
        f"Revisar primero el Top-N por riesgo (monto alto + {party_label.lower()}s con más repeticiones).",
        "Configurar en el ERP la validación de duplicados por Nº + contraparte + monto + fecha (con tolerancias).",
        f"Mantener limpio el maestro de {party_label.lower()}s (homónimos, RUC/NIT duplicados).",
        "Bloquear pagos hasta aclaración cuando el grupo (_match_id) tenga ≥3 facturas.",
    ])
    return alerts, concl, recs

alerts, concl, recs = construir_alertas_conclusiones(df, df_dups)

def _html_box(title_emoji: str, items: list, bg: str, border: str):
    if not items:
        return ""
    lis = "".join(f"<li>{x}</li>" for x in items)
    return f"""
    <div style="background:{bg}; border:1px solid {border}; padding:14px 16px; border-radius:10px; margin:12px 0;">
      <div style="font-weight:700; margin-bottom:6px;">{title_emoji}</div>
      <ul style="margin:0 0 0 18px; padding:0;">{lis}</ul>
    </div>
    """

st.markdown(
    _html_box("🚨 Alertas", alerts,    bg="#FFE8E8", border="#FF6B6B") +
    _html_box("🧠 Conclusiones", concl, bg="#E7F0FF", border="#5B8DEF") +
    _html_box("🛠️ Recomendaciones", recs, bg="#E8F8EF", border="#34A853"),
    unsafe_allow_html=True
)

# =============================================================================
# 8.1) EXPORTAR GRÁFICOS A PDF
# =============================================================================
from io import BytesIO

st.subheader("Exportar gráficos a PDF")

def _build_pdf_from_figs(plotly_figs=None, mpl_figs=None) -> bytes:
    plotly_figs = plotly_figs or []
    mpl_figs = mpl_figs or []
    buf = BytesIO()
    have_any = False

    # 1) Plotly (Kaleido)
    if plotly_figs:
        try:
            from PyPDF2 import PdfWriter, PdfReader  # PyPDF2 para combinar PDFs
            pdf_writer = PdfWriter()
            for f in plotly_figs:
                pdf_bytes = f.to_image(format="pdf")  # requiere kaleido
                tmp = BytesIO(pdf_bytes)
                reader = PdfReader(tmp)
                for page in reader.pages:
                    pdf_writer.add_page(page)
            pdf_writer.write(buf)
            have_any = True
        except Exception as e:
            st.warning(f"No fue posible exportar con Plotly/Kaleido: {e}")

    # 2) Matplotlib
    if mpl_figs:
        try:
            from matplotlib.backends.backend_pdf import PdfPages
            if have_any:
                # Crear PDF de MPL aparte y luego unir
                mpl_buf = BytesIO()
                with PdfPages(mpl_buf) as pdf:
                    for fig in mpl_figs:
                        pdf.savefig(fig, bbox_inches="tight")
                mpl_buf.seek(0)

                # Unir PDFs
                from PyPDF2 import PdfReader, PdfWriter
                buf.seek(0)
                writer = PdfWriter()
                for stream in (buf, mpl_buf):
                    reader = PdfReader(stream)
                    for p in reader.pages:
                        writer.add_page(p)
                final = BytesIO()
                writer.write(final)
                return final.getvalue()
            else:
                with PdfPages(buf) as pdf:
                    for fig in mpl_figs:
                        pdf.savefig(fig, bbox_inches="tight")
                have_any = True
        except Exception as e:
            st.warning(f"No fue posible exportar con Matplotlib: {e}")

    if not have_any:
        return b""
    return buf.getvalue()

if st.button("Descargar PDF de gráficos"):
    pdf_bytes = _build_pdf_from_figs(plotly_figs=plotly_figs, mpl_figs=mpl_figs)
    if not pdf_bytes:
        st.warning("No hay gráficos para exportar o faltan dependencias (kaleido / PyPDF2).")
    else:
        st.download_button(
            "Descargar gráficos.pdf",
            data=pdf_bytes,
            file_name="graficos_duplicados.pdf",
            mime="application/pdf"
        )

# =============================================================================
# 10) EXPORTACIÓN (Excel con corrección de longitudes y KPIs)
# =============================================================================
st.subheader("Exportar resultados")
if st.button("Descargar Excel (duplicados + resumen + hallazgos + KPIs)"):
    if df_dups.empty:
        st.warning("No hay duplicados para exportar.")
    else:
        output = io.BytesIO()
        # Intentar primero con xlsxwriter; si falla, usar openpyxl
        try:
            engine = "xlsxwriter"
            writer = pd.ExcelWriter(output, engine=engine)
        except Exception:
            engine = "openpyxl"
            writer = pd.ExcelWriter(output, engine=engine)

        with writer:
            # Hoja de duplicados
            df_dups.to_excel(writer, index=False, sheet_name="Duplicados")

            # Hoja de resumen por contraparte
            resumen = df_dups.groupby(c_prov, dropna=False).agg(
                total_monto=(c_monto, "sum"),
                n_items=(c_prov, "size"),
            ).reset_index().sort_values("total_monto", ascending=False)
            resumen.to_excel(writer, index=False, sheet_name=f"Resumen_{party_label}")

            # Hoja de hallazgos (alineando longitudes con zip_longest)
            rows = list(zip_longest(alerts or [""], concl or [""], recs or [""], fillvalue=""))
            hallazgos = pd.DataFrame(rows, columns=["Alertas", "Conclusiones", "Recomendaciones"])
            hallazgos.to_excel(writer, index=False, sheet_name="Hallazgos")

            # Hoja de KPIs/Parámetros para trazabilidad
            kpis = pd.DataFrame({
                "Métrica": ["Total Facturas","Duplicados","% Duplicados","Monto Total Duplicados"],
                "Valor":   [N, D, f"{porc}%", monto_dup]
            })
            kpis.to_excel(writer, index=False, sheet_name="Resumen_General")

            params = {
                "Modo": modo,
                "Umbral similitud": umbral_sim if modo=="Aproximado" else "N/A",
                "Tolerancia monto": tol_monto if modo=="Aproximado" else "N/A",
                "Tolerancia días": tol_dias if modo=="Aproximado" else "N/A",
                "Bloquear por contraparte": bloq_prov if modo=="Aproximado" else "N/A",
                "Bloquear por mes": bloq_mes if modo=="Aproximado" else "N/A",
                "Filtro monto": f"{f_min}–{f_max}",
                "Etiqueta contraparte": party_label,
                "Columnas": f"Nº={c_num} | Contraparte={c_prov} | Fecha={c_fecha} | Monto={c_monto}"
            }
            params_df = pd.DataFrame(list(params.items()), columns=["Parámetro", "Valor"])
            params_df.to_excel(writer, index=False, sheet_name="Parametros")

        # Mover el cursor al inicio antes de descargar
        output.seek(0)
        st.download_button(
            label="Descargar Excel",
            data=output.getvalue(),
            file_name="duplicados_avanzados.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

# =============================================================================
# 11) NOTAS
# =============================================================================
st.info(
    """
**Buenas prácticas**  
• Verifica la moneda antes de aplicar tolerancias.
• Ajusta la coincidencia mínima según falsos positivos o sospechas. 
• Usa filtros de contraparte/fecha para agilizar análisis.
• Exporta el Excel y el PDF para anexar a tus papeles de trabajo.
"""
)
