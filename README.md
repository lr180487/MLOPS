# Práctica MLOps · Colab → GitHub → Pipeline → Modelo → Gradio / FastAPI / Dashboard

Proyecto de práctica que recorre un flujo MLOps completo sobre el dataset agroclimático
`data/datos.csv` (**1 000 observaciones** de **café, papa y uva** con `temperatura`, `humedad`,
`radiacion_solar`, `precipitacion`, `viento`, la **`ciudad` asociada a cada cultivo** —café ·
Chanchamayo, papa · Huancayo, uva · Ica— y la etiqueta `resultado ∈ {SI, NO}`). Las 50 primeras
filas son las observaciones originales; las 950 restantes las genera `generar_datos.py` a partir
de ellas (ver §2, *Procedencia del dataset*).

Incluye un **dashboard web (HTML + Tailwind CSS + JavaScript)** con métricas en vivo,
matriz de confusión y mapas de calor, alimentado en tiempo real por la API FastAPI, y —desde
la versión 2.0— una **arquitectura de servicio completa**: API REST modular + SSE + Swagger,
**Cache Manager de dos niveles** (LRU local + Upstash Redis), **persistencia en PostgreSQL**
con **fallback automático a SQLite** y **exportación de la base de datos** a CSV / XLSX / PDF /
SQLite desde la página de resultados (§5.4 y §9).

---

## 1. Estructura del proyecto

```
Practica_MLOPS/
│
├── generar_datos.py           # Amplía el dataset: 50 originales + N sintéticas calibradas → data/datos.csv (+ .meta.json)
├── procesar_datos.py          # Ingesta + validación + estadísticas → output/resultado.json
├── exportar_base_datos.py     # Exporta la base de datos a output/exportaciones/ (CSV/XLSX/PDF/JSON/SQLite) sin la API
│
├── data/
│   ├── datos.csv              # Dataset de entrada (1 000 filas: 50 originales + 950 generadas)
│   ├── datos.meta.json        # Procedencia del dataset (lo escribe generar_datos.py; lo lee procesar_datos.py)
│   └── datos_original_50.csv  # Copia intacta de las 50 observaciones originales
│
├── output/
│   ├── resultado.json         # Resumen del procesamiento (filas, válidos, inválidos, promedios…)
│   ├── matriz_confusion.png   # Generado por el notebook
│   └── heatmap_correlacion.png
│
├── logs/
│   ├── ejecucion.log          # Log de procesar_datos.py
│   └── api.log                # Log de la API (predicciones, feedback, simulador)
│
├── models/
│   ├── modelo.joblib          # Pipeline scikit-learn serializado (artefacto que consumen Gradio/FastAPI)
│   └── metricas.json          # Métricas de entrenamiento, matriz de confusión, ROC, coeficientes, correlación
│
├── notebooks/
│   └── entrenamiento.ipynb    # Entrena el modelo y genera los artefactos anteriores
│
├── app/
│   ├── gradio_app.py          # Interfaz Gradio: predicción, métricas, matriz de confusión, mapas de calor, monitoreo
│   │                          #   + página /resultados para ver y descargar output/resultado.json
│   ├── preview_gradio.png     # Captura de la interfaz Gradio (panel principal)
│   └── preview_gradio_resultados.png  # Captura de la página /resultados en Gradio
│
├── api/                       # API REST (FastAPI) modular · v2.0 (ver §9)
│   ├── main.py                # create_app(): lifespan, routers, SSE, estáticos del dashboard
│   ├── config.py              # Settings: variables de entorno / .env (fallbacks incluidos)
│   ├── deps.py                # AppContext (db, cache, predictor, monitor, bus, simulador)
│   ├── schemas.py             # Modelos Pydantic de entrada/salida
│   ├── core/
│   │   ├── database.py        # PostgreSQL con fallback automático a SQLite
│   │   ├── cache.py           # CacheManager: L1 LRU en memoria + L2 Upstash Redis (REST)
│   │   ├── model.py           # Predictor (carga/recarga de modelo.joblib, hash, métricas)
│   │   ├── monitor.py         # Métricas en vivo: ventana móvil, acumulado, latencia, deriva
│   │   ├── events.py          # EventBus asíncrono → SSE
│   │   ├── service.py         # PredictionService: caché → modelo → persistencia → eventos
│   │   ├── simulator.py       # Simulador de tráfico (start/stop/burst)
│   │   ├── export.py          # Exportación de la base de datos a CSV / XLSX / PDF / JSON / SQLite (y copias estáticas)
│   │   ├── analisis.py        # Analizador: regresión, clasificación, clustering, anomalías y series temporales (§5.5)
│   │   └── publico.py         # URLs públicas de la API → escribe dashboard/api-base.js al arrancar
│   └── routers/               # health, predictions, feedback, metrics, stream, cache, simulator,
│                              # model, system, data, analisis, pages, legacy (alias deprecados)
│
├── storage/                   # (generado) mlops.sqlite3 cuando no hay PostgreSQL — ignorado por git
│
├── dashboard/                 # Dashboard HTML + Tailwind CSS (CDN) + JavaScript (modo claro)
│   ├── index.html             # Estructura + config de Tailwind + clases de componente; enlaza script.js
│   ├── script.js              # Lógica: SSE, Chart.js, heatmaps en <canvas>, formulario, tabs
│   ├── resultados.html        # Página /resultados: visor + descarga de output/resultado.json
│   ├── resultados.js          # Lógica de la página de resultados (árbol JSON, tabla, descargas)
│   ├── analisis.html          # Página /analisis: analizar los datos con varios tipos de algoritmos
│   ├── analisis.js            # Lógica de la página de análisis (controles, llamadas, gráficos Chart.js, tablas)
│   ├── apibase.js             # Localiza la API cuando la página se abre fuera de ella (aviso + modo estático)
│   ├── api-base.js            # Generado por la API al arrancar: URLs públicas (no editar)
│   ├── vendor/chart.umd.min.js# Respaldo local de Chart.js por si el CDN no está disponible
│   ├── preview.png            # Captura del dashboard
│   ├── preview_resultados.png # Captura de la página /resultados
│   ├── loader.js              # Pantalla de arranque: logo con anillo giratorio durante 5 s (las tres páginas)
│   ├── sonidos.js             # Sonidos sincronizados con cada acción + reverberación configurable (Web Audio) + sección «Sonidos»
│   ├── animaciones.js         # Animaciones de las gráficas (plugins Chart.js, transiciones de los mapas de calor, contadores, barras y tarjetas)
│   ├── preview_interpretacion.png # Captura de la sección «Interpretación de los resultados»
│   └── preview_analisis.png   # Captura de la página /analisis
│
├── requirements.txt
├── .env.example               # Todas las variables de entorno documentadas (copiar a .env)
├── README.md
└── .gitignore
```

## 2. Flujo MLOps

### Diccionario de datos (`data/datos.csv`)

