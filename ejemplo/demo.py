#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
demo.py — la cadena completa sobre datos sintéticos, de principio a fin.

    python3 ejemplo/generar_datos.py     # 1. fabrica la base
    python3 ejemplo/demo.py              # 2. zonifica, planifica, verifica, dibuja

Hace, en este orden:

    puntos → ZONAS (una corrida por grupo) → PLAN SEMANAL con rutas reales
           → QA que puede FALLAR → CALIBRACIÓN del estimador → mapa HTML

Sale con código 1 si el QA encuentra un fallo crítico: un entregable que no
cuadra no se publica. Los AVISOS no detienen la entrega pero se reportan, que es
distinto de esconderlos.
"""
from pathlib import Path
import sys
import time

import numpy as np
import pandas as pd

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from zonas import reglas as R, zonificar as Z, plan_semanal as PS, qa   # noqa: E402
import mapa as M                                                        # noqa: E402

DATOS = Path(__file__).resolve().parent / "datos" / "pdv_sinteticos.csv"
SALIDA = Path(__file__).resolve().parent / "salida"

# Asesores disponibles HOY por grupo. Es el techo del escenario base: primero se
# intenta resolver con la dotación actual y solo después se pide gente nueva.
ASESORES = {"DISTRIBUIDOR NORTE": 9, "DISTRIBUIDOR CENTRO": 11, "DISTRIBUIDOR RURAL": 4}


def matriz_minutos(lat, lon):
    """Minutos entre cada par de puntos, ya con el factor operativo aplicado.

    Aproximación en línea recta: para el ejemplo basta. En un proyecto real esta
    matriz sale del grafo vial (OSRM, OSMnx o un servicio de rutas), y es ahí
    donde el número deja de ser un supuesto.
    """
    lat0 = np.radians(np.mean(lat))
    x = np.radians(lon) * 6371.0 * np.cos(lat0)
    y = np.radians(lat) * 6371.0
    km = np.sqrt((x[:, None] - x[None, :]) ** 2 + (y[:, None] - y[None, :]) ** 2)
    return km * R.MIN_POR_KM * R.FACTOR_OPERATIVO


def area_km2(P):
    """El área con la que trabaja el estimador de viaje, para poder calibrarlo
    después contra la ruta que de verdad se calculó."""
    a = Z.Acumulador()
    for x, y in P:
        a.suma(float(x), float(y), 0.0, 0.0)
    return a.area()


def main() -> int:
    if not DATOS.exists():
        print(f"Falta {DATOS}.\nCorra primero:  python3 ejemplo/generar_datos.py")
        return 1
    SALIDA.mkdir(exist_ok=True)
    pdv = pd.read_csv(DATOS)
    pdv["zona"] = None
    crono = {}

    # ── 1. zonas, un grupo a la vez ─────────────────────────────────────────
    # Correr por grupo hace que "una zona no cruza grupos" se cumpla por
    # construcción, en vez de tener que comprobarlo después.
    print("\n── ZONIFICACIÓN ────────────────────────────────────────────")
    t = time.time()
    for grupo, g in pdv.groupby("grupo"):
        corto = grupo.split()[-1]
        etiquetas, informe = Z.zonificar_grupo(g, asesores=ASESORES.get(grupo))
        pdv.loc[g.index, "zona"] = [f"{corto}-Z{int(e)+1:02d}" if e >= 0 else None
                                    for e in etiquetas]
        print(f"  {grupo:<22} {informe.get('zonas', 0):>2} zonas de "
              f"{ASESORES.get(grupo)} asesores · "
              f"${informe.get('venta_capturada_mm', 0):>6,.0f} MM capturados · "
              f"podados {informe.get('podados', 0)} · "
              f"reabsorbidos {informe.get('reabsorbidos', 0)}")
    crono["zonificar"] = time.time() - t
    en = pdv.zona.notna()

    # ── 2. plan semanal y rutas, zona por zona ──────────────────────────────
    print("\n── PLAN SEMANAL ────────────────────────────────────────────")
    t = time.time()
    filas_plan, geometria = [], {}
    for z, g in pdv[en].groupby("zona"):
        g = g.reset_index(drop=True)
        lat, lon = g.lat.values.astype(float), g.lon.values.astype(float)
        P, D = Z.plano(lat, lon), matriz_minutos(lat, lon)
        geometria[z] = (area_km2(P), float(g.frecuencia_semana.sum()))
        for fila in PS.plan_de_zona(P, g.venta.values.astype(float),
                                    g.frecuencia_semana.values.astype(float), D):
            filas_plan.append({**fila, "zona": z, "grupo": g.grupo.iloc[0]})
    plan = pd.DataFrame(filas_plan)
    crono["planificar"] = time.time() - t
    conteo = plan.estado.value_counts()
    print(f"  {len(plan)} días-zona en {plan.zona.nunique()} zonas · " +
          " · ".join(f"{k} {v}" for k, v in conteo.items()))

    zonas = (pdv[en].groupby("zona")
             .agg(grupo=("grupo", "first"), puntos=("pdv_id", "size"),
                  venta=("venta", "sum")).reset_index()
             .merge(plan.groupby("zona").min_total.sum().rename("min_semana")
                    .reset_index(), on="zona", how="left"))

    # ── 3. QA: puede fallar y detener la entrega ────────────────────────────
    print("\n══ VERIFICACIÓN ════════════════════════════════════════════")
    ok = qa.verificar(pdv, zonas, plan)

    # ── 4. el conflicto de negocio que el analista NO debe resolver solo ────
    # Donde el territorio es delgado, las dos reglas duras —zona ≥ umbral y zona
    # recorrible— son incompatibles. No se maquilla: se reporta por grupo.
    nv = plan[plan.estado == "NO_VIABLE"]
    if len(nv):
        print("\n── CONFLICTO: el terreno exige más asesores de los que paga la venta ──")
        for grupo, g in nv.groupby("grupo"):
            paga = int(pdv[pdv.grupo == grupo].venta.sum() // R.UMBRAL_ZONA)
            print(f"  {grupo:<22} {len(g)} días sobre {R.JORNADA_MAX} min "
                  f"en {g.zona.nunique()} zonas · máx {g.min_total.max():.0f} min")
            print(f"  {'':<22} la venta paga {paga} zonas; el terreno pide más. "
                  f"Decisión de negocio, no del modelo.")

    # ── 5. calibrar el estimador contra las rutas ya calculadas ─────────────
    # Sin este paso, MIN_POR_KM es una constante inventada.
    reales = [{"visitas": v, "area_km2": a,
               "min_viaje_real": float(plan[plan.zona == z].min_viaje.sum())}
              for z, (a, v) in geometria.items()]
    cal = Z.calibrar_viaje(reales)
    print("\n── CALIBRACIÓN DEL ESTIMADOR DE VIAJE ──────────────────────")
    if cal:
        print(f"  MIN_POR_KM actual {R.MIN_POR_KM} → medido {cal['min_por_km']} "
              f"· correlación {cal['correlacion']} sobre {cal['zonas']} zonas")
        print("  Fijar el valor medido en zonas/reglas.py y volver a correr la cadena.")

    # ── 6. mapa ─────────────────────────────────────────────────────────────
    v_en, v_tot = pdv[en].venta.sum(), pdv.venta.sum()
    resumen = {
        "capturado": {
            "Puntos de venta": f"{len(pdv):,}",
            "Venta mensual": f"${v_tot/1e6:,.0f} MM",
            "Grupos": pdv.grupo.nunique(),
            "Zonas propuestas": int(zonas.zona.nunique()),
            "Cobertura de venta": f"{v_en/v_tot*100:.1f} %",
        },
        "fuera": {
            "Puntos sin zona": f"{int((~en).sum()):,}",
            "Venta residual": f"${(v_tot-v_en)/1e6:,.0f} MM",
            "Días no viables": int((plan.estado == "NO_VIABLE").sum()),
        },
    }
    t = time.time()
    coloreo = M.construir(pdv, zonas, resumen, R.parametros(), SALIDA / "mapa_zonas.html")
    crono["mapa"] = time.time() - t

    pdv.to_csv(SALIDA / "pdv_con_zona.csv", index=False)
    zonas.to_csv(SALIDA / "zonas.csv", index=False)
    plan.to_csv(SALIDA / "plan_semanal.csv", index=False)

    print(f"\n  geometría: {coloreo['vecindades']} vecindades · "
          f"{coloreo['choques']} pares vecinos del mismo color (objetivo 0) · "
          f"{coloreo['solapes']} zonas solapadas (objetivo 0)")
    print("  tiempos: " + " · ".join(f"{k} {v:.1f}s" for k, v in crono.items()))
    print("  salidas en ejemplo/salida/ · abrir mapa_zonas.html")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
