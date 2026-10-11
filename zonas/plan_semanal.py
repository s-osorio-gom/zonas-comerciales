#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
plan_semanal.py — de una zona a días concretos con rutas y tiempos reales.

El tiempo de un día es SIEMPRE:

    Σ minutos de carretera  +  Σ minutos de atención

Nunca uno solo. "La moto tarda 116 minutos" sin contar lo que el asesor trabaja
dentro de las tiendas no describe nada.

Tres piezas que costaron caro aprender y por eso están aquí:

  1. `tour_rapido` — vecino más cercano + 2-opt. Para DECIDIR (equilibrar días,
     podar) nunca se llama a un solver: cuesta horas. En cinco instancias de 22
     paradas tardó 1-2 ms frente a 2 s de OR-Tools, con rutas un 1,6-13,6 %
     más largas (mediana 7 %): basta para comparar alternativas. El solver se
     reserva para la ruta FINAL que se publica.

  2. `repartir` — los días son SECTORES GEOGRÁFICOS de la zona, no un reparto
     equilibrado de minutos. Repartir por carga hace que el asesor recorra la
     zona entera cada día: en el proyecto original produjo 245 días imposibles.

  3. `equilibrar_dias` — mide el día con la ruta real y mueve visitas del más
     largo al más corto. Un punto NUNCA se mueve a un día donde ya está: rompería
     su frecuencia.
