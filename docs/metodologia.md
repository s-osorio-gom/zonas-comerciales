# Metodología por eslabón

Cómo se resuelve cada paso de la cadena. Índice:

1. Territorio contractual desde documentos
2. Exclusividad: un territorio, un dueño
3. Asignación de puntos por geografía
4. Dotación real
5. Zonas desde cero
6. Frecuencia
7. Conflictos de negocio

---

## 1 · Territorio contractual desde documentos

Los contratos suelen traer anexos con las unidades territoriales de cada
distribuidor. Reglas de extracción:

- **Descubrir los archivos recorriendo carpetas**, no con una lista escrita a
  mano. Una lista fija dejó cuatro distribuidores fuera sin que nadie lo notara.
- **Detectar la tabla por su firma de encabezado** (código + departamento o
  municipio), no por el título de la sección. La numeración de anexos cambia
  entre contratos.
- **Prioridad de vigencia:** el año más reciente manda. Un anexo anterior solo
  se usa si no existe uno posterior, y queda marcado.
- **Comprobar que cada documento produjo filas.** Si sale en cero, revisar si su
  tabla es una imagen (ver `trampas.md §12`).

### Tablas en imagen

Cuando cada celda es una imagen independiente, la columna se conoce por
construcción y el OCR es fiable. Dos cuidados:

- Componer sobre blanco usando el canal alfa: si el fondo es transparente,
  Tesseract ve un rectángulo negro.
- **No tomar el código del OCR.** Los dígitos se leen mal de forma sistemática
  (15047 sale como "19504/"). Los **nombres** salen limpios: resolver la unidad
  **por nombre** contra el catálogo oficial y usar el código leído solo como
  verificación cruzada. Etiquetar cada fila con su nivel de certeza.

### Niveles de detalle

Un anexo puede declarar el territorio a distintos niveles. Usar **el que traiga
la fuente**, sin inventar subdivisiones:

```
barrio  >  sector censal  >  centro poblado  >  municipio
```

**El detalle manda.** Si A declara sectores dentro de un municipio y B declara el
municipio entero, no es conflicto: es un anexo más fino que el otro.

**Un listado de partes no es reclamar el todo.** Si un municipio ya está partido
a nivel fino, un distribuidor que lista dos corregimientos está reclamando esas
dos partes, no el municipio. Leerlo mal entregó 621 puntos a quien nunca los
reclamó.

## 2 · Exclusividad

- Dos reclamos **al mismo nivel** sí son conflicto.
- Lo que **nadie** reclama no se adjudica: va a un grupo explícito tipo
  `SIN ASIGNAR`, que se zonifica igual y se reporta como tal.
- Los conflictos se pueden resolver **por evidencia de la operación actual**
  (quién atiende hoy), siempre **marcados para revisión**. Si nadie opera ahí, no
  hay evidencia que usar: se deja pendiente.

## 3 · Asignación de puntos

Por **geografía**, de lo fino a lo grueso: barrio (nombre normalizado) → sector
(point-in-polygon) → municipio (código) → resto → sin cobertura.

Al normalizar nombres, distinguir **notación** de **identidad**: "POPULAR N 1" y
"POPULAR 1" son el mismo barrio; "AURES" y "LAURELES" **no**. Normalizar solo
numeración y abreviaturas; nunca aceptar un parecido suelto.

Mantener siempre la comparación contra la operación actual en una columna de
consistencia: `CONSISTENTE`, `REVIEW`, `CONFLICTO`, `SIN COBERTURA`.

**Puente de nombres:** la operación suele escribir el nombre del distribuidor
distinto a como aparece en el contrato ("A&B Norte" vs "AYB Norte"). Sin un
puente explícito de nombres, el cruce reporta falsos conflictos — en el proyecto
original, 621 puntos y $1.400 MM de conflicto inexistente.

## 4 · Dotación real

**No asumir que número de zonas = número de asesores.** Contar identificadores
únicos, y **verificar la cardinalidad del campo antes de usarlo como clave**.

Este número es el techo del escenario base: la propuesta debe intentar resolverse
con la dotación actual antes de pedir gente nueva.

## 5 · Zonas desde cero

Restricciones duras, en orden: un solo grupo · venta ≥ umbral · la carga cabe en
un asesor.

Prioridad de cobertura sugerida:

```
≥ PDV_OBLIGATORIO     debe entrar si es geométricamente posible
alta prioridad        se intenta con fuerza
resto                 sacrificable si arruina el recorrido
```

Entre dos soluciones parecidas gana la que deje **menos venta** residual, no la
que deje menos puntos.

## 6 · Frecuencia

Trabajar con F1/F2/F3. La frecuencia actual es la **línea base** y se conserva —
incluidas quincenal y mensual, que para un punto pequeño son la decisión correcta
y ahorran recurso. Solo se recorta lo que excede el máximo.

Mantener `frecuencia_actual` y `frecuencia_propuesta` **separadas y visibles**.

## 7 · Conflictos de negocio

El más frecuente: **en territorio disperso el terreno exige más asesores de los
que la venta paga**. Las dos reglas duras —zona ≥ umbral y zona recorrible— son
incompatibles donde el territorio es delgado.

No resolverlo por cuenta propia. Reportar por grupo: zonas que la venta paga vs
asesores que el terreno exige, con el detalle por zona. En el proyecto original
esto separó limpiamente lo urbano (sin problema) de lo rural (todo el conflicto).