| Columna | Tipo | Descripción |
|---------|------|-------------|
| `id` | entero | Identificador de la observación |
| `cultivo` | categórica | `cafe`, `papa` o `uva` |
| `ciudad` | categórica | **Variable predictora asociada al cultivo**: `chanchamayo` (café), `huancayo` (papa), `ica` (uva). Si el CSV no la trae, `procesar_datos.py`, el notebook, la API y Gradio la deducen del cultivo con esa regla; si la trae con otro valor, el pipeline la corrige y lo anota en `resultado.json` (`ciudad_inconsistentes_corregidas`). |
| `temperatura` | numérica | °C |
| `humedad` | numérica | % de humedad relativa |
| `radiacion_solar` | numérica | MJ/m² |
| `precipitacion` | numérica | mm |
| `viento` | numérica | km/h |
| `resultado` | objetivo | `SI` / `NO` |

### Procedencia del dataset (`generar_datos.py`)

El dataset original tiene **50 observaciones** (`data/datos_original_50.csv`). Para ejercitar el
flujo con más volumen, `generar_datos.py` lo amplía a **1 000 filas** conservando las 50
originales (ids 1–50) y añadiendo 950 sintéticas (ids 51–1000) **calibradas con los datos
reales**, por cultivo:

1. Las cinco variables climáticas se muestrean de una normal multivariante ajustada a cada
   cultivo (medias y covarianza de sus filas originales, con un ligero encogimiento de la
   covarianza para estabilizarla) y se recortan a rangos físicamente plausibles.
2. `ciudad` se asigna con la regla cultivo → ciudad.
3. `resultado` se sortea con una regresión logística ajustada a las 50 filas originales, cuyo
   intercepto se calibra por cultivo para que las tasas de SI sintéticas igualen las originales
   (café ≈ 0.38, uva ≈ 0.22, papa ≈ 0.05). Así se preserva la relación clima ↔ resultado.
4. Se escribe `data/datos.meta.json` con la procedencia (`origen`, filas originales / generadas,
   semilla). `procesar_datos.py` la copia en `resultado.json` (`origen_datos`) y la página de
   resultados la declara en *Calidad de los datos* y en *Límites*: **son datos generados para
   probar el flujo, no mediciones nuevas**.

```bash
python generar_datos.py --n 1000 --semilla 42          # reproducible: misma semilla → mismo CSV
python generar_datos.py --n 5000 --salida data/datos.csv
python generar_datos.py --n 300 --sin-originales        # solo filas sintéticas
# volver al dataset original de 50 filas:
cp data/datos_original_50.csv data/datos.csv && rm -f data/datos.meta.json
```

Tras cambiar el dataset hay que repetir los pasos 1 (procesar) y 2 (entrenar) de §4 y reiniciar
la API y Gradio, que cargan datos y modelo al arrancar (`POST /api/model/reload` recarga el
modelo y el dataset de referencia sin reiniciar la API).

> **Nota sobre `ciudad`:** en este dataset cada cultivo se asocia a una única ciudad, de modo que
> `ciudad` y `cultivo` son perfectamente colineales. El modelo (regresión logística con
> regularización L2) la incorpora como una categórica más con one-hot encoding y reparte el
> efecto conjunto entre los coeficientes `cultivo_*` y `ciudad_*` (en `metricas.json` ambos
> pares resultan idénticos). Por eso el dashboard presenta cultivo y ciudad **en pareja**.

```
                         ┌─────────────────┐
                         │  GOOGLE COLAB   │
                         │ entrenamiento   │
                         └────────┬────────┘
                                  ▼
                         ┌─────────────────┐
                         │    datos.csv    │
                         └────────┬────────┘
                                  ▼
                         ┌─────────────────┐
                         │     GITHUB      │
                         │ control versión │
                         └────────┬────────┘
                                  ▼
                       ┌─────────────────────┐
                       │  procesar_datos.py  │
                       │       Pandas        │
                       └─────────┬───────────┘
                    ┌────────────┴────────────┐
                    ▼                         ▼
             resultado.json             ejecucion.log
                    │
                    ▼
             ┌──────────────────┐
             │ entrenamiento    │
             │ .ipynb           │
             │ Scikit-Learn     │
             └────────┬─────────┘
                      ▼
             ┌──────────────────┐
             │ modelo.joblib    │
             │ + metricas.json  │
             └────────┬─────────┘
          ┌───────────┼───────────┐
          ▼           ▼           ▼
   ┌───────────┐ ┌───────────┐ ┌──────────────────────┐
   │  GRADIO   │ │  FASTAPI  │ │  DASHBOARD (HTML +   │
   │  Web UI   │ │  REST API │─│  Tailwind + JS, SSE) │
   └─────┬─────┘ └─────┬─────┘ └──────────┬───────────┘
         └─────────────┴──────────────────┘
                       ▼
                  ┌─────────┐
                  │ USUARIO │
                  └─────────┘
```

