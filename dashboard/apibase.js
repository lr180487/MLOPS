/*
 * apibase.js — localiza la API FastAPI cuando la página NO se sirve desde ella
 * (visor de archivos del workspace, file://, Live Server, otro host…).
 *
 * Orden de búsqueda (el primero que responda a GET /api/health gana):
 *   1. el origen de la propia página (caso normal: http://localhost:8000/resultados)
 *   2. ?api=https://host:puerto   (se recuerda en localStorage; ?api= vacío lo olvida)
 *   3. la URL guardada en localStorage
 *   4. las URLs de dashboard/api-base.js (las escribe la API al arrancar)
 *   5. http://localhost:8000 · http://127.0.0.1:8000
 *
 * Expone window.MLOPS: { base, url(path), listo (Promise), enOrigen, salud, candidatos, banner() }.
 * Las páginas esperan `await MLOPS.listo` antes de la primera llamada y usan MLOPS.url('/api/…').
 */
window.MLOPS = (() => {
  const KEY = 'mlops_api_base';
  const norm = (u) => (u || '').trim().replace(/\/+$/, '');
  const esHttp = location.protocol === 'http:' || location.protocol === 'https:';
  const params = new URLSearchParams(location.search);
  let forzada = '';
  if (params.has('api')) {
    forzada = norm(params.get('api'));
    try { if (forzada) localStorage.setItem(KEY, forzada); else localStorage.removeItem(KEY); } catch { /* sin storage */ }
  }
  let guardada = '';
  try { guardada = norm(localStorage.getItem(KEY)); } catch { /* sin storage */ }
  const generadas = (window.MLOPS_API_BASES || []).map(norm).filter(Boolean);
  const candidatos = [...new Set([esHttp ? location.origin : '', forzada, guardada, ...generadas, 'http://localhost:8000', 'http://127.0.0.1:8000'].filter(Boolean))];

  const M = {
    base: null, salud: null, candidatos, generadas,
    origen: esHttp ? location.origin : null,
    url(path) { return (M.base || '') + path; },
    get enOrigen() { return !!M.base && M.base === M.origen; },
    get pagina() { return location.pathname.split('/').pop() || 'index.html'; },
  };

  async function sondear(base, ms = 2500) {
    const ctl = new AbortController(); const t = setTimeout(() => ctl.abort(), ms);
    try {
      const r = await fetch(`${base}/api/health`, { signal: ctl.signal, cache: 'no-store' });
      if (!r.ok) return null;
      const j = await r.json();
      return j && j.componentes ? j : null;
    } catch { return null; } finally { clearTimeout(t); }
  }

  M.listo = (async () => {
    for (const b of candidatos) {
      const s = await sondear(b);
      if (s) { M.base = b; M.salud = s; break; }
    }
    if (!M.enOrigen) M.banner();
    return M.base;
  })();

  // Reescribe enlaces absolutos a la raíz (/docs, /download/…, /api/…) hacia la API localizada.
  M.reescribirEnlaces = (raiz = document) => {
    if (!M.base || M.enOrigen) return;
    raiz.querySelectorAll('a[href^="/"]').forEach((a) => { const h = a.getAttribute('href'); if (!h.startsWith('//')) a.setAttribute('href', M.base + h); });
  };

  // Aviso fijo (estilos en línea: funciona aunque Tailwind no cargue) cuando la página no viene de la API.
  M.banner = () => {
    let el = document.getElementById('mlops-apibase-banner');
    if (!el) {
      el = document.createElement('div'); el.id = 'mlops-apibase-banner';
      el.setAttribute('role', 'status');
      el.style.cssText = 'position:sticky;top:0;z-index:60;font:13px/1.45 system-ui,Segoe UI,Roboto,sans-serif;padding:9px 16px;border-bottom:1px solid;display:flex;flex-wrap:wrap;gap:6px 14px;align-items:center;';
      const montar = () => document.body.prepend(el);
      if (document.body) montar(); else document.addEventListener('DOMContentLoaded', montar);
    }
    const pag = M.pagina.replace('.html', '').replace('index', '');
    const campo = `<form id="mlops-apibase-form" style="display:inline-flex;gap:6px;align-items:center;margin-left:auto">
        <input name="api" placeholder="https://servidor:8000" value="${M.base || generadas[0] || ''}" style="font:12px monospace;padding:3px 6px;border:1px solid #94a3b8;border-radius:6px;min-width:260px">
        <button type="submit" style="font:12px system-ui;padding:3px 9px;border-radius:6px;border:1px solid #64748b;background:#fff;cursor:pointer">Conectar</button>
      </form>`;
    if (M.base) {
      el.style.background = '#eff6ff'; el.style.borderColor = '#bfdbfe'; el.style.color = '#1e3a8a';
      el.innerHTML = `<b>ℹ️ Conectado al servidor</b> <code style="font-family:monospace">${M.base}</code> · `
        + `<a href="${M.base}/${pag}" target="_blank" rel="noopener" style="color:#1d4ed8;font-weight:600;text-decoration:underline">Abrir esta página desde el servidor ↗</a>${campo}`;
    } else {
      el.style.background = '#fff7ed'; el.style.borderColor = '#fed7aa'; el.style.color = '#7c2d12';
      el.innerHTML = `<b>⚠️ Sin conexión con el servidor.</b> Se muestran los últimos datos guardados; las funciones en vivo se activarán al conectar. `
        + `Si conoces la dirección del servidor, escríbela aquí:${campo}`;
    }
    const form = el.querySelector('#mlops-apibase-form');
    form.onsubmit = (ev) => {
      ev.preventDefault();
      const u = new URL(location.href); u.searchParams.set('api', norm(form.api.value)); location.href = u.toString();
    };
  };

  return M;
})();
