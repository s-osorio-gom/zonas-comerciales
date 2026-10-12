#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
zonificar.py — zonas comerciales DESDE CERO, que se pagan y se pueden recorrer.

Construye zonas a partir de puntos georreferenciados con venta y frecuencia,
respetando tres restricciones DURAS:

  1. la zona vive dentro de un solo grupo (distribuidor/territorio)
  2. venta_zona >= UMBRAL
  3. la carga semanal (atención + desplazamiento) cabe en un asesor

NO usa la zona actual como semilla ni como geometría: eso reproduce la operación
que se quiere rediseñar.

Uso:
    import zonificar as Z
    etiquetas, informe = Z.zonificar_grupo(df, asesores=52)
    # df necesita: lat, lon, venta, frecuencia_semana

Entre dos soluciones parecidas gana la que deje MENOS VENTA residual, no la que
deje menos puntos: sacrificar diez tiendas de $1 MM es mejor que una de $30 MM.
"""
from pathlib import Path
import numbers
import sys

import numpy as np
from scipy.spatial import cKDTree

try:                       # dentro del paquete: el MISMO `zonas.reglas` del usuario
    from . import reglas as R
except ImportError:        # módulo copiado suelto a otro proyecto
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import reglas as R

RAD = np.pi / 180.0


# ---------------------------------------------------------------- geometría
def plano(lat, lon):
    """Coordenadas planas locales en km. Suficiente dentro de un grupo."""
    lat0 = np.mean(lat)
    return np.c_[(lon - np.mean(lon)) * 111.32 * np.cos(lat0 * RAD),
                 (lat - lat0) * 110.57]


class Acumulador:
    """Área y carga de una zona, actualizadas al vuelo.

    Hace falta porque la capacidad NO depende solo de la atención: una zona
    puede pagar el umbral y ser imposible de recorrer. Sin esto salen zonas que
    exigen cientos de horas de viaje por semana.
    """

    __slots__ = ("n", "sx", "sy", "sxx", "syy", "serv", "vis")

    def __init__(self):
        self.n = self.sx = self.sy = self.sxx = self.syy = 0.0
        self.serv = self.vis = 0.0

    def suma(self, x, y, serv, vis):
        self.n += 1; self.sx += x; self.sy += y
        self.sxx += x * x; self.syy += y * y
        self.serv += serv; self.vis += vis

    def _area(self, n, sx, sy, sxx, syy):
        if n < 3:
            return 0.05
        vx = max(sxx / n - (sx / n) ** 2, 0.0)
        vy = max(syy / n - (sy / n) ** 2, 0.0)
        return max(4.0 * np.sqrt(vx) * np.sqrt(vy), 0.05)

    def area(self):
        return self._area(self.n, self.sx, self.sy, self.sxx, self.syy)

    def trabajo(self):
        return self.serv + R.viaje_semana_min(self.vis, self.area())

    def con(self, x, y, serv, vis):
        """Trabajo semanal SI se añadiera este punto."""
        a = self._area(self.n + 1, self.sx + x, self.sy + y,
                       self.sxx + x * x, self.syy + y * y)
        return (self.serv + serv) + R.viaje_semana_min(self.vis + vis, a)


# ---------------------------------------------------------------- k-means capacitado
def _semillas(P, venta, k, rng):
    """k-means++ ponderado por venta: las semillas nacen donde está el dinero."""
    n = len(P)
    if k >= n:
        return P.copy()
    w = np.clip(venta, 1.0, None)
    idx = [int(rng.choice(n, p=w / w.sum()))]
    d2 = ((P - P[idx[0]]) ** 2).sum(1)
    for _ in range(k - 1):
        pr = d2 * w
        pr = pr / pr.sum() if pr.sum() > 0 else np.full(n, 1 / n)
        j = int(rng.choice(n, p=pr))
        idx.append(j)
        d2 = np.minimum(d2, ((P - P[j]) ** 2).sum(1))
    return P[idx]


def _asignar(P, carga, centros, cap):
    """Cada punto al centro más cercano que aún tenga capacidad de ATENCIÓN.

    Se recorre por distancia creciente: los puntos que solo tienen un centro
    cerca lo reclaman antes de que se lo llenen los que tienen alternativas.
    """
    k = len(centros)
    d = np.sqrt(((P[:, None, :] - centros[None, :, :]) ** 2).sum(2))
    orden = np.argsort(d.min(1))
    prefer = np.argsort(d, axis=1)
    usado = np.zeros(k)
    z = np.full(len(P), -1, int)
    for i in orden:
        for j in prefer[i]:
            if usado[j] + carga[i] <= cap:
                z[i] = j; usado[j] += carga[i]; break
        if z[i] < 0:
            j = int(np.argmin(usado)); z[i] = j; usado[j] += carga[i]
    return z


def _kmeans(P, venta, carga, k, cap, vueltas=25, semilla=7):
    rng = np.random.default_rng(semilla)
    C = _semillas(P, venta, k, rng)
    z = None
    for _ in range(vueltas):
        z2 = _asignar(P, carga, C, cap)
        if z is not None and np.array_equal(z, z2):
            break
        z = z2
        for j in range(k):
            m = z == j
            if m.any():
                w = np.clip(venta[m], 1.0, None)
                C[j] = (P[m] * w[:, None]).sum(0) / w.sum()
    return z


# ---------------------------------------------------------------- una pasada con k fijo
def _pasada(P, venta, carga, visitas, k_forzado, cap):
    k_paga = int(venta.sum() // R.UMBRAL_ZONA)
    if k_paga < 1:
        return np.full(len(P), -1), dict(zonas=0, motivo="venta total bajo umbral")
    k = max(1, min(int(k_forzado), k_paga))
    z = _kmeans(P, venta, carga, k, cap)

    def acc_de(z, j):
        a = Acumulador()
        for i in np.flatnonzero(z == j):
            a.suma(P[i][0], P[i][1], carga[i], visitas[i])
        return a

    def reequilibrar(z, vueltas):
        """Mueve puntos de frontera hacia la zona más pobre hasta que todas paguen.

        El destino solo acepta si SIGUE SIENDO ATENDIBLE con el viaje incluido:
        de nada sirve una zona que paga y no se puede recorrer.
        """
        for _ in range(vueltas):
            vz = np.array([venta[z == j].sum() for j in range(k)])
            vivos = [j for j in range(k) if (z == j).any()]
            pobres = [j for j in vivos if vz[j] < R.UMBRAL_ZONA]
            if not pobres:
                return z
            destino = min(pobres, key=lambda j: vz[j])
            acc = acc_de(z, destino)
            cen = P[z == destino].mean(0)
            cand = [i for i in range(len(P))
                    if z[i] != destino and z[i] >= 0
                    and vz[z[i]] - venta[i] >= R.UMBRAL_ZONA
                    and acc.con(P[i][0], P[i][1], carga[i], visitas[i]) <= cap]
            if not cand:
                return z
            z[cand[int(np.argmin(((P[cand] - cen) ** 2).sum(1)))]] = destino
        return z

    def podar(z):
        """Suelta los puntos que vuelven inmanejable una zona.

        En territorio disperso unas pocas tiendas lejanas y pequeñas disparan el
        desplazamiento de toda la semana. Se sueltan de una en una —la de peor
        relación venta/distancia primero— hasta que la zona cabe en la jornada.
        """
        n = 0
        for j in sorted({int(x) for x in z if x >= 0}):
            for _ in range(len(P)):
                m = np.flatnonzero(z == j)
                if len(m) < 5 or acc_de(z, j).trabajo() <= cap:
                    break
                cen = P[m].mean(0)
                dist = np.sqrt(((P[m] - cen) ** 2).sum(1))
                z[m[int(np.argmax(dist / np.maximum(venta[m], 1.0)))]] = -1
                n += 1
        return z, n

    def reabsorber(z):
        """Devuelve a una zona los sueltos que quepan sin romperla.

        Podar es necesario pero grosero: deja fuera puntos que la zona vecina sí
        puede atender. Sin este paso se pierde venta por pura mecánica.
        """
        n = 0
        vivos = [j for j in range(k) if (z == j).any()]
        if not vivos:
            return z, 0
        accs = {j: acc_de(z, j) for j in vivos}
        arbol = cKDTree(np.array([P[z == j].mean(0) for j in vivos]))
        sueltos = np.flatnonzero(z < 0)
        for i in sueltos[np.argsort(-venta[sueltos])]:
            _, kk = arbol.query(P[i], k=min(4, len(vivos)))
            for c in np.atleast_1d(kk):
                j = vivos[int(c)]
                if accs[j].con(P[i][0], P[i][1], carga[i], visitas[i]) <= cap:
                    z[i] = j; accs[j].suma(P[i][0], P[i][1], carga[i], visitas[i])
                    n += 1; break
        return z, n

    vueltas = max(600, 6 * len(P) + 40 * k)
    podados = reabsorbidos = 0
    for _ in range(4):
        z = reequilibrar(z, vueltas)
        z, np_ = podar(z)
        z, nr = reabsorber(z)
        podados += np_; reabsorbidos += nr
        if np_ == 0:
            break

    # lo que aun así no paga se disuelve y se reparte
    for _ in range(6):
        vz = np.array([venta[z == j].sum() for j in range(k)])
        malas = [j for j in range(k) if 0 < vz[j] < R.UMBRAL_ZONA]
        if not malas:
            break
        buenas = [j for j in range(k) if j not in malas and vz[j] > 0]
        if not buenas:
            break
        accs = {j: acc_de(z, j) for j in buenas}
        arbol = cKDTree(np.array([P[z == j].mean(0) for j in buenas]))
        for j in malas:
            for i in np.flatnonzero(z == j)[np.argsort(-venta[np.flatnonzero(z == j)])]:
                _, kk = arbol.query(P[i], k=min(3, len(buenas)))
                puesto = False
                for c in np.atleast_1d(kk):
                    d = buenas[int(c)]
                    if accs[d].con(P[i][0], P[i][1], carga[i], visitas[i]) <= cap:
                        z[i] = d; accs[d].suma(P[i][0], P[i][1], carga[i], visitas[i])
                        puesto = True; break
                if not puesto:
                    z[i] = -1
            z[z == j] = -1

    vz = {j: venta[z == j].sum() for j in set(z) if j >= 0}
    z = np.array([j if j >= 0 and vz.get(j, 0) >= R.UMBRAL_ZONA else -1 for j in z])
    tr = [acc_de(z, j).trabajo() for j in sorted({int(j) for j in z if j >= 0})]
    return z, dict(zonas=len(tr), k_paga=k_paga, k_probado=k,
                   podados=podados, reabsorbidos=reabsorbidos,
                   trabajo_max=round(max(tr), 0) if tr else 0)


# ---------------------------------------------------------------- API
def _validar(df, lat, lon, venta, frecuencia):
    """Rechaza la base antes de calcular: un NaN aquí no falla, se propaga.

    `int(NaN)` revienta lejos del origen y una venta negativa resta umbral sin
    que nadie lo note. Mejor un error que diga qué columna y cuántas filas.
    """
    faltan = [c for c in (lat, lon, venta, frecuencia) if c not in df.columns]
    if faltan:
        raise ValueError(f"faltan columnas: {', '.join(faltan)}")
    for c in (lat, lon, venta, frecuencia):
        s = df[c]
        # Texto y booleanos se rechazan aunque NumPy sepa convertirlos: '5000000'
        # suele venir de un CSV mal leído y True vale 1 peso sin que nadie lo note.
        if s.dtype.kind == "b":
            raise ValueError(f"'{c}' es booleana: se esperan números")
        if s.dtype.kind not in "iuf":
            raros = [v for v, nulo in zip(s, s.isna()) if not nulo and not _es_numero(v)]
            if raros:
                raise ValueError(f"'{c}' tiene {len(raros)} valores no numéricos "
                                 f"(p. ej. {raros[0]!r}); convertir antes con pd.to_numeric")
        try:
            x = np.asarray(s, dtype=float)
        except (TypeError, ValueError):
            raise ValueError(f"'{c}' tiene valores no numéricos") from None
        malos = int((~np.isfinite(x)).sum())
        if malos:
            raise ValueError(f"'{c}' tiene {malos} valores nulos o no finitos")
        if c in (venta, frecuencia) and (x < 0).any():
            raise ValueError(f"'{c}' tiene {int((x < 0).sum())} valores negativos")
    if ((df[lat].abs() > 90) | (df[lon].abs() > 180)).any():
        raise ValueError("coordenadas fuera de rango (|lat| ≤ 90, |lon| ≤ 180)")


def _es_numero(v):
    return isinstance(v, numbers.Real) and not isinstance(v, (bool, np.bool_))


def _validar_asesores(asesores):
    """None o un número entero. '3', True o 1,5 son casi siempre un error de
    lectura, no una dotación: se rechazan en vez de truncarse en silencio."""
    if asesores is None:
        return None
    if not _es_numero(asesores) or not float(asesores).is_integer():
        raise ValueError(f"asesores debe ser un número entero o None (recibido {asesores!r})")
    return int(asesores)


def zonificar_grupo(df, asesores=None, lat="lat", lon="lon",
                    venta="venta", frecuencia="frecuencia_semana"):
    """Zonas de UN grupo (distribuidor / territorio), con BÚSQUEDA del número.

    Fijar k de antemano falla en los dos extremos: en territorio urbano deja
    zonas gigantes que podrían partirse, y en territorio disperso pide más zonas
    de las que se pueden recorrer —al disolverse las que no llegan al umbral se
    pierde la venta de sus puntos—.

    Se prueban varios k y gana el que más VENTA deja dentro de zonas que pagan y
    se recorren. A igualdad de venta, el de más zonas: emplea más asesores.

    Devuelve (array de etiquetas -1..k-1, informe).
    """
    _validar(df, lat, lon, venta, frecuencia)
    asesores = _validar_asesores(asesores)
    if len(df) == 0:
        return np.full(0, -1), dict(zonas=0, motivo="grupo sin puntos")
    if asesores is not None and asesores < 1:
        return np.full(len(df), -1), dict(zonas=0, motivo="sin asesores", asesores=asesores)
    P = plano(df[lat].values.astype(float), df[lon].values.astype(float))
    v = df[venta].values.astype(float)
    f = df[frecuencia].values.astype(float)
    carga = np.array([R.carga_semanal_min(a, b) for a, b in zip(v, f)])
    cap = R.CAPACIDAD_ZONA

    k_max = int(v.sum() // R.UMBRAL_ZONA)
    if k_max < 1:
        return np.full(len(df), -1), dict(zonas=0, motivo="venta total bajo umbral")
    tope = min(k_max, int(asesores)) if asesores is not None else k_max
    rejilla = (list(range(tope, 0, -1)) if tope <= 8 else
               sorted({max(1, int(round(tope * x)))
                       for x in (1.0, .9, .8, .7, .6, .5, .4, .3)}, reverse=True))

    mejor, mejor_z, mejor_inf = -1.0, None, None
    for kk in rejilla:
        z, inf = _pasada(P, v, carga, f, kk, cap)
        cap_v = float(v[z >= 0].sum())
        nz = int(inf.get("zonas") or 0)
        if nz == 0:
            continue
        if cap_v > mejor * 1.001 or (abs(cap_v - mejor) <= mejor * 0.001
                                     and nz > int(mejor_inf.get("zonas") or 0)):
            mejor, mejor_z, mejor_inf = cap_v, z, inf
    if mejor_z is None:
        return np.full(len(df), -1), dict(zonas=0, motivo="ningún k viable", k_paga=k_max)
    mejor_inf["venta_capturada_mm"] = round(mejor / 1e6, 1)
    mejor_inf["asesores"] = asesores
    return mejor_z, mejor_inf


def calibrar_viaje(zonas_reales):
    """Ajusta R.MIN_POR_KM contra rutas YA calculadas sobre el grafo vial.

    `zonas_reales`: iterable de dicts con `visitas`, `area_km2` y `min_viaje_real`.

    Correr esto UNA VEZ con un primer plan y fijar el valor. El estimador BHH sin
    calibrar es una constante inventada; calibrado alcanzó correlación 0,955 y
    error mediano 0 % en el proyecto original.
    """
    import math
    km, real = [], []
    for z in zonas_reales:
        if z["visitas"] <= 0 or z["area_km2"] <= 0 or z["min_viaje_real"] <= 0:
            continue
        por_dia = max(z["visitas"] / R.DIAS_SEMANA, 1.0)
        km.append(R.DIAS_SEMANA * R.BHH * math.sqrt(por_dia * z["area_km2"]))
        real.append(z["min_viaje_real"])
    if not km:
        return None
    k = float(np.median(np.array(real) / np.array(km)))
    # con una sola zona, o sin variación, la correlación no está definida
    corr = (float(np.corrcoef(km, real)[0, 1])
            if len(km) > 1 and np.std(km) > 0 and np.std(real) > 0 else None)
    corr = round(corr, 3) if corr is not None else None
    return {"min_por_km": round(k, 2), "correlacion": corr, "zonas": len(km)}
