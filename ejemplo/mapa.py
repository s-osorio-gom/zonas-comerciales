#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mapa.py — la capa visual del ejemplo: un HTML de un solo archivo.

Aplica lo que dice `docs/mapa.md`:

  · el TERRITORIO del grupo se dibuja como BORDE grueso y la ZONA propuesta como
    RELLENO. Son dos cosas distintas —quién manda dónde, quién lo recorre— y si
    se dibujan igual nadie las separa.
  · las zonas NO SE SOLAPAN y cada punto cae dentro de la SUYA: cada zona es la
    unión de las celdas de Voronoi de sus puntos, recortada al área que esos
    puntos alcanzan. Una envolvente convexa por zona es más
    fácil de programar y produce zonas montadas unas sobre otras, que es
    justamente lo que no puede pasar en un mapa de territorios.
  · el color sale de un COLOREADO DE GRAFO sobre la adyacencia real, no de un
    contador `i % 8`, que deja zonas vecinas del mismo color justo donde hay que
    distinguirlas (`docs/trampas.md`, §8).
  · el panel de entrada dice también LO QUE QUEDÓ FUERA. Un resumen que solo
    cuenta lo bueno no sirve para decidir.

Las geometrías se calculan en grados. Cerca del ecuador la distorsión es
despreciable; lejos, proyectar antes de bufear.
"""
from __future__ import annotations

from html import escape

import folium
import numpy as np
from scipy.spatial import Voronoi
from shapely.geometry import MultiPoint, Polygon
from shapely.ops import unary_union

# Paleta neutra de trabajo. Sustituir por la de la marca de cada quien.
PALETA = ["#3B7DD8", "#E1843C", "#4FA167", "#B5539C",
          "#D6474B", "#2FA3A9", "#8B6BC7", "#A8802C"]
GRIS_BORDE = "#4A5462"

# Tres pasos que se distinguen a simple vista. Con grises muy juntos los tres
# niveles se leen como uno solo en pantalla aunque en el código parezcan
# distintos.
COLOR_FRECUENCIA = {1: "#C3CBD6", 2: "#6B7A90", 3: "#16202E"}

KM_POR_GRADO = 110.57


def nivel_frecuencia(f) -> int:
    """El color de F1/F2/F3 para cualquier frecuencia. Quincenal (0,5) y mensual
    (0,25) se pintan como F1; cualquier cosa por encima de 3, como F3."""
    return min(max(int(round(float(f))), 1), 3)


def _envolvente(puntos: np.ndarray, holgura_km: float = 0.4):
    """Envolvente convexa de un conjunto de puntos, con algo de aire."""
    return MultiPoint([(float(x), float(y)) for x, y in puntos]
                      ).convex_hull.buffer(holgura_km / KM_POR_GRADO)


def _area_servicio(puntos: np.ndarray, factor: float, tope_km: float):
    """Hasta dónde llega de verdad una zona: la unión de lo que alcanza cada
    punto, no el polígono que los encierra.

    El radio de cada punto se mide contra su vecino más cercano de la MISMA
    zona. Un radio fijo pensado para ciudad parte una zona rural en islas; uno
    pensado para el campo infla las urbanas sobre territorio que nadie atiende.
    """
    if len(puntos) == 1:
        radios = np.array([tope_km])
    else:
        d = np.sqrt(((puntos[:, None, :] - puntos[None, :, :]) ** 2).sum(2))
        np.fill_diagonal(d, np.inf)
        radios = np.clip(d.min(1) * KM_POR_GRADO * factor, 0.25, tope_km)
    return unary_union([
        Polygon(MultiPoint([(float(x), float(y))]).buffer(r / KM_POR_GRADO).exterior)
        for (x, y), r in zip(puntos, radios)])


def _celdas_voronoi(centros: np.ndarray, limite):
    """Una celda por centro, sin solapes y recortadas al límite del grupo.

    Se añaden cuatro puntos muy lejanos para que ninguna región real quede
    abierta: las regiones infinitas de un Voronoi no se pueden dibujar.
    """
    minx, miny, maxx, maxy = limite.bounds
    w, h = max(maxx - minx, 1e-4), max(maxy - miny, 1e-4)
    lejos = np.array([[minx - 5 * w, miny - 5 * h], [minx - 5 * w, maxy + 5 * h],
                      [maxx + 5 * w, miny - 5 * h], [maxx + 5 * w, maxy + 5 * h]])
    if len(centros) == 1:
        return [limite]
    vor = Voronoi(np.vstack([centros, lejos]))
    celdas = []
    for i in range(len(centros)):
        region = vor.regions[vor.point_region[i]]
        if not region or -1 in region or len(region) < 3:
            celdas.append(limite)
            continue
        celdas.append(Polygon(vor.vertices[region]).buffer(0).intersection(limite))
    return celdas


def geometrias(pdv, col_zona="zona", col_grupo="grupo",
               radio_factor=1.4, radio_tope_km=9.0):
    """Polígono de cada zona (sin solapes) y de cada territorio de grupo.

    La celda de Voronoi es la de cada PUNTO, no la del centro de su zona, y las
    celdas se disuelven por zona. Con celdas por centro, un punto asignado a una
    zona pero más cerca del centro de la vecina se dibujaba dentro de la vecina:
    en el ejemplo, 132 de 640 puntos quedaban fuera de su propia zona. Los puntos
    residuales también son sitios: su celda no se regala a ninguna zona.
    """
    zonas, territorios = {}, {}
    for grupo, g in pdv.groupby(col_grupo):
        territorios[grupo] = _envolvente(g[["lon", "lat"]].values, holgura_km=0.8)
        con_zona = g[g[col_zona].notna()]
        if con_zona.empty:
            continue
        # un sitio por coordenada: Voronoi no admite puntos repetidos
        sitios = g[["lon", "lat"]].astype(float).round(7).drop_duplicates()
        celdas = _celdas_voronoi(sitios.values, territorios[grupo])
        zona_de_sitio = g.loc[sitios.index, col_zona].values
        for z in sorted(con_zona[col_zona].unique()):
            union = unary_union([c for c, e in zip(celdas, zona_de_sitio) if e == z])
            puntos = con_zona[con_zona[col_zona] == z][["lon", "lat"]].values
            geo = union.intersection(_area_servicio(puntos, radio_factor, radio_tope_km))
            if not geo.is_empty:
                zonas[z] = geo
    return zonas, territorios


def colorear(poligonos: dict, tolerancia_km: float = 0.6) -> dict:
    """Un color por zona, de forma que NINGÚN par de zonas vecinas comparta color.

    Coloreado voraz sobre el grafo de adyacencia real, empezando por las zonas
    con más vecinos, que son las difíciles de acomodar.

    La adyacencia se mide con TOLERANCIA. Tras recortar cada celda al área que
    sus puntos alcanzan, dos zonas que el ojo ve pegadas pueden quedar separadas
    por unos metros de suelo vacío: sin tolerancia el grafo no las considera
    vecinas, les da el mismo color y en pantalla se leen como una sola.
    """
    claves = list(poligonos)
    holgura = tolerancia_km / KM_POR_GRADO
    inflados = {k: v.buffer(holgura) for k, v in poligonos.items()}
    vecinos = {k: set() for k in claves}
    for i, a in enumerate(claves):
        for b in claves[i + 1:]:
            if inflados[a].intersects(inflados[b]):
                vecinos[a].add(b); vecinos[b].add(a)

    color = {}
    for k in sorted(claves, key=lambda z: -len(vecinos[z])):
        usados = {color[v] for v in vecinos[k] if v in color}
        color[k] = next((c for c in PALETA if c not in usados), PALETA[-1])

    choques = sum(1 for k in claves for v in vecinos[k] if color[k] == color[v]) // 2
    return {"color": color,
            "vecindades": sum(len(v) for v in vecinos.values()) // 2,
            "choques": choques}


def _panel(resumen: dict, parametros: dict) -> str:
    def fila(k, v):
        return (f"<tr><td style='padding:1px 10px 1px 0;vertical-align:top'>{k}</td>"
                f"<td style='text-align:right'><b>{v}</b></td></tr>")

    def leyenda():
        p = "".join(
            f"<span style='display:inline-block;width:9px;height:9px;border-radius:50%;"
            f"background:{c};margin:0 4px 0 10px'></span>F{f}"
            for f, c in sorted(COLOR_FRECUENCIA.items()))
        return (f"<div style='margin-top:8px;color:#4b5563'>Punto = visitas/semana{p}</div>"
                "<div style='color:#4b5563'>Borde a rayas = territorio del grupo</div>")

    # El panel deja libre el control de zoom (arriba a la izquierda) y se pliega.
    # En pantallas estrechas baja al pie y arranca plegado: abierto tapaba casi
    # todo el mapa en un teléfono.
    return f"""
    <style>
      #panel-zonas {{position:fixed;top:12px;left:54px;z-index:9999;width:288px;
        background:#fff;border:1px solid #d7dbe0;border-radius:8px;padding:10px 14px;
        font:12px/1.45 system-ui,-apple-system,sans-serif;color:#111827;
        box-shadow:0 2px 10px rgba(0,0,0,.12);max-height:calc(100vh - 60px);overflow:auto}}
      #panel-zonas summary {{cursor:pointer;font-size:14px;font-weight:700}}
      #panel-zonas summary::after {{content:" · ver resumen ▾";font-weight:400;color:#6b7280}}
      #panel-zonas[open] summary::after {{content:" ▴"}}
      @media (max-width:600px) {{
        #panel-zonas {{top:auto;bottom:56px;left:8px;right:8px;width:auto;max-height:50vh}}
      }}
    </style>
    <details id="panel-zonas" open>
      <summary>Zonas propuestas</summary>
      <div style="color:#6b7280;margin-bottom:10px">Datos sintéticos · ejemplo reproducible</div>
      <table style="width:100%">{"".join(fila(k, v) for k, v in resumen["capturado"].items())}</table>
      <div style="margin:10px 0 4px;font-weight:700;color:#b4453f">Lo que quedó fuera</div>
      <table style="width:100%">{"".join(fila(k, v) for k, v in resumen["fuera"].items())}</table>
      <div style="margin:10px 0 4px;font-weight:700">Reglas con las que se calculó</div>
      <table style="width:100%;color:#4b5563">{"".join(fila(k, v) for k, v in parametros.items())}</table>
      {leyenda()}
    </details>
    <script>
      if (window.matchMedia("(max-width:600px)").matches)
        document.getElementById("panel-zonas").removeAttribute("open");
    </script>"""


def construir(pdv, zonas, resumen, parametros, salida,
              col_zona="zona", col_grupo="grupo"):
    """Escribe el mapa. `pdv` lleva lat/lon/venta/frecuencia_semana y `zona` nulo
    si el punto quedó residual."""
    poligonos, territorios = geometrias(pdv, col_zona, col_grupo)
    coloreo = colorear(poligonos)

    # El fondo gris claro de Esri. CartoDB Positron —el que Folium trae por
    # defecto— pasó a exigir llave: sin ella devuelve teselas estampadas con
    # "API KEY REQUIRED" y el mapa parece roto. Ningún chequeo automático lo ve;
    # la primera captura de pantalla lo delata.
    m = folium.Map(location=[float(pdv.lat.mean()), float(pdv.lon.mean())],
                   tiles=None, control_scale=True)
    folium.TileLayer(
        tiles=("https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/"
               "World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}"),
        attr="Esri · HERE · Garmin · OpenStreetMap contributors",
        name="Fondo claro", control=False).add_to(m)

    # ── territorio del grupo: borde grueso, sin relleno
    # En un proyecto real este polígono viene de la geometría oficial disuelta
    # por grupo (municipios o sectores censales), no de una envolvente.
    capa_t = folium.FeatureGroup(name="Territorio del grupo", show=True)
    for grupo, geo in territorios.items():
        g = pdv[pdv[col_grupo] == grupo]
        folium.GeoJson(
            geo.__geo_interface__,
            style_function=lambda _f: {"color": GRIS_BORDE, "weight": 2.5,
                                       "fill": False, "dashArray": "7,5"},
            tooltip=f"{escape(str(grupo))} · {len(g)} puntos · ${g.venta.sum()/1e6:,.0f} MM/mes",
        ).add_to(capa_t)
    capa_t.add_to(m)

    # ── zona propuesta: relleno
    capa_z = folium.FeatureGroup(name="Zona propuesta", show=True)
    for z, geo in poligonos.items():
        g = pdv[pdv[col_zona] == z]
        c = coloreo["color"][z]
        fila = zonas[zonas[col_zona] == z].iloc[0]
        folium.GeoJson(
            geo.__geo_interface__,
            style_function=lambda _f, c=c: {"color": c, "weight": 1.4,
                                            "fillColor": c, "fillOpacity": 0.30},
            tooltip=(f"<b>{escape(str(z))}</b><br>{len(g)} puntos"
                     f"<br>${g.venta.sum()/1e6:,.1f} MM/mes"
                     f"<br>{fila.get('min_semana', 0):,.0f} min/semana"),
        ).add_to(capa_z)
    capa_z.add_to(m)

    # ── puntos: una sola semántica por nivel, aquí la frecuencia
    capa_p = folium.FeatureGroup(name="Puntos de venta", show=True)
    for _, r in pdv.iterrows():
        residual = not isinstance(r[col_zona], str)
        c = COLOR_FRECUENCIA[nivel_frecuencia(r.frecuencia_semana)]
        folium.CircleMarker(
            [r.lat, r.lon], radius=2.4 + 0.8 * float(r.frecuencia_semana),
            color="#b4453f" if residual else "#ffffff",
            weight=1.4 if residual else 0.6, fill=True, fill_opacity=0.95,
            fill_color="#ffffff" if residual else c,
            tooltip=(f"{escape(str(r.pdv_id))} · {escape(str(r[col_grupo]))}"
                     f"<br>${r.venta/1e6:,.1f} MM/mes"
                     f"<br>F{float(r.frecuencia_semana):g} · "
                     f"{escape(r[col_zona]) if not residual else '<b>sin zona</b>'}"),
        ).add_to(capa_p)
    capa_p.add_to(m)

    m.fit_bounds([[float(pdv.lat.min()), float(pdv.lon.min())],
                  [float(pdv.lat.max()), float(pdv.lon.max())]], padding=(30, 30))
    folium.LayerControl(collapsed=False).add_to(m)
    m.get_root().html.add_child(folium.Element(_panel(resumen, parametros)))
    m.save(str(salida))

    # Prueba dura: dos zonas no pueden ocupar el mismo suelo.
    solapes = sum(
        1 for i, a in enumerate(poligonos) for b in list(poligonos)[i + 1:]
        if poligonos[a].intersection(poligonos[b]).area > 1e-9)
    coloreo["solapes"] = solapes
    return coloreo