"""
from pathlib import Path
import sys

import numpy as np

try:                       # dentro del paquete: el MISMO `zonas.reglas` del usuario
    from . import reglas as R
except ImportError:        # módulo copiado suelto a otro proyecto
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import reglas as R

DIAS = ["LU", "MA", "MI", "JU", "VI", "SA"][:R.DIAS_SEMANA]
NOMBRE = {"LU": "Lunes", "MA": "Martes", "MI": "Miércoles",
          "JU": "Jueves", "VI": "Viernes", "SA": "Sábado"}


def tour_rapido(D):
    """Longitud de un recorrido bueno, sin invocar al solver.

    Vecino más cercano + 2-opt: queda un 5-8 % por encima del óptimo, suficiente
    para comparar dos alternativas, y corre en microsegundos.
    """
    n = len(D)
    if n <= 1:
        return 0.0
    if n == 2:
        return float(D[0, 1])
    visto = np.zeros(n, bool); ruta = [0]; visto[0] = True
    for _ in range(n - 1):
        d = np.where(visto, np.inf, D[ruta[-1]])
        j = int(np.argmin(d)); ruta.append(j); visto[j] = True
    r = np.array(ruta)
    for _ in range(6):
        mejora = False
        for a in range(1, n - 1):
            for b in range(a + 1, n):
                i0, i1, j0 = r[a - 1], r[a], r[b]
                j1 = r[b + 1] if b + 1 < n else None
                antes = D[i0, i1] + (D[j0, j1] if j1 is not None else 0.0)
                ahora = D[i0, j0] + (D[i1, j1] if j1 is not None else 0.0)
                if ahora < antes - 1e-9:
                    r[a:b + 1] = r[a:b + 1][::-1]; mejora = True
        if not mejora:
            break
    return float(sum(D[r[k], r[k + 1]] for k in range(n - 1)))


def orden_optimo(D, segundos=None):
    """Orden de visita con OR-Tools. Solo para la ruta FINAL que se publica.

    Si OR-Tools no está disponible, cae al heurístico sin romper nada.

    El presupuesto se reparte por TAMAÑO DEL DÍA. La búsqueda local guiada no
    para cuando encuentra el óptimo: agota el tiempo que se le dé. Como la
    mediana de un día real son 8 paradas, un presupuesto plano de un segundo es
    tiempo quemado. Medido sobre los 115 días de `ejemplo/`: presupuesto plano
    de 1 s → 113,0 s y 9.864,2 min de ruta; presupuesto por tamaño → 33,3 s
    y 9.848,0 min. **3,4x más rápido y la misma ruta** (0,2 % de ruido).
    """
    n = len(D)
    if n <= 2:
        return list(range(n)), (float(D[0, 1]) if n == 2 else 0.0)
    try:
        from ortools.constraint_solver import routing_enums_pb2, pywrapcp
    except ImportError:
        return list(range(n)), tour_rapido(D)
    ms = (int(segundos * 1000) if segundos is not None else
          150 if n <= 10 else 600 if n <= 20 else 1500 if n <= 35 else 3000)
    # El día es un recorrido ABIERTO: empieza en una parada y termina en otra.
    # OR-Tools resuelve circuitos cerrados, así que se añade un depósito ficticio
    # (nodo n) a coste cero de todos: el circuito óptimo por él equivale al
    # camino abierto óptimo. Sin esto el solver optimiza la vuelta de regreso,
    # que nadie mide, y el camino publicado sale peor que el heurístico.
    coste = np.zeros((n + 1, n + 1), dtype=np.int64)
    coste[:n, :n] = np.round(D * 100).astype(np.int64)
    g = pywrapcp.RoutingIndexManager(n + 1, 1, n)
    rut = pywrapcp.RoutingModel(g)
    cb = rut.RegisterTransitCallback(
        lambda i, j: int(coste[g.IndexToNode(i)][g.IndexToNode(j)]))
    rut.SetArcCostEvaluatorOfAllVehicles(cb)
    par = pywrapcp.DefaultRoutingSearchParameters()
    par.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    par.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    par.time_limit.FromMilliseconds(ms)
    sol = rut.SolveWithParameters(par)
    if not sol:
        return list(range(n)), tour_rapido(D)
    orden, i = [], sol.Value(rut.NextVar(rut.Start(0)))
    while not rut.IsEnd(i):
        orden.append(g.IndexToNode(i))
        i = sol.Value(rut.NextVar(i))
    tot = float(sum(D[orden[k], orden[k + 1]] for k in range(n - 1)))
    return orden, tot


def repartir(P, frecuencias, carga, n_dias=len(DIAS)):
    """Reparte las visitas de la semana entre los días, por GEOGRAFÍA.

    La zona se parte en tantos sectores como días y cada punto entra en el suyo.
    Los de frecuencia 2 y 3 necesitan días SEPARADOS: se les da su sector y luego
    los más cercanos, que es donde el desvío cuesta menos.
    """
    n = len(P)
    dias = {d: [] for d in DIAS[:n_dias]}
    if n == 0:
        return dias
    k = min(n_dias, n)

    C = [P[int(np.argmax(((P - P.mean(0)) ** 2).sum(1)))]]
    for _ in range(k - 1):
        d2 = np.min([((P - c) ** 2).sum(1) for c in C], axis=0)
        C.append(P[int(np.argmax(d2))])
    C = np.array(C, dtype=float)
    lab = None
    for _ in range(30):
        d = np.sqrt(((P[:, None, :] - C[None, :, :]) ** 2).sum(2))
        nl = d.argmin(1)
        if lab is not None and np.array_equal(lab, nl):
            break
        lab = nl
        for j in range(k):
            if (lab == j).any():
                C[j] = P[lab == j].mean(0)

    # equilibrio de carga sin romper la contigüidad: solo puntos de frontera
    d = np.sqrt(((P[:, None, :] - C[None, :, :]) ** 2).sum(2))
    objetivo = carga.sum() / k
    for _ in range(4 * n):
        cz = np.array([carga[lab == j].sum() for j in range(k)])
        if cz.max() <= objetivo * 1.35 or cz.min() >= objetivo * 0.65:
            break
        alto, bajo = int(cz.argmax()), int(cz.argmin())
        m = np.flatnonzero(lab == alto)
        if len(m) <= 1:
            break
        lab[m[int(np.argmin(d[m, bajo] - d[m, alto]))]] = bajo

    orden = sorted(range(k), key=lambda j: C[j][0])   # de occidente a oriente
    dia_de = {j: DIAS[i] for i, j in enumerate(orden)}
    # Con menos puntos que días sobran días sin sector. Antes las visitas se
    # topaban en k y un único punto F3 recibía UNA visita a la semana, en
    # silencio. Las que no caben en un sector van a esos días libres.
    libres = DIAS[k:n_dias]
    for i in range(n):
        f = frecuencias[i]
        veces = min(max(1, int(round(f))) if f >= 1 else 1, n_dias)
        propio = int(lab[i])
        cerca = sorted(range(k), key=lambda x: (x != propio, d[i, x]))[:veces]
        for j in cerca:
            dias[dia_de[j]].append(i)
        for dia in libres[:veces - len(cerca)]:
            dias[dia].append(i)
    return dias


def _tiempo(ii, D, min_visita):
    if not ii:
        return 0.0, 0.0
    return tour_rapido(D[np.ix_(ii, ii)]), float(np.sum(min_visita[ii]))


def equilibrar_dias(reparto, D, min_visita, vueltas=30):
    """Mueve visitas entre días hasta que todos quepan en la jornada."""
    dias = {d: list(v) for d, v in reparto.items()}
    for _ in range(vueltas):
        t = {d: sum(_tiempo(v, D, min_visita)) for d, v in dias.items()}
        largo = max(t, key=t.get)
        if t[largo] <= R.JORNADA_OBJETIVO:
            break
        corto = min(t, key=t.get)
        if t[corto] >= t[largo] - 20:
            break
        mejor, ganancia = None, 0.0
        for i in dias[largo]:
            if i in dias[corto]:
                continue          # ya se visita ese día: rompería la frecuencia
            gana = t[largo] - sum(_tiempo([x for x in dias[largo] if x != i], D, min_visita))
            cuesta = sum(_tiempo(dias[corto] + [i], D, min_visita)) - t[corto]
            if gana - cuesta > ganancia:
                mejor, ganancia = i, gana - cuesta
        if mejor is None:
            break
        dias[largo].remove(mejor); dias[corto].append(mejor)
    return dias


def plan_de_zona(P, venta, frecuencias, D, rapido=False, segundos=None):
    """Días, orden de visita y tiempos de UNA zona.

    `D` es la matriz de minutos entre sus puntos, YA multiplicada por el factor
    operativo. `rapido=True` omite el solver y el equilibrio fino: se usa dentro
    de bucles de decisión, nunca para publicar.

    `segundos` es el presupuesto del solver por día. Dejarlo en `None`: el
    presupuesto se ajusta solo al tamaño del día. Es el parámetro que domina el
    tiempo total —el solver corre una vez por DÍA, no una vez por zona—, así que
    subirlo a mano solo tiene sentido en zonas con días de muchas paradas.

    Devuelve lista de dicts por día.
    """
    vv = np.array([R.venta_por_visita(v, f) / 1e6 for v, f in zip(venta, frecuencias)])
    min_visita = np.array([R.minutos_visita(x) for x in vv])
    carga = min_visita * frecuencias

    reparto = repartir(P, frecuencias, carga)
    if not rapido:
        reparto = equilibrar_dias(reparto, D, min_visita)

    filas = []
    for dia, ii in reparto.items():
        if not ii:
            continue
        sub = D[np.ix_(ii, ii)]
        if rapido:
            viaje, sec = tour_rapido(sub), list(ii)
        else:
            orden, viaje = orden_optimo(sub, segundos)
            sec = [int(ii[k]) for k in orden]
        serv = float(np.sum(min_visita[sec]))
        tot = serv + viaje
        filas.append(dict(
            dia=dia, dia_nombre=NOMBRE.get(dia, dia), visitas=len(sec),
            secuencia=sec, min_servicio=round(serv, 1), min_viaje=round(viaje, 1),
            min_total=round(tot, 1),
            estado=("VIABLE" if tot <= R.JORNADA_OBJETIVO
                    else "ALERTA" if tot <= R.JORNADA_MAX else "NO_VIABLE")))
    return filas
