/* ============================================================================
 * dashboard/analisis.js
 * Página /analisis: analiza el dataset con cinco tipos de algoritmos
 * (regresión, clasificación, clustering, anomalías y series temporales),
 * compara los algoritmos de cada tipo con sus métricas y dibuja los resultados
 * (Chart.js). Los cálculos los hace el servicio; esta página solo los pide,
 * los presenta y añade una lectura en lenguaje sencillo.
 * ========================================================================== */
(() => {
  'use strict';

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
  const son = (n, e) => { try { if (window.SONIDOS) window.SONIDOS.reproducir(n, e); } catch (_) { /* sin audio */ } };
  const esc = (s) => String(s ?? '').replace(/[<>&"]/g, (c) => ({ '<': '&lt;', '>': '&gt;', '&': '&amp;', '"': '&quot;' }[c]));
  const num = (v, d = 2) => (v === null || v === undefined || Number.isNaN(Number(v))) ? '—' : Number(v).toFixed(d);
  const pct = (v, d = 0) => (v === null || v === undefined) ? '—' : `${(v * 100).toFixed(d)}%`;
  const cap = (s) => s ? String(s).charAt(0).toUpperCase() + String(s).slice(1) : '';

  const PALETA = ['#2546e8', '#0e7490', '#7c3aed', '#b45309', '#059669', '#dc2626', '#db2777', '#64748b'];
  const CULTIVO_COLORS = { cafe: '#b45309', papa: '#7c3aed', uva: '#0e7490' };
  const CIUDAD = { cafe: 'Chanchamayo', papa: 'Huancayo', uva: 'Ica' };
  const VAR_LABEL = { temperatura: 'Temperatura', humedad: 'Humedad', radiacion_solar: 'Radiación solar', precipitacion: 'Precipitación', viento: 'Viento', cultivo: 'Cultivo (y ciudad)' };
  const VAR_UNIT = { temperatura: '°C', humedad: '%', radiacion_solar: 'MJ/m²', precipitacion: 'mm', viento: 'km/h' };
  const etiquetaVar = (v) => VAR_LABEL[v] || (v.startsWith('cultivo_') ? `Cultivo ${v.slice(8)} (${CIUDAD[v.slice(8)] || ''})` : v);
  const etiquetaCultivo = (c) => `${c} · ${CIUDAD[c] || ''}`;

  // Catálogo local de respaldo (la API devuelve el mismo contenido; así la página no queda vacía sin conexión)
  const CATALOGO_LOCAL = {
    tipos: [
      { id: 'regresion', orden: 1, titulo: 'Regresión', subtitulo: 'predecir valores numéricos', aprendizaje: 'Aprendizaje supervisado', para_que: 'Estima ventas, precios, demanda, temperaturas o valores futuros. Aquí: predecir una variable climática a partir de las demás y del cultivo.',
        algoritmos: [{ id: 'lineal', nombre: 'Regresión lineal' }, { id: 'ridge', nombre: 'Ridge' }, { id: 'random_forest', nombre: 'Random Forest Regressor' }, { id: 'gradient_boosting', nombre: 'Gradient Boosting Regressor' }],
        metricas: [{ id: 'mae', nombre: 'MAE' }, { id: 'rmse', nombre: 'RMSE' }, { id: 'r2', nombre: 'R²' }] },
      { id: 'clasificacion', orden: 2, titulo: 'Clasificación', subtitulo: 'asignar categorías', aprendizaje: 'Aprendizaje supervisado', para_que: 'Clasifica registros como fraude/no fraude, aprobado/rechazado o riesgo alto/medio/bajo. Aquí: resultado SI/NO o el cultivo de cada registro.',
        algoritmos: [{ id: 'logistica', nombre: 'Regresión logística' }, { id: 'arbol', nombre: 'Árbol de decisión' }, { id: 'random_forest', nombre: 'Random Forest' }, { id: 'svm', nombre: 'SVM' }, { id: 'gradient_boosting', nombre: 'Gradient Boosting' }],
        metricas: [{ id: 'precision', nombre: 'Precision' }, { id: 'recall', nombre: 'Recall' }, { id: 'f1', nombre: 'F1' }, { id: 'roc_auc', nombre: 'ROC-AUC' }] },
      { id: 'clustering', orden: 3, titulo: 'Clustering', subtitulo: 'descubrir grupos', aprendizaje: 'Aprendizaje no supervisado', para_que: 'Agrupa clientes, documentos, productos o comportamientos similares sin necesitar etiquetas previas. Aquí: agrupa los registros solo por su clima y comprueba si los grupos coinciden con los cultivos.',
        algoritmos: [{ id: 'kmeans', nombre: 'K-Means' }, { id: 'dbscan', nombre: 'DBSCAN' }, { id: 'jerarquico', nombre: 'Clustering jerárquico' }],
        metricas: [{ id: 'silhouette', nombre: 'Silhouette' }, { id: 'davies_bouldin', nombre: 'Davies–Bouldin' }] },
      { id: 'anomalias', orden: 4, titulo: 'Detección de anomalías', subtitulo: 'encontrar comportamientos inusuales', aprendizaje: 'No supervisado', para_que: 'Identifica transacciones atípicas, errores de sensores, valores extremos o posibles fraudes. Aquí: registros con un clima que no se parece al resto.',
        algoritmos: [{ id: 'isolation_forest', nombre: 'Isolation Forest' }, { id: 'lof', nombre: 'Local Outlier Factor (LOF)' }, { id: 'zscore', nombre: 'Desviación estándar (z-score)' }],
        metricas: [{ id: 'precision', nombre: 'Precision' }, { id: 'recall', nombre: 'Recall' }] },
      { id: 'series', orden: 5, titulo: 'Series temporales', subtitulo: 'analizar y pronosticar tendencias', aprendizaje: 'Pronóstico', para_que: 'Predice demanda, ventas, producción, temperatura o carga de trabajo a partir del historial temporal.',
        algoritmos: [{ id: 'media_movil', nombre: 'Media móvil' }, { id: 'suavizado', nombre: 'Suavizado exponencial' }, { id: 'holt', nombre: 'Holt (nivel + tendencia)' }, { id: 'arima', nombre: 'ARIMA' }, { id: 'regresion_temporal', nombre: 'Regresión con variables temporales' }],
        metricas: [{ id: 'mae', nombre: 'MAE' }, { id: 'rmse', nombre: 'RMSE' }, { id: 'mape', nombre: 'MAPE' }] },
    ],
    variables: ['temperatura', 'humedad', 'radiacion_solar', 'precipitacion', 'viento'].map((v) => ({ id: v, nombre: VAR_LABEL[v], unidad: VAR_UNIT[v] })),
    objetivos_clasificacion: [{ id: 'resultado', nombre: 'Resultado (SI / NO)' }, { id: 'cultivo', nombre: 'Cultivo (café / papa / uva)' }],
  };

  const state = { catalogo: CATALOGO_LOCAL, tipo: null, datos: {}, charts: {}, cargando: false, sel: {} };
  const modoEstatico = () => !MLOPS.base;

  async function api(path) {
    const res = await fetch(MLOPS.url(path), { headers: { Accept: 'application/json' } });
    if (!res.ok) {
      let detail = res.statusText;
      try { detail = (await res.json()).detail || detail; } catch { /* ignore */ }
      throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail));
    }
    return res.json();
  }

  function aviso(msg) {
    const el = $('#aviso');
    if (!msg) { el.classList.add('hidden'); return; }
    el.textContent = msg; el.classList.remove('hidden');
  }
  function setEstado(msg, tipo = 'info') {
    const el = $('#estado');
    el.innerHTML = tipo === 'cargando' ? `<span class="loader"></span> ${esc(msg)}` : esc(msg);
    el.className = `mt-2 min-h-[1rem] text-xs ${tipo === 'error' ? 'text-rose-700' : tipo === 'ok' ? 'text-emerald-700' : 'text-slate-500'}`;
  }

  // ───────────────────────────── gráficos ─────────────────────────────────────
  function chart(id, config) {
    if (state.charts[id]) { state.charts[id].destroy(); delete state.charts[id]; }
    const canvas = document.getElementById(id);
    if (!canvas || typeof Chart === 'undefined') return null;
    Chart.defaults.font.family = 'Inter, system-ui, sans-serif';
    Chart.defaults.color = '#64748b';
    state.charts[id] = new Chart(canvas, config);
    return state.charts[id];
  }
  function destruirCharts() { Object.values(state.charts).forEach((c) => c.destroy()); state.charts = {}; }
  const gridOpts = { color: 'rgba(148,163,184,.18)' };

  // ───────────────────────────── piezas HTML ──────────────────────────────────
  const card = (titulo, sub, cuerpo, extra = '') => `<div class="res-card">${titulo ? `<div class="card-head"><div><h3 class="res-title">${titulo}</h3>${sub ? `<p class="res-sub">${sub}</p>` : ''}</div>${extra}</div>` : ''}<div class="mt-3">${cuerpo}</div></div>`;
  const ORDEN_PRIO = { alta: 0, media: 1, baja: 2 };
  const recomendaciones = (recs) => {
    if (!Array.isArray(recs) || !recs.length) return '';
    const items = [...recs].sort((a, b) => (ORDEN_PRIO[a.prioridad] ?? 9) - (ORDEN_PRIO[b.prioridad] ?? 9))
      .map((x) => `<li><span class="int-prio int-prio-${esc(x.prioridad)}">${esc(x.prioridad)}</span><span><b>${esc(x.accion)}</b> <span class="int-porque">${esc(x.porque)}</span></span></li>`).join('');
    return `<div class="int-recs"><p class="text-[11px] font-semibold uppercase tracking-wider text-brand-700">Recomendaciones</p><ul class="int-rec-list">${items}</ul><p class="int-leyenda"><span>Prioridad:</span><span><span class="int-prio int-prio-alta">alta</span> hacerlo primero</span><span><span class="int-prio int-prio-media">media</span> siguiente paso</span><span><span class="int-prio int-prio-baja">baja</span> cuando haya tiempo</span></p></div>`;
  };
  const lectura = (texto, nota, recs) => `<div class="int-lead"><p class="text-[11px] font-semibold uppercase tracking-wider text-brand-700">Lectura de los resultados</p><p class="mt-1">${esc(texto)}</p>${nota ? `<p class="mt-2 text-xs text-slate-500">${esc(nota)}</p>` : ''}</div>${recomendaciones(recs)}`;
  const help = (txt) => `<span class="help" title="${esc(txt)}">?</span>`;
  const canvasBox = (id, h = 260) => `<div class="relative" style="height:${h}px"><canvas id="${id}" role="img"></canvas></div>`;
  const descMetrica = (tipo, id) => ((state.catalogo.tipos.find((t) => t.id === tipo) || {}).metricas || []).find((m) => m.id === id)?.descripcion || '';
  const th = (tipo, id, nombre) => `<th class="text-right">${nombre}${descMetrica(tipo, id) ? help(descMetrica(tipo, id)) : ''}</th>`;
  const selectAlgo = (id, algoritmos, ranking, actual) => `<label class="text-xs text-slate-500">Ver detalle de <select id="${id}" class="select-sm ml-1">${ranking.map((k) => `<option value="${k}" ${k === actual ? 'selected' : ''}>${esc(algoritmos[k].nombre)}</option>`).join('')}</select></label>`;

  // ───────────────────────────── tarjetas de tipo ─────────────────────────────
  function renderTipos() {
    const tipos = [...state.catalogo.tipos].sort((a, b) => a.orden - b.orden);
    $('#tipos').innerHTML = tipos.map((t) => `
      <button class="tipo-card ${state.tipo === t.id ? 'tipo-card-active' : ''}" data-tipo="${t.id}" role="tab" aria-selected="${state.tipo === t.id}">
        <div class="flex items-center gap-2"><span class="tipo-num">${t.orden}</span><div><p class="text-sm font-semibold text-slate-900">${esc(t.titulo)}</p><p class="text-[11px] text-slate-500">${esc(t.subtitulo)}</p></div></div>
        <p class="mt-2 text-[11px] font-medium text-brand-700">${esc(t.aprendizaje)}</p>
        <p class="mt-1 text-[12px] leading-relaxed text-slate-600">${esc(t.para_que)}</p>
        <div class="mt-2 flex flex-wrap gap-1">${t.algoritmos.map((a) => `<span class="chip">${esc(a.nombre)}</span>`).join('')}</div>
        <div class="mt-1.5 flex flex-wrap gap-1">${t.metricas.map((m) => `<span class="chip-metric">${esc(m.nombre)}</span>`).join('')}</div>
      </button>`).join('');
    $$('#tipos .tipo-card').forEach((b) => b.addEventListener('click', () => seleccionarTipo(b.dataset.tipo)));
  }

  function renderGlosario(tipoActivo) {
    const tipos = [...state.catalogo.tipos].sort((a, b) => a.orden - b.orden);
    const activo = tipos.find((t) => t.id === tipoActivo) || tipos[0];
    $('#glos-tabs').innerHTML = tipos.map((t) => `<button class="tab ${t.id === activo.id ? 'tab-active' : ''}" data-glos="${t.id}" role="tab">${esc(t.titulo)}</button>`).join('');
    $$('#glos-tabs .tab').forEach((b) => b.addEventListener('click', () => renderGlosario(b.dataset.glos)));
    const items = [
      ...activo.metricas.map((m) => `<div class="glos-item"><h4><span class="chip-metric">${esc(m.nombre)}</span> <span class="ml-1 text-slate-500 font-normal">métrica</span></h4><p>${esc(m.descripcion || '')}</p></div>`),
      ...activo.algoritmos.map((a) => `<div class="glos-item"><h4>${esc(a.nombre)} <span class="text-slate-500 font-normal">algoritmo</span></h4><p>${esc(a.descripcion || '')}</p></div>`),
    ];
    $('#glosario').innerHTML = items.join('');
  }

  // ───────────────────────────── controles ────────────────────────────────────
  const ctlSelect = (id, label, opciones, valor, ayuda = '') => `<div class="ctl"><label class="label" for="${id}">${label}${ayuda ? help(ayuda) : ''}</label><select id="${id}" class="select">${opciones.map((o) => `<option value="${o.id}" ${String(o.id) === String(valor) ? 'selected' : ''}>${esc(o.nombre)}</option>`).join('')}</select></div>`;
  const ctlRange = (id, label, min, max, step, valor, fmt = (v) => v, ayuda = '') => `<div class="ctl"><div class="ctl-row"><label for="${id}">${label}${ayuda ? help(ayuda) : ''}</label><span class="ctl-val" id="${id}-val">${fmt(valor)}</span></div><input type="range" id="${id}" class="range" min="${min}" max="${max}" step="${step}" value="${valor}" data-fmt="${id}"></div>`;
  const RANGE_FMT = {};
  function rango(id, label, min, max, step, valor, fmt, ayuda) { RANGE_FMT[id] = fmt || ((v) => v); return ctlRange(id, label, min, max, step, valor, RANGE_FMT[id], ayuda); }
  const ctlCheck = (id, label, checked) => `<label class="flex items-center gap-2 text-xs text-slate-700"><input type="checkbox" id="${id}" ${checked ? 'checked' : ''} class="h-3.5 w-3.5 rounded border-slate-300 text-brand-600"> ${label}</label>`;

  const VARS = () => state.catalogo.variables || CATALOGO_LOCAL.variables;
  const OPC_TEST = [{ id: 0.2, nombre: '20 % de prueba' }, { id: 0.25, nombre: '25 % de prueba' }, { id: 0.3, nombre: '30 % de prueba' }];
  const OPC_CV = [{ id: 3, nombre: '3 repeticiones' }, { id: 5, nombre: '5 repeticiones' }, { id: 10, nombre: '10 repeticiones' }];

  function renderControles(tipo) {
    const v = VARS();
    let html = '';
    if (tipo === 'regresion') {
      html = ctlSelect('c-objetivo', 'Variable a predecir', v, 'temperatura', 'El algoritmo intentará predecir esta variable usando las otras cuatro y el cultivo.')
        + ctlSelect('c-test', 'Registros reservados para la prueba', OPC_TEST, 0.25, 'Parte de los registros que el modelo no ve al entrenar y sirve para medir el error.')
        + ctlSelect('c-cv', 'Validación cruzada', OPC_CV, 5, 'El entrenamiento se repite varias veces con particiones distintas para comprobar que el resultado es estable.');
    } else if (tipo === 'clasificacion') {
      html = ctlSelect('c-objetivo', 'Categoría a predecir', state.catalogo.objetivos_clasificacion || CATALOGO_LOCAL.objetivos_clasificacion, 'resultado')
        + ctlSelect('c-test', 'Registros reservados para la prueba', OPC_TEST, 0.25)
        + ctlSelect('c-cv', 'Validación cruzada', OPC_CV, 5);
    } else if (tipo === 'clustering') {
      html = `<div class="ctl"><p class="label">Variables para agrupar</p><div class="grid grid-cols-1 gap-1">${v.map((x) => ctlCheck(`c-var-${x.id}`, x.nombre, true)).join('')}</div></div>`
        + rango('c-k', 'K-Means: número de grupos (k)', 2, 8, 1, 3)
        + rango('c-ncl', 'Jerárquico: número de grupos', 2, 8, 1, 3)
        + ctlSelect('c-enlace', 'Jerárquico: forma de unir', [{ id: 'ward', nombre: 'Ward (grupos compactos)' }, { id: 'average', nombre: 'Promedio' }, { id: 'complete', nombre: 'Completo' }, { id: 'single', nombre: 'Simple (cadenas)' }], 'ward')
        + rango('c-eps', 'DBSCAN: radio de vecindad (eps)', 0.3, 2.0, 0.1, 1.0, (x) => Number(x).toFixed(1), 'Distancia máxima (en unidades estandarizadas) para considerar dos registros vecinos.')
        + rango('c-ms', 'DBSCAN: vecinos mínimos', 3, 30, 1, 10, (x) => x, 'Cuántos vecinos necesita un punto para formar parte de un grupo denso.');
    } else if (tipo === 'anomalias') {
      html = rango('c-cont', 'Proporción esperada de anomalías', 0.01, 0.2, 0.01, 0.05, (x) => `${Math.round(x * 100)} %`, 'Isolation Forest y LOF señalan aproximadamente este porcentaje de registros.')
        + rango('c-z', 'Umbral de desviación estándar (z)', 2, 4, 0.5, 3, (x) => `${Number(x).toFixed(1)} σ`, 'La regla estadística marca un registro si alguna variable se aleja más de este número de desviaciones del promedio.')
        + rango('c-vec', 'LOF: vecinos comparados', 5, 50, 5, 20)
        + rango('c-iny', 'Anomalías artificiales para evaluar', 0, 100, 10, 0, (x) => x === 0 || x === '0' ? 'ninguna' : `${x} inyectadas`, 'Añade registros claramente anómalos (a más de 4 desviaciones) para medir precision y recall de cada método.');
    } else if (tipo === 'series') {
      html = ctlSelect('c-fuente', 'Serie a analizar', [{ id: 'dataset', nombre: 'Variable del dataset (orden de registro)' }, { id: 'predicciones', nombre: 'Actividad del servicio (historial real)' }, { id: 'simulada', nombre: 'Serie simulada con tendencia y estacionalidad' }], 'dataset')
        + `<div data-fuente="dataset simulada">${ctlSelect('c-variable', 'Variable', v, 'temperatura')}</div>`
        + `<div data-fuente="dataset">${ctlSelect('c-bloque', 'Promediar en bloques de', [{ id: 1, nombre: '1 registro (sin promediar)' }, { id: 5, nombre: '5 registros' }, { id: 10, nombre: '10 registros' }, { id: 20, nombre: '20 registros' }], 10, 'Promediar bloques consecutivos suaviza la serie y reduce el número de puntos.')}</div>`
        + `<div data-fuente="predicciones" class="space-y-3">${ctlSelect('c-medida', 'Qué medir', [{ id: 'conteo', nombre: 'Número de predicciones (carga de trabajo)' }, { id: 'tasa_si', nombre: 'Proporción de SI' }, { id: 'probabilidad', nombre: 'Probabilidad media de SI' }, { id: 'latencia', nombre: 'Tiempo medio de respuesta' }], 'conteo')}${ctlSelect('c-intervalo', 'Intervalo', [{ id: 'minuto', nombre: 'Por minuto' }, { id: '10min', nombre: 'Cada 10 minutos' }, { id: 'hora', nombre: 'Por hora' }, { id: 'dia', nombre: 'Por día' }], 'minuto')}</div>`
        + `<div data-fuente="simulada" class="space-y-3">${rango('c-n', 'Longitud de la serie', 48, 360, 12, 120, (x) => `${x} periodos`)}${rango('c-tend', 'Tendencia', -2, 2, 0.5, 1, (x) => `${Number(x) > 0 ? '+' : ''}${Number(x).toFixed(1)} σ`)}${rango('c-amp', 'Estacionalidad (amplitud)', 0, 2, 0.5, 1, (x) => `${Number(x).toFixed(1)} σ`)}${rango('c-ruido', 'Ruido', 0, 2, 0.25, 0.5, (x) => `${Number(x).toFixed(2)} σ`)}</div>`
        + `<details class="rounded-lg border border-surface-ring bg-white p-3"><summary class="cursor-pointer text-xs font-medium text-slate-700">Ajustes de los métodos</summary><div class="mt-3 space-y-3">`
        + ctlSelect('c-testf', 'Puntos reservados para la prueba', [{ id: 0.1, nombre: 'Últimos 10 %' }, { id: 0.2, nombre: 'Últimos 20 %' }, { id: 0.3, nombre: 'Últimos 30 %' }], 0.2)
        + rango('c-ventana', 'Media móvil: ventana', 2, 24, 1, 5, (x) => `${x} puntos`)
        + rango('c-alpha', 'Suavizado: peso de lo reciente (α)', 0.05, 0.95, 0.05, 0.3, (x) => Number(x).toFixed(2))
        + `<div class="ctl"><p class="label">ARIMA (p, d, q)${help('p: cuántos valores anteriores usa · d: cuántas veces diferencia la serie para quitar la tendencia · q: cuántos errores anteriores usa.')}</p><div class="grid grid-cols-3 gap-2">${['p', 'd', 'q'].map((k) => `<input type="number" id="c-${k}" class="select-sm" min="0" max="${k === 'd' ? 2 : 5}" value="1" aria-label="${k}">`).join('')}</div></div>`
        + rango('c-lags', 'Regresión temporal: valores anteriores', 1, 12, 1, 3)
        + rango('c-periodo', 'Estacionalidad (0 = ninguna)', 0, 52, 1, 0, (x) => Number(x) ? `${x} periodos` : 'ninguna', 'Si la serie se repite cada N periodos, indícalo para que la regresión temporal lo aproveche. En la serie simulada se usa 12 si se deja en 0.')
        + '</div></details>';
    }
    $('#controles').innerHTML = html;
    $$('#controles input[type=range]').forEach((r) => r.addEventListener('input', () => { const f = RANGE_FMT[r.id] || ((x) => x); const el = $(`#${r.id}-val`); if (el) el.textContent = f(r.value); }));
    if (tipo === 'series') {
      const sync = () => { const f = $('#c-fuente').value; $$('#controles [data-fuente]').forEach((d) => d.classList.toggle('hidden', !d.dataset.fuente.split(' ').includes(f))); };
      $('#c-fuente').addEventListener('change', sync); sync();
    }
  }

  function leerParametros(tipo) {
    const val = (id) => { const el = $(`#${id}`); return el ? el.value : undefined; };
    const p = new URLSearchParams();
    if (tipo === 'regresion' || tipo === 'clasificacion') { p.set('objetivo', val('c-objetivo')); p.set('test_size', val('c-test')); p.set('cv', val('c-cv')); }
    if (tipo === 'clustering') {
      const vars = VARS().filter((v) => $(`#c-var-${v.id}`)?.checked).map((v) => v.id);
      if (vars.length < 2) throw new Error('Elige al menos dos variables para agrupar.');
      if (vars.length < VARS().length) p.set('variables', vars.join(','));
      p.set('k', val('c-k')); p.set('n_clusters', val('c-ncl')); p.set('enlace', val('c-enlace')); p.set('eps', val('c-eps')); p.set('min_samples', val('c-ms'));
    }
    if (tipo === 'anomalias') { p.set('contaminacion', val('c-cont')); p.set('umbral_z', val('c-z')); p.set('vecinos', val('c-vec')); p.set('inyectar', val('c-iny')); }
    if (tipo === 'series') {
      const f = val('c-fuente'); p.set('fuente', f);
      if (f !== 'predicciones') p.set('variable', val('c-variable'));
      if (f === 'dataset') p.set('bloque', val('c-bloque'));
      if (f === 'predicciones') { p.set('medida', val('c-medida')); p.set('intervalo', val('c-intervalo')); }
      if (f === 'simulada') { p.set('n', val('c-n')); p.set('tendencia', val('c-tend')); p.set('amplitud', val('c-amp')); p.set('ruido', val('c-ruido')); }
      p.set('test_frac', val('c-testf')); p.set('ventana', val('c-ventana')); p.set('alpha', val('c-alpha'));
      p.set('p', val('c-p') || 1); p.set('d', val('c-d') || 1); p.set('q', val('c-q') || 1); p.set('lags', val('c-lags')); p.set('periodo', val('c-periodo'));
    }
    return p;
  }

  // ───────────────────────────── selección y ejecución ────────────────────────
  function seleccionarTipo(tipo, ejecutar = true) {
    state.tipo = tipo;
    const t = state.catalogo.tipos.find((x) => x.id === tipo);
    if (!t) return;
    $$('#tipos .tipo-card').forEach((b) => { const on = b.dataset.tipo === tipo; b.classList.toggle('tipo-card-active', on); b.setAttribute('aria-selected', on); });
    $('#p-titulo').textContent = `${t.orden}. ${t.titulo} — ${t.subtitulo}`;
    $('#p-sub').textContent = t.para_que;
    $('#p-aprendizaje').textContent = t.aprendizaje;
    $('#p-algos').innerHTML = t.algoritmos.map((a) => `<li><b class="font-medium text-slate-800">${esc(a.nombre)}</b>${a.descripcion ? `<span class="text-slate-500"> — ${esc(a.descripcion)}</span>` : ''}</li>`).join('');
    $('#p-metricas').innerHTML = t.metricas.map((m) => `<span class="chip-metric" title="${esc(m.descripcion || '')}">${esc(m.nombre)}</span>`).join('');
    renderControles(tipo);
    renderGlosario(tipo);
    try { history.replaceState(null, '', `#${tipo}`); } catch { /* ignore */ }
    if (ejecutar) ejecutarAnalisis();
  }

  async function ejecutarAnalisis() {
    const tipo = state.tipo;
    if (!tipo) return;
    if (modoEstatico()) {
      $('#resultados').innerHTML = '<div class="rounded-xl border border-amber-200 bg-amber-50 p-5 text-sm text-amber-800">Los análisis se calculan en el servicio. Abre esta página desde el servicio (enlace «Abrir esta página desde el servidor» en la parte superior) o conéctala con el botón «Conectar».</div>';
      son('aviso', 'error');
      return;
    }
    let params;
    try { params = leerParametros(tipo); } catch (e) { setEstado(e.message, 'error'); son('aviso', 'error'); return; }
    if (state.cargando) return;
    state.cargando = true;
    $('#btn-ejecutar').disabled = true;
    const lento = tipo === 'regresion' || tipo === 'clasificacion';
    setEstado(lento ? 'Entrenando y comparando los algoritmos… puede tardar unos segundos.' : 'Calculando…', 'cargando');
    $('#resultados').innerHTML = `<div class="rounded-xl border border-dashed border-surface-ring p-8 text-center text-sm text-slate-500"><span class="loader"></span> ${lento ? 'Entrenando varios algoritmos con validación cruzada…' : 'Calculando…'}</div>`;
    const t0 = performance.now();
    try {
      const datos = await api(`/api/analisis/${tipo}?${params.toString()}`);
      state.datos[tipo] = datos;
      state.sel[tipo] = (datos.ranking || [])[0];
      render(tipo, datos);
      if (window.ANIM) ANIM.escalonar($('#resultados'), '.int-lead, .res-card', 70);
      setEstado(`Listo en ${((performance.now() - t0) / 1000).toFixed(1)} s${datos.cache ? ' (resultado ya calculado)' : ''}.`, 'ok');
      son('exito', 'proceso');
    } catch (e) {
      $('#resultados').innerHTML = `<div class="rounded-xl border border-rose-200 bg-rose-50 p-5 text-sm text-rose-800"><b>No se pudo completar el análisis.</b> ${esc(e.message)}</div>`;
      setEstado('No se pudo completar el análisis.', 'error'); son('error', 'error');
    } finally {
      state.cargando = false; $('#btn-ejecutar').disabled = false;
    }
  }

  function render(tipo, d) {
    destruirCharts();
    const fn = { regresion: renderRegresion, clasificacion: renderClasificacion, clustering: renderClustering, anomalias: renderAnomalias, series: renderSeries }[tipo];
    if (fn) fn(d);
  }

  // ═══════════════════════════ 1. REGRESIÓN ═══════════════════════════════════
  function renderRegresion(d) {
    const A = d.algoritmos, rk = d.ranking, mejor = rk[0], u = d.unidad;
    const filas = rk.map((k, i) => `<tr class="${i === 0 ? 'row-best' : ''}"><td class="font-medium text-slate-800">${esc(A[k].nombre)}${i === 0 ? '<span class="badge-best">mejor</span>' : ''}</td><td class="text-right font-mono">${num(A[k].mae)} ${u}</td><td class="text-right font-mono">${num(A[k].rmse)} ${u}</td><td class="text-right font-mono">${num(A[k].r2)}</td><td class="text-right font-mono">${num(A[k].cv.mae)} ± ${num(A[k].cv.mae_std)}</td><td class="text-right font-mono">${num(A[k].cv.r2)}</td></tr>`).join('')
      + `<tr class="row-base"><td>${esc(d.baseline.nombre)} (referencia)</td><td class="text-right font-mono">${num(d.baseline.mae)} ${u}</td><td class="text-right font-mono">${num(d.baseline.rmse)} ${u}</td><td class="text-right font-mono">${num(d.baseline.r2)}</td><td class="text-right">—</td><td class="text-right">—</td></tr>`;
    $('#resultados').innerHTML = `
      ${lectura(d.lectura, `Variable predicha: ${VAR_LABEL[d.objetivo]} (${u}) · entrenamiento con ${d.n_train} registros y prueba con ${d.n_test} · validación cruzada de ${A[mejor].cv.folds} repeticiones sobre los ${d.n_filas}.`, d.recomendaciones)}
      ${card('Comparación de algoritmos', 'Métricas sobre los registros de prueba (que el modelo no vio al entrenar) y promedio de la validación cruzada. Cuanto menor el error (MAE, RMSE) y mayor el R², mejor.',
        `<div class="table-wrap"><table class="table"><thead><tr><th class="text-left">Algoritmo</th>${th('regresion', 'mae', 'MAE')}${th('regresion', 'rmse', 'RMSE')}${th('regresion', 'r2', 'R²')}<th class="text-right">MAE validación cruzada</th><th class="text-right">R² validación cruzada</th></tr></thead><tbody>${filas}</tbody></table></div>`)}
      <div class="grid grid-cols-1 gap-4 xl:grid-cols-2">
        ${card('Error medio por algoritmo', `MAE en ${u}: la barra gris es la referencia de predecir siempre el promedio.`, canvasBox('ch-reg-mae', 240))}
        ${card('Real frente a predicho', 'Cada punto es un registro de prueba; cuanto más pegados a la diagonal, mejor.', canvasBox('ch-reg-disp', 240), selectAlgo('sel-reg', A, rk, state.sel.regresion))}
      </div>
      ${card('Qué variables pesan más', 'Importancia relativa de cada variable en el algoritmo seleccionado (en los modelos lineales, el color indica si sube o baja la predicción).', canvasBox('ch-reg-imp', 220))}`;
    const labels = [...rk.map((k) => A[k].nombre), d.baseline.nombre];
    chart('ch-reg-mae', { type: 'bar', data: { labels, datasets: [{ data: [...rk.map((k) => A[k].mae), d.baseline.mae], backgroundColor: [...rk.map((_, i) => (i === 0 ? '#059669' : '#2546e8')), '#94a3b8'], borderRadius: 6 }] },
      options: { indexAxis: 'y', responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false }, tooltip: { callbacks: { label: (c) => ` MAE ${num(c.raw)} ${u}` } } }, scales: { x: { grid: gridOpts, title: { display: true, text: `MAE (${u})` } }, y: { grid: { display: false } } } } });
    const dibujarDetalle = () => {
      const k = state.sel.regresion, a = A[k];
      const pts = a.dispersion.real.map((r, i) => ({ x: r, y: a.dispersion.pred[i] }));
      const mn = Math.min(...a.dispersion.real, ...a.dispersion.pred), mx = Math.max(...a.dispersion.real, ...a.dispersion.pred);
      chart('ch-reg-disp', { type: 'scatter', data: { datasets: [{ label: 'Registros de prueba', data: pts, backgroundColor: 'rgba(37,70,232,.55)', pointRadius: 3 }, { type: 'line', label: 'Predicción perfecta', data: [{ x: mn, y: mn }, { x: mx, y: mx }], borderColor: '#94a3b8', borderDash: [5, 4], borderWidth: 1.5, pointRadius: 0 }] },
        options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: 'bottom' }, tooltip: { callbacks: { label: (c) => ` real ${num(c.raw.x, 1)} · predicho ${num(c.raw.y, 1)} ${u}` } } }, scales: { x: { title: { display: true, text: `Valor real (${u})` }, grid: gridOpts }, y: { title: { display: true, text: `Valor predicho (${u})` }, grid: gridOpts } } } });
      const imp = a.importancia.slice(0, 8);
      chart('ch-reg-imp', { type: 'bar', data: { labels: imp.map((x) => etiquetaVar(x.variable)), datasets: [{ data: imp.map((x) => x.valor), backgroundColor: imp.map((x) => (x.signo === '−' ? '#e11d48' : x.signo === '+' ? '#059669' : '#7c3aed')), borderRadius: 6 }] },
        options: { indexAxis: 'y', responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false }, tooltip: { callbacks: { label: (c) => ` ${pct(c.raw, 1)} del peso total${imp[c.dataIndex].signo ? ` · ${imp[c.dataIndex].signo === '+' ? 'sube' : 'baja'} la predicción` : ''}` } } }, scales: { x: { grid: gridOpts, ticks: { callback: (v) => pct(v) } }, y: { grid: { display: false } } } } });
    };
    dibujarDetalle();
    $('#sel-reg').addEventListener('change', (e) => { state.sel.regresion = e.target.value; dibujarDetalle(); });
  }

  // ═══════════════════════════ 2. CLASIFICACIÓN ═══════════════════════════════
  function renderClasificacion(d) {
    const A = d.algoritmos, rk = d.ranking, bin = d.binario, clases = d.clases;
    const filas = rk.map((k, i) => `<tr class="${i === 0 ? 'row-best' : ''}"><td class="font-medium text-slate-800">${esc(A[k].nombre)}${i === 0 ? '<span class="badge-best">mejor</span>' : ''}</td><td class="text-right font-mono">${pct(A[k].accuracy, 1)}</td><td class="text-right font-mono">${pct(A[k].precision, 1)}</td><td class="text-right font-mono">${pct(A[k].recall, 1)}</td><td class="text-right font-mono">${num(A[k].f1, 3)}</td><td class="text-right font-mono">${num(A[k].roc_auc, 3)}</td><td class="text-right font-mono">${num(A[k].cv.f1, 3)} ± ${num(A[k].cv.f1_std, 3)}</td><td class="text-right font-mono">${num(A[k].cv.roc_auc, 3)}</td></tr>`).join('')
      + `<tr class="row-base"><td>${esc(d.baseline.nombre)} (referencia)</td><td class="text-right font-mono">${pct(d.baseline.accuracy, 1)}</td><td class="text-right font-mono">${d.baseline.precision != null ? pct(d.baseline.precision, 1) : '—'}</td><td class="text-right font-mono">${pct(d.baseline.recall, 0)}</td><td class="text-right">—</td><td class="text-right font-mono">0.500</td><td class="text-right">—</td><td class="text-right">—</td></tr>`;
    const notaClases = bin ? `Clase positiva: SI (${d.distribucion_test.SI} de los ${d.n_test} registros de prueba).` : `Promedio de las ${clases.length} clases (${clases.map((c) => `${c}: ${d.distribucion_test[c]}`).join(', ')} en la prueba).`;
    $('#resultados').innerHTML = `
      ${lectura(d.lectura, `${notaClases} Entrenamiento con ${d.n_train} registros y prueba con ${d.n_test}; validación cruzada de ${A[rk[0]].cv.folds} repeticiones.`, d.recomendaciones)}
      ${card('Comparación de algoritmos', 'Métricas sobre los registros de prueba y promedio de la validación cruzada. Con una clase minoritaria, el acierto global (accuracy) engaña: fíjate en recall, F1 y ROC-AUC.',
        `<div class="table-wrap"><table class="table"><thead><tr><th class="text-left">Algoritmo</th><th class="text-right">Accuracy${help('Porcentaje total de aciertos.')}</th>${th('clasificacion', 'precision', 'Precision')}${th('clasificacion', 'recall', 'Recall')}${th('clasificacion', 'f1', 'F1')}${th('clasificacion', 'roc_auc', 'ROC-AUC')}<th class="text-right">F1 validación cruzada</th><th class="text-right">ROC-AUC validación cruzada</th></tr></thead><tbody>${filas}</tbody></table></div>`)}
      <div class="grid grid-cols-1 gap-4 xl:grid-cols-2">
        ${card('Métricas por algoritmo', 'Precision, recall, F1 y ROC-AUC lado a lado.', canvasBox('ch-clf-bar', 260))}
        ${bin ? card('Curvas ROC', 'Cuanto más se acerque la curva a la esquina superior izquierda, mejor separa SI de NO; la diagonal es el azar.', canvasBox('ch-clf-roc', 260))
              : card('Acierto por algoritmo', 'Porcentaje de registros de prueba bien clasificados.', canvasBox('ch-clf-acc', 260))}
      </div>
      <div class="grid grid-cols-1 gap-4 xl:grid-cols-2">
        ${card('Matriz de confusión', 'Qué predijo el algoritmo seleccionado frente a lo que ocurrió de verdad.', '<div id="clf-cm"></div>', selectAlgo('sel-clf', A, rk, state.sel.clasificacion))}
        ${card('Qué variables ayudan más', 'Cuánto empeora el algoritmo seleccionado si se desordena cada variable (importancia por permutación): más alto, más necesaria.', canvasBox('ch-clf-imp', 240))}
      </div>`;
    chart('ch-clf-bar', { type: 'bar', data: { labels: rk.map((k) => A[k].nombre), datasets: [
      { label: 'Precision', data: rk.map((k) => A[k].precision), backgroundColor: '#7c3aed' }, { label: 'Recall', data: rk.map((k) => A[k].recall), backgroundColor: '#0e7490' },
      { label: 'F1', data: rk.map((k) => A[k].f1), backgroundColor: '#2546e8' }, { label: 'ROC-AUC', data: rk.map((k) => A[k].roc_auc), backgroundColor: '#f59e0b' }].map((s) => ({ ...s, borderRadius: 4 })) },
      options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: 'bottom' } }, scales: { y: { min: 0, max: 1, grid: gridOpts }, x: { grid: { display: false }, ticks: { font: { size: 10 } } } } } });
    if (bin) {
      chart('ch-clf-roc', { type: 'line', data: { datasets: [...rk.map((k, i) => ({ label: `${A[k].nombre} (${num(A[k].roc_auc, 2)})`, data: A[k].roc.fpr.map((x, j) => ({ x, y: A[k].roc.tpr[j] })), borderColor: PALETA[i], borderWidth: 2, pointRadius: 0, tension: 0.1 })),
        { label: 'Azar', data: [{ x: 0, y: 0 }, { x: 1, y: 1 }], borderColor: '#94a3b8', borderDash: [5, 4], borderWidth: 1.5, pointRadius: 0 }] },
        options: { responsive: true, maintainAspectRatio: false, parsing: false, plugins: { legend: { position: 'bottom', labels: { boxWidth: 12, font: { size: 10 } } } }, scales: { x: { type: 'linear', min: 0, max: 1, title: { display: true, text: 'Falsas alarmas (1 − especificidad)' }, grid: gridOpts }, y: { min: 0, max: 1, title: { display: true, text: 'SI detectados (recall)' }, grid: gridOpts } } } });
    } else {
      chart('ch-clf-acc', { type: 'bar', data: { labels: rk.map((k) => A[k].nombre), datasets: [{ data: rk.map((k) => A[k].accuracy), backgroundColor: rk.map((_, i) => (i === 0 ? '#059669' : '#2546e8')), borderRadius: 6 }] },
        options: { indexAxis: 'y', responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false }, tooltip: { callbacks: { label: (c) => ` ${pct(c.raw, 1)}` } } }, scales: { x: { min: 0, max: 1, ticks: { callback: (v) => pct(v) }, grid: gridOpts }, y: { grid: { display: false } } } } });
    }
    const dibujarDetalle = () => {
      const k = state.sel.clasificacion, a = A[k], m = a.matriz;
      if (bin) {
        const [[tn, fp], [fn, tp]] = m, tot = tn + fp + fn + tp;
        const celda = (tag, n, cls) => `<div class="cm-cell ${cls}"><p class="cm-tag">${tag}</p><p class="cm-num">${n}</p><p class="cm-pct">${pct(n / tot, 1)} de la prueba</p></div>`;
        $('#clf-cm').innerHTML = `<div class="grid grid-cols-2 gap-2">${celda('NO correctos', tn, 'bg-slate-50')}${celda('Falsas alarmas (dijo SI, era NO)', fp, 'bg-rose-50')}${celda('SI que se escaparon', fn, 'bg-amber-50')}${celda('SI detectados', tp, 'bg-emerald-50')}</div><p class="mt-2 text-xs text-slate-500">${esc(a.nombre)}: detecta ${tp} de los ${tp + fn} SI reales (recall ${pct(a.recall, 0)}); de sus ${tp + fp} avisos de SI, ${tp} fueron correctos (precision ${pct(a.precision, 0)}).</p>`;
      } else {
        $('#clf-cm').innerHTML = `<div class="table-wrap"><table class="table"><thead><tr><th class="text-left">Real ↓ / Predicho →</th>${clases.map((c) => `<th class="text-right">${esc(cap(c))}</th>`).join('')}</tr></thead><tbody>${m.map((fila, i) => `<tr><td class="font-medium">${esc(cap(clases[i]))}</td>${fila.map((v, j) => `<td class="text-right font-mono ${i === j ? 'bg-emerald-50 font-semibold' : v ? 'bg-rose-50/60' : ''}">${v}</td>`).join('')}</tr>`).join('')}</tbody></table></div><p class="mt-2 text-xs text-slate-500">La diagonal (verde) son los aciertos; el resto, confusiones entre cultivos.</p>`;
      }
      const imp = a.importancia;
      chart('ch-clf-imp', { type: 'bar', data: { labels: imp.map((x) => etiquetaVar(x.variable)), datasets: [{ data: imp.map((x) => x.valor), backgroundColor: '#7c3aed', borderRadius: 6 }] },
        options: { indexAxis: 'y', responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false }, tooltip: { callbacks: { label: (c) => ` el F1 baja ${num(c.raw, 3)} si se desordena esta variable` } } }, scales: { x: { grid: gridOpts, title: { display: true, text: 'Caída de F1 al desordenar la variable' } }, y: { grid: { display: false } } } } });
    };
    dibujarDetalle();
    $('#sel-clf').addEventListener('change', (e) => { state.sel.clasificacion = e.target.value; dibujarDetalle(); });
  }

  // ═══════════════════════════ 3. CLUSTERING ══════════════════════════════════
  function renderClustering(d) {
    const A = d.algoritmos, rk = d.ranking;
    const filas = rk.map((k, i) => `<tr class="${i === 0 && A[k].silhouette != null ? 'row-best' : ''}"><td class="font-medium text-slate-800">${esc(A[k].nombre)}${i === 0 && A[k].silhouette != null ? '<span class="badge-best">mejor</span>' : ''}</td><td class="text-right font-mono">${A[k].n_clusters}</td><td class="text-right font-mono">${A[k].n_ruido || 0}</td><td class="text-right font-mono">${num(A[k].silhouette, 3)}</td><td class="text-right font-mono">${num(A[k].davies_bouldin, 3)}</td><td class="text-right font-mono">${num(A[k].ari_cultivo, 2)}</td><td class="text-right font-mono">${pct(A[k].pureza_cultivo, 0)}</td></tr>`).join('');
    $('#resultados').innerHTML = `
      ${lectura(d.lectura, `Variables usadas: ${d.variables.map((v) => VAR_LABEL[v]).join(', ')} (estandarizadas). El mapa de puntos proyecta esas variables en dos ejes que conservan el ${pct(d.varianza_pca[0] + d.varianza_pca[1], 0)} de la variación.`, d.recomendaciones)}
      ${card('Comparación de métodos', 'Silhouette alto y Davies–Bouldin bajo indican grupos nítidos. La coincidencia con cultivos (de 0 a 1) mide si los grupos encontrados «redescubren» el cultivo sin conocerlo.',
        `<div class="table-wrap"><table class="table"><thead><tr><th class="text-left">Método</th><th class="text-right">Grupos</th><th class="text-right">Ruido${help('Registros que DBSCAN deja fuera de todo grupo.')}</th>${th('clustering', 'silhouette', 'Silhouette')}${th('clustering', 'davies_bouldin', 'Davies–Bouldin')}<th class="text-right">Coincidencia con cultivos${help('Índice de Rand ajustado: 1 = los grupos son exactamente los cultivos; 0 = coincidencia casual.')}</th><th class="text-right">En grupo de su cultivo${help('Porcentaje de registros que caen en un grupo donde su cultivo es el mayoritario.')}</th></tr></thead><tbody>${filas}</tbody></table></div>`)}
      <div class="grid grid-cols-1 gap-4 xl:grid-cols-2">
        ${card('Mapa de los grupos', 'Cada punto es un registro; el color es el grupo asignado por el método seleccionado (o el cultivo real, para comparar).', canvasBox('ch-clu-scatter', 320), `<div class="flex flex-wrap items-center gap-3">${selectAlgo('sel-clu', A, rk, state.sel.clustering)}<label class="flex items-center gap-1.5 text-xs text-slate-500"><input type="checkbox" id="chk-clu-cultivo" class="h-3.5 w-3.5"> colorear por cultivo real</label></div>`)}
        ${card('¿Cuántos grupos elegir? (K-Means)', 'La inercia baja siempre al añadir grupos: busca el «codo». El silhouette marca el k con grupos más nítidos.', canvasBox('ch-clu-codo', 320))}
      </div>
      ${card('Perfil de cada grupo', 'Promedio de cada variable, proporción de SI y cultivo dominante en los grupos del método seleccionado.', '<div id="clu-perfiles"></div>')}`;
    chart('ch-clu-codo', { type: 'bar', data: { labels: d.barrido_kmeans.map((b) => `k = ${b.k}`), datasets: [{ label: 'Inercia (menor = grupos más compactos)', data: d.barrido_kmeans.map((b) => b.inercia), backgroundColor: 'rgba(37,70,232,.35)', borderRadius: 4, yAxisID: 'y' }, { type: 'line', label: 'Silhouette (mayor = grupos más nítidos)', data: d.barrido_kmeans.map((b) => b.silhouette), borderColor: '#059669', backgroundColor: '#059669', yAxisID: 'y2', tension: 0.3 }] },
      options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: 'bottom' } }, scales: { y: { grid: gridOpts, title: { display: true, text: 'Inercia' } }, y2: { position: 'right', min: 0, max: Math.max(0.5, ...d.barrido_kmeans.map((b) => b.silhouette)) + 0.05, grid: { display: false }, title: { display: true, text: 'Silhouette' } }, x: { grid: { display: false } } } } });
    const dibujar = () => {
      const k = state.sel.clustering, porCultivo = $('#chk-clu-cultivo').checked;
      const grupos = {};
      d.puntos.forEach((p) => { const g = porCultivo ? p.cultivo : p[k]; (grupos[g] = grupos[g] || []).push({ x: p.x, y: p.y, c: p.cultivo, si: p.si }); });
      const claves = Object.keys(grupos).sort((a, b) => (isNaN(a) ? a.localeCompare(b) : Number(a) - Number(b)));
      chart('ch-clu-scatter', { type: 'scatter', data: { datasets: claves.map((g, i) => ({ label: porCultivo ? etiquetaCultivo(g) : (Number(g) === -1 ? 'Ruido (sin grupo)' : `Grupo ${Number(g) + 1}`), data: grupos[g], backgroundColor: porCultivo ? CULTIVO_COLORS[g] : (Number(g) === -1 ? '#cbd5e1' : PALETA[i % PALETA.length]), pointRadius: 3 })) },
        options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: 'bottom' }, tooltip: { callbacks: { label: (c) => ` ${c.dataset.label} · ${etiquetaCultivo(c.raw.c)} · ${c.raw.si ? 'SI' : 'NO'}` } } }, scales: { x: { title: { display: true, text: 'Componente 1' }, grid: gridOpts }, y: { title: { display: true, text: 'Componente 2' }, grid: gridOpts } } } });
      const perf = A[k].perfiles;
      $('#clu-perfiles').innerHTML = `<div class="table-wrap"><table class="table"><thead><tr><th class="text-left">Grupo</th><th class="text-right">Registros</th>${d.variables.map((v) => `<th class="text-right">${VAR_LABEL[v]} (${VAR_UNIT[v]})</th>`).join('')}<th class="text-right">Tasa de SI</th><th class="text-left">Cultivo dominante</th></tr></thead><tbody>${perf.map((p, i) => `<tr><td class="font-medium"><span class="inline-block h-2.5 w-2.5 rounded-full mr-1.5" style="background:${p.cluster === -1 ? '#cbd5e1' : PALETA[claves.indexOf(String(p.cluster)) % PALETA.length] || PALETA[i]}"></span>${p.cluster === -1 ? 'Ruido (sin grupo)' : `Grupo ${p.cluster + 1}`}</td><td class="text-right font-mono">${p.tamano} <span class="text-slate-400">(${num(p.pct, 0)}%)</span></td>${d.variables.map((v) => `<td class="text-right font-mono">${num(p.medias[v], 1)}</td>`).join('')}<td class="text-right font-mono">${pct(p.tasa_si, 0)}</td><td>${p.cultivo_dominante ? `${etiquetaCultivo(p.cultivo_dominante)} <span class="text-slate-400">(${num(p.pct_dominante, 0)}%)</span>` : '—'}</td></tr>`).join('')}</tbody></table></div>`;
    };
    dibujar();
    $('#sel-clu').addEventListener('change', (e) => { state.sel.clustering = e.target.value; dibujar(); });
    $('#chk-clu-cultivo').addEventListener('change', dibujar);
  }

  // ═══════════════════════════ 4. ANOMALÍAS ═══════════════════════════════════
  function renderAnomalias(d) {
    const A = d.algoritmos, rk = d.ranking, evaluado = d.parametros.inyectar > 0;
    const tarjetas = rk.map((k, i) => { const a = A[k]; const topVar = Object.entries(a.por_variable).sort((x, y) => y[1] - x[1])[0]; return `<div class="mini-kpi"><dt>${esc(a.nombre)}</dt><dd>${a.n_anomalias} <span class="text-sm font-normal text-slate-500">(${num(a.pct, 1)}%)</span></dd><p class="mt-1 text-[11px] text-slate-500">${topVar ? `la variable más implicada: ${VAR_LABEL[topVar[0]].toLowerCase()}` : 'sin anomalías'}${a.tasa_si_anomalias != null ? ` · tasa de SI entre ellas ${pct(a.tasa_si_anomalias, 0)}` : ''}</p>${evaluado && a.evaluacion ? `<p class="mt-1 text-[11px] text-slate-700">recupera <b>${a.evaluacion.detectadas}/${a.evaluacion.inyectadas}</b> inyectadas · precision ${pct(a.evaluacion.precision, 0)} · recall ${pct(a.evaluacion.recall, 0)}</p>` : ''}</div>`; }).join('');
    const nombre = (k) => A[k].nombre;
    const coin = Object.entries(d.coincidencias).map(([par, n]) => { const [a, b] = par.split('|'); return `<li><b>${n}</b> señalados por ${esc(nombre(a))} y ${esc(nombre(b))}</li>`; }).join('');
    $('#resultados').innerHTML = `
      ${lectura(d.lectura, evaluado ? `Se añadieron ${d.parametros.inyectar} registros artificiales (marcados con un triángulo en el mapa) para medir cuántos recupera cada método; los registros reales cuentan como «normales» aunque algunos sean extremos.` : 'El dataset no incluye anomalías confirmadas; los métodos señalan los registros más alejados del comportamiento habitual.', d.recomendaciones)}
      <dl class="grid grid-cols-1 gap-3 md:grid-cols-3">${tarjetas}</dl>
      <div class="grid grid-cols-1 gap-4 xl:grid-cols-2">
        ${card('Mapa de anomalías', 'Los registros normales en gris; en rojo los que el método seleccionado considera anómalos.', canvasBox('ch-ano-scatter', 320), selectAlgo('sel-ano', A, rk, state.sel.anomalias))}
        <div class="space-y-4">
          ${card('Coincidencias entre métodos', 'Una anomalía es más creíble cuando varios métodos la señalan.', `<ul class="space-y-1 text-sm text-slate-700">${coin}<li><b>${d.en_todos}</b> señalados por los tres métodos a la vez</li><li><b>${d.en_alguno}</b> señalados por al menos uno (de ${d.n_total})</li></ul>`)}
          ${card('Anomalías por cultivo', 'Cuántos registros señala cada método en cada cultivo.', canvasBox('ch-ano-cultivo', 180))}
        </div>
      </div>
      ${evaluado ? card('Evaluación con anomalías inyectadas', 'Precision: de lo señalado, cuánto era inyectado · Recall: de lo inyectado, cuánto se detectó.', `<div class="table-wrap"><table class="table"><thead><tr><th class="text-left">Método</th><th class="text-right">Inyectadas detectadas</th>${th('anomalias', 'precision', 'Precision')}${th('anomalias', 'recall', 'Recall')}<th class="text-right">F1</th></tr></thead><tbody>${rk.map((k) => `<tr><td class="font-medium">${esc(A[k].nombre)}</td><td class="text-right font-mono">${A[k].evaluacion.detectadas} / ${A[k].evaluacion.inyectadas}</td><td class="text-right font-mono">${pct(A[k].evaluacion.precision, 1)}</td><td class="text-right font-mono">${pct(A[k].evaluacion.recall, 1)}</td><td class="text-right font-mono">${num(A[k].evaluacion.f1, 3)}</td></tr>`).join('')}</tbody></table></div>`) : ''}
      ${card('Registros más anómalos', 'Los 15 con mayor puntuación según el método seleccionado y la variable que más se desvía del promedio (en desviaciones estándar).', '<div id="ano-top"></div>')}`;
    const cultivos = ['cafe', 'papa', 'uva'];
    chart('ch-ano-cultivo', { type: 'bar', data: { labels: cultivos.map(etiquetaCultivo), datasets: rk.map((k, i) => ({ label: A[k].nombre, data: cultivos.map((c) => A[k].por_cultivo[c] || 0), backgroundColor: PALETA[i], borderRadius: 4 })) },
      options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: 'bottom', labels: { boxWidth: 12, font: { size: 10 } } } }, scales: { y: { grid: gridOpts, ticks: { precision: 0 } }, x: { grid: { display: false } } } } });
    const dibujar = () => {
      const k = state.sel.anomalias;
      const normales = d.puntos.filter((p) => !p[k]), anom = d.puntos.filter((p) => p[k] && !p.inyectada), iny = d.puntos.filter((p) => p[k] && p.inyectada);
      const ds = [{ label: 'Normal', data: normales, backgroundColor: 'rgba(148,163,184,.45)', pointRadius: 2.5 }, { label: 'Anómalo', data: anom, backgroundColor: '#e11d48', pointRadius: 4 }];
      if (evaluado) { ds.push({ label: 'Inyectado y detectado', data: iny, backgroundColor: '#f59e0b', pointStyle: 'triangle', pointRadius: 6 }); ds.push({ label: 'Inyectado no detectado', data: d.puntos.filter((p) => !p[k] && p.inyectada), backgroundColor: '#fde68a', borderColor: '#b45309', borderWidth: 1, pointStyle: 'triangle', pointRadius: 6 }); }
      chart('ch-ano-scatter', { type: 'scatter', data: { datasets: ds }, options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: 'bottom' }, tooltip: { callbacks: { label: (c) => ` ${c.dataset.label} · registro ${c.raw.id > 0 ? c.raw.id : 'artificial'} · ${etiquetaCultivo(c.raw.cultivo)}` } } }, scales: { x: { title: { display: true, text: 'Componente 1' }, grid: gridOpts }, y: { title: { display: true, text: 'Componente 2' }, grid: gridOpts } } } });
      const top = A[k].top;
      $('#ano-top').innerHTML = top.length ? `<div class="table-wrap"><table class="table"><thead><tr><th class="text-left">Registro</th><th class="text-left">Cultivo</th><th class="text-right">Temp. (°C)</th><th class="text-right">Hum. (%)</th><th class="text-right">Rad. (MJ/m²)</th><th class="text-right">Prec. (mm)</th><th class="text-right">Viento (km/h)</th><th class="text-left">Variable que más se desvía</th><th class="text-right">Puntuación</th></tr></thead><tbody>${top.map((t) => `<tr class="${t.inyectada ? 'bg-amber-50/60' : ''}"><td class="font-mono">${t.inyectada ? 'artificial' : `#${t.id}`}</td><td>${etiquetaCultivo(t.cultivo)} <span class="${t.resultado === 'SI' ? 'badge-si' : 'badge-no'}">${t.resultado}</span></td><td class="text-right font-mono">${num(t.temperatura, 1)}</td><td class="text-right font-mono">${num(t.humedad, 1)}</td><td class="text-right font-mono">${num(t.radiacion_solar, 1)}</td><td class="text-right font-mono">${num(t.precipitacion, 1)}</td><td class="text-right font-mono">${num(t.viento, 1)}</td><td>${VAR_LABEL[t.variable_principal]} <span class="${t.z_principal > 0 ? 'int-up' : 'int-down'}">(${t.z_principal > 0 ? '+' : ''}${num(t.z_principal, 1)} σ)</span></td><td class="text-right font-mono">${num(t.puntuacion, 2)}</td></tr>`).join('')}</tbody></table></div>` : '<p class="text-sm text-slate-500">Este método no señaló ningún registro con los ajustes actuales.</p>';
    };
    dibujar();
    $('#sel-ano').addEventListener('change', (e) => { state.sel.anomalias = e.target.value; dibujar(); });
  }

  // ═══════════════════════════ 5. SERIES TEMPORALES ═══════════════════════════
  function renderSeries(d) {
    const A = d.algoritmos, rk = d.ranking, u = d.meta.unidad || '';
    const detalle = (a) => { const x = a.detalle || {}; return [x.ventana != null ? `ventana ${x.ventana}` : '', x.alpha != null ? `α ${num(x.alpha, 2)}` : '', x.beta != null ? `β ${num(x.beta, 2)}` : '', x.orden ? `(${x.orden.join(', ')})` : '', x.aic != null ? `AIC ${num(x.aic, 0)}` : '', x.lags != null ? `${x.lags} valores previos` : '', x.estacionalidad ? `estacionalidad ${x.estacionalidad}` : '', x.tendencia_por_periodo != null ? `tendencia ${x.tendencia_por_periodo > 0 ? '+' : ''}${num(x.tendencia_por_periodo, 3)}/periodo` : ''].filter(Boolean).join(' · '); };
    const filas = rk.map((k, i) => { const a = A[k]; return `<tr class="${i === 0 && a.mae != null ? 'row-best' : ''}"><td class="font-medium text-slate-800">${esc(a.nombre)}${i === 0 && a.mae != null ? '<span class="badge-best">mejor</span>' : ''}</td><td class="text-right font-mono">${a.error ? '—' : num(a.mae, 3)}</td><td class="text-right font-mono">${a.error ? '—' : num(a.rmse, 3)}</td><td class="text-right font-mono">${a.mape != null ? `${num(a.mape, 1)}%` : '—'}</td><td class="text-xs text-slate-500">${a.error ? `<span class="text-rose-700">${esc(a.error)}</span>` : esc(detalle(a))}</td></tr>`; }).join('')
      + Object.values(d.baselines).map((b) => `<tr class="row-base"><td>${esc(b.nombre)} (referencia)</td><td class="text-right font-mono">${num(b.mae, 3)}</td><td class="text-right font-mono">${num(b.rmse, 3)}</td><td class="text-right font-mono">${b.mape != null ? `${num(b.mape, 1)}%` : '—'}</td><td></td></tr>`).join('');
    const opciones = [...rk.filter((k) => !A[k].error).map((k) => `<option value="${k}" ${k === state.sel.series ? 'selected' : ''}>${esc(A[k].nombre)}</option>`), '<option value="__todos">Todos los métodos (solo pronóstico)</option>'].join('');
    $('#resultados').innerHTML = `
      ${lectura(d.lectura, `${d.meta.descripcion || ''}. ${d.meta.nota || ''} Se usan ${d.n_train} puntos para ajustar y los últimos ${d.n_test} para comprobar; después se pronostican ${d.futuro} periodos más.`, d.recomendaciones)}
      ${card('Serie, ajuste y pronóstico', 'Línea gris: valores reales (la parte final, más oscura, es el tramo de prueba). Línea de color: lo que el método habría pronosticado para ese tramo; punteada: pronóstico futuro.', canvasBox('ch-ser-linea', 320), `<label class="text-xs text-slate-500">Método <select id="sel-ser" class="select-sm ml-1">${opciones}</select></label>`)}
      <div class="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
        ${card('Comparación de métodos', `Error del pronóstico sobre los últimos ${d.n_test} puntos (${u}).`, `<div class="table-wrap"><table class="table"><thead><tr><th class="text-left">Método</th>${th('series', 'mae', 'MAE')}${th('series', 'rmse', 'RMSE')}${th('series', 'mape', 'MAPE')}<th class="text-left">Ajustes</th></tr></thead><tbody>${filas}</tbody></table></div>`)}
        ${card('Error medio por método', 'MAE: las barras grises son las referencias simples.', canvasBox('ch-ser-mae', 260))}
      </div>`;
    const validos = rk.filter((k) => A[k].mae != null);
    const bases = Object.values(d.baselines);
    chart('ch-ser-mae', { type: 'bar', data: { labels: [...validos.map((k) => A[k].nombre), ...bases.map((b) => b.nombre)], datasets: [{ data: [...validos.map((k) => A[k].mae), ...bases.map((b) => b.mae)], backgroundColor: [...validos.map((_, i) => (i === 0 ? '#059669' : '#2546e8')), ...bases.map(() => '#94a3b8')], borderRadius: 6 }] },
      options: { indexAxis: 'y', responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false }, tooltip: { callbacks: { label: (c) => ` MAE ${num(c.raw, 3)} ${u}` } } }, scales: { x: { grid: gridOpts, title: { display: true, text: `MAE (${u})` } }, y: { grid: { display: false }, ticks: { font: { size: 10 } } } } } });
    const dibujar = () => {
      const k = $('#sel-ser').value;
      const n = d.n, nTr = d.n_train, fut = d.futuro;
      const labels = [...d.etiquetas, ...Array.from({ length: fut }, (_, i) => `+${i + 1}`)];
      const serieTrain = d.valores.map((v, i) => (i < nTr ? v : null)).concat(Array(fut).fill(null));
      const serieTest = d.valores.map((v, i) => (i >= nTr - 1 ? v : null)).concat(Array(fut).fill(null));
      const ds = [{ label: 'Real (ajuste)', data: serieTrain, borderColor: '#94a3b8', borderWidth: 1.5, pointRadius: 0, tension: 0.2 }, { label: 'Real (prueba)', data: serieTest, borderColor: '#334155', borderWidth: 2, pointRadius: 0, tension: 0.2 }];
      const metodos = k === '__todos' ? validos : [k];
      metodos.forEach((m, i) => {
        const a = A[m]; const color = k === '__todos' ? PALETA[i % PALETA.length] : '#2546e8';
        if (k !== '__todos' && a.ajuste) ds.push({ label: 'Ajuste del método', data: a.ajuste.concat(Array(n - nTr + fut).fill(null)), borderColor: 'rgba(37,70,232,.45)', borderDash: [3, 3], borderWidth: 1.5, pointRadius: 0, tension: 0.2 });
        ds.push({ label: k === '__todos' ? a.nombre : 'Pronóstico (tramo de prueba)', data: Array(nTr - 1).fill(null).concat([d.valores[nTr - 1]], a.pronostico_test).concat(Array(fut).fill(null)), borderColor: color, borderWidth: 2.5, pointRadius: 0, tension: 0.2 });
        if (k !== '__todos') ds.push({ label: 'Pronóstico futuro', data: Array(n - 1).fill(null).concat([d.valores[n - 1]], a.futuro), borderColor: '#7c3aed', borderDash: [6, 4], borderWidth: 2, pointRadius: 0, tension: 0.2 });
      });
      chart('ch-ser-linea', { type: 'line', data: { labels, datasets: ds }, options: { responsive: true, maintainAspectRatio: false, spanGaps: false, interaction: { mode: 'index', intersect: false }, plugins: { legend: { position: 'bottom', labels: { boxWidth: 14, font: { size: 10 } } } }, scales: { x: { grid: { display: false }, ticks: { maxTicksLimit: 14, font: { size: 10 } } }, y: { grid: gridOpts, title: { display: true, text: u } } } } });
    };
    dibujar();
    $('#sel-ser').addEventListener('change', (e) => { state.sel.series = e.target.value; dibujar(); });
  }

  // ───────────────────────────── arranque ─────────────────────────────────────
  async function init() {
    renderTipos();
    renderGlosario('regresion');
    $('#btn-ejecutar').addEventListener('click', ejecutarAnalisis);
    await MLOPS.listo;
    if (!modoEstatico()) {
      try {
        state.catalogo = await api('/api/analisis/catalogo');
        renderTipos();
        $('#k-filas').textContent = `${state.catalogo.n_filas ?? '—'} registros`;
      } catch (e) { aviso(`No se pudo cargar el catálogo de análisis: ${e.message}`); }
    } else {
      $('#k-filas').textContent = 'sin conexión';
    }
    const hash = (location.hash || '').replace('#', '');
    seleccionarTipo(state.catalogo.tipos.some((t) => t.id === hash) ? hash : 'regresion');
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})();