### 2.1 Arquitectura de servicio (v2.0)

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                     DASHBOARD  (HTML + Tailwind + JS)                        │
│         index.html · resultados.html              ◄──── SSE /api/stream      │
└───────────────┬───────────────────────────────┬──────────────────────────────┘
                │ REST /api/*                   │ Swagger /docs · ReDoc /redoc
                ▼                               ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                               FASTAPI  (api/)                                │
│  ┌───────────┐  ┌──────────┐  ┌──────────┐  ┌────────────────────────────┐   │
│  │ Predictor │  │ Metrics  │  │ Feedback │  │ Exportación (CSV·XLSX·PDF) │   │
│  └─────┬─────┘  └────┬─────┘  └────┬─────┘  └─────────────┬──────────────┘   │
│        └─────────────┴─────────────┴──────────────────────┘                  │
│                                    ▼                                         │
│  ┌──────────────────────── CACHE MANAGER ─────────────────────────────────┐  │
│  │  L1 · LRU en memoria (TTL, evicción)  ──►  L2 · Upstash Redis (REST)    │  │
│  └────────────────────────────────────────────────────────────────────────┘  │
│                                    ▼                                         │
│  ┌──────────────────────── PERSISTENCIA ──────────────────────────────────┐  │
│  │  PostgreSQL  (predicciones, feedback)                                  │  │
│  │  ⤷ fallback automático: SQLite (storage/mlops.sqlite3)                 │  │
│  └────────────────────────────────────────────────────────────────────────┘  │
│                                    │  EventBus                               │
└────────────────────────────────────┼─────────────────────────────────────────┘
                                     ▼  SSE (prediccion · feedback · metricas)
                                 DASHBOARD
```

## 3. Instalación

```bash
git clone <tu-repositorio> Practica_MLOPS
cd Practica_MLOPS
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## 4. Ejecución paso a paso

| Paso | Comando (desde la raíz) | Produce |
|------|--------------------------|---------|
| 0. (opcional) Ampliar dataset | `python generar_datos.py --n 1000 --semilla 42` | `data/datos.csv` (50 originales + sintéticas), `data/datos.meta.json`, copia `data/datos_original_50.csv` |
| 1. Procesar datos | `python procesar_datos.py` | `output/resultado.json`, `logs/ejecucion.log` |
| 2. Entrenar | `jupyter nbconvert --to notebook --execute --inplace notebooks/entrenamiento.ipynb` (o abrirlo en Colab/Jupyter) | `models/modelo.joblib`, `models/metricas.json`, `output/*.png` |
| 3. API + Dashboard | `uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload` | http://localhost:8000 (dashboard) · `/resultados` · `/analisis` · `/docs` (Swagger) |
| 4. Gradio | `python app/gradio_app.py` | http://localhost:7860 (panel con 6 pestañas, ver §5b) |
| (opcional) PostgreSQL | `export DATABASE_URL=postgresql://usuario:clave@localhost:5432/mlops` antes del paso 3 | Persistencia en PostgreSQL (§9.3) |
| (opcional) Upstash Redis | `export UPSTASH_REDIS_REST_URL=… UPSTASH_REDIS_REST_TOKEN=…` antes del paso 3 | Caché distribuida L2 (§9.2) |

Claves de `output/resultado.json` (paso 1): `fecha_ejecucion`, `archivo_origen`, `origen_datos`
(procedencia copiada de `data/datos.meta.json`, o `null` si no existe), `filas_totales` /
`filas_validas` / `filas_invalidas`, `columnas`, `columnas_categoricas`, `columnas_numericas` (por
variable: válidos, inválidos, nulos originales, promedio, **mediana**, **desviación**, mín, máx),
`promedio_general`, `distribucion_resultado`, `distribucion_cultivo`, `promedio_por_cultivo`,
`tasa_si_por_cultivo`, **`conteo_cultivo_resultado`** (SI/NO por cultivo), **`promedio_por_resultado`**
(promedio de cada variable en los casos SI y en los NO), `ciudad_por_cultivo`,
`ciudad_inconsistentes_corregidas`, `distribucion_ciudad`, `promedio_por_ciudad`, `tasa_si_por_ciudad`
y las claves de **relación con el SI** (`analizar_relacion_si`): **`tasa_si_por_tercio`** (para cada
variable, tasa de SI en los tercios bajo / medio / alto con sus límites), **`tasa_si_por_tercio_cultivo`**
(lo mismo dentro de cada cultivo), **`rango_tipico_si_por_cultivo`** (percentiles 25–75 de cada variable
entre los casos SI de cada cultivo, con `n_si`), **`promedio_por_cultivo_resultado`** (promedios SI/NO
por cultivo) y `correlacion_con_si` (correlación punto-biserial de cada variable con el resultado).
Las claves en negrita alimentan la **interpretación automática** de la página de resultados (§5.4).

> Sin variables de entorno **todo funciona igualmente en local y sin conexión**: SQLite,
> caché LRU en memoria. Las variables se documentan en `.env.example` y en §9.4.

> **Nota sobre el modelo:** como `resultado` es binaria (SI/NO) el notebook entrena una
> **`LogisticRegression`** (modelo lineal de clasificación) en lugar de `LinearRegression`
> (pensada para objetivos continuos). Así se obtienen probabilidades, matriz de confusión,
> precisión/recall/F1 y curva ROC, que son exactamente lo que muestra el dashboard.

## 5. Dashboard (HTML + Tailwind CSS + JavaScript)

Abre **http://localhost:8000** una vez levantada la API.

### 5.1 Cómo están integrados HTML + Tailwind (CDN) + script.js

```
index.html ──<script src>──▶ https://cdn.tailwindcss.com/3.4.17     (Tailwind CSS, CDN oficial)
           ──<script>──────▶ tailwind.config = { … }                 (paleta, sombras, animaciones)
           ──<style type="text/tailwindcss">──▶ @layer components    (.card .kpi .tab .badge-* …)
           ──<script src>──▶ https://cdn.jsdelivr.net/npm/chart.js   (Chart.js; respaldo: vendor/)
           ──<script src defer>──▶ script.js                          (consume /api/* y pinta todo)
```

* **Tailwind se carga desde el CDN oficial** con la versión fijada (`3.4.17`), por lo que
  **no hace falta Node ni ningún paso de compilación**: basta con servir la carpeta.
* La configuración del tema (`tailwind.config`) y las **clases de componente** (`.card`,
  `.kpi`, `.pill`, `.badge-si`, `.tab-active`, `.cm-cell`, `.btn-primary`, `.table`,
  `.log-view`, `.drift-bar`…) viven en el `<head>` de `index.html`. El CDN de Tailwind procesa
  el bloque `<style type="text/tailwindcss">`, que admite `@layer` y `@apply`.
* **`script.js`** se carga con `defer` al final del `<body>` y aplica esas mismas clases al
  generar filas, badges, botones y estados; el CDN de Tailwind observa el DOM (MutationObserver)
  y genera al vuelo las utilidades que el JS añada dinámicamente.
* La API sirve los archivos de `dashboard/` en la raíz: `/index.html`, `/resultados.html`,
  `/script.js`, `/resultados.js` y `/vendor/*`, además de `/output/*` para las imágenes del
  notebook. **`/` y `/dashboard` redirigen (307) a `/index.html`**, y `/resultados` a
  `/resultados.html`. Los enlaces entre páginas son relativos (`index.html` ↔ `resultados.html`),
  así que la carpeta también funciona publicada como sitio estático.

> El CDN de Tailwind está pensado para desarrollo y prototipos (muestra un aviso en consola).
> Para producción se recomienda compilar el CSS con Tailwind CLI; el HTML no cambiaría salvo
> sustituir el `<script>` del CDN por un `<link rel="stylesheet">`.

### 5.2 Diseño

Tema **claro profesional**: fondo gris-azulado (`#f6f8fb`), tarjetas blancas con borde
sutil y sombra ligera, tipografía Inter / JetBrains Mono, color primario índigo (`brand-600`)
y semántica de color consistente (verde = acierto/OK, rojo = error/FP-FN, violeta = clase SI,
ámbar = advertencia/pendiente). Layout responsive: 8 KPIs en fila en pantallas XL, 4 en
tablet y 2 en móvil; los mapas de calor se redibujan al cambiar el tamaño.

### 5.3 Secciones

> El dashboard está redactado para el usuario final: no muestra rutas de la API, nombres de
> archivos ni detalles de infraestructura (esos viven en esta documentación y en `/docs`).
> Los textos técnicos de los avisos de conexión también se simplificaron.

| Sección | Qué muestra | Fuente |
|---------|-------------|--------|
| **KPIs en vivo** | Predicciones totales, throughput/min, accuracy, F1, precisión, recall, tasa de SI, tiempo de respuesta (p95 / p50), pendientes de feedback | `GET /api/metrics/live` + SSE |
| **Serie temporal** | Evolución de accuracy / F1 / recall / tasa SI sobre una ventana móvil de 50 predicciones etiquetadas | SSE `/api/stream` |
| **Matriz de confusión** | 4 vistas: *Vivo* (ventana móvil), *Acumulado* (desde el arranque), *Hold-out* y *CV 5×* (entrenamiento). Celdas coloreadas por proporción | `/api/metrics/live`, `/api/metrics/training` |
| **Mapa de calor · superficie de decisión** | P(SI) del modelo sobre una rejilla 2-D (elige cultivo —con su ciudad— y par de variables). Superpone los puntos reales y la isolínea del umbral 0.5 | `GET /api/heatmap/probability` |
| **Mapa de calor · correlación** | Matriz de Pearson de las variables + objetivo binarizado | `models/metricas.json` |
| **Probar el modelo** | Formulario con **Cultivo y Ciudad enlazados** (al cambiar uno se ajusta el otro: café · Chanchamayo, papa · Huancayo, uva · Ica) + sliders → `POST /api/predictions`, y botones SI/NO → `POST /api/feedback` (cierra el ciclo y actualiza la matriz en vivo) | API |
| **Deriva de datos** | z-score de la media reciente vs. la media de entrenamiento por variable (ámbar > 1σ, rojo > 2σ) + predicciones por cultivo | `/api/metrics/live` |
| **Coeficientes / ROC / Ficha** | Importancia de variables (log-odds, incluidos `cultivo = …` y `ciudad = …`), curva ROC out-of-fold y ficha del modelo (variables, ciudad por cultivo) con las imágenes del notebook | `/api/metrics/training` |
| **Flujo de predicciones** | Tabla en vivo de eventos (cultivo, **ciudad**, variables, P(SI), predicción, real) con controles del simulador | SSE |
| **Resumen del procesamiento** | Contenido de `output/resultado.json` (promedios por cultivo · ciudad) + enlace a la página de resultados | `GET /api/data/summary` |

**Pantalla de arranque.** Las tres páginas cargan `dashboard/loader.js` en el `<head>` (antes de Tailwind) y llevan un contenedor `#app-loader` justo después de `<body>`: al abrir la página se muestra el logo con un anillo que gira a su alrededor durante **5 segundos** y después se desvanece y se retira del documento (sin dependencias, con los estilos inyectados desde el propio script para verse desde el primer fotograma; respeta `prefers-reduced-motion`). La duración (`DURACION_MS`) y la opción de mostrarlo solo una vez por sesión (`SOLO_PRIMERA_VEZ`) se ajustan al inicio del archivo. La API lo sirve en `/loader.js`.

**Caché de los scripts del dashboard.** `api/routers/pages.py` sirve los HTML con las referencias a los scripts locales **versionadas** (`sonidos.js?v=<fecha de modificación>-<tamaño>`, calculado en cada petición) y envía todos los recursos del dashboard con `Cache-Control: no-store` (más `Pragma`, `Expires`, `CDN-Cache-Control` y `Surrogate-Control`). Así, cualquier edición de un `.js` cambia su URL y ni el navegador ni los proxies de vista previa —que cachean los `.js` por extensión aunque se envíe `no-cache`— pueden seguir entregando una copia antigua. Los archivos HTML del disco no se modifican, de modo que abiertos como estáticos siguen funcionando igual.

**Sonidos sincronizados con cada acción, con reverberación.** `dashboard/sonidos.js` (cargado en las tres páginas, servido en `/sonidos.js`) añade sonidos de interfaz sintetizados con Web Audio —sin archivos de audio ni red— y una **sección «Sonidos»** propia en cada página (tarjeta `#sec-sonidos` al final del contenido, enlazada desde «🔊 Sonidos» en la cabecera, que además refleja si están activados). Una **capa de acciones** escucha `click` / `submit` / `change` en toda la página (también en los elementos creados después) y elige el sonido según el tipo de control: enviar un formulario o iniciar un proceso (`enviar`), pestañas y desplegables (`pestana`), interruptores y casillas (`activar` / `desactivar`), listas (`seleccion`), deslizadores (`ajuste`), los demás botones (`clic`), enlaces a otra página (`navegar`; la navegación se retrasa 180 ms para que se oiga) y el botón 🎲 (`dado`). Los scripts de página añaden los sonidos de resultado con `window.SONIDOS.reproducir(nombre, grupo)` a través de un ayudante `son()` que no falla si el módulo no está: predicción `si` / `no`, feedback registrado, proceso o análisis terminado (`exito`), descarga lista (`descarga`), texto copiado (`copiado`), errores y avisos (`error` / `aviso`), fin de la pantalla de carga (`inicio`) y predicciones en vivo (`flujo`, desactivado por defecto y limitado a ~6 por segundo). Un elemento puede forzar su sonido con `data-sonido="nombre"` o silenciar el automático con `data-sonido="ninguno"` (se usa cuando el sonido lo pone el resultado: botones de feedback SI / NO, «Copiar», interruptor del simulador); los eventos generados por código (`isTrusted = false`) no suenan y dos sonidos de interacción nunca se amontonan en menos de 60 ms. La sección permite activar/desactivar, volumen, tema de sonido (suave / campana / digital), **reverberación** por convolución con una respuesta de impulso generada en el momento (ruido estéreo con caída exponencial, primeras reflexiones y filtro según el brillo) ajustable en cantidad, cola (0,2–6 s), retardo inicial y brillo, botones «Probar», y elegir en qué grupos de acciones suena (10 grupos con ▶ para escuchar cada uno y «Todas sí / no»). Todo se guarda en `localStorage` (`mlops.sonidos.v2`; de la versión anterior se migran volumen, tema y reverberación). Los navegadores solo permiten audio tras un gesto del usuario: los sonidos pedidos antes del primer clic se ignoran en silencio y los pedidos mientras el audio arranca se encolan y suenan enseguida. Cada sonido reproducido emite en `document` el evento `sonidos:reproducido` con `{nombre, evento}`, útil para pruebas.

**Animaciones de las gráficas.** `dashboard/animaciones.js` (cargado en las tres páginas, servido en `/animaciones.js`) hace que cada gráfica «entre» en lugar de aparecer de golpe, y lo hace **cuando se ve**: nada se anima debajo de la pantalla de arranque ni fuera de la ventana; cada gráfica reproduce su entrada la primera vez que entra en pantalla al desplazarse, y la curva ROC lo hace al abrir su pestaña. En el panel: las **barras** (importancia de variables, predicciones por cultivo, gráficas del análisis) crecen desde cero una tras otra; las **líneas** (métricas en vivo, curva ROC) se trazan de izquierda a derecha punto a punto; los **puntos** de las gráficas de dispersión brotan con un pequeño rebote; las series en vivo llevan un **pulso luminoso** en su último valor que se detiene si la pestaña del navegador pasa a segundo plano; los dos **mapas de calor** se revelan con un barrido diagonal la primera vez y después se funden suavemente de un estado al siguiente (al cambiar cultivo, variables o umbral), sin transición en los redibujados por cambio de tamaño; los **indicadores numéricos** (tarjetas superiores, matriz de confusión) cuentan desde el valor anterior hasta el nuevo con un pequeño realce, y las **barras de deriva** se deslizan a su nueva posición en lugar de redibujarse. En Resultados, las barras de distribución y de la tabla de variables se llenan al entrar en pantalla, y las tarjetas y conclusiones de las tres páginas aparecen escalonadas. Las actualizaciones en vivo mantienen una transición corta (650 ms) para que la gráfica no «salte». Si el sistema tiene activado **«reducir movimiento»**, todo se muestra directamente en su estado final sin animaciones ni pulso. El módulo se apoya en dos plugins de Chart.js (`mlopsAnimaciones`, que se aplica a todas las gráficas, y `mlopsPulso`, que se activa por gráfica con `plugins.mlopsPulso`) y expone `window.ANIM` (`contar`, `pop`, `transicionCanvas`, `barrasAlVer`, `escalonar`, `trasLoader`) para los scripts de página; no usa librerías adicionales.

### 5.4 Página de resultados (`/resultados`)

Página independiente (`dashboard/resultados.html` + `resultados.js`, mismo tema claro y misma
integración con el CDN de Tailwind) para **ver y descargar `output/resultado.json`**, accesible
desde el botón **📄 Resultados (JSON)** de la barra superior del dashboard o directamente en
`http://localhost:8000/resultados.html` (`/resultados` redirige ahí; el enlace **Dashboard** de
su barra vuelve a `index.html`).

| Bloque | Contenido |
|--------|-----------|
| KPIs | Filas totales / válidas / inválidas, resultado SI / NO, cultivos con su ciudad (café · Chanchamayo, papa · Huancayo, uva · Ica) y fecha de ejecución. |
| **Interpretación de los resultados** | Lectura en lenguaje sencillo generada **automáticamente** a partir de las cifras actuales (se actualiza al reprocesar). **Vista compacta por defecto**: resumen «en pocas palabras», **cinco conclusiones clave** numeradas por importancia con su «evidencia» numérica (brecha entre cultivos, variable climática más ligada al SI medida por tercios, variables que aportan poco, efectos que cambian según el cultivo, por qué el acierto global engaña) y **«Empieza por aquí»** con las cuatro recomendaciones de prioridad alta. El botón **«Ver la interpretación completa»** despliega la **lectura detallada** en nueve bloques — calidad de los datos, balance SI/NO, cultivos y ciudades, condiciones climáticas, perfil climático por cultivo, **qué distingue a los casos SI** (tasa de SI en los tercios bajo / medio / alto de cada variable con mini-barras; relación fuerte ≥ ×2.5, moderada ≥ ×1.6, leve ≥ ×1.25, sin efecto por debajo; detecta cuando «destaca el tercio medio»), **condiciones típicas de los SI en cada cultivo** (rango p25–p75 y tercio que más separa; solo con ≥ 30 SI, aviso entre 10 y 29), qué dice el modelo (hold-out, CV, falsas alarmas por SI detectado y cuánto multiplica la eficacia de una revisión frente al azar; vía `GET /api/metrics/training` o `models/metricas.json` en modo estático) y límites de las conclusiones — y **todas las recomendaciones** (16) priorizadas alta / media / baja en cuatro grupos: usar los resultados hoy, mejorar los datos, mejorar el modelo y seguimiento continuo, cada una con el motivo numérico. Todo se calcula en el navegador (`resultados.js`) a partir de `resultado.json` y las métricas del modelo, sin texto fijo: cambia con el dataset. |
| Archivo de resultados | Botones **⬇ JSON** (`/download/resultado.json`, `Content-Disposition: attachment`), **⬇ CSV (tabla)** (estadísticas por variable), copiar al portapapeles, recargar y **volver a procesar los datos** desde el navegador (`POST /api/data/reprocess`, ejecuta `procesar_datos.py`). |
| Estadísticas por variable | Válidos, inválidos, mín / promedio / máx, posición del promedio en el rango y promedio por cultivo. |
| Distribuciones | Barras de `resultado` (SI/NO) y de `cultivo · ciudad` con su tasa de SI; chips de `ciudad` (variable del modelo) con conteo y tasa de SI (`distribucion_ciudad`, `tasa_si_por_ciudad`). |
| Contenido completo | **Árbol navegable** (nodos plegables) y **JSON con resaltado de sintaxis**. |

![Página de resultados](dashboard/preview_resultados.png)

![Interpretación automática de los resultados](dashboard/preview_interpretacion.png)

**Tiempo real:** el navegador se suscribe a `GET /api/stream` (Server-Sent Events). Si el
stream no está disponible, el dashboard cae automáticamente a *polling* cada 3 s.

**Simulador de tráfico:** la API incluye un generador de observaciones sintéticas
(filas reales + ruido gaussiano, con ~5 % de ruido de etiqueta) que llegan ya etiquetadas
para que las métricas se muevan. Desde la barra del dashboard puedes pausarlo, cambiar la
velocidad o lanzar una ráfaga (`POST /api/simulator`).

**Descargar base de datos** (sección de la misma página): tarjetas por tabla —dataset,
predicciones persistidas, feedback y estadísticas de `resultado.json`— con
botones **CSV / XLSX / PDF** (+ JSON) y, arriba a la derecha, la **base de datos completa** en
XLSX multi-hoja, PDF por secciones, ZIP de CSV o **archivo SQLite**. Las descargas se hacen con
`fetch` + Blob desde la propia página (mensaje de estado con tamaño y tiempo, error legible si la API
no responde y enlace alternativo «abrir en pestaña nueva»). El catálogo (filas, columnas, backend) se
lee de `GET /api/data/exports`.

**Si abres el HTML fuera de la API** (visor de archivos del workspace, `file://`, Live Server…)
la página no puede usar rutas relativas como `/download/...`. Para eso existe
`dashboard/apibase.js`, que se carga en las dos páginas y busca la API en este orden:
origen de la página → `?api=https://host:8000` (se recuerda en `localStorage`) →
`dashboard/api-base.js` (la API lo escribe al arrancar con sus URLs públicas: `PUBLIC_URL`, la URL
del sandbox E2B si existe, `http://localhost:8000`) → `http://localhost:8000`. Según lo que encuentre:

| Situación | Comportamiento |
|-----------|----------------|
| Página servida por la API (`http://localhost:8000/resultados`) | Normal, sin aviso |
| Página abierta fuera, API localizada | Aviso azul con la URL usada y enlace «Abrir esta página desde la API ↗»; todas las llamadas, SSE y descargas van a esa URL (CORS abierto) |
| Página abierta fuera, API no localizada | Aviso naranja con un campo para escribir la URL; la página de resultados entra en **modo estático**: lee `../output/resultado.json` y ofrece las **copias estáticas** de `output/exportaciones/` |

Las copias estáticas (`output/exportaciones/*.csv|xlsx|pdf|json`, `base_datos.*` e `index.json`)
las escribe la API al arrancar (`STATIC_EXPORTS=true`), `POST /api/data/exports/static` las
regenera y también se generan sin API con:

```bash
python exportar_base_datos.py            # todo → output/exportaciones/
python exportar_base_datos.py --solo predicciones.xlsx base_datos.pdf
```

### 5.5 Página de análisis (`/analisis`): los datos con varios tipos de algoritmos

`dashboard/analisis.html` + `analisis.js` permiten **analizar el mismo dataset con cinco tipos de
algoritmos**, comparar varios algoritmos de cada tipo con sus métricas y leer una interpretación
automática. Los cálculos los hace la API con scikit-learn (y statsmodels para las series) en
`api/core/analisis.py`; la página elige el tipo, ajusta los parámetros, llama a `/api/analisis/*`
y dibuja los resultados con Chart.js. Al arrancar, la API **precalcula** los cinco análisis por
defecto en segundo plano (`ANALISIS_PRECALCULAR=1`) y cachea cada combinación de parámetros
(clave = huella del dataset + parámetros), así que repetir un análisis es inmediato.

| # | Tipo | Pregunta que responde | Algoritmos comparados | Métricas | Aquí se aplica a… |
|---|------|-----------------------|-----------------------|----------|-------------------|
| 1 | **Regresión** (supervisado) | predecir un valor numérico | regresión lineal · Ridge · Random Forest Regressor · Gradient Boosting Regressor | MAE · RMSE · R² (hold-out 25 % + validación cruzada 5×) | predecir una variable climática a partir de las otras cuatro y del cultivo; referencia: «predecir siempre el promedio» |
| 2 | **Clasificación** (supervisado) | asignar una categoría | regresión logística · árbol de decisión · Random Forest · SVM · Gradient Boosting | precision · recall · F1 · ROC-AUC (+ accuracy, matriz de confusión, curvas ROC, importancia por permutación) | `resultado` SI/NO (binario) o `cultivo` (3 clases, métricas macro); referencia: «decir siempre la clase mayoritaria» |
| 3 | **Clustering** (no supervisado) | descubrir grupos | K-Means · DBSCAN · jerárquico (ward/average/complete/single) | silhouette · Davies–Bouldin (+ coincidencia con cultivos: índice de Rand ajustado y pureza) | agrupar los registros solo por su clima (variables estandarizadas, elegibles) y comprobar si «redescubren» los cultivos; barrido de k (codo + silhouette) y mapa PCA 2D |
| 4 | **Detección de anomalías** | encontrar registros inusuales | Isolation Forest · Local Outlier Factor · desviación estándar (|z| > umbral) | precision · recall · F1 **solo si hay anomalías etiquetadas** → opción de **inyectar N anomalías artificiales** (valores a > 4 σ) para evaluarlas | registros con clima atípico: top 15 por método, variable que más se desvía, coincidencias entre métodos, anomalías por cultivo |
| 5 | **Series temporales** | tendencia y pronóstico | media móvil · suavizado exponencial simple · Holt (nivel + tendencia) · ARIMA(p,d,q) · regresión con variables temporales (tendencia + retardos + estacionalidad) | MAE · RMSE · MAPE sobre el último tramo reservado (10–30 %); referencias: último valor y promedio | tres fuentes: **actividad real del servicio** (predicciones por minuto/10 min/hora/día: conteo, tasa de SI, probabilidad media o latencia), una **variable del dataset en orden de registro** (promediada por bloques; el CSV no tiene fecha y la página lo advierte) o una **serie simulada** con tendencia + estacionalidad + ruido calibrada con el dataset |

Cada resultado incluye una **lectura automática** en lenguaje sencillo (qué algoritmo ganó, cuánto
mejora la referencia simple, qué variables pesan, qué limita la conclusión), una lista de
**recomendaciones priorizadas** (alta / media / baja, con la cifra que las justifica; las genera
`Analizador` en el campo `recomendaciones` de cada respuesta y dependen del resultado: p. ej. «usar
el clasificador como filtro, no como decisión» si la precision es < 50 %, «repetir con k = N» si el
barrido de K-Means sugiere otro número de grupos, «no apoyar decisiones en estos pronósticos» si
ningún método supera la referencia simple) y un glosario con la explicación de cada métrica y
algoritmo. Como el resto del dashboard, la página no muestra rutas,
archivos ni detalles técnicos del servicio; sin conexión con la API muestra las tarjetas y un aviso
(los cálculos necesitan el servicio).

Notas sobre los resultados con el dataset de 1 000 filas: en clasificación SI/NO la logística y la
SVM (con `class_weight="balanced"`) obtienen el mejor F1 (≈ 0.43–0.46) mientras Random Forest y
Gradient Boosting, sin reponderar, detectan pocos SI; en clustering el clima forma una nube continua
(DBSCAN encuentra un solo grupo denso y ruido) y K-Means con k = 3 recupera parcialmente los cultivos
(ARI ≈ 0.49); en regresión los cuatro algoritmos quedan muy parecidos (el cultivo explica la mayor
parte de la temperatura, R² ≈ 0.5); en series, solo la serie simulada tiene estructura clara y ahí la
regresión temporal con estacionalidad gana con diferencia.

![Página de análisis](dashboard/preview_analisis.png)

## 5b. Interfaz Gradio (`app/gradio_app.py`)

Panel alternativo construido íntegramente en Python con **Gradio + Plotly** (gráficos
interactivos: zoom, hover, exportar PNG). Carga `models/modelo.joblib`, `models/metricas.json`,
`data/datos.csv` y `output/resultado.json`, y reproduce la misma partición hold-out y la
validación cruzada del notebook para que las matrices de confusión coincidan con `metricas.json`.

| Pestaña | Contenido |
|---------|-----------|
| 🔮 **Predicción** | Sliders por variable, cultivo (con su **ciudad** mostrada al lado y enviada al modelo) y umbral → etiqueta SI/NO, probabilidades, **gauge** de P(SI) y gráfico de **contribución de cada variable al logit** (coeficiente × valor transformado). Botón "fila aleatoria" y ejemplos. |
| 📊 **Métricas y matriz de confusión** | Selector de conjunto (hold-out / CV 5× out-of-fold) y **umbral ajustable**: KPIs (accuracy, precisión, recall, F1, ROC-AUC, especificidad), **matriz de confusión** interactiva (conteo o proporción), curva **ROC**, curva **Precision-Recall**, **métricas vs. umbral** y distribución de P(SI) por clase real. |
| 🔥 **Mapas de calor** | **Correlación** (Pearson/Spearman), **promedios por cultivo** (normalizados), radar de perfil por cultivo, **superficie de decisión** P(SI) sobre una rejilla 2D con isolínea del umbral 0.5 y datos reales superpuestos, y **tasa observada de SI** por celdas. |
| 🔍 **Exploración de datos** | Histogramas por clase, box plots por cultivo y resultado, dispersión (color = cultivo, relleno = SI, tamaño = P(SI)) y coeficientes del modelo. |
| 📡 **Monitoreo en vivo** | Simulador de tráfico con `gr.Timer` (cada 2 s): KPIs, matriz de confusión de la **ventana móvil** y **acumulada**, serie temporal de métricas, deriva de datos (z-score) y tabla de las últimas predicciones. Botones pausar / ráfaga +25 / reiniciar. |
| 🗂 **Datos** | Resumen de `procesar_datos.py` y el dataset filtrable por cultivo y resultado con la P(SI) del modelo. |

**Página 📄 Resultados (`/resultados`)** — segunda página de la app (multipágina de Gradio,
`demo.route("📄 Resultados", "/resultados")`), enlazada en la barra de navegación superior.
Muestra `output/resultado.json` con tarjetas resumen, gráficos de distribución y promedios por
cultivo, tablas de estadísticas, el **JSON completo** en un visor de código (con botón de copiar)
y la cola de `logs/ejecucion.log`. Botones: **⬇️ Descargar resultado.json** (`gr.DownloadButton`),
**🔄 Recargar** y **⚙️ Volver a ejecutar `procesar_datos.py`** (regenera el archivo y refresca la página).

![Página de resultados en Gradio](app/preview_gradio_resultados.png)

```bash
python app/gradio_app.py      # http://localhost:7860  ·  resultados: http://localhost:7860/resultados
```

## 6. API REST (v2.0)

Todos los endpoints cuelgan de `/api` y están documentados en Swagger (`/docs`) y ReDoc (`/redoc`).

```
/api
├── health/           GET  /            estado global (db · cache · modelo)
│                     GET  /database    backend, fallback, latencia, conteo de tablas
│                     GET  /cache       niveles L1/L2, hit ratio, latencia Upstash
├── predictions/      POST /            predicción individual (cachea por features; persiste)
│                     POST /batch       predicción por lotes
│                     GET  /{id}        predicción persistida (caché → BD)
│                     GET  /            listado paginado (limit, offset, origen, cultivo)
├── feedback/         POST /            {prediction_id, real} → acierto/error, actualiza métricas
│                     GET  /            listado paginado
│                     GET  /{id}
├── metrics/          GET  /training    metricas.json (hold-out, CV, coeficientes, correlación)
│                     GET  /live        ventana móvil, acumulado, latencia, deriva, simulador
│                     GET  /summary     entrenamiento + vivo + persistencia + caché
├── stream/           GET  /            SSE: prediccion · feedback · metricas · heartbeat
├── cache/            GET  /stats       estadísticas L1/L2, claves por grupo, muestra
│                     GET  /{key}       valor + nivel + TTL
│                     PUT  /{key}       {value, ttl?} escribe en L1 y L2
│                     DELETE /{key}
│                     DELETE /?prefix=  vacía todo o por prefijo (pred, model…)
├── simulator/        GET  /status
│                     POST /start       {intervalo?}
│                     POST /stop
│                     POST /burst       {cantidad}
├── model/            GET  /info        modelo, versión, hash, features, rangos
│                     GET  /metrics     = metrics/training
│                     POST /reload      recarga modelo.joblib e invalida la caché de inferencia
├── system/           GET  /info        versión, backends, configuración pública, uptime
│                     GET  /logs        ?archivo=api|ejecucion&n=
├── data/             GET  /summary · GET /sample · POST /reprocess · GET /events · GET /heatmap/probability
└── analisis/         GET  /catalogo        tipos, algoritmos, métricas y opciones (§5.5)
                      GET  /regresion       ?objetivo=temperatura&test_size=0.25&cv=5
                      GET  /clasificacion   ?objetivo=resultado|cultivo&test_size=&cv=&umbral=
                      GET  /clustering      ?k=3&eps=1.0&min_samples=10&n_clusters=3&enlace=ward&variables=a,b,…
                      GET  /anomalias       ?contaminacion=0.05&umbral_z=3&vecinos=20&inyectar=0
                      GET  /series          ?fuente=dataset|predicciones|simulada&variable=&bloque=&medida=&intervalo=
                                            &n=&tendencia=&amplitud=&ruido=&test_frac=&ventana=&alpha=&p=&d=&q=&lags=&periodo=
```

Además: `GET /` y `/dashboard` → `/index.html`, `/resultados` → `/resultados.html`, `/analisis` → `/analisis.html`.

**Descargas de la base de datos** (`GET /api/data/exports` lista el catálogo):

| Ruta | Contenido |
|------|-----------|
| `GET /download/{tabla}.{csv\|xlsx\|pdf\|json}` | `tabla` ∈ `datos` (data/datos.csv) · `predicciones` · `feedback` · `documentos` · `resultado` (estadísticas por variable) |
| `GET /download/base_datos.xlsx` | Libro Excel con una hoja *Info* + una hoja por tabla |
| `GET /download/base_datos.pdf` | Informe PDF apaisado con una sección por tabla (`?limite=` filas por sección) |
| `GET /download/base_datos.zip` (o `.csv`) | ZIP con un CSV por tabla + `LEEME.txt` |
| `GET /download/base_datos.json` | Todas las tablas en un solo JSON |
| `GET /download/base_datos.sqlite` | Archivo SQLite: copia consistente (backup online) de la BD en uso; con PostgreSQL, copia portable con las mismas tablas |
| `GET /download/resultado.json` | El archivo `output/resultado.json` tal cual |
| `POST /api/data/exports/static` | Regenera las copias estáticas en `output/exportaciones/` (índice en `/output/exportaciones/index.json`) |

Los archivos se generan en memoria en el momento (CSV con BOM UTF-8, XLSX con cabecera fija y
autofiltro, PDF con reportlab —si no está instalado se usa un respaldo con matplotlib—).

### 6.1 Alias deprecados (compatibilidad)

Las rutas de la v1 siguen respondiendo con el mismo formato (marcadas `deprecated` en Swagger;
la respuesta incluye `deprecated: true` y `usa`, y las cabeceras `Deprecation: true` y
`Link: <ruta nueva>; rel="successor-version"`):

| Ruta antigua | Sustituida por |
|--------------|----------------|
| `GET /health` | `GET /api/health` |
| `POST /predict?umbral=` | `POST /api/predictions` (`umbral` en el cuerpo) |
| `POST /predict/batch` | `POST /api/predictions/batch` |
| `POST /feedback` `{id, real}` | `POST /api/feedback` `{prediction_id, real}` |
| `GET /api/info` | `GET /api/model/info` |
| `GET /api/logs` | `GET /api/system/logs` |
| `POST /api/simulator` `{accion}` | `POST /api/simulator/start` · `/stop` · `/burst` |

### 6.2 Ejemplos

```bash
# Predicción (se persiste; la segunda llamada idéntica sale de la caché: cache_hit=true)
# `ciudad` es opcional: si se omite se deduce del cultivo (cafe→chanchamayo, papa→huancayo, uva→ica);
# si se envía y no corresponde al cultivo, la API responde 422.
curl -s -X POST http://localhost:8000/api/predictions -H "Content-Type: application/json" \
     -d '{"cultivo":"cafe","ciudad":"chanchamayo","temperatura":21,"humedad":80,"radiacion_solar":16,"precipitacion":12,"viento":5,"umbral":0.5}'
# {"id":"cf6fc2500d6d","prediccion":"SI","probabilidad_si":0.58,"features":{...,"cultivo":"cafe","ciudad":"chanchamayo"},...}

# Historial filtrado por ciudad
curl -s "http://localhost:8000/api/predictions?ciudad=huancayo&limit=5"

# Feedback
curl -s -X POST http://localhost:8000/api/feedback -H "Content-Type: application/json" \
     -d '{"prediction_id":"cf6fc2500d6d","real":"SI"}'

# Caché, salud y SSE
curl -s http://localhost:8000/api/cache/stats
curl -s http://localhost:8000/api/health
curl -N  http://localhost:8000/api/stream
```

## 7. Resultados de referencia (dataset de 1 000 filas)

Dataset: 1 000 filas (café 260 · papa 380 · uva 360), **188 SI / 812 NO** (tasa 0.188; café 0.354,
uva 0.208, papa 0.055). Modelo **v1.2.0** (regresión logística balanceada; 5 variables numéricas +
`cultivo` + `ciudad` con one-hot; partición 750 / 250 estratificada, semilla 42):

| Evaluación | Accuracy | Precisión | Recall | F1 | ROC-AUC |
|------------|---------:|----------:|-------:|---:|--------:|
| Hold-out (250 filas) | 0.668 | 0.320 | 0.681 | 0.435 | 0.725 |
| Validación cruzada 5× (1 000 filas) | 0.663 | 0.330 | 0.766 | 0.461 | 0.751 |

Matriz de confusión hold-out `[[135, 68], [15, 32]]` (TN, FP / FN, TP). Coeficientes (escala
estandarizada): `temperatura` 0.74 · `radiacion_solar` 0.38 · `humedad` 0.37 · `viento` 0.08 ·
`precipitacion` 0.01 · `cultivo_cafe` = `ciudad_chanchamayo` +0.42 · `cultivo_uva` = `ciudad_ica`
−0.17 · `cultivo_papa` = `ciudad_huancayo` −0.42.

Lectura: con `class_weight="balanced"` el modelo prioriza **no dejar escapar casos SI** (recall
0.68–0.77) a costa de muchas falsas alarmas (precisión ≈ 0.32), que es lo esperable con una clase
positiva del 19 % y un modelo lineal. Lo relevante frente a la versión anterior es la
**estabilidad**: hold-out y validación cruzada ahora coinciden (±0.03 en todas las métricas),
mientras que con 50 filas divergían.

Referencias anteriores (mismas variables, dataset original de 50 filas):

| Versión | Datos | Hold-out (acc / prec / rec / F1 / AUC) | CV 5× (acc / prec / rec / F1 / AUC) |
|---------|-------|----------------------------------------|-------------------------------------|
| 1.1.0 (con `ciudad`) | 50 filas (10 SI) | 0.769 / 0.500 / 1.000 / 0.667 / 0.867 (13 filas) | 0.640 / 0.250 / 0.400 / 0.308 / 0.615 |
| 1.0.0 (sin `ciudad`) | 50 filas (10 SI) | 0.846 / 0.600 / 1.000 / 0.750 / 0.900 (13 filas) | 0.620 / 0.235 / 0.400 / 0.296 / 0.610 |

Los hold-out de 13 filas eran optimistas por azar (3 positivos en la prueba); la validación
cruzada de 50 filas, pesimista e inestable. Con 1 000 filas ambas evaluaciones convergen en
AUC ≈ 0.73–0.75, que es la capacidad real de un modelo lineal sobre esta relación clima ↔ resultado.
Para volver a las cifras de 50 filas basta restaurar `data/datos_original_50.csv` (§2) y repetir
los pasos 1 y 2.

## 8. Uso en Google Colab

1. Sube el repositorio (o haz `!git clone …`) y sitúate en la raíz del proyecto.
2. Ejecuta `notebooks/entrenamiento.ipynb`; detecta automáticamente la raíz y guarda
   `models/modelo.joblib` y `models/metricas.json`.
3. Haz `git add models/ output/resultado.json && git commit && git push` para versionar el artefacto.

## 9. Arquitectura interna v2.0: caché y persistencia

### 9.1 Flujo de una predicción

`POST /api/predictions` → **CacheManager.get** (clave `mlops:pred:feat:<hash de features+umbral+hash del modelo>`)
→ si falla, **Predictor** (pipeline scikit-learn) → **persistencia** (`predictions`) → **Monitor**
(ventana móvil, acumulado, latencia, deriva) → **EventBus** → **SSE**. La respuesta indica
`cache_hit` y `cache_nivel` (`local` | `upstash`). `POST /api/feedback` actualiza la fila y
las métricas, y `POST /api/model/reload` invalida el prefijo `pred` en ambos niveles.

### 9.2 Cache Manager (`api/core/cache.py`)

| Nivel | Implementación | Cuándo se usa |
|-------|----------------|---------------|
| L1 | `LocalLRUCache`: `OrderedDict` con TTL por clave, evicción LRU, estadísticas (hits, misses, sets, evictions, expirations) | Siempre |
| L2 | `UpstashRedis`: API REST (`SET … EX`, `GET`, `DEL`, `SCAN`, `PING`) con `httpx`, timeouts cortos y *circuit breaker* (tras un error se deja de intentar durante 60 s) | Solo si `UPSTASH_REDIS_REST_URL` y `UPSTASH_REDIS_REST_TOKEN` están definidas |

Lectura: L1 → L2 (y se rellena L1). Escritura: ambos niveles. `DELETE /api/cache?prefix=` y
`clear()` operan por prefijo en los dos. Grupos de claves: `pred`, `model`, `metrics`,
`heatmap`, `data`.

### 9.3 Persistencia (`api/core/database.py`)

- Con `DATABASE_URL` válida → **PostgreSQL** (psycopg 3).
- Si no hay `DATABASE_URL`, falta `psycopg` o la conexión falla → **SQLite** en
  `storage/mlops.sqlite3` (WAL). El motivo del fallback se expone en `GET /api/health/database`
  (`fallback: true`, `fallback_reason`).
- Tablas: `predictions` y `feedback` (FK a predictions). Mismo SQL para ambos motores salvo
  placeholders y tipos numéricos. Al arrancar se eliminan, si existen, las tablas `documents` y
  `embeddings` del antiguo asistente RAG (retirado en la v2.1).
- **Migración aditiva** (`MIGRACIONES_COLUMNAS`): en bases creadas por versiones anteriores se añade
  `predictions.ciudad` con `ALTER TABLE` y se rellena a partir del cultivo (café → chanchamayo,
  papa → huancayo, uva → ica); funciona igual en PostgreSQL y SQLite y se registra en el log.
- Toda la base de datos se puede descargar desde `/resultados` o `GET /download/base_datos.*`
  (XLSX multi-hoja, PDF, ZIP de CSV, SQLite, JSON); ver §5.4.

Probado con PostgreSQL 17 y con SQLite 3.

### 9.4 Variables de entorno

| Variable | Por defecto | Efecto |
|----------|-------------|--------|
| `DATABASE_URL` | *(vacía)* | DSN PostgreSQL. Vacía o inválida → SQLite |
| `SQLITE_PATH` | `storage/mlops.sqlite3` | Archivo SQLite del fallback |
| `DB_CONNECT_TIMEOUT_S` | `5` | Tiempo máximo para intentar PostgreSQL antes de caer a SQLite |
| `UPSTASH_REDIS_REST_URL` / `UPSTASH_REDIS_REST_TOKEN` | *(vacías)* | Activan el nivel L2 de la caché |
| `CACHE_TTL_S` | `300` | TTL por defecto de las claves |
| `CACHE_MAX_ITEMS` | `2048` | Tamaño máximo de la LRU local |
| `CACHE_PREFIX` | `mlops:` | Prefijo de todas las claves |
| `METRICS_WINDOW` / `METRICS_HISTORY` | `50` / `500` | Ventana móvil y eventos en memoria |
| `SIMULATOR_ENABLED` / `SIMULATOR_INTERVAL_S` | `true` / `2.0` | Tráfico sintético al arrancar |
| `STATIC_EXPORTS` | `true` | Escribir las copias estáticas de las exportaciones en `output/exportaciones/` al arrancar |
| `ANALISIS_PRECALCULAR` | `true` | Precalcular en segundo plano los análisis por defecto de `/analisis` (regresión, clasificación, clustering, anomalías) al arrancar |
| `PUBLIC_URL` / `PORT` | — / `8000` | URL(s) públicas (separadas por coma) y puerto que la API anuncia en `dashboard/api-base.js` |
| `WARMUP_EVENTS` | `30` | Eventos sintéticos iniciales para que el dashboard no arranque vacío |
| `LOG_LEVEL` | `INFO` | Nivel de log de la API (`logs/api.log`) |

Todas están comentadas en `.env.example`; la API carga `.env` automáticamente al arrancar.
#   M L O P S  
 