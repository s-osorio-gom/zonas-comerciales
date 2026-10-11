#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
reglas.py — TODOS los parámetros de negocio del proyecto, en un solo sitio.

Ningún otro módulo define una constante de negocio. Si un número de aquí cambia,
cambia el modelo entero y hay que volver a correr la cadena.

Ajustar los valores al proyecto. Los de fábrica vienen de un despliegue real de
distribución a tienda de barrio y sirven de punto de partida razonable.
Las cifras de dinero están en la moneda local del proyecto (los valores de
fábrica están en pesos colombianos).

La cadena de cálculo, SIEMPRE en este orden:

    venta mensual → frecuencia semanal → visitas/mes → VENTA POR VISITA → minutos

Nunca al revés. Calcular el tiempo con la venta mensual completa infla la
atención de los clientes de baja frecuencia y la subestima en los de alta.
"""
import math

# ---------------------------------------------------------------- calendario
SEMANAS_MES = 4.0
DIAS_SEMANA = 5              # lunes a viernes

# ---------------------------------------------------------------- jornada
JORNADA_OBJETIVO = 450       # se planifica contra esto
JORNADA_MAX = 480            # tope absoluto; el colchón absorbe tráfico e imprevistos
CAPACIDAD_SEMANA = JORNADA_OBJETIVO * DIAS_SEMANA   # meta de planificación
# Tope de trabajo semanal (atención + viaje estimado) con el que se ARMA una zona.
# Usa la jornada máxima: el plan semanal se mide luego contra la objetivo.
CAPACIDAD_ZONA = JORNADA_MAX * DIAS_SEMANA

# ---------------------------------------------------------------- atención
# minutos de una visita = INTERCEPTO + PENDIENTE × (venta en MM de esa visita)
#
# El INTERCEPTO es el costo fijo de cualquier visita: saludar, revisar
# inventario, tomar el pedido, despedirse. CALIBRARLO CONTRA EL DATO REAL antes
# de aceptarlo: en el proyecto original, sin intercepto, el cliente mediano
# recibía 26 SEGUNDOS de atención y 23 asesores habrían cubierto el país entero.
INTERCEPTO_MIN = 10.0
PENDIENTE_MIN_POR_MM = 2.0
MIN_ATENCION, MAX_ATENCION = 3.0, 90.0     # guardarraíles, no reglas de negocio

# ---------------------------------------------------------------- economía
UMBRAL_ZONA = 100_000_000    # restricción DURA: por debajo la zona no se paga
# Colchón sobre el umbral del proyecto original (ver docs/trampas.md §5). Este
# motor NO lo aplica: en su lugar `zonificar_grupo` prueba varios k por debajo
# del máximo teórico, que da la misma holgura. Se conserva como referencia.
MARGEN_UMBRAL = 1.12

# ---------------------------------------------------------------- prioridad (§cobertura)
PDV_OBLIGATORIO = 20_000_000     # debe entrar si es geométricamente posible
PDV_ALTA_PRIORIDAD = 5_000_000   # se intenta con fuerza; por debajo es sacrificable
# (el motor aún no usa PDV_ALTA_PRIORIDAD; PDV_OBLIGATORIO solo lo verifica qa)

# ---------------------------------------------------------------- frecuencias
FRECUENCIAS = (1, 2, 3)      # F1, F2, F3. F4 no existe en zona especializada.

# ---------------------------------------------------------------- desplazamiento
FACTOR_OPERATIVO = 1.45      # flujo libre → operación real (congestión, parqueo, a pie)
TOPE_VIAJE_ZONA = 0.60       # si el viaje supera esto, la zona está mal armada

# Estimador para usar DENTRO de la zonificación, cuando aún no hay ruta que medir.
# Beardwood–Halton–Hammersley: el recorrido óptimo por n puntos repartidos en un
# área A mide ≈ 0,7124·√(n·A).
# MIN_POR_KM NO es un supuesto: se CALIBRA contra rutas ya calculadas sobre el
# grafo vial (ver calibrar_viaje() en zonificar.py). El valor de fábrica salió de
# 1.194 días reales con correlación 0,955 y error mediano 0 %.
BHH = 0.7124
MIN_POR_KM = 6.59


def minutos_visita(venta_visita_mm: float) -> float:
    """Minutos de atención de UNA visita, según lo que se vende EN ESA VISITA."""
    if venta_visita_mm is None or venta_visita_mm != venta_visita_mm or venta_visita_mm < 0:
        return MIN_ATENCION
    t = INTERCEPTO_MIN + PENDIENTE_MIN_POR_MM * venta_visita_mm
    return max(MIN_ATENCION, min(MAX_ATENCION, t))


def visitas_mes(frecuencia_semana: float) -> float:
    return frecuencia_semana * SEMANAS_MES


def venta_por_visita(venta_mensual: float, frecuencia_semana: float) -> float:
    v = visitas_mes(frecuencia_semana)
    return venta_mensual / v if v > 0 else 0.0


def carga_semanal_min(venta_mensual: float, frecuencia_semana: float) -> float:
    """Minutos de ATENCIÓN por semana de un PDV. No incluye desplazamiento."""
    vv = venta_por_visita(venta_mensual, frecuencia_semana) / 1e6
    return minutos_visita(vv) * frecuencia_semana


def viaje_semana_min(n_visitas: float, area_km2: float, dias: int = DIAS_SEMANA) -> float:
    """Minutos de desplazamiento por semana de una zona, ANTES de tener la ruta.

    Se recorre el área completa cada día con la parte proporcional de visitas,
    que es como opera un asesor: cinco vueltas pequeñas sobre el mismo
    territorio, no una gran vuelta semanal.
    """
    if n_visitas <= 0 or area_km2 <= 0:
        return 0.0
    por_dia = max(n_visitas / dias, 1.0)
    return dias * BHH * math.sqrt(por_dia * area_km2) * MIN_POR_KM


def parametros() -> dict:
    """Los parámetros que viajan al entregable, para que pueda decir con qué
    reglas se calculó. Sin esto habría que creerle al documento."""
    return {
        "semanas_mes": SEMANAS_MES, "dias_semana": DIAS_SEMANA,
        "jornada_objetivo": JORNADA_OBJETIVO, "jornada_max": JORNADA_MAX,
        "capacidad_zona_min": CAPACIDAD_ZONA,
        "umbral_zona_mm": UMBRAL_ZONA / 1e6,
        "atencion": f"{INTERCEPTO_MIN:.0f} min + {PENDIENTE_MIN_POR_MM:.0f} × venta MM por visita",
        "frecuencias": list(FRECUENCIAS),
        "factor_operativo": FACTOR_OPERATIVO, "viaje_min_por_km": MIN_POR_KM,
    }


def autotest() -> str:
    """Prueba de negocio: una zona en el umbral con frecuencia 2."""
    assert visitas_mes(2) == SEMANAS_MES * 2
    vv = venta_por_visita(UMBRAL_ZONA, 2) / 1e6
    esperado = INTERCEPTO_MIN + PENDIENTE_MIN_POR_MM * vv
    assert abs(minutos_visita(vv) - esperado) < 1e-9
    # la pendiente se conserva: +1 MM por visita = +PENDIENTE minutos
    assert abs((minutos_visita(10.0) - minutos_visita(9.0)) - PENDIENTE_MIN_POR_MM) < 1e-9
    return (f"OK · {UMBRAL_ZONA/1e6:.0f} MM/mes · F2 → {visitas_mes(2):.0f} visitas/mes · "
            f"${vv:.1f} MM/visita · {minutos_visita(vv):.0f} min de atención")


if __name__ == "__main__":
    print(autotest())
