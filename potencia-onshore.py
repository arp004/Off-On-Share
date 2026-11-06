#!/usr/bin/env python3
"""
Potencia OTEC ONSHORE (planta en costa) — Nihous 2013, Eq. 1 y 2.
SIN batimetría externa: las máscaras salen de los NaN de Copernicus.

  - Tierra        : T_surf es NaN
  - Costa         : T_surf válida con al menos un vecino tierra
  - Talud         : T_deep válida (océano con >= 800 m de fondo)
  - Toma profunda : T_deep de la celda "talud" más cercana a cada costa

Entrada : 1993.db ... 2025.db, tabla 'Temperature'
          fecha | lev | longitude | latitude | T
Salida  : potencia_costa_YYYY.xlsx (Excel)

Columnas de salida:
  date, latitude, longitude, level,
  delta_T, T_abs_K,
  P_gross_MW, P_pump_MW, P_net_MW, eficiencia,
  dist_talud_km
"""

import os
import sqlite3
import numpy as np
import pandas as pd
from scipy.ndimage import distance_transform_edt, binary_dilation

# ===========================================================================
# CONFIG
# ===========================================================================
DB_DIR = "/media/Alejandro/STORE/CarpetadeTrabajo/Atlas/Mexico/BD/"
YEAR_START = 1993
YEAR_END = 2025
TABLE_NAME = "Temperature"

COL_FECHA = "fecha"
COL_LEV = "lev"
COL_LON = "longitude"
COL_LAT = "latitude"
COL_T = "T"

LEV_SURF = 1  # Toma superficial
LEV_DEEP_LIST = [1000, 900, 800]  # Tomas profundas (m)

# ✅ CONSTANTES AJUSTADAS PARA RESULTADOS EN MW
W_CW = 309.7174  # Caudal de agua fría (m³/s)
RHO = 1025.0  # Densidad (kg/m³)
CP = 0.004  # Calor específico (MJ/kg·K)
E_RG = 0.75  # Eficiencia
GAMMA = 1.5  # Proporción
PERDIDAS = 0.30  # Factor de pérdidas por bombeo
DELTA_T_MIN = 18.0  # °C, umbral región OTEC


# ===========================================================================


# ---------------------------------------------------------------------------
# Ecuación de Nihous (vectorizada y corregida)
# ---------------------------------------------------------------------------
def otec_potencias(w_cw, delta_T, T_abs,
                   rho=RHO, cp=CP, e_rg=E_RG, gamma=GAMMA):
    coef = rho * cp * e_rg * gamma / (1.0 + gamma)

    # Cálculo de potencias
    P_gross = w_cw * (3.0 / 16.0) * coef * (delta_T ** 2) / T_abs
    P_pump = w_cw * PERDIDAS * (coef / 4.0)
    P_net = P_gross - P_pump

    # Aseguramos que P_pump sea un arreglo del mismo tamaño que delta_T
    P_pump_array = np.full_like(delta_T, P_pump)

    return P_gross, P_pump_array, P_net


