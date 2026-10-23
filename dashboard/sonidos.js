/*
 * Sonidos del dashboard sincronizados con cada acción, con reverberación configurable.
 *
 * - Sonidos sintetizados con Web Audio (sin archivos de audio ni red). Cada tipo de acción tiene
 *   el suyo: enviar un formulario, resultado SI / NO, proceso terminado, descarga, error/aviso,
 *   pestañas, interruptores, listas, deslizadores, clic en botones, cambio de página, fin de carga…
 * - Capa de acciones automática: escucha clic / envío / cambio en toda la página (también en los
 *   elementos que se crean después) y elige el sonido según el tipo de control. Un elemento puede
 *   forzar el suyo con data-sonido="nombre" o silenciarse con data-sonido="ninguno".
 * - Los scripts de cada página añaden los sonidos de resultado (predicción, proceso terminado,
 *   descarga lista, copiado, errores) mediante window.SONIDOS.reproducir(nombre, evento).
 * - Reverberación por convolución: la respuesta de impulso se genera aquí mismo (ruido con caída
 *   exponencial, filtrado según el «brillo») y se ajusta: cantidad, cola, retardo inicial y brillo.
 * - Configuración en la sección «Sonidos» de cada página (#sec-sonidos, enlazada desde «🔊 Sonidos»
 *   en la cabecera). Todo se guarda en el navegador.
 * - Los navegadores solo permiten sonido tras un gesto del usuario: el audio se desbloquea con el
 *   primer clic / tecla; los sonidos pedidos mientras arranca se encolan y suenan en cuanto está listo.
 *
 * API pública: window.SONIDOS.reproducir(nombre, evento) · .config() · .abrir() (va a la sección)
 *   nombre: ver SONIDOS más abajo · evento: clave de cfg.eventos (grupo que se puede silenciar).
 * Cada sonido que suena emite en document el evento «sonidos:reproducido» con {nombre, evento}.
 */
