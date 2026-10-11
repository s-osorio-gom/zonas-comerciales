#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pruebas.py — invariantes del motor y regresiones. Corren en segundos; el solver
solo se usa sobre instancias diminutas.

    python3 pruebas.py

No comprueban que el resultado sea *bueno* —eso lo decide el negocio— sino que
sea COHERENTE: que la venta cuadre, que ninguna zona quede bajo el umbral, que
ninguna mezcle grupos y que los polígonos del mapa no se pisen.
"""
from pathlib import Path
import sys

import numpy as np
import pandas as pd

RAIZ = Path(__file__).resolve().parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "ejemplo"))

from zonas import reglas as R, zonificar as Z, plan_semanal as PS   # noqa: E402

fallos = []


def revisar(nombre, ok, detalle=""):
    print(f"  [{'OK  ' if ok else 'FALLA'}] {nombre}" + (f" — {detalle}" if detalle else ""))
    if not ok:
        fallos.append(nombre)


def base(n=180, semilla=3):
    rng = np.random.default_rng(semilla)
    lat = 4.65 + rng.normal(0, 0.025, n)
    lon = -74.08 + rng.normal(0, 0.025, n)
    venta = np.clip(np.round(rng.lognormal(np.log(3_000_000), 0.8, n), -3), 2e5, None)
    frec = np.where(venta >= np.quantile(venta, .85), 3,
                    np.where(venta >= np.quantile(venta, .55), 2, 1)).astype(float)
    return pd.DataFrame({"lat": lat, "lon": lon, "venta": venta,
                         "frecuencia_semana": frec, "grupo": "G1"})


print("\n── REGLAS DE NEGOCIO ───────────────────────────────────────")
print("  " + R.autotest())
revisar("la atención crece con la venta por visita",
        R.minutos_visita(20) > R.minutos_visita(5))
revisar("la atención respeta sus guardarraíles",
        R.minutos_visita(1e9) == R.MAX_ATENCION and R.minutos_visita(-1) == R.MIN_ATENCION)
revisar("la venta por visita usa la frecuencia, no el mes completo",
        R.venta_por_visita(100e6, 2) == 100e6 / (R.SEMANAS_MES * 2))
revisar("una zona sin puntos no genera viaje", R.viaje_semana_min(0, 10) == 0.0)

print("\n── ZONIFICACIÓN ────────────────────────────────────────────")
df = base()
z, inf = Z.zonificar_grupo(df, asesores=6)
df = df.assign(zona=[f"Z{int(e)+1:02d}" if e >= 0 else None for e in z])
en = df.zona.notna()
revisar("produce zonas", inf.get("zonas", 0) > 0, f"{inf.get('zonas')} zonas")
v = df[en].groupby("zona").venta.sum()
revisar("ninguna zona queda bajo el umbral", bool((v >= R.UMBRAL_ZONA).all()),
        f"mínima ${v.min()/1e6:,.1f} MM")
revisar("la venta cuadra al peso",
        abs(df[en].venta.sum() + df[~en].venta.sum() - df.venta.sum()) < 1e-6)
revisar("ninguna zona mezcla grupos",
        int(df[en].groupby("zona").grupo.nunique().max()) == 1)
revisar("toda etiqueta es una zona válida o nula",
        set(z) <= set(range(-1, int(inf.get("k_probado", 0)) + 1)))

print("\n── RUTAS ───────────────────────────────────────────────────")
D = np.array([[0., 5., 9., 4.], [5., 0., 3., 8.], [9., 3., 0., 6.], [4., 8., 6., 0.]])
revisar("el heurístico nunca supera la vuelta trivial",
        PS.tour_rapido(D) <= sum(D[i, i + 1] for i in range(3)) + 1e-9)
revisar("un solo punto no tiene recorrido", PS.tour_rapido(np.zeros((1, 1))) == 0.0)
orden, largo = PS.orden_optimo(D, segundos=0.2)
revisar("el solver visita cada parada una vez", sorted(orden) == [0, 1, 2, 3])
revisar("el solver no empeora al heurístico", largo <= PS.tour_rapido(D) + 1e-6,
        f"{largo:.1f} vs {PS.tour_rapido(D):.1f}")

print("\n── PLAN SEMANAL ────────────────────────────────────────────")
g = df[en & (df.zona == df[en].zona.iloc[0])].reset_index(drop=True)
P = Z.plano(g.lat.values, g.lon.values)
Dz = np.sqrt(((P[:, None, :] - P[None, :, :]) ** 2).sum(2)) * R.MIN_POR_KM * R.FACTOR_OPERATIVO
filas = PS.plan_de_zona(P, g.venta.values, g.frecuencia_semana.values, Dz, rapido=True)
revisar("el día cuadra: viaje + atención = total",
        all(abs(f["min_servicio"] + f["min_viaje"] - f["min_total"]) < 0.15 for f in filas))
visitas = sum(f["visitas"] for f in filas)
revisar("cada punto recibe sus visitas de la semana",
        visitas == int(g.frecuencia_semana.sum()), f"{visitas} visitas")
revisar("ningún punto se visita dos veces el mismo día",
        all(len(f["secuencia"]) == len(set(f["secuencia"])) for f in filas))

print("\n── GEOMETRÍA DEL MAPA ──────────────────────────────────────")
import mapa as M   # noqa: E402
poligonos, territorios = M.geometrias(df)
revisar("hay un polígono por zona", len(poligonos) == df[en].zona.nunique())
solapes = sum(1 for i, a in enumerate(poligonos) for b in list(poligonos)[i + 1:]
              if poligonos[a].intersection(poligonos[b]).area > 1e-9)
revisar("las zonas no se solapan", solapes == 0, f"{solapes} solapes")
from shapely.geometry import Point   # noqa: E402
fuera = [r.zona for r in df[en].itertuples()
         if not poligonos[r.zona].buffer(1e-9).covers(Point(r.lon, r.lat))]
revisar("cada punto cae dentro del polígono de su zona", not fuera,
        f"{len(fuera)} fuera de su zona" if fuera else f"{int(en.sum())} puntos")
col = M.colorear(poligonos)
revisar("ninguna zona vecina comparte color", col["choques"] == 0,
        f"{col['vecindades']} vecindades")

print("\n── REGRESIONES ─────────────────────────────────────────────")
import contextlib, importlib, io, tempfile   # noqa: E401, E402
from zonas import qa                          # noqa: E402
import qa_visual as QV                        # noqa: E402

# El día es un camino ABIERTO. Optimizar un circuito cerrado daba rutas peores
# que el heurístico en 83 de los 115 días del ejemplo.
peores = []
for s in range(4):
    Pr = np.random.default_rng(s).uniform(0, 5, (14, 2))
    Dr = np.sqrt(((Pr[:, None] - Pr[None]) ** 2).sum(2))
    o, largo = PS.orden_optimo(Dr)   # sin reloj: con 0,3 s fallaba bajo carga
    largo_real = sum(Dr[o[k], o[k + 1]] for k in range(len(o) - 1))
    if sorted(o) != list(range(14)) or abs(largo - largo_real) > 1e-6 or largo > PS.tour_rapido(Dr) + 1e-6:
        peores.append(s)
revisar("el solver optimiza el camino abierto que se mide", not peores,
        f"semillas con problema: {peores}" if peores else "4 de 4 instancias")

# Por defecto el solver para por número de soluciones, no por reloj: la misma
# entrada debe dar la misma ruta aunque la máquina esté cargada.
Pd = np.random.default_rng(11).uniform(0, 8, (25, 2))
Dd = np.sqrt(((Pd[:, None] - Pd[None]) ** 2).sum(2))
r1, r2 = PS.orden_optimo(Dd), PS.orden_optimo(Dd)
revisar("el solver por defecto repite la misma ruta", r1 == r2, f"{r1[1]:.2f} vs {r2[1]:.2f}")

revisar("el motor usa el mismo módulo de reglas que el usuario",
        Z.R is R and PS.R is R and qa.R is R)

dias_antes = R.DIAS_SEMANA
try:
    R.DIAS_SEMANA = 6
    importlib.reload(PS)
    seis = list(PS.DIAS)
finally:
    R.DIAS_SEMANA = dias_antes
    importlib.reload(PS)
revisar("una semana de seis días incluye el sábado", seis[-1] == "SA" and len(seis) == 6,
        " · ".join(seis))

# Con menos puntos que días, un punto F3 recibía UNA visita: la frecuencia se
# topaba en el número de sectores, que no puede pasar del número de puntos.
def visitas_por_punto(frecs):
    P2 = np.array([[0.0, 0.0], [1.0, 0.0], [0.0, 1.0]])[:len(frecs)]
    D2 = np.sqrt(((P2[:, None] - P2[None]) ** 2).sum(2)) * 10
    filas2 = PS.plan_de_zona(P2, np.full(len(frecs), 30e6), np.array(frecs, float), D2, rapido=True)
    cuenta = [sum(i in f["secuencia"] for f in filas2) for i in range(len(frecs))]
    distintos = all(len(f["secuencia"]) == len(set(f["secuencia"])) for f in filas2)
    return cuenta, distintos


c1, ok1 = visitas_por_punto([3])
c2, ok2 = visitas_por_punto([3, 2])
revisar("una zona más chica que la semana respeta la frecuencia",
        c1 == [3] and c2 == [3, 2] and ok1 and ok2, f"F3 → {c1} · F3,F2 → {c2}")


def lanza(fn):
    try:
        fn()
    except ValueError:
        return True
    return False


malo = base(30).assign(venta=lambda d: d.venta.where(d.index != 3))
revisar("una venta nula se rechaza con ValueError", lanza(lambda: Z.zonificar_grupo(malo)))
revisar("una columna faltante se rechaza con ValueError",
        lanza(lambda: Z.zonificar_grupo(base(30).drop(columns="frecuencia_semana"))))
z0, inf0 = Z.zonificar_grupo(base(), asesores=0)
revisar("cero asesores no produce zonas", inf0["zonas"] == 0 and (z0 == -1).all(),
        inf0.get("motivo", ""))

cal = Z.calibrar_viaje([{"visitas": 40, "area_km2": 3.0, "min_viaje_real": 500.0}])
revisar("calibrar con una sola zona no inventa correlación",
        cal is not None and cal["correlacion"] is None)

sin_plan = pd.DataFrame(columns=["zona", "min_servicio", "min_viaje", "min_total"])
zonas_df = df[en].groupby("zona").venta.sum().reset_index()
with contextlib.redirect_stdout(io.StringIO()):
    ok_vacio = qa.verificar(df, zonas_df, sin_plan)
revisar("el QA falla (sin romperse) si no hay plan semanal", ok_vacio is False)

quincenal = df.assign(pdv_id=[f"P{i:03d}" for i in range(len(df))])
quincenal.loc[quincenal.index[0], "frecuencia_semana"] = 0.5
with tempfile.TemporaryDirectory() as tmp:
    try:
        M.construir(quincenal, zonas_df.assign(min_semana=0.0), {"capturado": {}, "fuera": {}},
                    R.parametros(), Path(tmp) / "m.html")
        mapa_ok = True
    except Exception as e:   # noqa: BLE001
        mapa_ok = repr(e)
revisar("el mapa acepta frecuencia quincenal (0,5)", mapa_ok is True, "" if mapa_ok is True else mapa_ok)

panel_ok = "Zonas propuestas · Lo que quedó fuera · Cobertura de venta"
revisar("el QA visual pasa un panel completo", QV.veredicto(10, [], panel_ok) == [])
revisar("el QA visual falla con NaN en pantalla", bool(QV.veredicto(10, [], panel_ok + " NaN")))
revisar("el QA visual falla si al panel le falta un bloque",
        bool(QV.veredicto(10, [], "Zonas propuestas")))
revisar("el QA visual falla si algo tapa el control de zoom",
        bool(QV.veredicto(10, [], panel_ok, [".leaflet-control-zoom-in"])))

print("\n" + "─" * 60)
print(f"  {len(fallos)} fallos")
raise SystemExit(1 if fallos else 0)
