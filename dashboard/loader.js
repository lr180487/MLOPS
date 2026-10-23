/*
 * Pantalla de arranque del dashboard: el logo con un anillo que gira a su alrededor
 * durante 5 segundos; después se desvanece y se retira del documento.
 *
 * Uso: cargar este archivo en el <head> de la página (sin defer) y colocar, justo
 * después de <body>, el contenedor:
 *   <div id="app-loader" role="status" aria-live="polite" aria-label="Cargando">
 *     <div class="al-centro"><span class="al-anillo"></span><span class="al-punto"></span><span class="al-logo"></span></div>
 *     <p class="al-titulo">MLOps Dashboard</p><p class="al-texto">Cargando…</p>
 *   </div>
 * Los estilos se inyectan desde aquí para que el loader se vea desde el primer
 * fotograma, sin depender de Tailwind ni de la red. No requiere ninguna librería.
 */
(function () {
  'use strict';
  var DURACION_MS = 5000;     // tiempo que permanece visible
  var DESVANECER_MS = 450;    // duración del fundido de salida
  var SOLO_PRIMERA_VEZ = false; // true → se muestra solo en la primera página de cada sesión del navegador

  // Logo: mismo dibujo que el favicon (cuadrado azul con línea de tendencia)
  var LOGO = "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'%3E%3Crect width='100' height='100' rx='20' fill='%232546e8'/%3E%3Cpath d='M22 72 L42 46 L58 58 L80 28' stroke='white' stroke-width='9' fill='none' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E\")";

  var css = [
    'html.al-abierto { overflow: hidden; }',
    '#app-loader { position: fixed; inset: 0; z-index: 9999; display: flex; flex-direction: column; align-items: center; justify-content: center;',
    '  gap: 6px; background: #ffffff; color: #0f172a; font-family: Inter, ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;',
    '  opacity: 1; transition: opacity ' + DESVANECER_MS + 'ms ease; }',
    '#app-loader.al-salir { opacity: 0; pointer-events: none; }',
    '#app-loader .al-centro { position: relative; width: 124px; height: 124px; margin-bottom: 14px; }',
    // anillo que gira alrededor del logo: arco azul sobre una pista tenue
    '#app-loader .al-anillo { position: absolute; inset: 0; border-radius: 50%;',
    '  background: conic-gradient(from 0deg, #2546e8 0 28%, rgba(37, 70, 232, .12) 28% 100%);',
    '  -webkit-mask: radial-gradient(farthest-side, transparent calc(100% - 6px), #000 calc(100% - 5px));',
    '          mask: radial-gradient(farthest-side, transparent calc(100% - 6px), #000 calc(100% - 5px));',
    '  animation: al-girar 1.1s linear infinite; }',
    // punto brillante en la cabeza del arco: gira con la misma animación que el anillo (fuera de su máscara)
    '#app-loader .al-punto { position: absolute; inset: 0; animation: al-girar 1.1s linear infinite; }',
    '#app-loader .al-punto::after { content: ""; position: absolute; top: 50%; left: 50%; width: 10px; height: 10px; margin: -5px 0 0 -5px; border-radius: 50%;',
    '  background: #2546e8; box-shadow: 0 0 0 3px rgba(37, 70, 232, .18); transform: rotate(100deg) translateY(-59px); }',
    '#app-loader .al-logo { position: absolute; left: 50%; top: 50%; width: 68px; height: 68px; margin: -34px 0 0 -34px; border-radius: 16px;',
    '  background: ' + LOGO + ' center / contain no-repeat; box-shadow: 0 6px 18px rgba(37, 70, 232, .28); animation: al-latir 2.2s ease-in-out infinite; }',
    '#app-loader .al-titulo { margin: 0; font-size: 15px; font-weight: 600; letter-spacing: .01em; }',
    '#app-loader .al-texto { margin: 0; font-size: 12px; color: #64748b; }',
    '#app-loader .al-texto::after { content: ""; display: inline-block; width: 1.2em; text-align: left; animation: al-puntos 1.5s steps(4, end) infinite; }',
    '@keyframes al-girar { to { transform: rotate(360deg); } }',
    '@keyframes al-latir { 0%, 100% { transform: scale(1); } 50% { transform: scale(1.04); } }',
    '@keyframes al-puntos { 0% { content: ""; } 25% { content: "."; } 50% { content: ".."; } 75% { content: "..."; } }',
    '@media (prefers-reduced-motion: reduce) {',
    '  #app-loader .al-anillo { animation: al-pulso 1.6s ease-in-out infinite; }',
    '  #app-loader .al-punto, #app-loader .al-logo, #app-loader .al-texto::after { animation: none; }',
    '  #app-loader .al-punto { display: none; }',
    '  @keyframes al-pulso { 0%, 100% { opacity: .35; } 50% { opacity: 1; } } }',
  ].join('\n');

  if (SOLO_PRIMERA_VEZ) {
    try {
      if (sessionStorage.getItem('app-loader-visto')) {
        // ya se mostró en esta sesión: ocultar el contenedor en cuanto exista y no bloquear nada
        var ocultar = document.createElement('style'); ocultar.textContent = '#app-loader { display: none !important; }';
        (document.head || document.documentElement).appendChild(ocultar);
        return;
      }
      sessionStorage.setItem('app-loader-visto', '1');
    } catch (e) { /* almacenamiento no disponible: se muestra siempre */ }
  }

  var style = document.createElement('style');
  style.id = 'app-loader-style';
  style.textContent = css;
  (document.head || document.documentElement).appendChild(style);
  document.documentElement.classList.add('al-abierto');

  function cerrar(el) {
    el.classList.add('al-salir');
    el.setAttribute('aria-hidden', 'true');
    window.setTimeout(function () {
      if (el.parentNode) el.parentNode.removeChild(el);
      document.documentElement.classList.remove('al-abierto');
      if (style.parentNode) style.parentNode.removeChild(style);
      try { document.dispatchEvent(new CustomEvent('app-loader:fin')); } catch (e) { /* navegadores muy antiguos */ }
    }, DESVANECER_MS);
  }

  // El temporizador arranca ya (no espera a que terminen de descargarse las librerías de la página).
  // Si al cumplirse los 5 s el contenedor aún no existe, se cierra en cuanto aparezca.
  var cerrado = false;
  function intentarCerrar() {
    if (cerrado) return true;
    var el = document.getElementById('app-loader');
    if (!el) return false;
    cerrado = true; cerrar(el); return true;
  }
  window.setTimeout(function () {
    if (intentarCerrar()) return;
    var reintento = window.setInterval(function () { if (intentarCerrar()) window.clearInterval(reintento); }, 50);
  }, DURACION_MS);

  // Si la página no incluye el contenedor, no dejar el documento sin desplazamiento.
  document.addEventListener('DOMContentLoaded', function () {
    if (!document.getElementById('app-loader')) document.documentElement.classList.remove('al-abierto');
  });
})();
