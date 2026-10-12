#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
qa_visual.py — el protocolo de QA visual de `docs/mapa.md`, automatizado.

    python3 ejemplo/qa_visual.py

Abre el mapa en un navegador de verdad —escritorio 1440×900 y teléfono
390×844 vertical y apaisado—, comprueba que nada tape el zoom, espera a que la capa termine de pintar,
recoge los errores de JavaScript y guarda capturas. **Mirar las capturas** es el
paso que no se puede automatizar: cifras que no coinciden entre panel y tooltip,
etiquetas que tapan datos o estados mal marcados solo se ven así.

Requiere:  pip install playwright && playwright install chromium
"""
from pathlib import Path

SALIDA = Path(__file__).resolve().parent / "salida"
MAPA = SALIDA / "mapa_zonas.html"
TEXTOS_PANEL = ("Zonas propuestas", "Lo que quedó fuera", "Cobertura de venta")


# Controles que nada debe tapar: el panel llegó a cubrir el zoom en escritorio y
# casi todo el mapa en un teléfono, con la consola limpia.
CONTROLES = (".leaflet-control-zoom-in", ".leaflet-control-zoom-out")
TAPADOS_JS = """(sel) => sel.filter(s => {
    const e = document.querySelector(s); if (!e) return true;
    const r = e.getBoundingClientRect();
    const x = r.left + r.width / 2, y = r.top + r.height / 2;
    return !e.contains(document.elementFromPoint(x, y));
})"""


def veredicto(capas: int, errores: list, panel: str, tapados=()) -> list:
    """Motivos por los que la captura NO se entrega. Vacío = pasa.

    Las peticiones fallidas no cuentan: sin red las teselas del fondo fallan y
    el mapa sigue siendo correcto. Un `NaN` en pantalla o un panel incompleto,
    en cambio, son defectos del entregable aunque la consola esté limpia.
    """
    motivos = []
    if errores:
        motivos.append(f"{len(errores)} errores de JavaScript")
    if capas == 0:
        motivos.append("ninguna forma dibujada")
    if "NaN" in panel:
        motivos.append("'NaN' en pantalla")
    motivos += [f"falta «{t}» en el panel" for t in TEXTOS_PANEL if t not in panel]
    motivos += [f"control tapado: {s}" for s in tapados]
    return motivos


def main() -> int:
    if not MAPA.exists():
        print(f"Falta {MAPA}. Corra antes: python3 ejemplo/demo.py")
        return 1
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Falta playwright:  pip install playwright && playwright install chromium")
        return 1

    errores, fallidas = [], []
    with sync_playwright() as p:
        nav = p.chromium.launch()
        pg = nav.new_page(viewport={"width": 1440, "height": 900})
        pg.on("console", lambda m: errores.append(m.text) if m.type == "error" else None)
        pg.on("pageerror", lambda e: errores.append(str(e)))
        pg.on("requestfailed", lambda r: fallidas.append(r.url))

        pg.goto(MAPA.as_uri())
        pg.wait_for_selector(".leaflet-container", timeout=30_000)
        pg.wait_for_timeout(4_000)          # las teselas siguen subiendo tras `load`

        capas = pg.evaluate("document.querySelectorAll('path.leaflet-interactive').length")
        panel = pg.inner_text("body")
        tapados = pg.evaluate(TAPADOS_JS, list(CONTROLES))
        pg.screenshot(path=str(SALIDA / "qa_01_general.png"), full_page=False)

        # Acercar sobre una zona REAL. Un zoom sobre el centro del viewport cae
        # en territorio vacío y la captura no prueba nada.
        import csv
        with open(SALIDA / "pdv_con_zona.csv", encoding="utf-8") as f:
            filas = [r for r in csv.DictReader(f) if r["zona"]]
        z = sorted({r["zona"] for r in filas})[0]
        pun = [r for r in filas if r["zona"] == z]
        lat = sum(float(r["lat"]) for r in pun) / len(pun)
        lon = sum(float(r["lon"]) for r in pun) / len(pun)
        pg.evaluate("""([lat, lon]) => {
            const k = Object.keys(window).find(k => k.startsWith('map_'));
            window[k].setView([lat, lon], 14);
        }""", [lat, lon])
        pg.wait_for_timeout(3_000)
        pg.screenshot(path=str(SALIDA / "qa_02_zona.png"))
        print(f"  zoom sobre       {z}")

        # Teléfono, vertical y apaisado: el panel debe arrancar plegado y dejar
        # ver el mapa. Apaisado (844×390) el panel abierto ocupaba casi todo el alto.
        for nombre, (ancho_v, alto_v), archivo in (("vertical", (390, 844), "qa_03_movil.png"),
                                                    ("apaisado", (844, 390), "qa_04_movil_apaisado.png")):
            mv = nav.new_page(viewport={"width": ancho_v, "height": alto_v}, is_mobile=True,
                              has_touch=True, device_scale_factor=2)
            mv.on("pageerror", lambda e: errores.append(str(e)))
            mv.goto(MAPA.as_uri())
            mv.wait_for_selector(".leaflet-container", timeout=30_000)
            mv.wait_for_timeout(3_000)
            tapados += [f"{s} (móvil {nombre})" for s in mv.evaluate(TAPADOS_JS, list(CONTROLES))]
            if mv.evaluate("document.getElementById('panel-zonas')?.open === true"):
                tapados.append(f"panel abierto al cargar en móvil {nombre}")
            ancho = mv.evaluate("document.documentElement.scrollWidth")
            if ancho > ancho_v:
                tapados.append(f"scroll horizontal en móvil {nombre} ({ancho} px)")
            mv.screenshot(path=str(SALIDA / archivo))
        nav.close()

    print(f"  formas dibujadas    {capas}")
    print(f"  errores de JS       {len(errores)}")
    for e in errores[:5]:
        print(f"      · {e}")
    print(f"  peticiones fallidas {len(fallidas)}")
    for u in fallidas[:5]:
        print(f"      · {u}")
    for texto in TEXTOS_PANEL:
        print(f"  panel «{texto}»  {'OK' if texto in panel else 'FALTA'}")
    print(f"  'NaN' en pantalla   {'SÍ ← defecto' if 'NaN' in panel else 'no'}")
    print(f"  controles tapados   {len(tapados)}")
    print("  capturas en ejemplo/salida/qa_*.png — MIRARLAS")
    motivos = veredicto(capas, errores, panel, tapados)
    for m in motivos:
        print(f"  FALLA: {m}")
    return 1 if motivos else 0


if __name__ == "__main__":
    raise SystemExit(main())
