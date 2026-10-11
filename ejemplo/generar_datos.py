#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
generar_datos.py — base sintética de puntos de venta para probar el motor.

No hay datos reales de ninguna empresa en este repositorio. Este script fabrica
una operación verosímil: tres territorios, dos de ellos urbanos y uno rural
disperso, con la distribución de venta que se ve en distribución detallista
(muchos puntos pequeños, unos pocos que pesan mucho).

    python3 ejemplo/generar_datos.py

Escribe `ejemplo/datos/pdv_sinteticos.csv` con las columnas que espera el motor:

    pdv_id · grupo · lat · lon · venta · frecuencia_semana
"""
from pathlib import Path

import numpy as np
import pandas as pd

SALIDA = Path(__file__).resolve().parent / "datos" / "pdv_sinteticos.csv"
SEMILLA = 20260101

# Tres territorios ficticios. Las coordenadas caen sobre Colombia solo para que
# el mapa de demostración tenga un fondo reconocible; los puntos son inventados.
TERRITORIOS = [
    # nombre,               centro lat, lon,   n,   núcleos, dispersión km, venta mediana
    ("DISTRIBUIDOR NORTE",     4.760, -74.050, 260, 5,  3.5,  2_600_000),
    ("DISTRIBUIDOR CENTRO",    4.598, -74.090, 240, 4,  2.5,  3_400_000),
    ("DISTRIBUIDOR RURAL",     5.320, -73.820, 140, 6, 14.0,  1_500_000),
]


def _frecuencia(venta: np.ndarray) -> np.ndarray:
    """F1/F2/F3 por tamaño: al que más vende se le visita más. Es la línea base
    de la operación, no una decisión del modelo."""
    q1, q2 = np.quantile(venta, [0.55, 0.88])
    return np.where(venta >= q2, 3, np.where(venta >= q1, 2, 1)).astype(float)


def generar(semilla: int = SEMILLA) -> pd.DataFrame:
    rng = np.random.default_rng(semilla)
    filas = []
    for nombre, lat0, lon0, n, nucleos, disp_km, mediana in TERRITORIOS:
        # los puntos no se reparten uniformemente: se apiñan en núcleos
        c_lat = lat0 + rng.normal(0, disp_km / 111.0, nucleos)
        c_lon = lon0 + rng.normal(0, disp_km / 111.0, nucleos)
        cual = rng.integers(0, nucleos, n)
        sigma = disp_km / 3.0
        lat = c_lat[cual] + rng.normal(0, sigma / 111.0, n)
        lon = c_lon[cual] + rng.normal(0, sigma / (111.0 * np.cos(np.radians(lat0))), n)

        # venta lognormal: cola larga, como en la realidad
        venta = np.round(rng.lognormal(np.log(mediana), 0.85, n), -3)
        venta = np.clip(venta, 200_000, None)

        filas.append(pd.DataFrame({
            "grupo": nombre,
            "lat": np.round(lat, 6),
            "lon": np.round(lon, 6),
            "venta": venta,
            "frecuencia_semana": _frecuencia(venta),
        }))

    df = pd.concat(filas, ignore_index=True)
    df.insert(0, "pdv_id", [f"PDV{i:05d}" for i in range(1, len(df) + 1)])
    return df


if __name__ == "__main__":
    df = generar()
    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(SALIDA, index=False)
    print(f"{len(df):,} puntos · ${df.venta.sum()/1e6:,.0f} MM/mes → {SALIDA}")
    print(df.groupby("grupo").agg(puntos=("pdv_id", "size"),
                                  venta_mm=("venta", lambda s: round(s.sum() / 1e6))))
