#!/usr/bin/env python3
"""
Potencia OTEC (Nihous 2013, Eq. 1 y 2) para tres profundidades de toma:
800 m, 900 m y 1000 m.

Entrada : 1993.db ... 2025.db, tabla 'Temperature'
Salida  : potencia_offshore_1993.xlsx ... potencia_offshore_2025.xlsx
"""

import os
import sqlite3
import pandas as pd
import numpy as np  # <-- Necesario para np.nan

# ===========================================================================
# CONFIG
# ===========================================================================
DB_DIR = "/media/Alejandro/STORE/CarpetadeTrabajo/Atlas/Mexico/BD/"
YEAR_START = 2014
YEAR_END = 2025
TABLE_NAME = "Temperature"

COL_FECHA = "fecha"
COL_LEV = "lev"
COL_LON = "longitude"
COL_LAT = "latitude"
COL_T = "T"

LEV_SURF = 1  # toma superficial
LEV_DEEPS = [1000, 900, 800]  # tomas profundas (m)

# ✅ NUEVAS CONSTANTES (Ajustadas para dar resultados en MW)
W_CW = 309.7174  # Caudal de agua fría (m³/s)
RHO = 1025.0  # Densidad (kg/m³)
CP = 0.004  # Calor específico (MJ/kg·K)
E_RG = 0.75  # Eficiencia
GAMMA = 1.5  # Proporción
PERDIDAS = 0.30  # Factor de pérdidas por bombeo
DELTA_T_MIN = 18.0  # °C, umbral región OTEC


# ===========================================================================

def otec_potencias(delta_T, T_abs,
                   w_cw=W_CW, rho=RHO, cp=CP, e_rg=E_RG, gamma=GAMMA, perdidas=PERDIDAS):
    """(P_gross, P_pump, P_net) en MW. delta_T en K (=°C), T_abs en K."""
    coef = rho * cp * e_rg * gamma / (1.0 + gamma)

    # Potencia Bruta (MW)
    P_gross = w_cw * (3.0 / 16.0) * coef * (delta_T ** 2) / T_abs

    # Potencia de Bombeo (MW)
    P_pump = w_cw * perdidas * (coef / 4.0) + (delta_T * 0.0)

    # Potencia Neta (MW)
    P_net = P_gross - P_pump
    return P_gross, P_pump, P_net


def leer_y_pivotear(db_path):
    """Devuelve DataFrame con T_surf y T_{z}m para cada z en LEV_DEEPS."""
    con = sqlite3.connect(db_path)
    niveles = [LEV_SURF] + LEV_DEEPS
    placeholders = ",".join(str(v) for v in niveles)
    query = f"""
        SELECT {COL_FECHA} AS fecha,
               {COL_LAT}   AS latitude,
               {COL_LON}   AS longitude,
               {COL_LEV}   AS lev,
               {COL_T}     AS T
        FROM {TABLE_NAME}
        WHERE {COL_LEV} IN ({placeholders})
    """
    df = pd.read_sql_query(query, con)
    con.close()

    df = df.pivot_table(
        index=["fecha", "latitude", "longitude"],
        columns="lev",
        values="T",
        aggfunc="first",
    ).reset_index()

    df = df.rename(columns={LEV_SURF: "T_surf"})
    for z in LEV_DEEPS:
        df = df.rename(columns={z: f"T_{z}m"})

    df = df.dropna(subset=["T_surf"] + [f"T_{z}m" for z in LEV_DEEPS])
    return df


def calcular_potencias_multi(df):
    # ✅ Cambiamos 'fecha' por 'date' al inicio para el Excel de salida
    out = df[["fecha", "latitude", "longitude"]].copy().rename(columns={"fecha": "date"})

    # Temperatura superficial en Celsius
    T_surf_numeric = pd.to_numeric(df["T_surf"].astype(str).str.replace(",", "."), errors="coerce")
    out["T_surf_C"] = T_surf_numeric

    # Temperatura absoluta en Kelvin para las fórmulas
    T_abs = T_surf_numeric + 273.15

    for z in LEV_DEEPS:
        # ✅ Extraer y guardar la temperatura profunda en Celsius
        T_profunda_C = pd.to_numeric(df[f"T_{z}m"].astype(str).str.replace(",", "."), errors="coerce")
        out[f"T_{z}m_C"] = T_profunda_C

        # Cálculo del gradiente térmico
        delta_T = T_surf_numeric - T_profunda_C
        P_gross, P_pump, P_net = otec_potencias(delta_T, T_abs)

        mask = delta_T >= DELTA_T_MIN

        # ✅ Usamos np.nan en lugar de -9999 para dejar las celdas en blanco en Excel
        out[f"delta_T_C_{z}m"] = delta_T.where(mask, np.nan).fillna(np.nan)
        out[f"P_gross_{z}m"] = P_gross.where(mask, np.nan).fillna(np.nan)
        out[f"P_pump_{z}m"] = P_pump.where(mask, np.nan).fillna(np.nan)
        out[f"P_net_{z}m"] = P_net.where(mask, np.nan).fillna(np.nan)
        out[f"eficiencia_{z}m"] = (P_net / P_gross).where(mask, np.nan).fillna(np.nan)

    return out


def main():
    for year in range(YEAR_START, YEAR_END + 1):
        db_path = os.path.join(DB_DIR, f"{year}")
        # ✅ Guardar con extensión .xlsx
        out_path = os.path.join(DB_DIR, f"potencia_offshore_{year}.xlsx")

        if not os.path.exists(db_path):
            print(f"[{year}] SKIP: no existe {db_path}")
            continue

        print(f"[{year}] procesando...")
        df = leer_y_pivotear(db_path)
        res = calcular_potencias_multi(df)

        # ✅ Guardar directamente en Excel
        res.to_excel(out_path, index=False, engine='openpyxl')

        n = len(res)
        # Imprimir el máximo por nivel (protegido por si todo es NaN)
        pmax = {z: (res[f"P_net_{z}m"].max() if not res[f"P_net_{z}m"].isna().all() else 0.0) for z in LEV_DEEPS}

        print(f"[{year}] -> {out_path}  ({n} filas)  " +
              "  ".join(f"P_net_{z}m máx={pmax[z]:.3f} MW" for z in LEV_DEEPS))

    print("\nListo. Archivos Excel generados.")


if __name__ == "__main__":
    main()