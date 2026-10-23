/* ============================================================================
 * dashboard/resultados.js
 * Página /resultados: carga output/resultado.json desde la API, lo muestra
 * (KPIs, tabla de variables, distribuciones, árbol navegable y JSON resaltado)
 * y ofrece descarga (JSON / CSV), copia al portapapeles y re-procesado.
 * ========================================================================== */
(() => {
  'use strict';

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
  const son = (n, e) => { try { if (window.SONIDOS) window.SONIDOS.reproducir(n, e); } catch (_) { /* sin audio */ } };
  const esc = (s) => String(s).replace(/[<>&"]/g, (c) => ({ '<': '&lt;', '>': '&gt;', '&': '&amp;', '"': '&quot;' }[c]));
  const fmtNum = (v, d = 2) => (v === null || v === undefined || Number.isNaN(v)) ? '—' : Number(v).toFixed(d);
  const fmtPct = (v, d = 0) => (v === null || v === undefined) ? '—' : `${(v * 100).toFixed(d)}%`;
  const LABELS = { temperatura: 'Temperatura (°C)', humedad: 'Humedad (%)', radiacion_solar: 'Radiación solar (MJ/m²)', precipitacion: 'Precipitación (mm)', viento: 'Viento (km/h)' };
  const CULTIVO_COLORS = { cafe: '#b45309', papa: '#7c3aed', uva: '#0e7490' };

  let datos = null;
  let metricasModelo;   // undefined = aún no se intentó cargar; null = no disponibles
  // Modo estático: la página se abrió sin la API (visor de archivos, file://…). Entonces lee
  // ../output/resultado.json y las copias de ../output/exportaciones/ (rutas relativas a la página).
  const ESTATICO = { resultado: '../output/resultado.json', carpeta: '../output/exportaciones/', indice: '../output/exportaciones/index.json' };
  const modoEstatico = () => !MLOPS.base;

  async function api(path, opts = {}) {
    const res = await fetch(MLOPS.url(path), { headers: { 'Content-Type': 'application/json' }, ...opts });
    if (!res.ok) {
      let detail = res.statusText;
      try { detail = (await res.json()).detail || detail; } catch { /* ignore */ }
      throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail));
    }
    return res.json();
  }

  function setEstado(msg, ok = true) {
    const el = $('#estado'); el.textContent = msg; el.className = `text-xs ${ok ? 'text-emerald-700' : 'text-rose-700'}`;
    if (msg) setTimeout(() => { if (el.textContent === msg) el.textContent = ''; }, 5000);
  }

  // Ciudad asociada a cada cultivo (cafe → Chanchamayo, papa → Huancayo, uva → Ica); se lee del resultado si está disponible
  const CIUDAD_BASE = { cafe: 'chanchamayo', papa: 'huancayo', uva: 'ica' };
  const cap = (s) => s ? String(s).charAt(0).toUpperCase() + String(s).slice(1) : '';
  const ciudadDe = (r, cultivo) => ((r && r.ciudad_por_cultivo) || CIUDAD_BASE)[cultivo] || null;
  const etiquetaCultivo = (r, cultivo) => ciudadDe(r, cultivo) ? `${cultivo} · ${cap(ciudadDe(r, cultivo))}` : cultivo;

  // ─────────────────────────────── KPIs ──────────────────────────────────────
  function renderKPIs(r, tamano) {
    const total = r.filas_totales || 0;
    const dist = r.distribucion_resultado || {};
    const si = dist.SI || 0, no = dist.NO || 0;
    const cultivos = Object.keys(r.distribucion_cultivo || {}).sort();
    $('#k-filas').textContent = total;
    $('#k-origen').textContent = 'registros procesados';
    $('#k-validas').textContent = r.filas_validas ?? '—';
    $('#k-validas-pct').textContent = total ? `${fmtPct(r.filas_validas / total, 1)} del total` : '—';
    $('#k-invalidas').textContent = r.filas_invalidas ?? '—';
    $('#k-si-no').textContent = `${si} / ${no}`;
    $('#k-tasa-si').textContent = (si + no) ? `tasa de SI ${fmtPct(si / (si + no), 1)}` : '—';
    $('#k-cultivos').textContent = cultivos.length;
    $('#k-cultivos-lista').textContent = cultivos.map((c) => etiquetaCultivo(r, c)).join(' / ') || '—';
    const fecha = r.fecha_ejecucion ? new Date(r.fecha_ejecucion) : null;
    $('#k-fecha').textContent = fecha ? fecha.toLocaleDateString('es-PE', { day: '2-digit', month: '2-digit', year: 'numeric' }) + ' ' + fecha.toLocaleTimeString('es-PE', { hour: '2-digit', minute: '2-digit', hour12: false }) : '—';
    $('#k-tamano').textContent = tamano ? `${(tamano / 1024).toFixed(1)} KB` : '';
  }

  // ─────────────────────────────── tabla de variables ────────────────────────
  function renderTabla(r) {
    const cols = r.columnas_numericas || {};
    const cultivos = Object.keys(r.promedio_por_cultivo || {}).sort();
    $('#tabla-vars thead').innerHTML = `<tr><th class="text-left">Variable</th><th class="text-right">Válidos</th><th class="text-right">Inválidos</th>
      <th class="text-right">Mín</th><th class="text-right">Promedio</th><th class="text-right">Máx</th><th class="text-left w-40">Posición del promedio</th>
      ${cultivos.map((c) => `<th class="text-right">Prom. ${esc(etiquetaCultivo(r, c))} <span class="lowercase text-slate-400">(SI ${fmtPct((r.tasa_si_por_cultivo || {})[c])})</span></th>`).join('')}</tr>`;
    $('#tabla-vars tbody').innerHTML = Object.entries(cols).map(([f, c]) => {
      const rango = (c.max - c.min) || 1; const pos = Math.max(0, Math.min(100, ((c.promedio - c.min) / rango) * 100));
      return `<tr>
        <td class="font-sans text-slate-800">${esc(LABELS[f] || f)}</td>
        <td class="text-right">${c.validos}</td>
        <td class="text-right ${c.invalidos ? 'text-rose-600 font-medium' : 'text-slate-400'}">${c.invalidos}</td>
        <td class="text-right">${fmtNum(c.min, 1)}</td>
        <td class="text-right font-medium text-brand-700">${fmtNum(c.promedio, 2)}</td>
        <td class="text-right">${fmtNum(c.max, 1)}</td>
        <td><div class="relative h-2 w-36 rounded-full bg-slate-100"><div class="absolute inset-y-0 left-0 mini-bar" style="width:${pos}%" data-ancho="${pos}%"></div></div></td>
        ${cultivos.map((cu) => `<td class="text-right">${fmtNum((r.promedio_por_cultivo[cu] || {})[f], 2)}</td>`).join('')}
      </tr>`;
    }).join('');
  }

  // ─────────────────────────────── distribuciones ────────────────────────────
  function barra(label, valor, total, color, extra = '') {
    const pct = total ? (valor / total) * 100 : 0;
    return `<div>
      <div class="flex items-baseline justify-between text-xs"><span class="font-medium text-slate-700">${esc(label)}</span>
        <span class="font-mono text-slate-500"><b class="text-slate-900">${valor}</b> · ${pct.toFixed(1)}%${extra}</span></div>
      <div class="mt-1 h-2.5 w-full rounded-full bg-slate-100"><div class="h-full rounded-full transition-all duration-700" style="width:${pct}%;background:${color}" data-ancho="${pct}%"></div></div>
    </div>`;
  }
  function renderDistribuciones(r) {
    const dr = r.distribucion_resultado || {}; const totalR = Object.values(dr).reduce((a, b) => a + b, 0);
    $('#dist-resultado').innerHTML = ['SI', 'NO'].filter((k) => k in dr).concat(Object.keys(dr).filter((k) => !['SI', 'NO'].includes(k)))
      .map((k) => barra(`Resultado ${k}`, dr[k], totalR, k === 'SI' ? '#7c3aed' : '#64748b')).join('') || '<p class="text-xs text-slate-400">Sin datos.</p>';
    const dc = r.distribucion_cultivo || {}; const totalC = Object.values(dc).reduce((a, b) => a + b, 0);
    $('#dist-cultivo').innerHTML = Object.keys(dc).sort().map((c) => barra(etiquetaCultivo(r, c), dc[c], totalC, CULTIVO_COLORS[c] || '#2546e8',
      ` · <span class="text-violet-700">SI ${fmtPct((r.tasa_si_por_cultivo || {})[c])}</span>`)).join('') || '<p class="text-xs text-slate-400">Sin datos.</p>';
    // ciudad: variable predictora que acompaña al cultivo
    const dci = r.distribucion_ciudad || {}; const mapa = r.ciudad_por_cultivo || {};
    const cont = $('#dist-ciudad');
    if (!cont) return;
    if (!Object.keys(dci).length) { cont.classList.add('hidden'); return; }
    cont.classList.remove('hidden');
    const cultivoDe = (ci) => Object.keys(mapa).find((cu) => mapa[cu] === ci);
    cont.innerHTML = `<p class="text-[11px] font-medium uppercase tracking-wider text-slate-500">Ciudad (variable del modelo)</p>
      <div class="mt-2 flex flex-wrap gap-2">${Object.keys(dci).sort().map((ci) => {
        const cu = cultivoDe(ci); const color = (cu && CULTIVO_COLORS[cu]) || '#2546e8';
        return `<span class="inline-flex items-center gap-1.5 rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1 text-xs text-slate-700">
          <span class="h-2 w-2 rounded-full" style="background:${color}"></span>${esc(cap(ci))}${cu ? ` <span class="text-slate-400">(${esc(cu)})</span>` : ''}
          <b class="font-mono text-slate-900">${dci[ci]}</b><span class="text-violet-700">SI ${fmtPct((r.tasa_si_por_ciudad || {})[ci])}</span></span>`;
      }).join('')}</div>`;
  }

  // ─────────────────────────────── JSON resaltado ────────────────────────────
  function resaltar(json) {
    return esc(JSON.stringify(json, null, 2)).replace(
      /("(\\u[a-zA-Z0-9]{4}|\\[^u]|[^\\"])*"(\s*:)?|\b(true|false)\b|\bnull\b|-?\d+(?:\.\d*)?(?:[eE][+-]?\d+)?)/g,
      (m) => {
        let cls = 'json-num';
        if (/^"/.test(m)) cls = /:$/.test(m) ? 'json-key' : 'json-str';
        else if (/true|false/.test(m)) cls = 'json-bool';
        else if (/null/.test(m)) cls = 'json-null';
        return `<span class="${cls}">${m}</span>`;
      });
  }

  // ─────────────────────────────── árbol navegable ───────────────────────────
  function nodo(clave, valor, nivel) {
    const esObj = valor !== null && typeof valor === 'object';
    if (!esObj) {
      const cls = typeof valor === 'string' ? 'json-str' : typeof valor === 'number' ? 'json-num' : typeof valor === 'boolean' ? 'json-bool' : 'json-null';
      const txt = typeof valor === 'string' ? `"${esc(valor)}"` : String(valor);
      return `<div class="tree-row"><span class="tree-toggle"></span><span class="json-key">${esc(clave)}</span><span class="text-slate-400">:</span><span class="${cls}">${txt}</span></div>`;
    }
    const esArr = Array.isArray(valor); const n = esArr ? valor.length : Object.keys(valor).length;
    const abierto = nivel < 1;
    const hijos = (esArr ? valor.map((v, i) => [i, v]) : Object.entries(valor)).map(([k, v]) => nodo(k, v, nivel + 1)).join('');
    return `<details class="tree-details" ${abierto ? 'open' : ''}>
      <summary class="tree-row cursor-pointer list-none"><span class="tree-toggle">▸</span><span class="json-key">${esc(clave)}</span>
        <span class="text-slate-400">${esArr ? `[${n}]` : `{${n}}`}</span></summary>
      <div class="tree-node">${hijos}</div></details>`;
  }
  function renderArbol(r) {
    $('#vista-arbol').innerHTML = Object.entries(r).map(([k, v]) => nodo(k, v, 0)).join('');
  }


  // ─────────────────────────────── interpretación ────────────────────────────
  // Texto en lenguaje sencillo generado a partir de las cifras actuales (no está escrito a mano:
  // cambia si cambian los datos). Cubre calidad de datos, balance SI/NO, cultivos y ciudades,
  // condiciones climáticas, perfil de cada cultivo, qué distingue a los casos SI, el modelo y límites.
  const VAR_INFO = {
    temperatura:     { nombre: 'temperatura',     unidad: '°C',    alto: 'más cálido',   bajo: 'más frío',       masSI: 'más temperatura',      menosSI: 'menos temperatura' },
    humedad:         { nombre: 'humedad',         unidad: '%',     alto: 'más húmedo',   bajo: 'más seco',       masSI: 'más humedad',          menosSI: 'menos humedad' },
    radiacion_solar: { nombre: 'radiación solar', unidad: 'MJ/m²', alto: 'más soleado',  bajo: 'menos soleado',  masSI: 'más radiación solar',  menosSI: 'menos radiación solar' },
    precipitacion:   { nombre: 'precipitación',   unidad: 'mm',    alto: 'más lluvioso', bajo: 'menos lluvioso', masSI: 'más lluvia',           menosSI: 'menos lluvia' },
    viento:          { nombre: 'viento',          unidad: 'km/h',  alto: 'más ventoso',  bajo: 'menos ventoso',  masSI: 'más viento',           menosSI: 'menos viento', m: true },
  };
  const NOMBRE_CULTIVO = { cafe: 'café', papa: 'papa', uva: 'uva' };
  const nomCultivo = (r, c) => `${NOMBRE_CULTIVO[c] || c}${ciudadDe(r, c) ? ` · ${cap(ciudadDe(r, c))}` : ''}`;
  const pct = (v, d = 0) => fmtPct(v, d);
  const signo = (v, d = 0) => `${v >= 0 ? '+' : '−'}${Math.abs(v * 100).toFixed(d)}%`;
  const lista = (arr) => arr.length <= 1 ? (arr[0] || '') : `${arr.slice(0, -1).join(', ')} y ${arr[arr.length - 1]}`;
  const bloque = (icono, titulo, cuerpo) => `<article class="int-bloque"><h3><span aria-hidden="true">${icono}</span>${esc(titulo)}</h3><div class="mt-2">${cuerpo}</div></article>`;
  const chip = (t) => `<span class="int-chip">${esc(t)}</span>`;
  const varNom = (f) => (VAR_INFO[f] || {}).nombre || f;
  const varUni = (f) => (VAR_INFO[f] || {}).unidad || '';
  const varM = (f) => !!(VAR_INFO[f] || {}).m;                      // ¿sustantivo masculino?
  const varArt = (f, b = false) => `${varM(f) ? 'el' : 'la'} ${b ? `<b>${varNom(f)}</b>` : varNom(f)}`;

  function interpretarCalidad(r) {
    const total = r.filas_totales || 0, validas = r.filas_validas ?? total, invalidas = r.filas_invalidas || 0;
    const cols = r.columnas_numericas || {};
    const nulos = Object.values(cols).reduce((a, c) => a + (c.nulos_originales || 0), 0);
    const malas = Object.entries(cols).filter(([, c]) => (c.invalidos || 0) > 0).map(([f, c]) => `${varNom(f)} (${c.invalidos})`);
    const partes = [];
    if (!invalidas && !nulos) {
      partes.push(`<p>Se procesaron <b>${total} registros</b> y <b>todos son válidos</b>: ninguno tenía valores vacíos o no numéricos, así que no se descartó nada y las estadísticas representan el conjunto completo.</p>`);
    } else {
      partes.push(`<p>De <b>${total} registros</b>, <b>${validas}</b> son válidos (${pct(total ? validas / total : 0, 1)}) y <b>${invalidas}</b> se descartaron por tener valores incorrectos${malas.length ? ` en ${lista(malas)}` : ''}.${nulos ? ` Además había <b>${nulos}</b> casillas vacías de origen.` : ''} Conviene revisar la fuente de esos datos antes de volver a procesarlos.</p>`);
    }
    const corr = r.ciudad_inconsistentes_corregidas || 0;
    partes.push(corr
      ? `<p>En <b>${corr}</b> registros la ciudad no coincidía con la del cultivo y se corrigió automáticamente (café · Chanchamayo, papa · Huancayo, uva · Ica).</p>`
      : `<p>La ciudad de cada registro coincide con la que corresponde a su cultivo (café · Chanchamayo, papa · Huancayo, uva · Ica): no hubo que corregir nada.</p>`);
    const ncol = (r.columnas || []).length;
    if (ncol) partes.push(`<p>Cada registro tiene <b>${ncol} columnas</b>: identificador, cultivo, ciudad, ${Object.keys(cols).length} condiciones climáticas y el resultado.</p>`);
    const od = r.origen_datos;
    if (od && od.filas_generadas) {
      partes.push(`<p><b>Procedencia:</b> ${od.filas_originales ? `<b>${od.filas_originales}</b> registros originales más ` : ''}<b>${od.filas_generadas}</b> registros generados a partir de ellos (mismas proporciones de cultivo, condiciones climáticas parecidas por cultivo y resultado sorteado con la relación clima ↔ resultado de los datos originales). Sirven para probar el flujo con más volumen, pero <b>no son observaciones reales</b>.</p>`);
    }
    return bloque('🧹', 'Calidad de los datos', partes.join(''));
  }

  function interpretarBalance(r) {
    const d = r.distribucion_resultado || {}; const si = d.SI || 0, no = d.NO || 0, tot = si + no;
    if (!tot) return bloque('⚖️', 'Balance del resultado', '<p>No hay registros con resultado.</p>');
    const pSi = si / tot, ratio = si ? (no / si) : null;
    const estado = pSi < 0.3 || pSi > 0.7 ? 'claramente desbalanceado' : pSi < 0.4 || pSi > 0.6 ? 'algo desbalanceado' : 'razonablemente equilibrado';
    const partes = [`<p><b>${si}</b> registros terminaron en <b>SI</b> (${pct(pSi, 1)}) y <b>${no}</b> en <b>NO</b> (${pct(1 - pSi, 1)}). El conjunto está <b>${estado}</b>${ratio ? `: por cada caso SI hay ${fmtNum(ratio, 1)} casos NO` : ''}.</p>`];
    if (pSi < 0.4) {
      partes.push(`<p>Esto importa al leer cualquier porcentaje de acierto: un sistema que respondiera siempre «NO» acertaría el <b>${pct(1 - pSi, 0)}</b> de las veces sin haber aprendido nada. Por eso, más que el acierto global, interesa <b>cuántos SI reales se detectan</b>.</p>`);
    } else if (pSi > 0.6) {
      partes.push(`<p>Al predominar el SI, un sistema que respondiera siempre «SI» acertaría el <b>${pct(pSi, 0)}</b> de las veces; conviene fijarse en cuántos NO reales se reconocen.</p>`);
    } else {
      partes.push('<p>Con las dos clases presentes en proporciones parecidas, el porcentaje de acierto global es una medida razonable del desempeño.</p>');
    }
    return bloque('⚖️', 'Balance del resultado (SI / NO)', partes.join(''));
  }

  function interpretarCultivos(r) {
    const dc = r.distribucion_cultivo || {}; const tot = Object.values(dc).reduce((a, b) => a + b, 0);
    const tasas = r.tasa_si_por_cultivo || {}; const conteo = r.conteo_cultivo_resultado || {};
    const cultivos = Object.keys(dc);
    if (!cultivos.length) return bloque('🌱', 'Cultivos y ciudades', '<p>Sin datos por cultivo.</p>');
    const orden = [...cultivos].sort((a, b) => (tasas[b] || 0) - (tasas[a] || 0));
    const items = orden.map((c) => {
      const n = dc[c] || 0; const nSi = conteo[c] ? (conteo[c].SI || 0) : Math.round((tasas[c] || 0) * n);
      return `<li><span><b>${esc(nomCultivo(r, c))}</b>: ${n} registros (${pct(tot ? n / tot : 0)} del total), <b>${nSi}</b> con SI → tasa de SI <b>${pct(tasas[c], 1)}</b>.</span></li>`;
    }).join('');
    const top = orden[0], bottom = orden[orden.length - 1];
    const brecha = ((tasas[top] || 0) - (tasas[bottom] || 0)) * 100;
    const mayor = [...cultivos].sort((a, b) => dc[b] - dc[a])[0];
    const partes = [`<ul>${items}</ul>`];
    if (cultivos.length > 1) {
      partes.push(`<p>El cultivo con <b>mayor</b> proporción de SI es <b>${esc(nomCultivo(r, top))}</b> y el de <b>menor</b>, <b>${esc(nomCultivo(r, bottom))}</b>: una brecha de <b>${brecha.toFixed(0)} puntos porcentuales</b>, ${brecha >= 20 ? 'lo que indica que el tipo de cultivo es un factor muy relevante en el resultado' : brecha >= 10 ? 'una diferencia apreciable: el tipo de cultivo influye en el resultado' : 'una diferencia pequeña: el tipo de cultivo influye poco por sí solo'}. El cultivo con más registros es <b>${esc(nomCultivo(r, mayor))}</b> (${dc[mayor]}).</p>`);
    }
    partes.push('<p>Como cada cultivo se registró en una sola ciudad, <b>cultivo y ciudad cuentan lo mismo</b>: con estos datos no se puede separar el efecto del cultivo del de la ciudad. Por eso en toda la página aparecen en pareja.</p>');
    return bloque('🌱', 'Cultivos y ciudades', partes.join(''));
  }

  function interpretarClima(r) {
    const cols = r.columnas_numericas || {}; const porC = r.promedio_por_cultivo || {};
    const feats = Object.keys(cols);
    if (!feats.length) return bloque('🌦️', 'Condiciones climáticas', '<p>Sin variables numéricas.</p>');
    const items = feats.map((f) => {
      const c = cols[f]; const u = varUni(f);
      const cults = Object.keys(porC).filter((cu) => porC[cu] && porC[cu][f] != null).sort((a, b) => porC[b][f] - porC[a][f]);
      const extremos = cults.length > 1 ? ` El promedio más alto es el de <b>${esc(nomCultivo(r, cults[0]))}</b> (${fmtNum(porC[cults[0]][f], 1)} ${u}) y el más bajo el de <b>${esc(nomCultivo(r, cults[cults.length - 1]))}</b> (${fmtNum(porC[cults[cults.length - 1]][f], 1)} ${u}).` : '';
      const cv = c.desviacion != null && c.promedio ? c.desviacion / Math.abs(c.promedio) : null;
      const variab = cv == null ? '' : cv >= 0.5 ? ' <b>Varía mucho</b> de un registro a otro.' : cv >= 0.25 ? ' Varía moderadamente entre registros.' : ' Es bastante estable entre registros.';
      return `<li><span><b>${esc(cap(varNom(f)))}</b>: promedio <b>${fmtNum(c.promedio, 1)} ${u}</b>${c.mediana != null ? ` (mediana ${fmtNum(c.mediana, 1)})` : ''}, entre ${fmtNum(c.min, 1)} y ${fmtNum(c.max, 1)} ${u}.${extremos}${variab}</span></li>`;
    }).join('');
    return bloque('🌦️', 'Condiciones climáticas registradas', `<ul>${items}</ul>`);
  }

  function interpretarPerfiles(r) {
    const gen = r.promedio_general || {}; const porC = r.promedio_por_cultivo || {};
    const cultivos = Object.keys(porC);
    if (!cultivos.length) return bloque('🧭', 'Perfil de cada cultivo', '<p>Sin promedios por cultivo.</p>');
    const items = cultivos.sort().map((cu) => {
      const difs = Object.keys(gen).filter((f) => gen[f] && porC[cu] && porC[cu][f] != null)
        .map((f) => ({ f, rel: (porC[cu][f] - gen[f]) / Math.abs(gen[f]) }))
        .sort((a, b) => Math.abs(b.rel) - Math.abs(a.rel));
      const marcadas = difs.filter((d) => Math.abs(d.rel) >= 0.08);
      const frases = marcadas.map((d) => `<span class="${d.rel > 0 ? 'int-up' : 'int-down'}">${(VAR_INFO[d.f] || {})[d.rel > 0 ? 'alto' : 'bajo'] || varNom(d.f)}</span> (${signo(d.rel)})`);
      const iguales = difs.filter((d) => Math.abs(d.rel) < 0.08).map((d) => varNom(d.f));
      const texto = frases.length
        ? `${lista(frases)} que el promedio general${iguales.length ? `; en ${lista(iguales)} se parece al promedio` : ''}.`
        : 'condiciones muy cercanas al promedio general en todas las variables.';
      return `<li><span><b>${esc(nomCultivo(r, cu))}</b> (tasa de SI ${pct((r.tasa_si_por_cultivo || {})[cu], 0)}): ${texto}</span></li>`;
    }).join('');
    return bloque('🧭', 'Perfil climático de cada cultivo', `<p>Comparado con el promedio de todos los registros:</p><ul>${items}</ul>`);
  }

  // Fuerza de la relación entre una variable y el SI a partir de la tasa de SI por tercios (bajo / medio / alto)
  function efectoTercios(t) {
    if (!t || !t.bajo || !t.alto || t.bajo.tasa_si == null || t.alto.tasa_si == null) return null;
    const b = t.bajo.tasa_si, m = (t.medio || {}).tasa_si ?? null, a = t.alto.tasa_si;
    const r = (x, y) => (Math.min(x, y) > 0 ? Math.max(x, y) / Math.min(x, y) : (Math.max(x, y) > 0 ? 9 : 1));
    const ext = r(a, b);
    // el tercio medio «destaca» solo si se separa claramente de AMBOS extremos
    const medio = m == null ? null : (m > Math.max(b, a) * 1.4 ? 'max' : m < Math.min(b, a) / 1.4 ? 'min' : null);
    const razon = medio ? Math.max(b, m, a) / Math.max(Math.min(b, m, a), 1e-9) : ext;
    const fuerza = razon >= 2.5 ? 'fuerte' : razon >= 1.6 ? 'moderada' : razon >= 1.25 ? 'leve' : 'nula';
    const forma = fuerza === 'nula' ? 'sin efecto claro' : medio === 'max' ? 'destacan los valores medios' : medio === 'min' ? 'destacan los valores extremos' : a > b ? 'a más valor, más SI' : 'a más valor, menos SI';
    return { b, m, a, razon: Math.min(razon, 9), fuerza, forma, sube: a > b, medio, limites: t.limites || [] };
  }
  // «temperatura alta (desde 22.4 °C)» · «viento medio (entre 5.3 y 7.9 km/h)» · «humedad baja (hasta 62.7 %)»
  function condicionTexto(f, e) {
    const u = varUni(f), L = e.limites;
    const g = varM(f) ? 'o' : 'a';
    if (e.medio === 'max') return `${varNom(f)} medi${g}${L.length === 2 ? ` (entre ${fmtNum(L[0], 1)} y ${fmtNum(L[1], 1)} ${u})` : ''}`;
    if (e.medio === 'min') return `${varNom(f)} baj${g} o alt${g}${L.length === 2 ? ` (fuera de ${fmtNum(L[0], 1)}–${fmtNum(L[1], 1)} ${u})` : ''}`;
    return e.sube ? `${varNom(f)} alt${g}${L.length === 2 ? ` (desde ${fmtNum(L[1], 1)} ${u})` : ''}` : `${varNom(f)} baj${g}${L.length === 2 ? ` (hasta ${fmtNum(L[0], 1)} ${u})` : ''}`;
  }
  const tasaMejor = (e) => e.medio === 'max' ? e.m : e.medio === 'min' ? Math.max(e.b, e.a) : (e.sube ? e.a : e.b);
  const tasaPeor = (e) => e.medio === 'max' ? Math.min(e.b, e.a) : e.medio === 'min' ? e.m : (e.sube ? e.b : e.a);
  const etiquetaMasSI = (f, e) => e.medio === 'max' ? `${varNom(f)} medi${varM(f) ? 'o' : 'a'}` : e.medio === 'min' ? `${varNom(f)} baj${varM(f) ? 'o' : 'a'} o alt${varM(f) ? 'o' : 'a'}` : ((VAR_INFO[f] || {})[e.sube ? 'masSI' : 'menosSI'] || varNom(f));
  const efectosDe = (terc) => Object.keys(terc || {}).map((f) => ({ f, e: efectoTercios(terc[f]) })).filter((x) => x.e).sort((a, b) => b.e.razon - a.e.razon);

  const miniBarras = (b, m, a) => {
    const mx = Math.max(b, m ?? 0, a, 0.01);
    const barra = (v, lab) => `<span class="int-mini" title="${lab}: ${pct(v, 0)}"><span style="height:${Math.max(8, Math.round(v / mx * 100))}%"></span></span>`;
    return `<span class="int-minis" aria-hidden="true">${barra(b, 'tercio bajo')}${m != null ? barra(m, 'tercio medio') : ''}${barra(a, 'tercio alto')}</span>`;
  };

  function interpretarSI(r) {
    const pr = r.promedio_por_resultado;
    if (!pr || !pr.SI || !pr.NO) {
      return bloque('🔎', 'Qué distingue a los casos SI', '<p>Esta comparación se calcula al procesar los datos. Pulsa <b>«Volver a procesar los datos»</b> para generarla con la versión más reciente.</p>');
    }
    const terc = r.tasa_si_por_tercio || {};
    const feats = Object.keys(pr.SI).filter((f) => pr.NO[f] != null);
    const filas = feats.map((f) => {
      const e = efectoTercios(terc[f]);
      const rel = (pr.SI[f] - pr.NO[f]) / Math.abs(pr.NO[f] || 1);
      return { f, e, rel, si: pr.SI[f], no: pr.NO[f] };
    }).sort((a, b) => ((b.e ? b.e.razon : 1) - (a.e ? a.e.razon : 1)) || (Math.abs(b.rel) - Math.abs(a.rel)));
    const conEfecto = filas.filter((x) => x.e && x.e.fuerza !== 'nula'), sinEfecto = filas.filter((x) => !x.e || x.e.fuerza === 'nula');
    const items = filas.map(({ f, e, rel, si, no }) => {
      const u = varUni(f);
      if (e) {
        const lim = e.limites.length === 2 ? ` (bajo: hasta ${fmtNum(e.limites[0], 1)} ${u} · alto: desde ${fmtNum(e.limites[1], 1)} ${u})` : '';
        const frase = e.fuerza === 'nula'
          ? `la tasa de SI apenas cambia entre tercios: ${pct(e.b, 0)} → ${pct(e.m ?? e.b, 0)} → ${pct(e.a, 0)}${lim.replace(/^ \((.*)\)$/, ' ($1)')}; <b>no marca la diferencia por sí sola</b>`
          : `la tasa de SI es <b>${pct(e.b, 0)}</b> en el tercio bajo, <b>${pct(e.m ?? e.b, 0)}</b> en el medio y <b>${pct(e.a, 0)}</b> en el alto${lim}: relación <b>${e.fuerza}</b>, ${e.forma} (×${fmtNum(e.razon, 1)} entre el tercio con menos y con más SI)`;
        return `<li><span>${miniBarras(e.b, e.m, e.a)}<b>${esc(cap(varNom(f)))}</b>: ${frase}. Promedio ${fmtNum(si, 1)} ${u} en los SI frente a ${fmtNum(no, 1)} ${u} en los NO.</span></li>`;
      }
      return `<li><span><b>${esc(cap(varNom(f)))}</b>: ${fmtNum(si, 1)} ${u} en los SI frente a ${fmtNum(no, 1)} ${u} en los NO (<span class="${Math.abs(rel) < 0.05 ? '' : rel > 0 ? 'int-up' : 'int-down'}">${signo(rel)}</span>).</span></li>`;
    }).join('');
    const base = '<p>Para ver qué condiciones acompañan al SI, cada variable se divide en tres tercios (valores bajos, medios y altos) y se mira qué proporción de registros termina en SI en cada uno.';
    const intro = conEfecto.length
      ? `${base} Con más SI aparecen ${lista(conEfecto.map((x) => `<b>${etiquetaMasSI(x.f, x.e)}</b> (relación ${x.e.fuerza})`))}${sinEfecto.length ? `; ${lista(sinEfecto.map((x) => varArt(x.f)))} ${sinEfecto.length > 1 ? 'no cambian' : 'no cambia'} la tasa de SI de forma apreciable` : ''}.</p>`
      : `${base} Ninguna, por sí sola, cambia de forma apreciable la proporción de SI: el resultado depende sobre todo de la combinación de factores y del cultivo.</p>`;
    const nSi = (r.distribucion_resultado || {}).SI || 0;
    const cierre = nSi >= 100
      ? `<p>Con ${nSi} casos SI estas proporciones son estables, pero describen tendencias de grupo, no reglas para cada registro: un registro «frío» también puede terminar en SI.</p>`
      : '<p>Son proporciones de grupos pequeños: señalan tendencias, no reglas fijas.</p>';
    return bloque('🔎', 'Qué distingue a los casos SI', `${intro}<ul>${items}</ul>${cierre}`);
  }

  function interpretarCondicionesCultivo(r) {
    const rango = r.rango_tipico_si_por_cultivo, prom = r.promedio_por_cultivo_resultado, terc = r.tasa_si_por_tercio_cultivo || {};
    if (!rango || !prom) return '';
    const cultivos = Object.keys(rango).sort((a, b) => ((r.tasa_si_por_cultivo || {})[b] || 0) - ((r.tasa_si_por_cultivo || {})[a] || 0));
    const items = cultivos.map((cu) => {
      const nSi = rango[cu].n_si || 0, total = (r.distribucion_cultivo || {})[cu] || 0;
      const cab = `<b>${esc(nomCultivo(r, cu))}</b> (${nSi} SI de ${total})`;
      if (nSi < 10 || !prom[cu] || !prom[cu].SI || !prom[cu].NO) return `<li><span>${cab}: demasiado pocos casos SI para describir sus condiciones con fiabilidad.</span></li>`;
      const difs = Object.keys(prom[cu].SI).map((f) => ({ f, rel: (prom[cu].SI[f] - prom[cu].NO[f]) / Math.abs(prom[cu].NO[f] || 1) }));
      const efectos = nSi >= 30 ? efectosDe(terc[cu]).filter((x) => x.e.fuerza !== 'nula') : [];
      // variables que más distinguen a los SI dentro del cultivo: por tercios si hay casos suficientes, si no por promedio
      const claves = efectos.length ? efectos.slice(0, 3).map((x) => x.f) : difs.filter((d) => Math.abs(d.rel) >= 0.04).sort((a, b) => Math.abs(b.rel) - Math.abs(a.rel)).slice(0, 2).map((d) => d.f);
      const rangos = (claves.length ? claves : difs.slice(0, 2).map((d) => d.f)).map((f) => rango[cu][f] ? `<b>${varNom(f)}</b> ${fmtNum(rango[cu][f][0], 1)}–${fmtNum(rango[cu][f][1], 1)} ${varUni(f)}` : null).filter(Boolean);
      let detalle = '';
      if (efectos.length) {
        const { f, e } = efectos[0];
        detalle = ` La condición que más separa dentro de este cultivo es ${varArt(f, true)}: con ${condicionTexto(f, e)} el <b>${pct(tasaMejor(e), 0)}</b> de los registros termina en SI, frente al ${pct(tasaPeor(e), 0)} en el tercio opuesto.`;
      } else {
        const top = difs.filter((d) => Math.abs(d.rel) >= 0.04).sort((a, b) => Math.abs(b.rel) - Math.abs(a.rel)).slice(0, 3);
        detalle = top.length ? ` Frente a los NO del mismo cultivo, el entorno de los SI es ${lista(top.map((d) => `<span class="${d.rel > 0 ? 'int-up' : 'int-down'}">${(VAR_INFO[d.f] || {})[d.rel > 0 ? 'alto' : 'bajo'] || varNom(d.f)}</span> (${signo(d.rel)})`))}.` : ' Sus condiciones promedio apenas se distinguen de las de los NO del mismo cultivo.';
      }
      const fiab = nSi < 30 ? ' <i>(pocos casos SI: tómalo solo como orientación)</i>' : '';
      return `<li><span>${cab}: la mitad central de los casos SI se dio con ${lista(rangos)}.${detalle}${fiab}</span></li>`;
    }).join('');
    return bloque('🎯', 'Condiciones típicas de los casos SI en cada cultivo', `<p>Rango en el que se concentra la mitad central de los casos SI (del 25 % al 75 %) en las variables que más los distinguen dentro de cada cultivo:</p><ul>${items}</ul><p>Sirve para saber <b>qué registros revisar primero</b>; no garantiza el resultado individual.</p>`);
  }

  function interpretarModelo(m) {
    if (!m || !m.holdout) {
      return bloque('🤖', 'Qué dice el modelo', '<p>La evaluación del modelo no está disponible en este momento (solo se muestra cuando el servidor está conectado o el archivo de métricas está accesible).</p>');
    }
    const h = m.holdout, cv = m.cv || {}; const cm = h.matriz_confusion || null;
    const partes = [];
    partes.push(`<p>Con estos datos se entrenó un modelo que, en una <b>prueba con ${h.n} registros apartados</b>, acertó el <b>${pct(h.accuracy, 0)}</b> de los casos, detectó el <b>${pct(h.recall, 0)}</b> de los SI reales y, cuando dijo SI, acertó el <b>${pct(h.precision, 0)}</b> de las veces.${cm ? ` En detalle: ${cm[1][1]} SI detectados, ${cm[1][0]} SI que se escaparon, ${cm[0][1]} falsas alarmas y ${cm[0][0]} NO correctos${cm[1][1] ? ` (≈ ${fmtNum(cm[0][1] / cm[1][1], 1)} falsas alarmas por cada SI detectado)` : ''}.` : ''}</p>`);
    if (cm && (cm[0][1] + cm[1][1])) {
      const revisados = cm[0][1] + cm[1][1], totalPrueba = cm[0][0] + cm[0][1] + cm[1][0] + cm[1][1];
      partes.push(`<p><b>En la práctica:</b> si solo se revisaran los ${revisados} registros que el modelo marca como SI (el ${pct(revisados / totalPrueba, 0)} del total), se encontrarían ${cm[1][1]} de los ${cm[1][1] + cm[1][0]} SI reales. Revisar al azar la misma cantidad encontraría unos ${Math.round((cm[1][1] + cm[1][0]) * revisados / totalPrueba)}: el modelo <b>multiplica por ${fmtNum(cm[1][1] / Math.max((cm[1][1] + cm[1][0]) * revisados / totalPrueba, 1e-9), 1)}</b> la eficacia de la revisión.</p>`);
    }
    if (cv.accuracy != null) {
      const n = cv.n || 0; const brecha = Math.abs((cv.accuracy || 0) - (h.accuracy || 0));
      const lectura = n >= 500 && brecha < 0.05
        ? `la prueba apartada y la evaluación repetida <b>coinciden</b>, señal de que con ${n} registros las cifras son estables y representativas`
        : n >= 200 ? 'las cifras son razonablemente estables, aunque conviene seguir midiéndolas con datos nuevos'
        : 'con tan pocos registros los resultados <b>varían bastante</b> y deben tomarse como orientativos, no como una garantía';
      partes.push(`<p>En una evaluación más exigente (repetida ${cv.n_splits || 5} veces con distintos subconjuntos de los ${n || '—'} registros) el acierto fue del <b>${pct(cv.accuracy, 0)}</b> y la detección de SI del <b>${pct(cv.recall, 0)}</b>: ${lectura}.</p>`);
    }
    if (h.recall != null && h.precision != null && h.recall - h.precision >= 0.2) {
      partes.push(`<p>El modelo está ajustado para <b>no dejar escapar casos SI</b> (detecta la mayoría) a cambio de bastantes <b>falsas alarmas</b>: de cada 10 veces que anuncia SI, acierta unas ${Math.round(h.precision * 10)}. Es el compromiso adecuado si pasar por alto un SI cuesta más que revisar una alarma falsa; si no, se puede subir el umbral de decisión desde el panel.</p>`);
    } else if (h.recall != null && h.precision != null && h.precision - h.recall >= 0.2) {
      partes.push('<p>El modelo es <b>prudente al anunciar SI</b>: cuando lo hace suele acertar, pero deja pasar una parte de los SI reales. Si detectar todos los SI es prioritario, conviene bajar el umbral de decisión desde el panel.</p>');
    }
    const coef = m.coeficientes || {};
    const nombres = Object.keys(coef).filter((k) => !k.startsWith('ciudad_'));   // ciudad repite exactamente el peso del cultivo
    if (nombres.length) {
      const orden = nombres.sort((a, b) => Math.abs(coef[b]) - Math.abs(coef[a]));
      const nomCult = (k) => `${NOMBRE_CULTIVO[k.slice(8)] || k.slice(8)}${(m.ciudad_por_cultivo || {})[k.slice(8)] ? ` (${cap(m.ciudad_por_cultivo[k.slice(8)])})` : ''}`;
      const describir = (ks) => {
        const vars = ks.filter((k) => !k.startsWith('cultivo_')).map((k) => `<b>la ${esc(varNom(k))}</b>`);
        const cults = ks.filter((k) => k.startsWith('cultivo_')).map((k) => `<b>${esc(nomCult(k))}</b>`);
        if (cults.length) vars.push(`que el cultivo sea ${cults.join(' o ')}`);
        return lista(vars);
      };
      const favor = orden.filter((k) => coef[k] > 0).slice(0, 4), contra = orden.filter((k) => coef[k] < 0).slice(0, 4);
      partes.push(`<p>Lo que más empuja la predicción hacia <b>SI</b> es ${describir(favor)}${contra.length ? `; en cambio ${describir(contra)} la empujan hacia <b>NO</b>` : ''}. Cultivo y ciudad pesan exactamente lo mismo porque van en pareja.</p>`);
    }
    return bloque('🤖', 'Qué dice el modelo entrenado con estos datos', partes.join(''));
  }

  function interpretarLimites(r, m) {
    const total = r.filas_totales || 0; const si = (r.distribucion_resultado || {}).SI || 0;
    const dc = r.distribucion_cultivo || {}; const minC = Object.keys(dc).sort((a, b) => dc[a] - dc[b])[0];
    const items = [];
    if (total && total < 200) items.push(`<li><span><b>Pocos registros</b>: con ${total} observaciones cada caso pesa un ${pct(1 / total, 1)} del total, así que un solo registro puede mover los porcentajes.</span></li>`);
    else if (total) items.push(`<li><span><b>Tamaño suficiente</b>: con ${total} registros${si ? ` y ${si} casos SI` : ''} los porcentajes de esta página son estables; un registro aislado ya no los mueve.</span></li>`);
    if (si && si < 30) items.push(`<li><span><b>Pocos casos SI</b> (${si}): las conclusiones sobre qué condiciones acompañan al SI se apoyan en muy pocos ejemplos.</span></li>`);
    if (minC && Object.keys(dc).length > 1 && (dc[minC] < 30 || dc[minC] / Math.max(total, 1) < 0.15)) items.push(`<li><span><b>Grupos desiguales</b>: ${esc(nomCultivo(r, minC))} es el grupo más pequeño (${dc[minC]} registros), por lo que su tasa de SI es la menos fiable.</span></li>`);
    if (r.origen_datos && r.origen_datos.filas_generadas) items.push(`<li><span><b>Datos generados</b>: ${r.origen_datos.filas_generadas} de los ${total} registros se crearon a partir de los ${r.origen_datos.filas_originales || 0} originales; reproducen sus patrones, no nuevas mediciones. Las conclusiones valen para el flujo de trabajo, no para el campo.</span></li>`);
    items.push('<li><span><b>Ciudad = cultivo</b>: para saber si la ciudad influye por sí misma haría falta registrar un mismo cultivo en varias ciudades.</span></li>');
    items.push('<li><span><b>Asociación, no causa</b>: que los SI coincidan con ciertas condiciones no demuestra que esas condiciones los provoquen.</span></li>');
    if (m && m.holdout && m.holdout.precision != null && m.holdout.precision < 0.5) items.push(`<li><span><b>El modelo no decide solo</b>: cuando anuncia SI acierta el ${pct(m.holdout.precision, 0)} de las veces; sus avisos son una lista de prioridades para revisar, no un veredicto.</span></li>`);
    return bloque('⚠️', 'Límites de estas conclusiones', `<ul>${items.join('')}</ul>`);
  }

  // ── conclusiones clave (ordenadas por importancia, con su evidencia) ────────
  function conclusionesClave(r, m) {
    const out = [];
    const tasas = r.tasa_si_por_cultivo || {}; const cults = Object.keys(tasas).sort((a, b) => tasas[b] - tasas[a]);
    const d = r.distribucion_resultado || {}; const total = (d.SI || 0) + (d.NO || 0); const pSi = total ? (d.SI || 0) / total : 0;
    if (cults.length > 1) {
      const top = cults[0], low = cults[cults.length - 1]; const brecha = (tasas[top] - tasas[low]) * 100;
      out.push({ t: `El <b>cultivo (y su ciudad)</b> es ${brecha >= 20 ? 'el factor que más cambia' : brecha >= 10 ? 'un factor relevante en' : 'un factor menor en'} el resultado.`, e: `tasa de SI del ${pct(tasas[top], 0)} en ${nomCultivo(r, top)} frente al ${pct(tasas[low], 0)} en ${nomCultivo(r, low)} (${brecha.toFixed(0)} puntos de diferencia).` });
    }
    const efectos = efectosDe(r.tasa_si_por_tercio);
    if (efectos.length) {
      const { f, e } = efectos[0];
      if (e.fuerza !== 'nula') {
        out.push({ t: `${cap(varArt(f, true))} es la condición climática más ligada al SI (relación ${e.fuerza}).`, e: `con ${condicionTexto(f, e)} el ${pct(tasaMejor(e), 0)} de los registros termina en SI, frente al ${pct(tasaPeor(e), 0)} en el tercio opuesto (×${fmtNum(e.razon, 1)}).` });
      } else {
        out.push({ t: 'Ninguna condición climática, por sí sola, cambia mucho la probabilidad de SI.', e: 'la tasa de SI varía poco entre los tercios bajo, medio y alto de todas las variables.' });
      }
      const flojos = efectos.filter((x) => x.e.fuerza === 'nula' || x.e.fuerza === 'leve').map((x) => varNom(x.f));
      if (flojos.length && flojos.length < efectos.length) out.push({ t: `${cap(lista(flojos))} ${flojos.length > 1 ? 'aportan' : 'aporta'} poco por separado.`, e: 'sus tercios bajo, medio y alto tienen tasas de SI parecidas (menos de ×1.6 entre ellos); solo cuentan en combinación con el resto.' });
      // ¿alguna condición se comporta distinto dentro de un cultivo que en el conjunto?
      const tc = r.tasa_si_por_tercio_cultivo || {}, rg = r.rango_tipico_si_por_cultivo || {};
      let mejorCaso = null;
      Object.keys(tc).filter((cu) => (rg[cu] || {}).n_si >= 30).forEach((cu) => efectosDe(tc[cu]).filter((x) => x.e.fuerza !== 'nula' && !x.e.medio).forEach((x) => {
        const g = efectos.find((y) => y.f === x.f); if (!g) return;
        const distinto = g.e.fuerza === 'nula' || g.e.medio || g.e.sube !== x.e.sube;
        if (distinto && (!mejorCaso || x.e.razon > mejorCaso.e.razon)) mejorCaso = { cu, f: x.f, e: x.e, g: g.e };
      }));
      if (mejorCaso) out.push({ t: `El efecto de una condición puede <b>cambiar según el cultivo</b>: conviene leer cada cultivo por separado.`, e: `dentro de ${nomCultivo(r, mejorCaso.cu)}, con ${condicionTexto(mejorCaso.f, mejorCaso.e)} el ${pct(tasaMejor(mejorCaso.e), 0)} termina en SI frente al ${pct(tasaPeor(mejorCaso.e), 0)} en el tercio opuesto, mientras que en el conjunto ${mejorCaso.g.fuerza === 'nula' ? `${varArt(mejorCaso.f)} no muestra efecto claro` : mejorCaso.g.medio ? `en ${varArt(mejorCaso.f)} ${mejorCaso.g.forma}` : `la relación va en sentido contrario`}.` });
    }
    if (total) out.push({ t: `El SI es ${pSi < 0.25 ? 'poco frecuente' : pSi < 0.45 ? 'minoritario' : 'frecuente'} (${pct(pSi, 0)}), así que el <b>acierto global engaña</b>.`, e: `responder siempre «NO» acertaría el ${pct(1 - pSi, 0)}; lo que importa es cuántos SI se detectan y cuántas falsas alarmas cuesta.` });
    if (m && m.holdout) {
      const h = m.holdout, cm = h.matriz_confusion; const fpPorTp = cm && cm[1][1] ? cm[0][1] / cm[1][1] : null;
      out.push({ t: `El modelo sirve para <b>priorizar</b>, no para sentenciar.`, e: `detecta el ${pct(h.recall, 0)} de los SI y acierta el ${pct(h.precision, 0)} de sus avisos${fpPorTp != null ? ` (≈ ${fmtNum(fpPorTp, 1)} falsas alarmas por cada SI detectado)` : ''}${m.cv && m.cv.roc_auc != null ? `; capacidad de ordenar bien los casos: ${fmtNum(m.cv.roc_auc, 2)} sobre 1` : ''}.` });
      if (m.cv && m.cv.accuracy != null && (m.cv.n || 0) >= 500 && Math.abs(m.cv.accuracy - h.accuracy) < 0.05) out.push({ t: 'Las cifras del modelo son <b>estables</b>.', e: `la prueba apartada (${h.n} registros) y la evaluación repetida (${m.cv.n}) coinciden en ±${(Math.abs(m.cv.accuracy - h.accuracy) * 100).toFixed(0)} puntos.` });
    }
    if (r.origen_datos && r.origen_datos.filas_generadas) out.push({ t: 'Las conclusiones valen para el <b>flujo de trabajo</b>, todavía no para el campo.', e: `${r.origen_datos.filas_generadas} de los ${r.filas_totales} registros son generados a partir de los ${r.origen_datos.filas_originales || 0} originales.` });
    return `<ol class="int-claves">${out.slice(0, 5).map((x) => `<li><p>${x.t}</p><p class="int-evid">${esc(x.e).replace(/&lt;b&gt;/g, '<b>').replace(/&lt;\/b&gt;/g, '</b>')}</p></li>`).join('')}</ol>`;
  }

  // ── recomendaciones priorizadas, agrupadas por horizonte ────────────────────
  function recomendaciones(r, m) {
    const d = r.distribucion_resultado || {}; const total = (d.SI || 0) + (d.NO || 0); const pSi = total ? (d.SI || 0) / total : 0;
    const tasas = r.tasa_si_por_cultivo || {}; const cults = Object.keys(tasas).sort((a, b) => tasas[b] - tasas[a]);
    const terc = r.tasa_si_por_tercio || {};
    const efectos = efectosDe(terc).filter((x) => x.e.fuerza !== 'nula');
    const h = m && m.holdout ? m.holdout : null; const cm = h && h.matriz_confusion; const fpPorTp = cm && cm[1][1] ? cm[0][1] / cm[1][1] : null;
    const od = r.origen_datos; const generados = od && od.filas_generadas ? od.filas_generadas : 0;
    const cols = r.columnas_numericas || {};
    const G = { hoy: [], datos: [], modelo: [], seguimiento: [] };
    const add = (g, p, accion, porque) => G[g].push({ p, accion, porque });

    // 1) usar los resultados hoy
    if (h) {
      if ((h.precision || 0) < 0.5) add('hoy', 'alta', 'Usar las predicciones como lista de prioridades, con revisión humana antes de actuar', `acierta el ${pct(h.precision, 0)} de sus avisos de SI${fpPorTp != null ? `: cada SI detectado trae ≈ ${fmtNum(fpPorTp, 1)} falsas alarmas` : ''}.`);
      else add('hoy', 'media', 'Actuar sobre los avisos de SI, revisando periódicamente una muestra', `acierta el ${pct(h.precision, 0)} de sus avisos y detecta el ${pct(h.recall, 0)} de los SI.`);
    }
    if (cults.length) {
      const top = cults[0]; const mejor = efectos[0];
      const cond = mejor ? ` y los registros con ${condicionTexto(mejor.f, mejor.e)}` : '';
      add('hoy', 'alta', `Revisar primero ${nomCultivo(r, top)}${cond}`, `concentran la mayor proporción de SI (${pct(tasas[top], 0)} en ${nomCultivo(r, top)}${mejor ? `; ${pct(tasaMejor(mejor.e), 0)} con ${condicionTexto(mejor.f, mejor.e).replace(/ \(.*\)$/, '')}` : ''}).`);
    }
    if (h && h.recall != null && h.precision != null && h.recall - h.precision >= 0.2) add('hoy', 'media', 'Ajustar el umbral de decisión según lo que cueste equivocarse', `hoy el modelo prefiere no dejar escapar SI (detecta el ${pct(h.recall, 0)}) a costa de falsas alarmas; si revisar una alarma falsa es caro, sube el umbral desde el panel y acepta perder algunos SI.`);
    add('hoy', 'media', 'No tratar la ciudad como causa ni usar el modelo fuera de las tres ciudades registradas', 'cada cultivo se observó en una sola ciudad, así que ciudad y cultivo son indistinguibles.');

    // 2) mejorar los datos
    if (generados) add('datos', 'alta', `Sustituir progresivamente los ${generados} registros generados por mediciones reales`, `hoy describen el patrón de ${od.filas_originales || 0} observaciones amplificado; cada lote real debe reemplazar generados, no sumarse a ellos.`);
    if (pSi < 0.3) add('datos', generados ? 'media' : 'alta', 'Recoger más casos SI reales (y registrar también los NO del mismo lugar y época)', `con ${d.SI || 0} SI (${pct(pSi, 0)}) el modelo aprende sobre todo a decir NO; el objetivo razonable es acercarse al 30–40 % de SI o, al menos, superar los 100 SI reales.`);
    else if (total < 300) add('datos', 'alta', 'Ampliar el conjunto de datos', `con ${total} registros las cifras aún varían con cada nuevo lote.`);
    add('datos', 'media', 'Registrar un mismo cultivo en más de una ciudad', 'es la única forma de separar el efecto del cultivo del de la ciudad.');
    add('datos', 'media', 'Añadir la fecha de cada registro (y, si se puede, la etapa del cultivo)', 'permitiría estudiar estacionalidad y tendencias; hoy el conjunto no tiene fecha y las series temporales solo pueden simularse.');
    if (r.filas_invalidas) add('datos', 'alta', `Corregir en origen los ${r.filas_invalidas} registros inválidos`, 'se descartan al procesar y no aportan nada al análisis.');
    else add('datos', 'baja', 'Mantener la validación automática al cargar datos nuevos', `hoy no hay registros inválidos${r.ciudad_inconsistentes_corregidas ? ` (${r.ciudad_inconsistentes_corregidas} ciudades se corrigieron solas)` : ''}; conviene que siga así cuando lleguen mediciones reales.`);

    // 3) mejorar el modelo
    add('modelo', 'media', 'Comparar varios algoritmos antes de cambiar el modelo', 'la página de Análisis entrena y compara cinco algoritmos de clasificación con validación cruzada; elige el de mejor equilibrio entre SI detectados y falsas alarmas, no el de mayor acierto global.');
    if (h && (h.precision || 0) < 0.5) add('modelo', 'media', 'Buscar el equilibrio entre detectar SI y evitar falsas alarmas', 'probar distintos umbrales y pesos de la clase SI, y elegir según el coste real de cada tipo de error.');
    if (efectos.length && efectos.length < Object.keys(terc).length) add('modelo', 'baja', `Incorporar información nueva, no solo más registros del mismo tipo`, `${lista(Object.keys(terc).filter((f) => !efectos.some((x) => x.f === f)).map(varNom))} aportan poco por separado; variables de suelo, manejo o fecha podrían explicar los SI que el clima no explica.`);
    add('modelo', 'media', `Reentrenar cuando se acumulen unos 100 registros reales nuevos o cambie la proporción de SI`, `el modelo actual se entrenó con ${total} registros${m && m.version ? ` (versión ${esc(String(m.version))})` : ''}; con datos reales nuevos sus cifras cambiarán.`);

    // 4) seguimiento continuo
    add('seguimiento', 'alta', 'Registrar el resultado real de cada predicción desde el panel', 'es la única forma de comprobar si el acierto se mantiene con datos nuevos y de detectar a tiempo cuándo reentrenar.');
    const rangos = Object.entries(cols).filter(([, c]) => c.min != null && c.max != null).slice(0, 2).map(([f, c]) => `${varNom(f)} ${fmtNum(c.min, 0)}–${fmtNum(c.max, 0)} ${varUni(f)}`);
    add('seguimiento', 'media', 'Vigilar que los datos nuevos se parezcan a los de entrenamiento', `fuera de los rangos vistos (${lista(rangos)}…) o con otra proporción de SI, las predicciones pierden fiabilidad.`);
    add('seguimiento', 'baja', 'Anotar versión del modelo y del conjunto de datos en cada cambio', 'así cada cifra de esta página puede rastrearse hasta los datos que la produjeron.');

    const titulo = { hoy: 'Para usar los resultados hoy', datos: 'Para mejorar los datos', modelo: 'Para mejorar el modelo', seguimiento: 'Para el seguimiento continuo' };
    const orden = { alta: 0, media: 1, baja: 2 };
    const col = (g) => `<div class="int-rec-col"><h4>${titulo[g]}</h4><ul>${G[g].sort((a, b) => orden[a.p] - orden[b.p]).map((x) => `<li><span class="int-prio int-prio-${x.p}">${x.p}</span><span><b>${x.accion}</b> <span class="int-porque">${x.porque}</span></span></li>`).join('')}</ul></div>`;
    const primeras = ['hoy', 'datos', 'modelo', 'seguimiento'].flatMap((g) => G[g].filter((x) => x.p === 'alta')).slice(0, 4);
    return {
      top: `<ol class="int-rec-top">${primeras.map((x) => `<li><b>${x.accion}</b> <span class="int-porque">${x.porque}</span></li>`).join('')}</ol>`,
      grid: `<div class="int-rec-grid !mt-0">${['hoy', 'datos', 'modelo', 'seguimiento'].map(col).join('')}</div>`,
    };
  }

  function resumenGeneral(r, m) {
    const total = r.filas_totales || 0; const d = r.distribucion_resultado || {}; const si = d.SI || 0, no = d.NO || 0;
    const tasas = r.tasa_si_por_cultivo || {}; const cultivos = Object.keys(tasas).sort((a, b) => tasas[b] - tasas[a]);
    const terc = r.tasa_si_por_tercio || {};
    const partes = [`Se analizaron <b>${total} registros</b> de ${cultivos.length} cultivos (${esc(lista(Object.keys(r.distribucion_cultivo || {}).sort().map((c) => nomCultivo(r, c))))}).`];
    if (si + no) partes.push(`Solo <b>${si}</b> (${pct(si / (si + no), 0)}) terminaron en <b>SI</b>: el resultado positivo es ${si / (si + no) < 0.3 ? 'poco frecuente' : 'relativamente frecuente'}.`);
    if (cultivos.length > 1) partes.push(`La proporción de SI es <b>mayor en ${esc(nomCultivo(r, cultivos[0]))}</b> (${pct(tasas[cultivos[0]], 0)}) y <b>menor en ${esc(nomCultivo(r, cultivos[cultivos.length - 1]))}</b> (${pct(tasas[cultivos[cultivos.length - 1]], 0)}).`);
    const efectos = efectosDe(terc).filter((x) => x.e.fuerza !== 'nula');
    if (efectos.length) {
      const { f, e } = efectos[0];
      partes.push(`La condición que más acompaña al SI es ${varArt(f, true)}: con ${condicionTexto(f, e)} el <b>${pct(tasaMejor(e), 0)}</b> de los registros termina en SI, frente al ${pct(tasaPeor(e), 0)} en el tercio opuesto.`);
    } else {
      const pr = r.promedio_por_resultado;
      if (pr && pr.SI && pr.NO) {
        const claras = Object.keys(pr.SI).map((f) => ({ f, rel: (pr.SI[f] - pr.NO[f]) / Math.abs(pr.NO[f] || 1) })).filter((x) => Math.abs(x.rel) >= 0.05).sort((a, b) => Math.abs(b.rel) - Math.abs(a.rel));
        if (claras.length) partes.push(`Los casos SI se dieron, en promedio, con ${lista(claras.map((x) => `<b>${(VAR_INFO[x.f] || {})[x.rel > 0 ? 'masSI' : 'menosSI'] || varNom(x.f)}</b>`))} que los casos NO.`);
      }
    }
    if (m && m.holdout) partes.push(`El modelo detecta el <b>${pct(m.holdout.recall, 0)}</b> de los SI y acierta el <b>${pct(m.holdout.precision, 0)}</b> de sus avisos: útil para <b>priorizar revisiones</b>, no para decidir solo${total < 200 ? ', y con la cautela que exige un conjunto tan pequeño' : ''}.`);
    if (r.origen_datos && r.origen_datos.filas_generadas) partes.push(`${r.origen_datos.filas_generadas} de los registros son <b>generados</b> a partir de los ${r.origen_datos.filas_originales || 0} originales, así que estas conclusiones describen el flujo de trabajo, no todavía el campo.`);
    return `<p class="text-[11px] font-medium uppercase tracking-wider text-brand-700">En pocas palabras</p><p class="mt-1">${partes.join(' ')}</p>`;
  }

  function renderInterpretacion(r, m) {
    try {
      $('#int-resumen').innerHTML = resumenGeneral(r, m);
      $('#int-claves').innerHTML = conclusionesClave(r, m);
      $('#int-bloques').innerHTML = [
        interpretarCalidad(r), interpretarBalance(r), interpretarCultivos(r), interpretarClima(r),
        interpretarPerfiles(r), interpretarSI(r), interpretarCondicionesCultivo(r), interpretarModelo(m), interpretarLimites(r, m),
      ].join('');
      const recs = recomendaciones(r, m);
      $('#int-rec-top').innerHTML = recs.top;
      $('#int-recomendaciones').innerHTML = recs.grid;
      const btn = $('#int-toggle');
      if (btn && !btn.dataset.listo) {
        btn.dataset.listo = '1';
        btn.addEventListener('click', () => {
          const abierto = btn.getAttribute('aria-expanded') === 'true';
          btn.setAttribute('aria-expanded', String(!abierto));
          $('#int-detalle').classList.toggle('hidden', abierto);
          const lbl = btn.querySelector('span'); lbl.textContent = abierto ? lbl.dataset.cerrado : lbl.dataset.abierto;
        });
      }
      const f = r.fecha_ejecucion ? new Date(r.fecha_ejecucion) : null;
      $('#int-fecha').textContent = f ? `Datos del ${f.toLocaleDateString('es-PE', { day: '2-digit', month: '2-digit', year: 'numeric' })} ${f.toLocaleTimeString('es-PE', { hour: '2-digit', minute: '2-digit', hour12: false })}` : '';
      const nota = $('#int-nota');
      if (r.filas_invalidas) { nota.classList.remove('hidden'); nota.textContent = `Atención: ${r.filas_invalidas} registros se descartaron por datos incorrectos; las conclusiones se basan en los ${r.filas_validas} válidos.`; }
      else nota.classList.add('hidden');
    } catch (e) {
      $('#int-resumen').textContent = 'No se pudo generar la interpretación con los datos actuales.';
    }
  }

  // Métricas del modelo para el bloque «Qué dice el modelo»: del servidor si está conectado;
  // si no, del archivo de métricas del proyecto (ruta relativa a la página). Si no hay, el bloque lo indica.
  async function cargarMetricasModelo() {
    try {
      if (!modoEstatico()) return await api('/api/metrics/training');
      const res = await fetch('../models/metricas.json', { cache: 'no-store' });
      return res.ok ? await res.json() : null;
    } catch { return null; }
  }

  // ─────────────────────────────── carga ─────────────────────────────────────
  async function cargar() {
    try {
      let r, tamano = null;
      if (modoEstatico()) {
        const res = await fetch(ESTATICO.resultado, { cache: 'no-store' });
        if (!res.ok) throw new Error(`${res.status} ${res.statusText} al leer ${ESTATICO.resultado}`);
        const texto = await res.text(); r = JSON.parse(texto); tamano = new Blob([texto]).size;
      } else {
        const head = await fetch(MLOPS.url('/download/resultado.json'), { method: 'HEAD' }).catch(() => null);
        r = await api('/api/data/summary');
        tamano = head && head.ok ? Number(head.headers.get('content-length')) : null;
      }
      datos = r;
      $('#aviso').classList.add('hidden');
      renderKPIs(r, tamano); renderTabla(r); renderDistribuciones(r); renderArbol(r);
      if (window.ANIM) { ANIM.barrasAlVer(document, '[data-ancho]'); ANIM.escalonar(document, '[data-kpi], .kpi', 40, 12); }
      renderInterpretacion(r, metricasModelo);
      if (metricasModelo === undefined) {           // primera carga: las métricas del modelo llegan aparte
        metricasModelo = await cargarMetricasModelo();
        renderInterpretacion(r, metricasModelo);
      }
      $('#vista-codigo').innerHTML = resaltar(r);
      document.title = `Resultados · ${r.filas_totales} filas · resultado.json`;
    } catch (e) {
      const av = $('#aviso'); av.classList.remove('hidden');
      av.innerHTML = `No se pudieron cargar los resultados: ${esc(e.message)}. Pulsa «Volver a procesar los datos» o inténtalo de nuevo más tarde.`;
    }
  }

  // ─────────────────────────────── descargas de la base de datos ────────────
  const ICONOS = { datos: '🗂️', predicciones: '🎯', feedback: '✅', resultado: '📊' };
  const fmtBytes = (n) => n >= 1048576 ? `${(n / 1048576).toFixed(1)} MB` : n >= 1024 ? `${(n / 1024).toFixed(1)} KB` : `${n} B`;

  function dlEstado(html, tipo = 'info') {
    const el = $('#dl-estado');
    el.className = `mt-3 rounded-lg border px-3 py-2 text-xs ${
      tipo === 'error' ? 'border-rose-200 bg-rose-50 text-rose-700' : tipo === 'ok' ? 'border-emerald-200 bg-emerald-50 text-emerald-700' : 'border-brand-100 bg-brand-50 text-brand-700'}`;
    el.innerHTML = html;
  }

  // Descarga vía fetch + Blob: el archivo se genera en el servidor y se guarda sin salir de la página,
  // con estado visible (generando / listo / error). Si el navegador bloquea la descarga automática,
  // el enlace «abrir en pestaña nueva» del mensaje usa la misma URL.
  async function descargar(a) {
    const url = a.getAttribute('href'); const nombre = a.getAttribute('download') || url.split('/').pop();
    const fuera = !$('#sec-descargas').contains(a);   // enlaces de la cabecera / ficha Archivo: el aviso también va a #estado
    const txt = a.innerHTML; a.innerHTML = '⏳ generando…'; a.classList.add('pointer-events-none', 'opacity-70');
    dlEstado(`Generando <b>${esc(nombre)}</b> en el servidor…`);
    const t0 = performance.now();
    try {
      const res = await fetch(url, { cache: 'no-store' });
      if (!res.ok) {
        let detalle = `${res.status} ${res.statusText}`;
        try { detalle = (await res.json()).detail || detalle; } catch { /* sin cuerpo JSON */ }
        throw new Error(detalle);
      }
      const blob = await res.blob();
      const href = URL.createObjectURL(blob);
      const tmp = document.createElement('a'); tmp.href = href; tmp.download = nombre; document.body.appendChild(tmp); tmp.click(); tmp.remove();
      setTimeout(() => URL.revokeObjectURL(href), 60000);
      dlEstado(`✓ <b>${esc(nombre)}</b> listo (${fmtBytes(blob.size)} · ${Math.round(performance.now() - t0)} ms). ` +
        `¿No apareció la descarga? <a href="${esc(url)}" target="_blank" rel="noopener" class="underline font-medium">Ábrela en una pestaña nueva ↗</a>`, 'ok');
      if (fuera) setEstado(`✓ ${nombre} descargado (${fmtBytes(blob.size)}).`);
      son('descarga', 'descarga');
    } catch (e) {
      const sinRed = /Failed to fetch|NetworkError|Load failed/i.test(e.message);
      dlEstado(`✗ No se pudo descargar <b>${esc(nombre)}</b>: ${esc(e.message)}. ` +
        (sinRed ? 'El servidor no responde en este momento; inténtalo de nuevo en unos segundos. ' : '') +
        `<a href="${esc(url)}" target="_blank" rel="noopener" class="underline font-medium">Intentar en una pestaña nueva ↗</a>`, 'error');
      if (fuera) setEstado(`✗ No se pudo descargar ${nombre}: ${e.message}`, false);
      son('error', 'error');
    } finally {
      a.innerHTML = txt; a.classList.remove('pointer-events-none', 'opacity-70');
    }
  }

  function setupDescargas() {
    document.addEventListener('click', (ev) => {
      const a = ev.target.closest('a[download]');
      if (!ev.isTrusted || !a || ev.ctrlKey || ev.metaKey || ev.shiftKey || ev.button !== 0) return;   // solo clics reales del usuario (el anclaje temporal del Blob no); ctrl/cmd/“guardar como” → enlace nativo
      ev.preventDefault(); descargar(a);
    });
  }
  function tarjetasDescarga(tablas, hrefDe) {
    return tablas.map((t) => `
        <div class="rounded-xl border border-surface-ring bg-white p-3 flex flex-col gap-2 ${t.error ? 'opacity-60' : ''}">
          <div class="flex items-start gap-2">
            <span class="text-lg leading-none">${ICONOS[t.clave] || '📄'}</span>
            <div class="min-w-0">
              <p class="text-sm font-semibold text-slate-800 leading-tight">${esc(t.titulo)}</p>
              <p class="text-[11px] text-slate-500 leading-snug mt-0.5">${esc(t.descripcion)}</p>
            </div>
          </div>
          <p class="text-[11px] text-slate-500"><span class="font-mono text-slate-800">${t.filas.toLocaleString('es-PE')}</span> filas · ${t.columnas.length} columnas</p>
          ${t.error ? `<p class="text-[11px] text-rose-600">${esc(t.error)}</p>` : ''}
          <div class="mt-auto flex flex-wrap gap-1.5">
            <a href="${hrefDe(t.clave, 'csv')}" download="${t.clave}.csv" class="btn-secondary btn-xs">⬇ CSV</a>
            <a href="${hrefDe(t.clave, 'xlsx')}" download="${t.clave}.xlsx" class="btn-secondary btn-xs">⬇ XLSX</a>
            <a href="${hrefDe(t.clave, 'pdf')}" download="${t.clave}.pdf" class="btn-secondary btn-xs">⬇ PDF</a>
            <a href="${hrefDe(t.clave, 'json')}" target="_blank" rel="noopener" class="btn-secondary btn-xs" title="Ver como JSON">JSON ↗</a>
          </div>
        </div>`).join('');
  }

  // Botones de «Base de datos completa» y enlaces del archivo resultado.json según el modo.
  function apuntarEnlacesCompleta(hrefDe) {
    $$('#dl-completa a').forEach((a) => {
      const nombre = a.getAttribute('download') || 'base_datos.json';
      const [clave, formato] = [nombre.slice(0, nombre.lastIndexOf('.')), nombre.slice(nombre.lastIndexOf('.') + 1)];
      a.setAttribute('href', hrefDe(clave, formato));
    });
  }

  async function cargarDescargas() {
    const cont = $('#dl-tablas');
    try {
      if (modoEstatico()) {
        // Sin API: copias estáticas generadas por la API al arrancar o por `python exportar_base_datos.py`.
        const res = await fetch(ESTATICO.indice, { cache: 'no-store' });
        if (!res.ok) throw new Error('no hay una copia guardada de las descargas; vuelve a intentarlo cuando el servidor esté disponible');
        const idx = await res.json();
        const hrefDe = (clave, formato) => `${ESTATICO.carpeta}${clave}.${formato === 'csv' && clave === 'base_datos' ? 'zip' : formato}`;
        cont.innerHTML = tarjetasDescarga(idx.tablas, hrefDe);
        apuntarEnlacesCompleta(hrefDe);
        $('#dl-completa').querySelector('span').textContent = `Base de datos completa (${Number(idx.total_filas).toLocaleString('es-PE')} filas)`;
        dlEstado(`ℹ️ Sin conexión con el servidor: se ofrece la <b>última copia guardada</b> de las descargas (generada el ${esc(idx.generado)}).`);
        return;
      }
      const cat = await api('/api/data/exports');
      const hrefDe = (clave, formato) => MLOPS.url(clave === 'base_datos' ? cat.completa.descargas[formato] : `/download/${clave}.${formato}`);
      cont.innerHTML = tarjetasDescarga(cat.tablas, hrefDe);
      apuntarEnlacesCompleta(hrefDe);
      const total = cat.completa.filas.toLocaleString('es-PE');
      $('#dl-completa').querySelector('span').textContent = `Base de datos completa (${total} filas)`;
    } catch (e) {
      cont.innerHTML = `<p class="text-xs text-rose-600">No se pudo cargar el catálogo de descargas: ${esc(e.message)} · <button class="underline" id="dl-reintentar">reintentar</button></p>`;
      $('#dl-reintentar').onclick = cargarDescargas;
    }
  }

  // ─────────────────────────────── acciones ──────────────────────────────────
  function setupAcciones() {
    $$('.tab[data-vista]').forEach((b) => b.onclick = () => {
      $$('.tab[data-vista]').forEach((x) => x.classList.toggle('tab-active', x === b));
      $('#vista-arbol').classList.toggle('hidden', b.dataset.vista !== 'arbol');
      $('#vista-codigo').classList.toggle('hidden', b.dataset.vista !== 'codigo');
    });
    $('#btn-recargar').onclick = async () => { await cargar(); setEstado('Recargado.'); son('exito', 'proceso'); };
    $('#btn-copiar').onclick = async () => {
      if (!datos) return;
      try { await navigator.clipboard.writeText(JSON.stringify(datos, null, 2)); setEstado('JSON copiado al portapapeles.'); son('copiado', 'descarga'); }
      catch { setEstado('El navegador bloqueó el portapapeles; descarga el archivo JSON.', false); son('aviso', 'error'); }
    };
    $('#btn-reprocesar').onclick = async (ev) => {
      const b = ev.currentTarget; b.disabled = true; const txt = b.textContent; b.textContent = '⏳ Ejecutando…';
      try { await api('/api/data/reprocess', { method: 'POST' }); await cargar(); cargarDescargas(); setEstado('Datos procesados de nuevo; resultados actualizados.'); son('exito', 'proceso'); }
      catch (e) { setEstado(`Error: ${e.message}`, false); son('error', 'error'); }
      finally { b.disabled = false; b.textContent = txt; }
    };
  }

  function modoEstaticoUI() {
    // Enlaces del archivo resultado.json → copias del workspace; el re-procesado necesita la API.
    $$('a[download="resultado.json"]').forEach((a) => a.setAttribute('href', ESTATICO.resultado));
    $$('a[download="resultado.csv"]').forEach((a) => a.setAttribute('href', `${ESTATICO.carpeta}resultado.csv`));
    $$('a[href="/api/data/summary"]').forEach((a) => a.setAttribute('href', ESTATICO.resultado));
    const b = $('#btn-reprocesar'); b.disabled = true; b.classList.add('opacity-50', 'cursor-not-allowed'); b.title = 'Disponible cuando el servidor esté conectado';
    setEstado('Sin conexión con el servidor: se muestra la última copia guardada de los resultados.', true);
  }

  async function init() {
    setupAcciones(); setupDescargas();
    await MLOPS.listo;
    if (modoEstatico()) modoEstaticoUI(); else MLOPS.reescribirEnlaces();
    cargar(); cargarDescargas();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})();
