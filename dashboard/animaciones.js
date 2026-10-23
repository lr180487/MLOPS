/*
 * Animaciones de las gráficas y de los indicadores del dashboard.
 *
 * Sin dependencias (usa Chart.js solo si está cargado). Expone window.ANIM con:
 *   - reducida()                      → true si el usuario prefiere menos movimiento (todo se vuelve instantáneo)
 *   - contar(el, texto, ms)           → el número del texto «cuenta» desde el valor anterior (respeta prefijo, sufijo,
 *                                       decimales y separador de miles: «68.0%», «1,234», «12.50 ms», «0.725»)
 *   - pop(el)                         → pequeño «latido» de escala al cambiar un valor
 *   - transicionCanvas(canvas, op)    → tras dibujar un <canvas> de golpe, lo revela con un barrido diagonal (primera vez)
 *                                       o con un fundido desde el fotograma anterior (actualizaciones)
 *   - barrasAlVer(raiz, selector)     → barras con data-ancho crecen desde 0 cuando entran en pantalla
 *   - escalonar(raiz, selector, paso) → entrada escalonada (subir + aparecer) de tarjetas o filas
 *   - configurarChart()               → registra en Chart.js los plugins de animación (se llama solo al cargar)
 *
 * Chart.js (plugin «mlopsAnimaciones»): por tipo de gráfico, al crearse y al volver a entrar en pantalla:
 *   barras → crecen escalonadas desde la base · líneas → se trazan de izquierda a derecha ·
 *   dispersión → los puntos brotan escalonados · doughnut → giran al abrirse.
 *   La animación de entrada se reproduce cuando el gráfico está a la vista (y, si hay pantalla de carga, cuando
 *   termina), no antes, para que no se pierda. Las actualizaciones posteriores se interpolan con suavidad.
 * Chart.js (plugin «mlopsPulso»): un pulso luminoso en el último punto de las series en vivo
 *   (options.plugins.mlopsPulso = { datasets: [0, 1] } o true).
 */
