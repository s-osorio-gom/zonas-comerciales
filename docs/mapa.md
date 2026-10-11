# La capa visual

Qué se dibuja, cómo se colorea y cómo se verifica. El mapa es el producto: si no
se entiende de un vistazo, el análisis no sirvió.

> **Alcance.** Esta guía describe el mapa completo del proyecto original. El
> mapa de `ejemplo/mapa.py` implementa una parte: las dos capas (territorio y
> zona), zonas sin solapes por Voronoi de puntos disuelto por zona, coloreado por grafo, puntos por
> frecuencia, el panel de entrada con lo que quedó fuera y el QA visual con
> Playwright. No implementa la navegación por niveles, las migas de pan, las
> métricas que se recalculan, el rotulado ni las etapas de carga, y su radio de
> servicio es 1,4 × vecino con tope de 9 km, sin cierre morfológico.

## Dos capas con orígenes distintos

| Capa | Origen | Se dibuja como |
|---|---|---|
| **Territorio** | geometría oficial (municipios/sectores) disuelta por grupo | **borde grueso** |
| **Zona propuesta** | calculada desde sus propios puntos | **relleno** |

Separarlas visualmente es lo que permite responder "de quién es esto" y "quién lo
recorre" sin confundirlas.

Para la zona: Voronoi de los **puntos** (no de los centros de zona), disuelto por
zona y recortado al radio de servicio de sus puntos, con cierre morfológico y
re-recorte contra el teselado para que **no se solapen**. Con celdas por centro de
zona, un punto asignado a A pero más cerca del centro de B se dibuja dentro de B:
el mapa contradice la asignación sin que ningún chequeo de solapes lo vea. Nunca
hexágonos: un hexágono no es una zona, es una celda de agregación.

**Ajustar el radio de servicio al territorio.** Un radio pensado para ciudad
(0,85 × distancia al vecino, tope 6 km) parte una zona rural en cinco islas. Con
2,0 × vecino y tope 20 km la mediana baja a **una pieza** sin inflar las urbanas,
donde el vecino está a doscientos metros y el tope nunca se alcanza.

## Color

- **Grupo/distribuidor:** un color estable, ordenado por venta.
- **Zona:** coloreado de **grafo** sobre la adyacencia real, partiendo de un tono
  distinto por zona dentro de su grupo. Objetivo: **cero pares vecinos con el
  mismo color**.
- **Punto de venta:** siempre la misma semántica (frecuencia). Una semántica por
  nivel, nunca dos compitiendo.

## Navegación

```
País → Departamento → Distribuidor → Zona → Día → Punto
```

Con migas de pan que permitan volver a cualquier nivel. Las métricas se
**recalculan** con la selección; nada estático.

## El panel de entrada

Abrir el mapa y ver un país mudo es un desperdicio. El primer panel responde lo
que cualquiera pregunta primero:

- Total de puntos, venta mensual, grupos, zonas propuestas, asesores
- **Cobertura**: cuánta venta quedó dentro
- **Lo que quedó fuera** — puntos sin zona, venta residual, puntos sin coordenada.
  Un resumen que solo cuenta lo bueno no sirve para decidir.
- Las reglas con las que se calculó todo

## Etiquetas

- El nombre va **debajo** de su burbuja, a la distancia que marque su radio.
  Encima, oculta el dato: en el proyecto original un departamento parecía tener
  884 puntos y tenía **2.364**.
- Recortar nombres largos.
- **Suprimir el rótulo de lo que cae fuera del encuadre** conservando su marca.
  Un rótulo mutilado informa peor que ninguno.
- Anticolisión propia: reservar primero el sitio de las burbujas y de los paneles
  flotantes, y solo después repartir el texto.

## Carga

Esperar al primer `idle` del mapa, no a `load`. Mostrar **etapas** y una señal
discreta mientras la cámara se mueve: medio segundo de espera sin señal se lee
como que la aplicación se colgó.

## Protocolo de QA visual

Automatizable con Playwright. **No es opcional**: los defectos que importan solo
se ven mirando.

```
BUILD → ABRIR → CAPTURAR CADA NIVEL → REVISAR LA IMAGEN → CORREGIR → REPETIR
```

Qué buscar en cada captura, con ejemplos reales encontrados así:

| Qué revisar | Defecto real encontrado |
|---|---|
| ¿Las cifras del tooltip y del panel coinciden? | 546 vs 222 puntos bajo la misma etiqueta |
| ¿Hay `NaN` o campos vacíos? | "Visitas/semana: NaN" |
| ¿Los estados están bien marcados? | zona de $215,9 MM marcada "BAJO UMBRAL" |
| ¿Las etiquetas tapan datos? | el nombre del departamento ocultaba su número |
| ¿Los rótulos siguen siendo ciertos? | "días reales del rutero" cuando ya se calculaban |
| ¿Se distinguen las zonas? | todas del mismo color |
| ¿Hay filas duplicadas en los paneles? | un grupo con 3 bodegas multiplicaba su territorio |

Correr además: el recorrido completo en **tema claro y oscuro**, la prueba
**offline** (cero peticiones de red) y la prueba en **WebKit** además de Chromium.
