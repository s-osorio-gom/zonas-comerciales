#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
qa_visual.py — el protocolo de QA visual de `docs/mapa.md`, automatizado.

    python3 ejemplo/qa_visual.py

Abre el mapa en un navegador de verdad, espera a que la capa termine de pintar,
recoge los errores de JavaScript y guarda capturas. **Mirar las capturas** es el
paso que no se puede automatizar: cifras que no coinciden entre panel y tooltip,
etiquetas que tapan datos o estados mal marcados solo se ven así.

Requiere:  pip install playwright && playwright install chromium
"""
from pathlib import Path

SALIDA = Path(__file__).resolve().parent / "salida"
MAPA = SALIDA / "mapa_zonas.html"
TEXTOS_PANEL = ("Zonas propuestas", "Lo que quedó fuera", "Cobertura de venta")


def veredicto(capas: int, errores: list, panel: str) -> list:
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
    print("  capturas en ejemplo/salida/qa_*.png — MIRARLAS")
    motivos = veredicto(capas, errores, panel)
    for m in motivos:
        print(f"  FALLA: {m}")
    return 1 if motivos else 0


if __name__ == "__main__":
    raise SystemExit(main())