(function () {
  'use strict';

  // ───────────────────────────── utilidades ─────────────────────────────
  function reducida() { try { return window.matchMedia('(prefers-reduced-motion: reduce)').matches; } catch (e) { return false; } }
  var easings = {
    outCubic: function (t) { return 1 - Math.pow(1 - t, 3); },
    outQuart: function (t) { return 1 - Math.pow(1 - t, 4); },
    outBack: function (t) { var c = 1.70158; return 1 + (c + 1) * Math.pow(t - 1, 3) + c * Math.pow(t - 1, 2); },
    inOutCubic: function (t) { return t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2; },
  };
  function hayLoader() { return !!document.getElementById('app-loader'); }
  // Ejecuta cb cuando la pantalla de carga haya terminado (o ya, si no la hay)
  function trasLoader(cb) {
    if (!hayLoader()) { cb(); return; }
    document.addEventListener('app-loader:fin', function () { cb(); }, { once: true });
  }
  function enPantalla(el) {
    if (!el || !el.isConnected) return false;
    var r = el.getBoundingClientRect();
    if (!r.width && !r.height) return false;                      // oculto (display:none o pestaña cerrada)
    return r.bottom > 0 && r.top < (window.innerHeight || document.documentElement.clientHeight);
  }

  // CSS propio (independiente de Tailwind)
  var css = [
    '@keyframes anim-subir { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: translateY(0); } }',
    '@keyframes anim-latido { 0% { transform: scale(1); } 35% { transform: scale(1.07); } 100% { transform: scale(1); } }',
    '@keyframes anim-destello { 0% { background-color: rgba(59, 99, 245, .10); } 100% { background-color: transparent; } }',
    '.anim-subir { animation: anim-subir .5s cubic-bezier(.2,.7,.2,1) both; }',
    '.anim-latido { animation: anim-latido .45s ease-out; }',
    '#events-body tr.animate-rise > td { animation: anim-destello 1.4s ease-out; }',
    '.drift-bar { transition: left .7s cubic-bezier(.2,.7,.2,1), width .7s cubic-bezier(.2,.7,.2,1), background-color .4s; }',
    '.mini-bar { transition: width .8s cubic-bezier(.2,.7,.2,1); }',
    '@media (prefers-reduced-motion: reduce) { .anim-subir, .anim-latido, #events-body tr.animate-rise > td { animation: none !important; } .drift-bar, .mini-bar { transition: none !important; } }',
  ].join('\n');
  function inyectarCSS() {
    if (document.getElementById('anim-estilos')) return;
    var s = document.createElement('style'); s.id = 'anim-estilos'; s.textContent = css; document.head.appendChild(s);
  }

  // ───────────────────────────── contador numérico ─────────────────────────────
  var RE_NUM = /-?\d[\d,]*(?:\.\d+)?/;
  var contadores = new WeakMap();
  function cancelarContador(el) { var id = contadores.get(el); if (id) { cancelAnimationFrame(id); contadores.delete(el); } }
  function contar(el, texto, ms) {
    if (!el) return;
    texto = String(texto);
    var mNuevo = RE_NUM.exec(texto), mViejo = RE_NUM.exec(el.textContent || '');
    cancelarContador(el);
    if (!mNuevo || !mViejo || reducida()) { el.textContent = texto; return; }
    var hasta = parseFloat(mNuevo[0].replace(/,/g, '')), desde = parseFloat(mViejo[0].replace(/,/g, ''));
    if (!isFinite(hasta) || !isFinite(desde) || desde === hasta) { el.textContent = texto; return; }
    var dec = (mNuevo[0].split('.')[1] || '').length, miles = mNuevo[0].indexOf(',') >= 0;
    var pre = texto.slice(0, mNuevo.index), post = texto.slice(mNuevo.index + mNuevo[0].length);
    var dur = ms || 700, t0 = performance.now();
    function fmt(v) {
      var s = Math.abs(v).toFixed(dec);
      if (miles) s = s.replace(/\B(?=(\d{3})+(?!\d))/g, ',');
      return (v < 0 ? '-' : '') + s;
    }
    function frame(ahora) {
      var p = Math.min(1, (ahora - t0) / dur), e = easings.outCubic(p);
      el.textContent = p < 1 ? pre + fmt(desde + (hasta - desde) * e) + post : texto;
      if (p < 1) contadores.set(el, requestAnimationFrame(frame)); else contadores.delete(el);
    }
    contadores.set(el, requestAnimationFrame(frame));
  }
  function pop(el) {
    if (!el || reducida()) return;
    el.classList.remove('anim-latido'); void el.offsetWidth; el.classList.add('anim-latido');
  }

  // ───────────────────────────── transición de canvas ─────────────────────────────
  var fotogramas = new WeakMap();   // canvas → { ultimo: canvas clonado, raf, pendiente }
  function clonarCanvas(c) { var k = document.createElement('canvas'); k.width = c.width; k.height = c.height; k.getContext('2d').drawImage(c, 0, 0); return k; }
  function pintar(ctx, W, H, fn) { ctx.save(); ctx.setTransform(1, 0, 0, 1, 0, 0); ctx.clearRect(0, 0, W, H); fn(ctx); ctx.restore(); }
  function transicionCanvas(canvas, op) {
    if (!canvas || !canvas.width || !canvas.height) return;
    op = op || {};
    var reg = fotogramas.get(canvas) || {};
    if (reg.raf) { cancelAnimationFrame(reg.raf); reg.raf = 0; }
    if (reg.pendiente) { document.removeEventListener('app-loader:fin', reg.pendiente); reg.pendiente = null; }
    var nuevo = clonarCanvas(canvas);
    var anterior = reg.ultimo && reg.ultimo.width === nuevo.width && reg.ultimo.height === nuevo.height ? reg.ultimo : null;
    reg.ultimo = nuevo; fotogramas.set(canvas, reg);
    if (reducida() || op.modo === 'ninguno') return;
    var modo = op.modo || (anterior ? 'fundido' : 'barrido');
    var ms = op.ms || (modo === 'barrido' ? 850 : 500);
    var ctx = canvas.getContext('2d'), W = canvas.width, H = canvas.height;

    function arrancar() {
      var t0 = performance.now();
      function frame(ahora) {
        var p = Math.min(1, (ahora - t0) / ms), e = easings.outCubic(p);
        pintar(ctx, W, H, function (c) {
          if (modo === 'fundido') {
            if (anterior) c.drawImage(anterior, 0, 0);
            c.globalAlpha = e; c.drawImage(nuevo, 0, 0);
          } else {                                                   // barrido diagonal de izquierda a derecha
            if (anterior) c.drawImage(anterior, 0, 0);
            var sesgo = H * 0.35, x = -sesgo + (W + 2 * sesgo) * e;
            c.beginPath(); c.moveTo(0, 0); c.lineTo(x + sesgo, 0); c.lineTo(x - sesgo, H); c.lineTo(0, H); c.closePath(); c.clip();
            c.globalAlpha = Math.min(1, 0.35 + e); c.drawImage(nuevo, 0, 0);
          }
        });
        if (p < 1) reg.raf = requestAnimationFrame(frame);
        else { reg.raf = 0; pintar(ctx, W, H, function (c) { c.drawImage(nuevo, 0, 0); }); }
      }
      reg.raf = requestAnimationFrame(frame);
    }
    if (hayLoader()) {                                               // bajo la pantalla de carga: espera a que termine para que se vea
      pintar(ctx, W, H, function (c) { if (anterior) c.drawImage(anterior, 0, 0); });
      reg.pendiente = function () { reg.pendiente = null; arrancar(); };
      document.addEventListener('app-loader:fin', reg.pendiente, { once: true });
    } else arrancar();
  }

  // ───────────────────────────── barras y tarjetas ─────────────────────────────
  function barrasAlVer(raiz, selector) {
    var els = (raiz || document).querySelectorAll(selector || '[data-ancho]');
    if (!els.length) return;
    if (reducida() || !('IntersectionObserver' in window)) { els.forEach(function (el) { el.style.width = el.dataset.ancho; }); return; }
    var io = new IntersectionObserver(function (entradas) {
      entradas.forEach(function (en) { if (en.isIntersecting) { en.target.style.width = en.target.dataset.ancho; io.unobserve(en.target); } });
    }, { threshold: 0.15 });
    els.forEach(function (el) { el.style.width = '0%'; });
    trasLoader(function () { els.forEach(function (el) { io.observe(el); }); });
  }
  function escalonar(raiz, selector, paso, max) {
    if (reducida()) return;
    var els = Array.prototype.slice.call((raiz || document).querySelectorAll(selector), 0, max || 24);
    els.forEach(function (el, i) {
      el.style.animationDelay = (i * (paso || 60)) + 'ms';
      el.classList.remove('anim-subir'); void el.offsetWidth; el.classList.add('anim-subir');
      el.addEventListener('animationend', function fin() { el.classList.remove('anim-subir'); el.style.animationDelay = ''; el.removeEventListener('animationend', fin); });
    });
  }

  // ───────────────────────────── Chart.js ─────────────────────────────
  function marcarListo(chart) {
    var conDatos = (chart.data.datasets || []).some(function (d) { return d.data && d.data.length; });
    if (conDatos) chart.$mlopsListo = true;
  }
  function entrada(chart, ctx) {                                     // ¿estamos en la animación de entrada de este elemento?
    return ctx.type === 'data' && ctx.mode === 'default' && !chart.$mlopsListo && !chart.$mlopsEsperando;
  }
  function yPrevio(ctx) {
    var chart = ctx.chart, esc = chart.scales.y || null;
    if (!esc) { var claves = Object.keys(chart.scales); for (var i = 0; i < claves.length; i++) if (chart.scales[claves[i]].axis === 'y') { esc = chart.scales[claves[i]]; break; } }
    if (ctx.index === 0 || !ctx.index) return esc ? esc.getPixelForValue(esc.min) : 0;
    var meta = chart.getDatasetMeta(ctx.datasetIndex), prev = meta.data[ctx.index - 1];
    return prev ? prev.getProps(['y'], true).y : 0;
  }

  // Duración «normal» de un cambio, respetando los modos de Chart.js: nada mientras el gráfico espera su
  // entrada, nada en resize/none/reset (deben ser instantáneos) y breve al pasar el ratón (active).
  function durModo(chart, ctx, porDefecto) {
    if (chart.$mlopsEsperando) return 0;
    var modo = ctx && ctx.mode;
    if (modo === 'resize' || modo === 'none' || modo === 'reset') return 0;
    if (modo === 'active') return 220;
    return porDefecto;
  }

  var pluginAnimaciones = {
    id: 'mlopsAnimaciones',
    beforeInit: function (chart) {
      // Se trabaja sobre las opciones «crudas» (objeto plano) y no sobre chart.options, que es un proxy de
      // resolución de Chart.js: copiar sus sub-objetos congelaría valores ya resueltos (p. ej. duración 0
      // mientras el gráfico espera bajo la pantalla de carga) y la entrada nunca llegaría a reproducirse.
      var o = chart.config.options || (chart.config.options = {});
      if (o.plugins && o.plugins.mlopsAnimaciones === false) return;
      if (reducida()) { o.animation = false; return; }
      var tipo = chart.config.type;
      var base = (o.animation && typeof o.animation === 'object') ? Object.assign({}, o.animation) : {};
      var dur = base.duration || 950, origComplete = base.onComplete;
      o.animation = Object.assign(base, {
        easing: base.easing || 'easeOutQuart',
        duration: function (ctx) { return durModo(chart, ctx, dur); },
        onComplete: function (ev) { if (origComplete) origComplete.call(this, ev); marcarListo(chart); },
      });
      o.animations = (o.animations && typeof o.animations === 'object') ? Object.assign({}, o.animations) : {};
      if (tipo === 'bar') {
        var paso = o.indexAxis === 'y' ? 80 : 55;
        o.animation.delay = function (ctx) { return entrada(chart, ctx) ? Math.min(ctx.dataIndex * paso + ctx.datasetIndex * 140, 1400) : 0; };
      } else if (tipo === 'line') {
        var total = 1200;
        function pasoLinea(ctx) { var d = chart.data.datasets[ctx.datasetIndex]; var n = d && d.data ? d.data.length : 1; return total / Math.max(n, 1); }
        o.animations.x = {
          type: 'number', easing: 'linear',
          duration: function (ctx) { return entrada(chart, ctx) ? pasoLinea(ctx) : durModo(chart, ctx, dur); },
          from: function (ctx) { return entrada(chart, ctx) ? NaN : undefined; },
          delay: function (ctx) { if (!entrada(chart, ctx) || ctx.xIniciado) return 0; ctx.xIniciado = true; return ctx.index * pasoLinea(ctx); },
        };
        o.animations.y = {
          type: 'number', easing: 'linear',
          duration: function (ctx) { return entrada(chart, ctx) ? pasoLinea(ctx) : durModo(chart, ctx, dur); },
          from: function (ctx) { return entrada(chart, ctx) ? yPrevio(ctx) : undefined; },
          delay: function (ctx) { if (!entrada(chart, ctx) || ctx.yIniciado) return 0; ctx.yIniciado = true; return ctx.index * pasoLinea(ctx); },
        };
      } else if (tipo === 'scatter' || tipo === 'bubble') {
        o.animations.radius = {
          type: 'number', easing: 'easeOutBack',
          duration: function (ctx) { return entrada(chart, ctx) ? 550 : durModo(chart, ctx, dur); },
          from: function (ctx) { return entrada(chart, ctx) ? 0 : undefined; },
          delay: function (ctx) { return entrada(chart, ctx) ? Math.min(ctx.dataIndex * 3 + ctx.datasetIndex * 160, 1500) : 0; },
        };
      } else if (tipo === 'doughnut' || tipo === 'pie' || tipo === 'polarArea') {
        o.animation.animateRotate = true; o.animation.animateScale = true;
      }
      // La entrada se reproduce cuando el gráfico está a la vista y sin pantalla de carga por encima
      chart.$mlopsEsperando = true;
    },
    afterInit: function (chart) {
      if (!chart.$mlopsEsperando) return;
      var canvas = chart.canvas;
      function reproducir() {
        if (chart.$mlopsDestruido) return;
        if (typeof chart.stop === 'function') chart.stop();               // corta cualquier animación en curso (p. ej. un resize o una actualización en vivo)
        chart.$mlopsEsperando = false; chart.$mlopsListo = false;
        (chart.data.datasets || []).forEach(function (d, i) { var meta = chart.getDatasetMeta(i); (meta.data || []).forEach(function (el) { if (el.$context) { el.$context.xIniciado = false; el.$context.yIniciado = false; } }); });
        chart.reset(); chart.update();
      }
      function vigilar() {
        if (chart.$mlopsDestruido) return;
        if (enPantalla(canvas)) { reproducir(); return; }
        if (!('IntersectionObserver' in window)) { reproducir(); return; }
        var io = new IntersectionObserver(function (ents) {
          if (ents.some(function (e) { return e.isIntersecting && e.boundingClientRect.width > 0; })) { io.disconnect(); reproducir(); }
        }, { threshold: 0.2 });
        io.observe(canvas); chart.$mlopsIO = io;
      }
      trasLoader(function () { setTimeout(vigilar, 30); });
    },
    afterDestroy: function (chart) { chart.$mlopsDestruido = true; if (chart.$mlopsIO) chart.$mlopsIO.disconnect(); },
  };

  var pluginPulso = {
    id: 'mlopsPulso',
    afterDatasetsDraw: function (chart, args, opts) {
      if (!opts || !opts.datasets || chart.$mlopsEsperando) return;
      var lista = opts.datasets === true ? chart.data.datasets.map(function (_, i) { return i; }) : opts.datasets;
      var ctx = chart.ctx, fase = (Date.now() % 1700) / 1700, quieto = reducida();
      lista.forEach(function (i) {
        var meta = chart.getDatasetMeta(i); if (!meta || meta.hidden || !chart.isDatasetVisible(i)) return;
        var pts = meta.data || [], ultimo = pts[pts.length - 1]; if (!ultimo || ultimo.skip) return;
        var x = ultimo.x, y = ultimo.y; if (!isFinite(x) || !isFinite(y)) return;
        var color = chart.data.datasets[i].borderColor || '#2546e8';
        ctx.save();
        if (!quieto) {
          ctx.beginPath(); ctx.arc(x, y, 3 + 10 * fase, 0, Math.PI * 2);
          ctx.strokeStyle = color; ctx.globalAlpha = 0.55 * (1 - fase); ctx.lineWidth = 2; ctx.stroke();
        }
        ctx.globalAlpha = 1; ctx.beginPath(); ctx.arc(x, y, 3.2, 0, Math.PI * 2); ctx.fillStyle = color; ctx.fill();
        ctx.lineWidth = 1.5; ctx.strokeStyle = '#ffffff'; ctx.stroke();
        ctx.restore();
      });
      if (!quieto && !chart.$pulsoTimer) {
        chart.$pulsoTimer = setTimeout(function () {
          chart.$pulsoTimer = 0;
          if (chart.$mlopsDestruido || !chart.canvas || !chart.canvas.isConnected || document.hidden) return;
          requestAnimationFrame(function () { if (!chart.$mlopsDestruido) chart.draw(); });
        }, 40);
      }
    },
    afterDestroy: function (chart) { chart.$mlopsDestruido = true; clearTimeout(chart.$pulsoTimer); },
  };

  function configurarChart() {
    if (typeof Chart === 'undefined' || Chart.$mlopsAnim) return false;
    Chart.$mlopsAnim = true;
    Chart.defaults.animation.duration = 950;
    Chart.defaults.animation.easing = 'easeOutQuart';
    Chart.defaults.transitions.active.animation.duration = 220;
    Chart.defaults.elements.point.hoverRadius = 6;
    Chart.defaults.elements.point.hitRadius = 8;
    Chart.defaults.elements.bar.hoverBorderWidth = 0;
    Chart.register(pluginAnimaciones, pluginPulso);
    return true;
  }

  // Si el documento tiene pantalla de carga, cuando termine las tarjetas principales entran escalonadas
  function entradaPagina() {
    trasLoader(function () {
      escalonar(document, 'main [data-kpi]', 40, 12);
      escalonar(document, 'main > section, main > div.card, main > div > .card', 70, 14);
    });
  }

  inyectarCSS();
  configurarChart();
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', entradaPagina); else entradaPagina();

  window.ANIM = { reducida: reducida, easings: easings, contar: contar, pop: pop, transicionCanvas: transicionCanvas, barrasAlVer: barrasAlVer, escalonar: escalonar, configurarChart: configurarChart, trasLoader: trasLoader };
})();
