"""Motor de zonificación comercial.

    from zonas import reglas, zonificar, plan_semanal, qa

Dentro del paquete todos los módulos comparten `zonas.reglas`: cambiar un
parámetro en tiempo de ejecución (`reglas.UMBRAL_ZONA = ...`) lo ve todo el
motor. Cada módulo funciona también suelto: si se copia sin el paquete, inserta
su propia carpeta en `sys.path` para encontrar `reglas`.
"""
from . import reglas, zonificar, plan_semanal, qa   # noqa: F401

__all__ = ["reglas", "zonificar", "plan_semanal", "qa"]
__version__ = "1.0.0"
