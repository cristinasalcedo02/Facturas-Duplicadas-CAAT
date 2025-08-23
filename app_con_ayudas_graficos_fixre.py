
# === Cálculo coherente de duplicados para indicadores ===
# Claves para detección (flexible según columnas disponibles)
_DUP_KEYS = [k for k in [PARTY_COL, INVOICE_COL, DATE_COL, TOTAL_COL] if k]

# Máscara de "todos los involucrados" (útil para tabla)
__dups_all_mask = df.duplicated(subset=_DUP_KEYS, keep=False)

# Máscara de "excedentes" (útil para indicador): solo cuenta los repetidos extra
__dups_extra_mask = df.duplicated(subset=_DUP_KEYS, keep="first")

# Métricas estándar
NUM_FACTURAS_TOTAL = int(len(df))
NUM_FACTURAS_DUP_EXCESO = int(__dups_extra_mask.sum())
PCT_DUP = (NUM_FACTURAS_DUP_EXCESO / NUM_FACTURAS_TOTAL) if NUM_FACTURAS_TOTAL else 0.0

# Compatibilidad con variables existentes
try:
    num_dup = NUM_FACTURAS_DUP_EXCESO
except Exception:
    pass

# Tablas auxiliares (por si las quieres usar en la UI)
try:
    df_dups_involucradas = df[__dups_all_mask].copy()
    df_dups_excedentes  = df[__dups_extra_mask].copy()
except Exception:
    pass
# === Fin cálculo duplicados ===

# CAAT Avanzado — Detección de Facturas Duplicadas con Análisis de Riesgo
# Autor: Grupo A

import io
import re
import unicodedata
import numpy as np
import pandas as pd
import streamlit as st

# ── Gráficos (Plotly opcional)
try:
    import plotly.express as px
    _HAS_PLOTLY = True
except Exception:
    _HAS_PLOTLY = False

# ── Fuzzy matching (rapidfuzz > thefuzz > none)
try:
    from rapidfuzz import fuzz
    _FUZZ_OK = True
except Exception:
    try:
        from thefuzz import fuzz
# === Helper para mapear columnas de Proveedor/Cliente e Invoice ===
import re

# === Helper UI: subtítulo con "i" de ayuda ===============================
import streamlit as st

def section_header(title: str, help_text: str):
    """
    Muestra un subtítulo con un ícono "i" a la derecha.
    Si existe st.popover, lo usa; si no, usa un expander compacto.
    """
    # Layout: título + botón/ícono a la derecha
    left, right = st.columns([1, 0.06])
    with left:
        st.subheader(title)
    with right:
        # Preferimos popover moderno si está disponible
        if hasattr(st, "popover"):
            with st.popover("ℹ️"):
                st.markdown(help_text)
        else:
            with st.expander("ℹ️"):
                st.markdown(help_text)
# === Fin helper UI =======================================================


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
        "fecha factura", "f.emision", "f emision"
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

def auto_map_columns(df):
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
            df["__TotalDerived"] = df[amount_col].astype(float) + df[tax_col].astype(float)
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
# === Fin helper ===

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
6) **Exporta** resultados a Excel (duplicados + resumen).
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
        return pd.read_excel(bio)
    # Ajusta sep=";" si tus CSV lo requieren
    return pd.read_csv(bio)

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
    n = _norm(h)
    if any(k in n for k in _SYNONYMS["cli_keys"]):
        return "Cliente"
    if any(k in n for k in _SYNONYMS["ter_keys"]):
        return "Tercero"
    return "Proveedor"

party_label = _party_label_from_header(h_party)
_defaults = {"num": h_num, "party": h_party, "fecha": h_fecha, "monto": h_monto}

if "edit_mapping" not in st.session_state:
    st.session_state.edit_mapping = False

section_header("Mapeo de columnas", """
**Objetivo:** Confirmar qué columnas del archivo se usan como *Parte* (Proveedor/Cliente), *Número*, *Fecha* y *Montos*.
La app detecta nombres comunes automáticamente; puedes corregirlos si algo quedó mal.
""")
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

# Validaciones rápidas
sel_cols = [c_num, c_prov, c_fecha, c_monto]
if len(set(sel_cols)) < len(sel_cols):
    st.error("Has seleccionado la **misma columna** para más de un rol (Nº/Parte/Fecha/Monto). Corrige el mapeo.")
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
        bloq_prov = st.checkbox(f"Comparar solo dentro del mismo {party_label.lower()}", value=True)
        bloq_mes  = st.checkbox("Bloquear por mismo mes de emisión", value=False)

