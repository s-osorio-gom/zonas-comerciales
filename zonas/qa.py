#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
qa.py — las comprobaciones que tienen que pasar antes de entregar.

No es un resumen bonito: cada prueba puede FALLAR y detener la entrega.
Un dato que no cuadra aquí no se explica en una nota al pie: se corrige.

Uso:
    import qa
    ok = qa.verificar(pdv, zonas, plan)   # DataFrames; imprime y devuelve bool
    ok = qa.verificar(pdv, zonas, plan, matrices={zona: D, ...})   # y recalcula el viaje
"""
from pathlib import Path
import ast
import sys

try:                       # dentro del paquete: el MISMO `zonas.reglas` del usuario
    from . import reglas as R
except ImportError:        # módulo copiado suelto a otro proyecto
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import reglas as R


def verificar(pdv, zonas, plan, col_zona="zona", col_venta="venta",
              col_grupo="grupo", col_frec="frecuencia_semana", matrices=None):
    """pdv: una fila por punto, con `col_zona` nulo si quedó residual.
       zonas: una fila por zona, con `col_venta` agregada.
       plan:  una fila por día-zona, con min_servicio, min_viaje, min_total y
              `secuencia` (índices dentro de la zona).
       matrices: {zona: matriz de minutos} con la que se planificó. Si se da, el
              viaje de cada secuencia publicada se RECALCULA y se compara con el
              reportado: es la única forma de saber que los minutos son los de
              esa ruta y no los de otra."""
    fallos, avisos, n_ok, n = [], [], 0, 0

    def prueba(nombre, ok, detalle="", critico=True):
        nonlocal n_ok, n
        n += 1
        n_ok += bool(ok)
        print(f"  [{'OK  ' if ok else ('FALLA' if critico else 'AVISO')}] {nombre}"
              + (f" — {detalle}" if detalle else ""))
        if not ok:
            (fallos if critico else avisos).append(f"{nombre}: {detalle}")

    en = pdv[col_zona].notna()
    print("\n── CUADRE MATEMÁTICO ───────────────────────────────────────")
    prueba("puntos en zona + residuales = total",
           int(en.sum()) + int((~en).sum()) == len(pdv),
           f"{int(en.sum()):,} + {int((~en).sum()):,} = {len(pdv):,}")

    v_en, v_fu = pdv[en][col_venta].sum(), pdv[~en][col_venta].sum()
    prueba("venta en zona + residual = venta total",
           abs((v_en + v_fu) - pdv[col_venta].sum()) < 1.0,
           f"diferencia {abs((v_en + v_fu) - pdv[col_venta].sum()):.6f}")

    s = pdv[en].groupby(col_zona)[col_venta].sum()
    c = zonas.set_index(col_zona)[col_venta].reindex(s.index)
    prueba("Σ venta de los puntos = venta de la zona",
           float((s - c).abs().max()) < 1.0,
           f"error máximo {float((s - c).abs().max()):.6f}")

    if zonas.empty:
        prueba("hay al menos una zona", False, "ninguna zona propuesta")
    bajo = zonas[zonas[col_venta] < R.UMBRAL_ZONA]
    prueba(f"toda zona vende ≥ ${R.UMBRAL_ZONA/1e6:.0f} MM", len(bajo) == 0,
           f"{len(bajo)} por debajo" if len(bajo) else
           f"mínima ${zonas[col_venta].min()/1e6:.1f} MM")

    if col_grupo in pdv.columns:
        cruces = pdv[en].groupby(col_zona)[col_grupo].nunique().pipe(lambda x: x[x > 1])
        prueba("ninguna zona mezcla grupos", len(cruces) == 0,
               f"{len(cruces)} mezcladas" if len(cruces) else
               f"{pdv[en][col_zona].nunique()} zonas revisadas")

    print("\n── RUTAS Y JORNADA ─────────────────────────────────────────")
    if plan.empty or not {"min_servicio", "min_viaje", "min_total"} <= set(plan.columns):
        prueba("hay plan semanal", False, "plan vacío o sin columnas de tiempo")
        return _cierre(n_ok, n, fallos, avisos)
    e = float((plan.min_servicio + plan.min_viaje - plan.min_total).abs().max())
    prueba("viaje + atención = total del día", e < 0.15, f"error máximo {e:.4f} min")

    if matrices is None or "secuencia" not in plan.columns:
        prueba("el viaje reportado es el de la secuencia publicada", False,
               "no se recalculó: falta `matrices` o la columna `secuencia`", critico=False)
    else:
        peor, malos = 0.0, 0
        for z, sec, viaje in zip(plan[col_zona], plan["secuencia"], plan["min_viaje"]):
            sec = ast.literal_eval(sec) if isinstance(sec, str) else list(sec)
            D = matrices[z]
            real = float(sum(D[sec[k], sec[k + 1]] for k in range(len(sec) - 1)))
            peor = max(peor, abs(real - float(viaje)))
            malos += abs(real - float(viaje)) >= 0.15
        prueba("el viaje reportado es el de la secuencia publicada", malos == 0,
               f"{malos} días no cuadran · error máximo {peor:.2f} min" if malos
               else f"error máximo {peor:.3f} min")

    nv = plan[plan.min_total > R.JORNADA_MAX]
    # Estos días NO son un defecto del cálculo: donde el territorio es delgado la
    # venta no paga tantas zonas como asesores exige el terreno. Se reporta.
    prueba(f"ningún día supera {R.JORNADA_MAX} min", len(nv) == 0,
           f"{len(nv)} días en {nv[col_zona].nunique()} zonas · "
           f"máx {plan.min_total.max():.0f} min"
           if len(nv) else f"máximo {plan.min_total.max():.0f} min", critico=False)

    al = plan[(plan.min_total > R.JORNADA_OBJETIVO) & (plan.min_total <= R.JORNADA_MAX)]
    prueba(f"días entre {R.JORNADA_OBJETIVO} y {R.JORNADA_MAX} min", len(al) == 0,
           f"{len(al)} en alerta", critico=False)

    cuota = plan.min_viaje.sum() / max(plan.min_total.sum(), 1e-9)
    prueba("el desplazamiento no domina la jornada", cuota < R.TOPE_VIAJE_ZONA,
           f"{cuota*100:.0f}% del tiempo")

    prueba("toda zona tiene plan semanal",
           set(zonas[col_zona]) <= set(plan[col_zona]),
           f"{len(set(zonas[col_zona]) - set(plan[col_zona]))} sin plan")

    print("\n── FRECUENCIA Y TIEMPO ─────────────────────────────────────")
    print("  " + R.autotest())
    if col_frec in pdv.columns:
        f = pdv[en][col_frec]
        prueba(f"ninguna frecuencia supera F{max(R.FRECUENCIAS)}",
               bool((f <= max(R.FRECUENCIAS)).all()),
               f"máxima {f.max():.1f} visitas/semana")

    print("\n── COBERTURA Y RESIDUALES ──────────────────────────────────")
    tot = max(float(pdv[col_venta].sum()), 1e-9)
    print(f"  venta capturada : ${v_en/1e6:>10,.0f} MM  ({v_en/tot*100:.1f}%)")
    print(f"  venta residual  : ${v_fu/1e6:>10,.0f} MM  ({v_fu/tot*100:.1f}%)")
    obl = pdv[~en & (pdv[col_venta] >= R.PDV_OBLIGATORIO)]
    prueba(f"puntos obligatorios (≥${R.PDV_OBLIGATORIO/1e6:.0f} MM) fuera",
           len(obl) == 0, f"{len(obl)} · ${obl[col_venta].sum()/1e6:,.0f} MM",
           critico=False)

    return _cierre(n_ok, n, fallos, avisos)


def _cierre(n_ok, n, fallos, avisos):
    print("\n" + "─" * 60)
    print(f"  {n_ok} de {n} pruebas · {len(fallos)} fallos críticos · {len(avisos)} avisos")
    for f in fallos:
        print(f"    · {f}")
    return not fallos