(function () {
  'use strict';
  var CLAVE = 'mlops.sonidos.v2', CLAVE_ANTERIOR = 'mlops.sonidos.v1';
  var DEFECTO = {
    activo: true,
    volumen: 0.6,                 // 0–1
    tema: 'suave',                // suave | campana | digital
    reverb: { activo: true, mezcla: 0.35, cola: 1.8, retardo: 0.02, brillo: 0.5 },
    eventos: { prediccion: true, envio: true, proceso: true, descarga: true, error: true, interaccion: true, clic: true, navegacion: true, carga: true, flujo: false },
  };
  // [clave, etiqueta, sonido de muestra]
  var EVENTOS = [
    ['prediccion', 'Resultado de una predicción (SI / NO)', 'si'],
    ['envio', 'Enviar un formulario o iniciar un proceso', 'enviar'],
    ['proceso', 'Proceso o análisis terminado', 'exito'],
    ['descarga', 'Descarga lista o texto copiado', 'descarga'],
    ['error', 'Errores y avisos', 'error'],
    ['interaccion', 'Pestañas, interruptores, listas y deslizadores', 'pestana'],
    ['clic', 'Clic en los demás botones', 'clic'],
    ['navegacion', 'Cambiar de página', 'navegar'],
    ['carga', 'Fin de la pantalla de carga', 'inicio'],
    ['flujo', 'Predicciones en vivo (una por cada registro nuevo)', 'flujo'],
  ];
  // Grupo al que pertenece cada sonido cuando lo dispara la capa de acciones
  var GRUPO = {
    si: 'prediccion', no: 'prediccion', enviar: 'envio', exito: 'proceso', descarga: 'descarga', copiado: 'descarga',
    error: 'error', aviso: 'error', pestana: 'interaccion', activar: 'interaccion', desactivar: 'interaccion',
    seleccion: 'interaccion', ajuste: 'interaccion', dado: 'interaccion', clic: 'clic', navegar: 'navegacion',
    inicio: 'carga', flujo: 'flujo', flujoSi: 'flujo',
  };

  // ───────────────────────────── configuración ─────────────────────────────
  function clonar(o) { return JSON.parse(JSON.stringify(o)); }
  function fusionar(base, extra) {
    var out = clonar(base);
    if (!extra || typeof extra !== 'object') return out;
    Object.keys(out).forEach(function (k) {
      if (out[k] && typeof out[k] === 'object' && !Array.isArray(out[k])) out[k] = fusionar(out[k], extra[k]);
      else if (extra[k] !== undefined && typeof extra[k] === typeof out[k]) out[k] = extra[k];
    });
    return out;
  }
  function cargar() {
    try {
      var v2 = JSON.parse(localStorage.getItem(CLAVE) || 'null');
      if (v2) return fusionar(DEFECTO, v2);
      var v1 = JSON.parse(localStorage.getItem(CLAVE_ANTERIOR) || 'null');   // versión anterior: se conservan volumen, tema y reverberación
      if (v1) return fusionar(DEFECTO, { activo: v1.activo, volumen: v1.volumen, tema: v1.tema, reverb: v1.reverb });
    } catch (e) { /* almacenamiento no disponible o dañado */ }
    return clonar(DEFECTO);
  }
  function guardar() { try { localStorage.setItem(CLAVE, JSON.stringify(cfg)); } catch (e) { /* almacenamiento no disponible */ } }
  var cfg = cargar();

  // ───────────────────────────── motor de audio ─────────────────────────────
  var AC = window.AudioContext || window.webkitAudioContext;
  var ctx = null, master = null, seco = null, mojado = null, convolver = null, timerIR = null;
  var gesto = false, pendientes = [];

  function listo() { return !!ctx && ctx.state === 'running'; }
  function asegurar() {
    if (!AC) return null;
    if (!ctx) {
      ctx = new AC();
      master = ctx.createGain();
      seco = ctx.createGain();
      mojado = ctx.createGain();
      convolver = ctx.createConvolver();
      seco.connect(master);
      convolver.connect(mojado); mojado.connect(master);
      master.connect(ctx.destination);
      aplicarMezcla(); reconstruirIR();
      ctx.addEventListener('statechange', vaciarPendientes);
    }
    if (ctx.state === 'suspended') ctx.resume().then(vaciarPendientes).catch(function () { /* sin gesto todavía */ });
    return ctx;
  }
  function vaciarPendientes() {
    if (!listo() || !pendientes.length) return;
    var lista = pendientes.splice(0);
    lista.forEach(function (p, i) {
      try { SONIDOS[p.nombre](ctx.currentTime + 0.01 + i * 0.14); notificar(p.nombre, p.evento); } catch (e) { /* ignorar */ }
    });
  }

  // Respuesta de impulso: ruido estéreo con caída exponencial (−60 dB al final de la «cola»),
  // precedido por el retardo inicial y filtrado con un paso-bajo cuya apertura depende del «brillo».
  function reconstruirIR() {
    if (!ctx) return;
    var r = cfg.reverb, sr = ctx.sampleRate;
    var nPre = Math.floor(Math.max(0, r.retardo) * sr);
    var nCola = Math.max(Math.floor(Math.max(0.1, r.cola) * sr), 1);
    var buf = ctx.createBuffer(2, nPre + nCola, sr);
    var alpha = 0.08 + 0.9 * Math.min(1, Math.max(0, r.brillo));   // 0.08 = muy oscuro · 0.98 = muy brillante
    for (var c = 0; c < 2; c++) {
      var d = buf.getChannelData(c), lp = 0;
      for (var i = 0; i < nCola; i++) {
        var ruido = Math.random() * 2 - 1;
        lp += alpha * (ruido - lp);
        d[nPre + i] = lp * Math.exp(-6.91 * i / nCola);
      }
      // primeras reflexiones discretas para dar sensación de sala
      [0.011, 0.019, 0.027, 0.041].forEach(function (t, k) {
        var idx = nPre + Math.floor(t * sr);
        if (idx < d.length) d[idx] += (0.5 - k * 0.1) * (c ? -1 : 1);
      });
    }
    convolver.normalize = true;
    convolver.buffer = buf;
  }
  function aplicarMezcla() {
    if (!ctx) return;
    var r = cfg.reverb, m = r.activo ? Math.min(1, Math.max(0, r.mezcla)) : 0;
    var t = ctx.currentTime;
    master.gain.setTargetAtTime(cfg.activo ? cfg.volumen : 0, t, 0.02);
    seco.gain.setTargetAtTime(1 - 0.45 * m, t, 0.02);
    mojado.gain.setTargetAtTime(1.6 * m, t, 0.02);
  }
  function programarIR() { clearTimeout(timerIR); timerIR = setTimeout(reconstruirIR, 150); }

  function onda() { return cfg.tema === 'campana' ? 'triangle' : cfg.tema === 'digital' ? 'square' : 'sine'; }

  // Una nota: oscilador → envolvente → (seco + reverberación)
  function nota(freq, t0, dur, vol, opciones) {
    var o = opciones || {};
    var osc = ctx.createOscillator(), g = ctx.createGain();
    osc.type = o.tipo || onda();
    osc.frequency.setValueAtTime(freq, t0);
    if (o.hasta) osc.frequency.exponentialRampToValueAtTime(o.hasta, t0 + dur);
    var v = vol * (osc.type === 'square' ? 0.35 : osc.type === 'sawtooth' ? 0.4 : 1);
    g.gain.setValueAtTime(0.0001, t0);
    g.gain.exponentialRampToValueAtTime(v, t0 + (o.ataque || 0.012));
    g.gain.exponentialRampToValueAtTime(0.0001, t0 + dur);
    osc.connect(g);
    var salida = g;
    if (cfg.tema === 'digital') {               // suaviza los armónicos de la onda cuadrada
      var f = ctx.createBiquadFilter(); f.type = 'lowpass'; f.frequency.value = Math.min(8000, freq * 4); g.connect(f); salida = f;
    }
    salida.connect(seco); salida.connect(convolver);
    if (cfg.tema === 'campana') {               // armónico brillante típico de campana
      var o2 = ctx.createOscillator(), g2 = ctx.createGain();
      o2.type = 'sine'; o2.frequency.setValueAtTime(freq * 2.76, t0);
      g2.gain.setValueAtTime(0.0001, t0); g2.gain.exponentialRampToValueAtTime(v * 0.25, t0 + 0.005); g2.gain.exponentialRampToValueAtTime(0.0001, t0 + dur * 0.5);
      o2.connect(g2); g2.connect(seco); g2.connect(convolver); o2.start(t0); o2.stop(t0 + dur * 0.5 + 0.05);
    }
    osc.start(t0); osc.stop(t0 + dur + 0.05);
  }
  function ruidoCorto(t0, dur, vol) {           // clic: ráfaga de ruido filtrada
    var n = Math.floor(ctx.sampleRate * dur), buf = ctx.createBuffer(1, n, ctx.sampleRate), d = buf.getChannelData(0);
    for (var i = 0; i < n; i++) d[i] = (Math.random() * 2 - 1) * Math.pow(1 - i / n, 3);
    var src = ctx.createBufferSource(), f = ctx.createBiquadFilter(), g = ctx.createGain();
    src.buffer = buf; f.type = 'bandpass'; f.frequency.value = 2400; f.Q.value = 1.2; g.gain.value = vol;
    src.connect(f); f.connect(g); g.connect(seco); g.connect(convolver); src.start(t0);
  }

  var ESCALA = [523.25, 587.33, 659.25, 783.99, 880, 1046.5];
  var SONIDOS = {
    // resultados y procesos
    si:         function (t) { nota(659.25, t, 0.16, 0.5); nota(880, t + 0.12, 0.45, 0.5); },
    no:         function (t) { nota(440, t, 0.16, 0.45); nota(329.63, t + 0.12, 0.4, 0.4); },
    enviar:     function (t) { nota(440, t, 0.08, 0.28); nota(659.25, t + 0.07, 0.16, 0.3); },
    exito:      function (t) { nota(523.25, t, 0.14, 0.4); nota(659.25, t + 0.09, 0.14, 0.4); nota(783.99, t + 0.18, 0.55, 0.45); },
    descarga:   function (t) { nota(783.99, t, 0.12, 0.4); nota(1046.5, t + 0.1, 0.4, 0.4); },
    copiado:    function (t) { nota(1318.5, t, 0.05, 0.25); nota(1318.5, t + 0.09, 0.1, 0.25); },
    aviso:      function (t) { nota(740, t, 0.12, 0.4); nota(740, t + 0.18, 0.25, 0.4); },
    error:      function (t) { nota(180, t, 0.3, 0.5, { tipo: 'sawtooth', hasta: 120 }); nota(150, t + 0.22, 0.25, 0.35, { tipo: 'sawtooth', hasta: 100 }); },
    // interacción
    pestana:    function (t) { nota(880, t, 0.06, 0.22); },
    activar:    function (t) { nota(520, t, 0.09, 0.3, { hasta: 780 }); },
    desactivar: function (t) { nota(780, t, 0.09, 0.3, { hasta: 520 }); },
    seleccion:  function (t) { nota(1046.5, t, 0.05, 0.2); },
    ajuste:     function (t) { nota(1318.5, t, 0.035, 0.15); },
    dado:       function (t) { for (var i = 0; i < 3; i++) nota(ESCALA[Math.floor(Math.random() * ESCALA.length)], t + i * 0.06, 0.07, 0.22); },
    clic:       function (t) { ruidoCorto(t, 0.04, 0.5); },
    navegar:    function (t) { nota(783.99, t, 0.07, 0.28); nota(1174.66, t + 0.06, 0.14, 0.28); },
    inicio:     function (t) { nota(523.25, t, 0.12, 0.3); nota(659.25, t + 0.1, 0.12, 0.3); nota(783.99, t + 0.2, 0.12, 0.3); nota(1046.5, t + 0.3, 0.7, 0.35); },
    flujo:      function (t) { nota(1200, t, 0.05, 0.12); },
    flujoSi:    function (t) { nota(1600, t, 0.07, 0.16); },
  };

  function notificar(nombre, evento) {
    try { document.dispatchEvent(new CustomEvent('sonidos:reproducido', { detail: { nombre: nombre, evento: evento || GRUPO[nombre] || null } })); } catch (e) { /* ignorar */ }
  }
  var ultimoFlujo = 0;
  function reproducir(nombre, evento) {
    if (!cfg.activo || !SONIDOS[nombre]) return false;
    var grupo = evento || GRUPO[nombre];
    if (grupo && cfg.eventos[grupo] === false) return false;
    if (grupo === 'flujo') {                                   // no más de ~6 por segundo
      var ahora = Date.now(); if (ahora - ultimoFlujo < 160) return false; ultimoFlujo = ahora;
    }
    if (!listo()) {
      // Sin gesto todavía: se ignora. Con gesto pero el audio aún arrancando: sonará en cuanto esté listo.
      if (gesto && ctx && pendientes.length < 4) { pendientes.push({ nombre: nombre, evento: grupo }); return true; }
      return false;
    }
    try { SONIDOS[nombre](ctx.currentTime + 0.01); } catch (e) { return false; }
    notificar(nombre, grupo);
    return true;
  }

  // Desbloqueo con el primer gesto (política de reproducción automática de los navegadores).
  // Se escuchan varios tipos de gesto porque algunos navegadores solo aceptan el toque/clic completo.
  var GESTOS = ['pointerdown', 'pointerup', 'touchstart', 'touchend', 'keydown', 'keyup', 'click'];
  function desbloquear() {
    gesto = true; asegurar();
    if (listo()) GESTOS.forEach(function (ev) { document.removeEventListener(ev, desbloquear, true); });
  }
  GESTOS.forEach(function (ev) { document.addEventListener(ev, desbloquear, { capture: true, passive: true }); });

  // ───────────────────────────── capa de acciones ─────────────────────────────
  // Un sonido por acción, elegido según el tipo de control. Los controles de la propia sección «Sonidos»
  // tienen los suyos; los eventos generados por código (isTrusted = false) no suenan.
  var SEL_ACCION = '[data-sonido], a[href], button, [role="button"], [role="tab"], summary';
  var LIGEROS = { pestana: 1, activar: 1, desactivar: 1, seleccion: 1, ajuste: 1, clic: 1 };
  var ultimoTick = 0, ultimoNombre = '';
  function tick(nombre, grupo) {                               // evita que dos sonidos ligeros se amontonen; los de acción (enviar, navegar…) siempre suenan
    var ahora = Date.now();
    if (ahora - ultimoTick < 60 && (nombre === ultimoNombre || (LIGEROS[nombre] && LIGEROS[ultimoNombre]))) return false;
    ultimoTick = ahora; ultimoNombre = nombre;
    return reproducir(nombre, grupo);
  }
  function enSeccionSonidos(el) { return !!(el && el.closest && el.closest('#sec-sonidos')); }
  function sonidoPropio(el) { return el && el.getAttribute ? el.getAttribute('data-sonido') : null; }

  document.addEventListener('click', function (ev) {
    if (!ev.isTrusted || ev.button) return;
    var el = ev.target && ev.target.closest ? ev.target.closest(SEL_ACCION) : null;
    if (!el || enSeccionSonidos(el) || el.disabled || el.getAttribute('aria-disabled') === 'true') return;
    var propio = sonidoPropio(el);
    if (propio === 'ninguno') return;                          // el script de la página pone el sonido del resultado
    if (propio) { tick(propio, GRUPO[propio]); return; }
    if (el.tagName === 'A') {
      var href = el.getAttribute('href') || '';
      if (el.hasAttribute('download')) return;                 // suena cuando la descarga está lista
      if (!href || href.charAt(0) === '#' || /^javascript:/i.test(href)) { tick('pestana', 'interaccion'); return; }
      var otraPestana = el.target === '_blank' || ev.ctrlKey || ev.metaKey || ev.shiftKey || ev.altKey;
      var sono = tick('navegar', 'navegacion');
      if (sono && !otraPestana) {                              // deja oír el sonido antes de cambiar de página
        ev.preventDefault(); var destino = el.href;
        setTimeout(function () { window.location.assign(destino); }, 180);
      }
      return;
    }
    if (el.matches('[role="tab"], summary, [aria-expanded], [aria-pressed], .tab')) { tick('pestana', 'interaccion'); return; }
    if (el.tagName === 'BUTTON') {
      var tipo = (el.getAttribute('type') || 'submit').toLowerCase();
      if (tipo === 'submit' && el.form) return;                // el envío del formulario ya suena
      if (tipo === 'reset') { tick('desactivar', 'interaccion'); return; }
    }
    tick('clic', 'clic');
  }, true);

  document.addEventListener('submit', function (ev) {
    if (!enSeccionSonidos(ev.target) && sonidoPropio(ev.target) !== 'ninguno') tick('enviar', 'envio');
  }, true);

  document.addEventListener('change', function (ev) {
    var el = ev.target;
    if (!ev.isTrusted || !el || !el.tagName || enSeccionSonidos(el)) return;
    var propio = sonidoPropio(el);
    if (propio === 'ninguno') return;
    if (propio) { tick(propio, GRUPO[propio]); return; }
    var tipo = (el.type || '').toLowerCase();
    if (el.tagName === 'SELECT') tick('seleccion', 'interaccion');
    else if (tipo === 'checkbox' || tipo === 'radio' || el.getAttribute('role') === 'switch') tick(el.checked ? 'activar' : 'desactivar', 'interaccion');
    else if (tipo === 'range') tick('ajuste', 'interaccion');
    else if (tipo === 'file') tick('clic', 'clic');
  }, true);

  // Fin de la pantalla de carga (solo sonará si el navegador ya permite audio en esta página)
  document.addEventListener('app-loader:fin', function () { reproducir('inicio', 'carga'); });

  // ───────────────────────────── sección «Sonidos» en la página ─────────────────────────────
  // La página aporta la tarjeta (#sec-sonidos con #sn-config y, opcionalmente, #sn-estado) y el enlace de
  // cabecera (#sn-pill); aquí se pintan los controles y se mantienen sincronizados con la configuración.
  var css = [
    '#sec-sonidos { scroll-margin-top: 84px; }',
    '#sn-config { font-size: 13px; color: #334155; }',
    '#sn-config .sn-grid { display: grid; grid-template-columns: 1fr; gap: 14px; }',
    '@media (min-width: 1024px) { #sn-config .sn-grid { grid-template-columns: 1fr 1fr 1.35fr; } }',
    '#sn-config .sn-col { border: 1px solid #e6eaf0; border-radius: 12px; padding: 12px 14px; background: #fff; }',
    '#sn-config .sn-col.sn-deshab { opacity: .5; pointer-events: none; }',
    '#sn-config .sn-cab { display: flex; align-items: center; justify-content: space-between; gap: 10px; min-height: 24px; }',
    '#sn-config h3 { margin: 0; font-size: 11px; font-weight: 600; letter-spacing: .06em; text-transform: uppercase; color: #64748b; }',
    '#sn-config .sn-fila { display: grid; grid-template-columns: 1fr auto; align-items: center; gap: 6px 10px; margin: 8px 0; }',
    '#sn-config .sn-fila label { color: #334155; }',
    '#sn-config .sn-fila output { font-variant-numeric: tabular-nums; color: #64748b; min-width: 48px; text-align: right; font-size: 12px; }',
    '#sn-config .sn-fila input[type=range] { grid-column: 1 / -1; width: 100%; accent-color: #2546e8; margin: 0; }',
    '#sn-config select { border: 1px solid #e6eaf0; border-radius: 8px; padding: 4px 8px; font: inherit; color: #0f172a; background: #fff; }',
    '#sn-config .sn-switch { position: relative; width: 36px; height: 20px; flex: none; }',
    '#sn-config .sn-switch input { position: absolute; inset: 0; opacity: 0; margin: 0; cursor: pointer; }',
    '#sn-config .sn-switch span { position: absolute; inset: 0; border-radius: 9999px; background: #cbd5e1; transition: background .15s; }',
    '#sn-config .sn-switch span::after { content: ""; position: absolute; top: 2px; left: 2px; width: 16px; height: 16px; border-radius: 50%; background: #fff; transition: transform .15s; box-shadow: 0 1px 2px rgba(0,0,0,.2); }',
    '#sn-config .sn-switch input:checked + span { background: #2546e8; }',
    '#sn-config .sn-switch input:checked + span::after { transform: translateX(16px); }',
    '#sn-config .sn-switch input:focus-visible + span { box-shadow: 0 0 0 3px rgba(59,99,245,.35); }',
    '#sn-config .sn-evento { display: flex; align-items: center; gap: 8px; padding: 5px 0; border-top: 1px solid #f1f5f9; }',
    '#sn-config .sn-evento:first-of-type { border-top: 0; }',
    '#sn-config .sn-evento label { flex: 1; cursor: pointer; }',
    '#sn-config .sn-evento input[type=checkbox] { accent-color: #2546e8; width: 15px; height: 15px; margin: 0; }',
    '#sn-config .sn-probar { border: 1px solid #e6eaf0; background: #fff; border-radius: 8px; padding: 3px 9px; font: inherit; font-size: 12px; color: #2546e8; cursor: pointer; white-space: nowrap; }',
    '#sn-config .sn-probar:hover { background: #eef4ff; }',
    '#sn-config .sn-pie { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 8px; margin-top: 12px; }',
    '#sn-config .sn-nota { font-size: 11px; color: #94a3b8; line-height: 1.4; }',
    '#sn-config .sn-link { background: none; border: 0; padding: 0; font: inherit; font-size: 12px; color: #64748b; text-decoration: underline; cursor: pointer; }',
    '#sn-config .sn-aviso { margin-bottom: 10px; padding: 6px 10px; border-radius: 8px; background: #fffbeb; border: 1px solid #fde68a; color: #92400e; font-size: 12px; }',
    '#sn-config .sn-aviso[hidden] { display: none; }',
    '#sn-pill.sn-off { color: #64748b; background: #f8fafc; border-color: #e6eaf0; }',
    '@media print { #sec-sonidos { display: none !important; } }',
  ].join('\n');

  function $(sel, raiz) { return (raiz || document).querySelector(sel); }
  function fila(id, etiqueta, min, max, paso, valor, formato) {
    return '<div class="sn-fila"><label for="' + id + '">' + etiqueta + '</label><output id="' + id + '-v">' + formato(valor) + '</output>' +
      '<input type="range" id="' + id + '" min="' + min + '" max="' + max + '" step="' + paso + '" value="' + valor + '"></div>';
  }
  function interruptor(id, marcado, etiqueta) {
    return '<label class="sn-switch" title="' + etiqueta + '"><input type="checkbox" id="' + id + '"' + (marcado ? ' checked' : '') + ' aria-label="' + etiqueta + '"><span></span></label>';
  }
  var pct = function (v) { return Math.round(v * 100) + ' %'; };
  var fmtS = function (v) { return Number(v).toFixed(1) + ' s'; };
  var fmtMs = function (v) { return Math.round(v * 1000) + ' ms'; };

  function pintarEstado() {
    var pill = $('#sn-pill'), estado = $('#sn-estado');
    var activos = EVENTOS.filter(function (e) { return cfg.eventos[e[0]]; }).length;
    var texto = cfg.activo
      ? ('Activados · ' + activos + ' de ' + EVENTOS.length + ' acciones · reverberación ' + (cfg.reverb.activo ? pct(cfg.reverb.mezcla) : 'apagada'))
      : 'Desactivados';
    if (pill) { pill.textContent = (cfg.activo ? '🔊' : '🔇') + ' Sonidos'; pill.classList.toggle('sn-off', !cfg.activo); pill.title = 'Sonidos ' + texto.toLowerCase() + ' · ir a la configuración'; }
    if (estado) estado.textContent = texto;
    var r = $('#sn-col-reverb'), e = $('#sn-col-eventos');
    if (r) r.classList.toggle('sn-deshab', !cfg.activo);
    if (e) e.classList.toggle('sn-deshab', !cfg.activo);
    var rv = $('#sn-rv'); if (rv) rv.classList.toggle('sn-deshab', !cfg.reverb.activo);
  }

  function montarUI() {
    var cont = $('#sn-config');
    if (!cont) { pintarEstado(); return; }
    if (!$('#sn-estilos')) { var style = document.createElement('style'); style.id = 'sn-estilos'; style.textContent = css; document.head.appendChild(style); }
    cont.innerHTML =
      '<div class="sn-aviso" id="sn-bloqueado" hidden>El navegador solo permite sonido después de tu primer clic en la página. Pulsa «Probar» para activarlo.</div>' +
      '<div class="sn-grid">' +
        '<div class="sn-col" id="sn-col-general"><div class="sn-cab"><h3>General</h3>' + interruptor('sn-activo', cfg.activo, 'Activar sonidos') + '</div>' +
          fila('sn-volumen', 'Volumen', 0, 1, 0.01, cfg.volumen, pct) +
          '<div class="sn-fila"><label for="sn-tema">Tema de sonido</label><select id="sn-tema">' +
            '<option value="suave"' + (cfg.tema === 'suave' ? ' selected' : '') + '>Suave</option>' +
            '<option value="campana"' + (cfg.tema === 'campana' ? ' selected' : '') + '>Campana</option>' +
            '<option value="digital"' + (cfg.tema === 'digital' ? ' selected' : '') + '>Digital</option></select></div>' +
          '<div class="sn-fila"><span class="sn-nota">Escucha el ajuste actual</span><button type="button" class="sn-probar" data-probar="exito">▶ Probar</button></div>' +
        '</div>' +
        '<div class="sn-col" id="sn-col-reverb"><div class="sn-cab"><h3>Reverberación</h3>' + interruptor('sn-rv-activo', cfg.reverb.activo, 'Activar reverberación') + '</div>' +
          '<div id="sn-rv">' +
            fila('sn-rv-mezcla', 'Cantidad', 0, 1, 0.01, cfg.reverb.mezcla, pct) +
            fila('sn-rv-cola', 'Cola (duración)', 0.2, 6, 0.1, cfg.reverb.cola, fmtS) +
            fila('sn-rv-retardo', 'Retardo inicial', 0, 0.12, 0.005, cfg.reverb.retardo, fmtMs) +
            fila('sn-rv-brillo', 'Brillo', 0, 1, 0.01, cfg.reverb.brillo, pct) +
            '<div class="sn-fila"><span class="sn-nota">Compara con y sin reverberación</span><button type="button" class="sn-probar" data-probar="si">▶ Probar</button></div>' +
          '</div>' +
        '</div>' +
        '<div class="sn-col" id="sn-col-eventos"><div class="sn-cab"><h3>Cuándo suena</h3><button type="button" class="sn-link" id="sn-todos">Todas sí / no</button></div>' +
          EVENTOS.map(function (e) {
            return '<div class="sn-evento"><input type="checkbox" id="sn-ev-' + e[0] + '" data-evento="' + e[0] + '"' + (cfg.eventos[e[0]] ? ' checked' : '') + '>' +
              '<label for="sn-ev-' + e[0] + '">' + e[1] + '</label><button type="button" class="sn-probar" data-probar="' + e[2] + '" title="Escuchar">▶</button></div>';
          }).join('') +
        '</div>' +
      '</div>' +
      '<div class="sn-pie"><span class="sn-nota">Cada acción del panel tiene su propio sonido. La configuración se guarda en este navegador y se aplica en todas las páginas.</span><button type="button" class="sn-link" id="sn-reset">Restablecer valores</button></div>';

    $('#sn-activo').addEventListener('change', function (ev) { cfg.activo = ev.target.checked; guardar(); aplicarMezcla(); pintarEstado(); if (cfg.activo) { asegurar(); reproducir('activar'); } });
    $('#sn-volumen').addEventListener('input', function (ev) { cfg.volumen = Number(ev.target.value); $('#sn-volumen-v').value = pct(cfg.volumen); guardar(); aplicarMezcla(); });
    $('#sn-volumen').addEventListener('change', function () { reproducir('aviso'); });
    $('#sn-tema').addEventListener('change', function (ev) { cfg.tema = ev.target.value; guardar(); reproducir('exito'); });
    $('#sn-rv-activo').addEventListener('change', function (ev) { cfg.reverb.activo = ev.target.checked; guardar(); aplicarMezcla(); pintarEstado(); reproducir('exito'); });
    [['mezcla', pct, aplicarMezcla], ['cola', fmtS, programarIR], ['retardo', fmtMs, programarIR], ['brillo', pct, programarIR]].forEach(function (d) {
      var el = $('#sn-rv-' + d[0]);
      el.addEventListener('input', function (ev) { cfg.reverb[d[0]] = Number(ev.target.value); $('#sn-rv-' + d[0] + '-v').value = d[1](cfg.reverb[d[0]]); guardar(); d[2](); pintarEstado(); });
      el.addEventListener('change', function () { setTimeout(function () { reproducir('exito'); }, 180); });
    });
    cont.querySelectorAll('[data-evento]').forEach(function (cb) {
      cb.addEventListener('change', function (ev) { cfg.eventos[ev.target.dataset.evento] = ev.target.checked; guardar(); pintarEstado(); reproducir(ev.target.checked ? 'activar' : 'desactivar'); });
    });
    $('#sn-todos').addEventListener('click', function () {
      var todos = EVENTOS.every(function (e) { return cfg.eventos[e[0]]; });
      EVENTOS.forEach(function (e) { cfg.eventos[e[0]] = !todos; var cb = $('#sn-ev-' + e[0]); if (cb) cb.checked = !todos; });
      guardar(); pintarEstado(); reproducir(todos ? 'desactivar' : 'activar');
    });
    cont.querySelectorAll('[data-probar]').forEach(function (b) {
      b.addEventListener('click', function (ev) {
        asegurar();
        var nombre = ev.currentTarget.dataset.probar;
        if (!cfg.activo) { cfg.activo = true; $('#sn-activo').checked = true; guardar(); aplicarMezcla(); pintarEstado(); }
        reproducir(nombre);                                      // si el audio aún arranca, queda en cola y suena enseguida
        setTimeout(function () { var av = $('#sn-bloqueado'); if (av) av.hidden = listo(); }, 250);
      });
    });
    $('#sn-reset').addEventListener('click', function () {
      cfg = clonar(DEFECTO); guardar(); aplicarMezcla(); programarIR();
      montarUI(); reproducir('aviso');
    });
    pintarEstado();
  }

  function irASeccion() {
    var sec = $('#sec-sonidos'); if (!sec) return;
    sec.scrollIntoView({ behavior: 'smooth', block: 'start' });
    var primero = $('#sn-activo'); if (primero) setTimeout(function () { primero.focus({ preventScroll: true }); }, 400);
  }
  function enlazarPill() {
    var pill = $('#sn-pill');
    if (pill && !pill.dataset.listo) { pill.dataset.listo = '1'; pill.addEventListener('click', function (ev) { ev.preventDefault(); asegurar(); irASeccion(); }); }
  }
  function iniciar() { montarUI(); enlazarPill(); }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', iniciar); else iniciar();

  window.SONIDOS = {
    reproducir: reproducir,
    config: function () { return clonar(cfg); },
    abrir: irASeccion,
    cerrar: function () { /* la configuración es una sección de la página: no hay nada que cerrar */ },
  };
})();