# =============================================================================
# 5) DETECCIÓN
# =============================================================================
@st.cache_data(show_spinner=False)
def detect_exact(df: pd.DataFrame, c_num: str, c_prov: str, c_monto: str, c_fecha: str):
    mask = df.duplicated(subset=[c_num, c_prov, c_monto], keep=False)
    out = df.loc[mask].copy()
    out["_regla"] = "Exacto (num+parte+monto)"
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
    if c_fecha in merged:
        merged = merged.sort_values([c_prov, c_num, c_monto, c_fecha], na_position="last")
    return merged

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
section_header("Indicadores clave", """
**Qué ves aquí:** KPIs del archivo cargado.
- *Total Facturas*: cantidad de filas del dataset.
- *Duplicadas*: **excedentes** detectados (copias sobre el original).
- *% Duplicados*: excedentes / total.
- *Monto Total Duplicados*: suma del **Total** de las copias.
""")
N = len(df)
D = len(df_dups)
porc = round((D / N) * 100, 2) if N else 0.0
monto_dup = float(df_dups[c_monto].sum()) if not df_dups.empty else 0.0
col1, col2, col3, col4 = st.columns(4)
col1.metric("Total Facturas", f"{N:,}")
col2.metric("Duplicados", f"{D:,}")
col3.metric("% Duplicados (excedentes)", f"{porc}%")
col4.metric("Monto Total Duplicados", f"$ {monto_dup:,.2f}")

section_header("Tabla de facturas potencialmente duplicadas", """
**Cómo usar:** Filtra y ordena para revisar grupos marcados por la columna `_regla`.
- *Exacto (num+parte+monto)*: coincidencia estricta.
- *Variante número*: cambios de formato (guión, mayúsculas, ceros).
- *Combo (parte+fecha+total)*: posible duplicado sin mismo número.
Marca los casos válidos en *Comentarios* o *Riesgo* para tu informe.
""")
st.dataframe(df_dups, use_container_width=True)

# =============================================================================
# 8) VISUALIZACIONES
# =============================================================================
st.subheader("Visualizaciones")
if not df_dups.empty:
    prov_agg = df_dups.groupby(c_prov, dropna=False)[c_monto].sum().reset_index()
    if _HAS_PLOTLY:
        fig1 = px.bar(prov_agg, x=c_prov, y=c_monto, title=f"Monto duplicado por {party_label.lower()}")
        st.plotly_chart(fig1, use_container_width=True)
    else:
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots()
        ax.bar(prov_agg[c_prov].astype(str), prov_agg[c_monto])
        ax.set_title(f"Monto duplicado por {party_label.lower()}"); ax.set_xlabel(party_label); ax.set_ylabel("Monto")
        st.pyplot(fig)

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
            "Verifica el mapeo de columnas (Nº, Parte, Fecha, Monto) y, si aplica, combina campos.",
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
        alerts.append(f"Hay números de factura repetidos en distintos {party_label.lower()}s (posible cruce o error de alta).")

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
        "Configurar en el ERP la validación de duplicados por Nº + parte + monto + fecha (con tolerancias).",
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
# 10) EXPORTACIÓN (sin hoja Parametros)
# =============================================================================
st.subheader("Exportar resultados")
if st.button("Descargar Excel (duplicados + resumen + hallazgos)"):
    if df_dups.empty:
        st.warning("No hay duplicados para exportar.")
    else:
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
            # Hoja de duplicados
            df_dups.to_excel(writer, index=False, sheet_name="Duplicados")

            # Hoja de resumen
            resumen = df_dups.groupby(c_prov, dropna=False).agg(
                total_monto=(c_monto, "sum"),
                n_items=(c_prov, "size"),
            ).reset_index().sort_values("total_monto", ascending=False)
            resumen.to_excel(writer, index=False, sheet_name=f"Resumen_{party_label}")

            # Hoja de hallazgos
            hallazgos = pd.DataFrame({
                "Alertas": alerts or [""],
                "Conclusiones": concl or [""],
                "Recomendaciones": recs or [""]
            })
            hallazgos.to_excel(writer, index=False, sheet_name="Hallazgos")

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
• Usa filtros de proveedor/fecha para agilizar análisis.
• Exporta el Excel para anexar a tus papeles de trabajo.
"""
)

# === Helper UI: encabezado de gráfico con "i" de ayuda ==================
def chart_header(title: str, help_text: str):
    """
    Encabezado para gráficos con ícono ℹ️ a la derecha.
    Usa popover si está disponible; si no, expander.
    """
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
# === Fin helper gráfico ==================================================
