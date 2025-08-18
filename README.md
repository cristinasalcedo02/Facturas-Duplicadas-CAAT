# 📊 CAAT Avanzado — Detección de Facturas Duplicadas con Análisis de Riesgo

Aplicación interactiva desarrollada en **Streamlit** que permite detectar facturas duplicadas en grandes volúmenes de datos, calcular indicadores clave y priorizar riesgos según su impacto económico y frecuencia.

## ✨ Funcionalidades principales
- 📂 **Carga de archivos**: Excel (`.xlsx`, `.xls`) o CSV.  
- 🔍 **Mapeo automático de columnas**: detecta número de factura, proveedor/cliente, fecha y monto.  
- ⚙️ **Detección de duplicados**:
  - **Exacta**: coincidencia estricta de número, parte y monto.  
  - **Aproximada**: fuzzy matching (similaridad de texto + tolerancias de monto y fecha).  
- 🧾 **Filtros dinámicos**:
  - Por proveedor/cliente.  
  - Por rango de montos.  
  - Por rango de fechas.  
- 📊 **Indicadores clave (KPIs)**: % de duplicados, monto afectado, etc.  
- 📈 **Visualizaciones**:  
  - Monto duplicado por proveedor/cliente.  
  - Evolución mensual de duplicados.  
- 🚨 **Priorización de riesgo**:
  - Puntaje de riesgo basado en monto y frecuencia.  
  - Categorización automática: **Alto, Medio, Bajo**.  
  - Control *Top-N* para mostrar solo los casos más críticos.  
- 📤 **Exportación a Excel**:  
  - Hoja `Duplicados` con los casos detectados.  
  - Hoja `Resumen` con agregados por proveedor/cliente.  
  - Hoja `Hallazgos` con alertas, conclusiones y recomendaciones generadas automáticamente.

---

## 🛠️ Instalación

1. Clona este repositorio:
   ```bash
   git clone https://github.com/usuario/caat-facturas-duplicadas.git
   cd caat-facturas-duplicadas