# ---------------------------------------------------------------------------
# 1) Leer DB y pivotear niveles
# ---------------------------------------------------------------------------
def leer_y_pivotear(db_path):
    con = sqlite3.connect(db_path)
    query = f"""
        SELECT {COL_FECHA} AS fecha,
               {COL_LAT}   AS latitude,
               {COL_LON}   AS longitude,
               {COL_LEV}   AS lev,
               {COL_T}     AS T
        FROM {TABLE_NAME}
        WHERE {COL_LEV} IN ({LEV_SURF}, {LEV_DEEP_LIST[0]}, {LEV_DEEP_LIST[1]}, {LEV_DEEP_LIST[2]})
    """
    df = pd.read_sql_query(query, con)
    con.close()

    df = df.pivot_table(
        index=["fecha", "latitude", "longitude"],
        columns="lev",
        values="T",
        aggfunc="first",
    ).reset_index()

    # Renombrar según los niveles
    df = df.rename(columns={
        LEV_SURF: "T_surf",
        LEV_DEEP_LIST[0]: f"T_{LEV_DEEP_LIST[0]}",
        LEV_DEEP_LIST[1]: f"T_{LEV_DEEP_LIST[1]}",
        LEV_DEEP_LIST[2]: f"T_{LEV_DEEP_LIST[2]}"
    })

    # Forzar a float para evitar errores en np.isnan
    for col in ["T_surf", f"T_{LEV_DEEP_LIST[0]}", f"T_{LEV_DEEP_LIST[1]}", f"T_{LEV_DEEP_LIST[2]}"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        else:
            df[col] = np.nan  # Si el nivel no existía en ese año

    return df


# ---------------------------------------------------------------------------
# 2) Construir máscaras y vecino "talud"
# ---------------------------------------------------------------------------
def preparar_grilla_desde_datos(df_ref):
    lat = np.sort(df_ref["latitude"].unique())
    lon = np.sort(df_ref["longitude"].unique())
    nlat, nlon = len(lat), len(lon)

    lat_index = {round(v, 4): i for i, v in enumerate(lat)}
    lon_index = {round(v, 4): j for j, v in enumerate(lon)}

    df_ref = df_ref.copy()
    df_ref['i'] = df_ref['latitude'].apply(lambda x: lat_index.get(round(x, 4)))
    df_ref['j'] = df_ref['longitude'].apply(lambda x: lon_index.get(round(x, 4)))

    df_ref = df_ref.dropna(subset=['i', 'j'])
    df_ref['i'] = df_ref['i'].astype(int)
    df_ref['j'] = df_ref['j'].astype(int)

    surf_ok = np.zeros((nlat, nlon), dtype=bool)
    deep_ok = np.zeros((nlat, nlon), dtype=bool)

    # Superficie
    df_surf = df_ref[df_ref['T_surf'].notna()]
    surf_ok[df_surf['i'].values, df_surf['j'].values] = True

    # Profundidad: válida si AL MENOS UNO de los niveles tiene dato
    for lev in LEV_DEEP_LIST:
        col_name = f"T_{lev}"
        if col_name in df_ref.columns:
            df_deep = df_ref[df_ref[col_name].notna()]
            deep_ok[df_deep['i'].values, df_deep['j'].values] = True

    land = ~surf_ok
    ocean = surf_ok
    vecinos_tierra = binary_dilation(land, structure=np.ones((3, 3), bool))
    coastal_mask = ocean & vecinos_tierra
    deep_mask = deep_ok

    dist_px, (row_near, col_near) = distance_transform_edt(
        ~deep_mask, return_indices=True
    )

    R = 6371.0
    dlat = np.abs(np.diff(lat)).mean() if len(lat) > 1 else 1.0
    dlon = np.abs(np.diff(lon)).mean() if len(lon) > 1 else 1.0
    deg_km = R * np.deg2rad(np.sqrt(dlat ** 2 + dlon ** 2))
    dist_km = dist_px * deg_km

    return lat, lon, coastal_mask, deep_mask, row_near, col_near, dist_km


# ---------------------------------------------------------------------------
# 3) Calcular potencia onshore para un año
# ---------------------------------------------------------------------------
def calcular_potencia_costa(df_year, lat, lon,
                            coastal_mask, row_near, col_near, dist_km):
    lat_index = {round(v, 4): i for i, v in enumerate(lat)}
    lon_index = {round(v, 4): j for j, v in enumerate(lon)}

    resultados = []

    df_year = df_year.copy()
    df_year['i'] = df_year['latitude'].apply(lambda x: lat_index.get(round(x, 4)))
    df_year['j'] = df_year['longitude'].apply(lambda x: lon_index.get(round(x, 4)))

    df_year = df_year.dropna(subset=['i', 'j'])
    df_year['i'] = df_year['i'].astype(int)
    df_year['j'] = df_year['j'].astype(int)

    for date, grupo in df_year.groupby("fecha"):
        T_surf_2d = np.full((len(lat), len(lon)), np.nan)
        T_surf_2d[grupo['i'].values, grupo['j'].values] = grupo['T_surf'].values

        # Iteramos sobre cada nivel profundo (1000, 900, 800)
        for lev in LEV_DEEP_LIST:
            col_name = f"T_{lev}"
            if col_name not in df_year.columns:
                continue

            T_deep_2d = np.full((len(lat), len(lon)), np.nan)
            T_deep_2d[grupo['i'].values, grupo['j'].values] = grupo[col_name].values

            T_deep_talud = T_deep_2d[row_near, col_near]

            # Celdas costeras con T_surf y T_deep válidas para ESTE nivel
            ii, jj = np.where(
                coastal_mask
                & ~np.isnan(T_surf_2d)
                & ~np.isnan(T_deep_talud)
            )
            if len(ii) == 0:
                continue

            T_surf_c = T_surf_2d[ii, jj]
            T_deep_c = T_deep_talud[ii, jj]
            dist_c = dist_km[ii, jj]

            delta_T = T_surf_c - T_deep_c
            T_abs = T_surf_c + 273.15

            P_gross, P_pump, P_net = otec_potencias(W_CW, delta_T, T_abs)

            mask_otec = delta_T >= DELTA_T_MIN
            if not np.any(mask_otec):
                continue

            # DataFrame con los nombres corregidos
            df_temp = pd.DataFrame({
                "date": date,
                "latitude": lat[ii[mask_otec]],
                "longitude": lon[jj[mask_otec]],
                "level": lev,
                "delta_T": delta_T[mask_otec],
                "T_abs_K": T_abs[mask_otec],
                "P_gross_MW": P_gross[mask_otec],
                "P_pump_MW": P_pump[mask_otec],
                "P_net_MW": P_net[mask_otec],
                "eficiencia": P_net[mask_otec] / P_gross[mask_otec],
                "dist_talud_km": dist_c[mask_otec],
            })

            resultados.append(df_temp)

    return pd.concat(resultados, ignore_index=True) if resultados else pd.DataFrame()


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------
def main():
    print(f"Construyendo máscaras a partir de {YEAR_START} ...")

    db_ref_path = os.path.join(DB_DIR, f"{YEAR_START}")
    if not os.path.exists(db_ref_path):
        db_ref_path = os.path.join(DB_DIR, f"{YEAR_START}.db")

    df_ref = leer_y_pivotear(db_ref_path)

    (lat, lon, coastal_mask, deep_mask,
     row_near, col_near, dist_km) = preparar_grilla_desde_datos(df_ref)

    print(f"  grilla: {len(lat)} lat × {len(lon)} lon")
    print(f"  celdas costeras        : {coastal_mask.sum()}")
    print(f"  celdas con talud válido: {deep_mask.sum()}")

    for year in range(YEAR_START, YEAR_END + 1):
        db_path = os.path.join(DB_DIR, f"{year}")
        if not os.path.exists(db_path):
            db_path = os.path.join(DB_DIR, f"{year}.db")

        if not os.path.exists(db_path):
            print(f"[{year}] SKIP: no existe {db_path}")
            continue

        # Guardar como Excel (.xlsx)
        out_path = os.path.join(DB_DIR, f"potencia_costa_{year}.xlsx")

        print(f"[{year}] procesando...")
        try:
            df = leer_y_pivotear(db_path)
            res = calcular_potencia_costa(df, lat, lon,
                                          coastal_mask, row_near, col_near, dist_km)

            if not res.empty:
                columnas_orden = [
                    "date", "latitude", "longitude", "level",
                    "delta_T", "T_abs_K", "P_gross_MW", "P_pump_MW",
                    "P_net_MW", "eficiencia", "dist_talud_km"
                ]
                res = res[columnas_orden]
                res.to_excel(out_path, index=False)
                print(f"[{year}] -> {out_path}  "
                      f"({len(res)} filas, P_net máx={res['P_net_MW'].max():.3f} MW)")
            else:
                columnas_orden = [
                    "date", "latitude", "longitude", "level",
                    "delta_T", "T_abs_K", "P_gross_MW", "P_pump_MW",
                    "P_net_MW", "eficiencia", "dist_talud_km"
                ]
                pd.DataFrame(columns=columnas_orden).to_excel(out_path, index=False)
                print(f"[{year}] -> {out_path}  (sin filas válidas)")

        except Exception as e:
            print(f"[{year}] ERROR: {e}")
            continue

    print("\nListo. Todos los años procesados.")


if __name__ == "__main__":
    main()