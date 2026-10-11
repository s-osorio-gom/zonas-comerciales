# Trampas

Errores que ya costaron entre veinte minutos y una hora de cómputo perdido cada
uno. Leer antes de tocar el motor.

## 1 · Llamar a un solver dentro de un bucle de decisión

**Síntoma:** el proceso corre media hora sin terminar y sin imprimir nada.

**Causa:** equilibrar días o podar puntos evalúa cientos de configuraciones por
zona. Con OR-Tools a 1–2 segundos por evaluación, una sola zona tarda minutos.

**Regla:** para **decidir** se usa `plan_semanal.tour_rapido()` — vecino más
cercano + 2-opt, microsegundos. El solver se reserva para la **ruta final que se
publica**.

Medido sobre cinco instancias de 22 paradas: el heurístico tarda **1–2 ms**;
OR-Tools con 2 s tarda **~2.000 ms** y encuentra rutas un 1,6–13,6 % más cortas
(mediana 7 %). Para comparar dos alternativas esa diferencia no cambia la
decisión; mil veces el tiempo, sí.

**Ojo con el solver:** el día es un camino **abierto** (empieza en una parada y
termina en otra). Si se le pide a OR-Tools un circuito cerrado y luego se le
quita el regreso, optimiza un tramo que nadie recorre: en el ejemplo, 83 de 115
días salían peores que el heurístico. `orden_optimo()` añade un depósito
ficticio a coste cero para resolver el camino abierto.

## 2 · Zonificar sin restringir la dispersión geográfica

**Síntoma:** las zonas cumplen el umbral pero el plan da días de 5.959 minutos.

**Causa:** la capacidad se controló por tiempo de atención, que es pequeño. Una
zona puede reunir el umbral con puntos repartidos en 400 km².

**Regla:** la capacidad incluye el desplazamiento estimado. `reglas.viaje_semana_min()`
usa Beardwood–Halton–Hammersley y `zonificar.Acumulador` lo mantiene al vuelo.

**Calibrar `MIN_POR_KM` contra rutas reales**, no dejar el valor de fábrica.
`zonificar.calibrar_viaje()` lo hace. En el proyecto original: correlación 0,955,
error mediano 0 %.

## 3 · Repartir los días equilibrando minutos de atención

**Síntoma:** el desplazamiento se come el 65 % de la jornada; 245 días imposibles.

**Causa:** si los días se equilibran solo por carga, cada día toca puntos de toda
la zona y el asesor la recorre entera cinco veces.

**Regla:** los días son **sectores geográficos**. Un asesor trabaja una parte del
territorio por día. `plan_semanal.repartir()` ya lo hace.

Solo con esto: días no viables de 245 → 99, desplazamiento del 50 % al 35 %.

## 4 · Confundir "no se puede recorrer" con "hay que mover visitas"

Equilibrar entre días **no reduce el trabajo total** de una zona. Si la zona
entera excede la capacidad semanal, hay que **soltar puntos** (podar) o
**partirla** si su venta da para dos que sigan pagando.

Orden correcto: reequilibrar → podar → reabsorber → partir lo que sobre de venta.

## 5 · Fijar el número de zonas de antemano

Falla en los dos extremos: en territorio urbano deja zonas gigantes que podrían
partirse; en disperso pide más de las que se pueden recorrer, y al disolver las
que no llegan al umbral se pierde la venta de sus puntos.

**Regla:** probar varios k y quedarse con el que más **venta** deja dentro de
zonas viables. A igualdad, más zonas (emplea más asesores).

Además, apuntar al máximo teórico deja cero holgura: con $3.406 MM y umbral de
$100 MM, 34 zonas exigirían que todas quedaran en $100,2 MM exactos y el
reequilibrio se bloquea. En el proyecto original un colchón de 12 % sobre el
umbral (`MARGEN_UMBRAL = 1.12`) lo resolvió — de 15 a 30 zonas en ese
distribuidor. Este motor obtiene la misma holgura de otra forma: `zonificar_grupo`
prueba varios k por debajo del máximo y se queda con el que más venta captura, así
que `MARGEN_UMBRAL` queda en `reglas.py` solo como referencia.

## 6 · Medir FPS en un entorno headless

Renderiza por software. Un perfil de CPU mostró **4.797 ms en código nativo
contra 28 ms de JavaScript**: los FPS bajos no probaban nada.

**Lo que sí importa** es cuánto **bloquea el hilo principal**, que es lo que
congela un navegador real. Medir bloqueos con un `requestAnimationFrame` que
registre huecos mayores de 50 ms.

En el proyecto original: bloqueos de **415–651 ms**, ocho veces en un movimiento
de tres segundos. Causa: cada micro-movimiento reconstruía todas las capas.

**Regla:** separar el zoom que alimenta la interfaz (barato, continuo) del que
dispara la reconstrucción de capas (caro, solo al cruzar umbrales o al parar).

## 7 · Enteros que viajan como texto en el GeoJSON

**Síntoma:** todo se pinta del color por defecto pese a que los datos son
correctos.

**Causa:** al recorrer con `iterrows()` los enteros llegan como `int` de Python.
Una comprobación `isinstance(v, np.integer)` no los reconoce y caen a `str()`.
MapLibre compara contra números y no encuentra coincidencia.

**Regla:** convertir explícitamente. Comprobar siempre `int` **y** `np.integer`.

## 8 · Colorear zonas con un contador

`color_idx = i % 8` por orden de lista deja zonas **vecinas** con el mismo color,
justo donde importa distinguirlas.

**Regla:** construir la adyacencia real (`sjoin` con `predicate="intersects"`) y
colorear partiendo de un tono distinto por zona dentro de su grupo, cambiándolo
solo si choca con una vecina. Resultado esperado: **cero pares vecinos con el
mismo color**.

## 9 · Retirar el indicador de carga cuando carga el estilo

`map.on("load")` avisa de que el **estilo** está listo; las teselas siguen
subiendo y el usuario ve una pantalla vacía y cree que se rompió.

**Regla:** esperar al primer `idle`, con temporizador de seguridad. Y **explicar
la espera** por etapas.

## 10 · Confiar en un solo motor de navegador

Chromium y WebKit (Safari) se comportan distinto en WebGL, memoria y protocolos
personalizados. Probar en ambos antes de entregar.

## 11 · Campos del rutero que parecen identificadores y no lo son

En el proyecto original, un campo llamado `Cod_Vendedor_Proveedor` contenía el
mismo valor constante —el nombre del fabricante— en sus 209.338 filas. **Verificar la cardinalidad de cualquier campo antes de
usarlo como clave.**

## 12 · Tablas de documento que son imágenes

Seis anexos traían el territorio pegado como imagen. Una extracción de texto los
devuelve vacíos **sin error**. En uno de ellos eso significaba leer 13 municipios
de un anexo que declaraba 67.

**Regla:** después de extraer, comprobar que cada documento produjo filas. Si un
documento sale en cero, mirar si tiene imágenes antes de darlo por vacío.
