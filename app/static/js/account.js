// Личный кабинет: интерактивный график динамики и связь с историей оценок
(function () {
  'use strict';

  const track = typeof window.track === 'function' ? window.track : function () {};

  // ---------- История: 4 последние оценки, остальные — под «Показать ещё» ----------
  const extras = Array.prototype.slice.call(document.querySelectorAll('.timeline li.extra'));
  const moreBtn = document.querySelector('[data-history-more]');
  const collapseAllBtn = document.querySelector('[data-collapse-all]');
  const entries = Array.prototype.slice.call(document.querySelectorAll('.entry'));
  let historyExpanded = false;

  function setHistoryExpanded(on) {
    historyExpanded = on;
    extras.forEach(function (li) {
      li.hidden = !on;
      if (!on) li.querySelector('details').open = false;
    });
    if (moreBtn) {
      moreBtn.textContent = on ? 'Скрыть старые оценки' : moreBtn.dataset.moreLabel;
      moreBtn.setAttribute('aria-expanded', String(on));
    }
    updateCollapseAll();
  }

  function updateCollapseAll() {
    if (collapseAllBtn) collapseAllBtn.hidden = !entries.some(function (e) { return e.open; });
  }

  // показать скрытую оценку, если к ней перешли с графика
  function revealEntry(entry) {
    if (!historyExpanded && entry.closest('li.extra')) setHistoryExpanded(true);
  }

  if (moreBtn && extras.length) {
    moreBtn.parentElement.hidden = false;
    setHistoryExpanded(false);
    moreBtn.addEventListener('click', function () {
      setHistoryExpanded(!historyExpanded);
      if (!historyExpanded) moreBtn.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
      track('account_history_more', { expanded: historyExpanded });
    });
  }

  if (collapseAllBtn) {
    collapseAllBtn.addEventListener('click', function () {
      entries.forEach(function (e) { e.open = false; });
      updateCollapseAll();
      document.getElementById('history').scrollIntoView({ block: 'start', behavior: 'smooth' });
      track('account_history_collapse_all');
    });
  }

  document.querySelectorAll('[data-entry-close]').forEach(function (btn) {
    btn.hidden = false;
    btn.addEventListener('click', function () {
      const entry = btn.closest('.entry');
      entry.open = false;
      // если заголовок оценки ушёл вверх за экран — вернуть его в поле зрения
      if (entry.getBoundingClientRect().top < 0) entry.scrollIntoView({ block: 'start', behavior: 'smooth' });
    });
  });

  entries.forEach(function (e) { e.addEventListener('toggle', updateCollapseAll); });
  updateCollapseAll();

  const panel = document.querySelector('[data-dynamics]');
  const source = document.getElementById('history-data');
  if (!panel || !source) return;

  const payload = JSON.parse(source.textContent);
  const data = payload.points;
  const svg = panel.querySelector('.chart');
  const tip = panel.querySelector('.chart-tip');
  const empty = panel.querySelector('.chart-empty');

  // график рисуется в реальных пикселях контейнера: на телефоне подписи остаются читаемыми
  let W = 640, H = 260, IW, IH;
  const L = 34, R = 16, T = 16, B = 34;
  function layout() {
    W = Math.max(280, Math.round(svg.getBoundingClientRect().width) || 640);
    H = W < 520 ? 230 : 260;
    IW = W - L - R;
    IH = H - T - B;
    svg.setAttribute('viewBox', '0 0 ' + W + ' ' + H);
  }
  layout();
  // линии графика задаёт сервер: итог + сферы ядра действующей методики; цвета берутся из токенов темы
  const NAMES = {}, ORDER = payload.series.map(function (s) { NAMES[s[0]] = s[1]; return s[0]; });
  const COLORS = {};
  function readColors() {
    const root = getComputedStyle(document.documentElement);
    ORDER.forEach(function (k) { COLORS[k] = root.getPropertyValue('--s-' + k).trim(); });
  }
  readColors();

  const state = { period: 'all', series: { total: true }, points: [], selected: null, hover: null };

  function visiblePoints() {
    if (state.period === 'all') return data;
    const from = Date.now() - Number(state.period) * 864e5;
    return data.filter(function (d) { return Date.parse(d.t) >= from; });
  }
  function x(i, n) { return L + (n === 1 ? IW / 2 : i * IW / (n - 1)); }
  function y(v) { return T + (100 - v) * IH / 100; }
  function value(d, key) { return key === 'total' ? d.total : d[key]; }
  function r1(n) { return Math.round(n * 10) / 10; }
  // плавная монотонная кривая (Fritsch–Carlson): линия не «перелетает» значения между замерами
  function curve(xs, ys) {
    const n = xs.length;
    if (n < 2) return '';
    const dx = [], m = [], t = [];
    for (let i = 0; i < n - 1; i++) { dx[i] = xs[i + 1] - xs[i]; m[i] = (ys[i + 1] - ys[i]) / dx[i]; }
    t[0] = m[0]; t[n - 1] = m[n - 2];
    for (let i = 1; i < n - 1; i++) t[i] = m[i - 1] * m[i] <= 0 ? 0 : (m[i - 1] + m[i]) / 2;
    for (let i = 0; i < n - 1; i++) {
      if (m[i] === 0) { t[i] = t[i + 1] = 0; continue; }
      const p = t[i] / m[i], q = t[i + 1] / m[i], s = p * p + q * q;
      if (s > 9) { const k = 3 / Math.sqrt(s); t[i] = k * p * m[i]; t[i + 1] = k * q * m[i]; }
    }
    let d = 'M' + r1(xs[0]) + ',' + r1(ys[0]);
    for (let i = 0; i < n - 1; i++) {
      const h = dx[i] / 3;
      d += ' C' + r1(xs[i] + h) + ',' + r1(ys[i] + t[i] * h) + ' ' + r1(xs[i + 1] - h) + ',' + r1(ys[i + 1] - t[i + 1] * h) + ' ' + r1(xs[i + 1]) + ',' + r1(ys[i + 1]);
    }
    return d;
  }

  // ---------- Отрисовка ----------
  function draw() {
    const pts = state.points = visiblePoints();
    const n = pts.length;
    updateStats(pts);
    empty.hidden = n > 0;
    if (!n) { svg.innerHTML = ''; hideTip(); return; }

    let out = '';
    out += '<defs><linearGradient id="area-grad" x1="0" y1="0" x2="0" y2="1"><stop class="g0" offset="0"/><stop class="g1" offset="1"/></linearGradient></defs>';
    [0, 50, 100].forEach(function (v) {
      out += '<line class="grid" x1="' + L + '" x2="' + (W - R) + '" y1="' + y(v) + '" y2="' + y(v) + '"/>' +
        '<text class="axis" x="' + (L - 8) + '" y="' + (y(v) + 4) + '" text-anchor="end">' + v + '</text>';
    });
    const step = Math.max(1, Math.ceil(n / 7));
    pts.forEach(function (d, i) {
      if (i % step === 0 || i === n - 1) {
        out += '<text class="axis" x="' + x(i, n) + '" y="' + (H - 10) + '" text-anchor="middle">' + d.label + '</text>';
      }
    });
    if (state.series.total && n > 1) {
      const ax = pts.map(function (d, i) { return x(i, n); }), ay = pts.map(function (d) { return y(d.total); });
      out += '<path class="area" d="' + curve(ax, ay) + ' L' + r1(x(n - 1, n)) + ',' + r1(y(0)) + ' L' + r1(x(0, n)) + ',' + r1(y(0)) + ' Z"/>';
    }
    out += '<line class="guide" y1="' + T + '" y2="' + (T + IH) + '" x1="-10" x2="-10"/>';
    ORDER.slice().reverse().forEach(function (key) {
      if (!state.series[key]) return;
      const cx = pts.map(function (d, i) { return x(i, n); }), cy = pts.map(function (d) { return y(value(d, key)); });
      if (n > 1) out += '<path class="line line-' + key + '" pathLength="1" style="stroke:' + COLORS[key] + '" d="' + curve(cx, cy) + '"/>';
      pts.forEach(function (d, i) {
        const sel = d.id === state.selected ? ' selected' : '';
        out += '<circle class="dot dot-' + key + sel + '" data-id="' + d.id + '" cx="' + x(i, n) + '" cy="' + y(value(d, key)) +
          '" r="' + (key === 'total' ? (i === n - 1 ? 6 : 3.5) : 3) + '" style="fill:' + COLORS[key] + '"/>';
      });
    });
    svg.innerHTML = out;
    if (!state.drawn) {
      // линии «прорисовываются» один раз при первом показе: направление времени слева направо
      state.drawn = true;
      svg.classList.add('first-draw');
      setTimeout(function () { svg.classList.remove('first-draw'); }, 900);
    }
    if (state.hover !== null) showHover(state.hover);
  }

  function updateStats(pts) {
    const set = function (name, text, cls) {
      const el = panel.querySelector('[data-stat="' + name + '"]');
      el.textContent = text;
      el.className = cls || '';
    };
    if (!pts.length) { ['count', 'best', 'avg', 'change'].forEach(function (k) { set(k, k === 'count' ? '0' : '—'); }); return; }
    const totals = pts.map(function (d) { return d.total; });
    const change = totals.length > 1 ? totals[totals.length - 1] - totals[0] : null;
    set('count', String(totals.length));
    set('best', String(Math.max.apply(null, totals)));
    set('avg', String(Math.round(totals.reduce(function (a, b) { return a + b; }, 0) / totals.length)));
    set('change', change ? (change > 0 ? '+' : '') + change : '—', change > 0 ? 'up' : change < 0 ? 'down' : '');
  }

  // ---------- Подсказка при наведении ----------
  function nearestIndex(clientX) {
    const rect = svg.getBoundingClientRect();
    const sx = (clientX - rect.left) * W / rect.width;
    const n = state.points.length;
    if (n === 1) return 0;
    return Math.max(0, Math.min(n - 1, Math.round((sx - L) / IW * (n - 1))));
  }

  function showHover(i) {
    const pts = state.points, n = pts.length, d = pts[i];
    if (!d) return hideTip();
    state.hover = i;
    const guide = svg.querySelector('.guide');
    guide.setAttribute('x1', x(i, n));
    guide.setAttribute('x2', x(i, n));
    svg.querySelectorAll('.dot').forEach(function (c) { c.classList.toggle('hover', Number(c.dataset.id) === d.id); });

    let html = '<p class="tip-date">' + d.date + '</p><p class="tip-total">' + d.total + '<span>/100</span></p><ul>';
    ORDER.slice(1).forEach(function (k) {
      html += '<li><i style="background:' + COLORS[k] + '"></i>' + NAMES[k] + '<b>' + d[k] + '</b></li>';
    });
    tip.innerHTML = html + '</ul>';
    tip.hidden = false;
    const rect = svg.getBoundingClientRect();
    const px = x(i, n) * rect.width / W;
    const flip = px > rect.width / 2;
    tip.style.left = (flip ? px - tip.offsetWidth - 14 : px + 14) + 'px';
    tip.style.top = Math.max(0, y(d.total) * rect.height / H - tip.offsetHeight / 2) + 'px';
  }

  function hideTip() {
    state.hover = null;
    tip.hidden = true;
    const guide = svg.querySelector('.guide');
    if (guide) { guide.setAttribute('x1', -10); guide.setAttribute('x2', -10); }
    svg.querySelectorAll('.dot.hover').forEach(function (c) { c.classList.remove('hover'); });
  }

  svg.addEventListener('pointermove', function (e) { if (state.points.length) showHover(nearestIndex(e.clientX)); });
  svg.addEventListener('pointerleave', function (e) { if (e.pointerType === 'mouse') hideTip(); });
  svg.addEventListener('click', function (e) {
    if (!state.points.length) return;
    const d = state.points[nearestIndex(e.clientX)];
    openEntry(d.id, true);
    track('account_chart_point', { id: d.id });
  });

  // ---------- Связь с историей ----------
  function openEntry(id, scroll) {
    const entry = document.getElementById('entry-' + id);
    if (!entry) return;
    revealEntry(entry);
    entry.open = true;
    select(id);
    if (scroll) {
      entry.scrollIntoView({ behavior: 'smooth', block: 'center' });
      entry.classList.remove('flash-entry');
      void entry.offsetWidth; // перезапуск анимации
      entry.classList.add('flash-entry');
    }
  }

  function select(id) {
    state.selected = id;
    document.querySelectorAll('.entry').forEach(function (el) { el.classList.toggle('selected', Number(el.dataset.id) === id); });
    svg.querySelectorAll('.dot').forEach(function (c) { c.classList.toggle('selected', Number(c.dataset.id) === id); });
  }

  document.querySelectorAll('.entry').forEach(function (entry) {
    const id = Number(entry.dataset.id);
    entry.addEventListener('toggle', function () {
      if (entry.open) { select(id); track('account_history_open', { id: id }); }
    });
    entry.querySelector('summary').addEventListener('mouseenter', function () {
      const i = state.points.findIndex(function (d) { return d.id === id; });
      if (i >= 0) showHover(i);
    });
    entry.querySelector('summary').addEventListener('mouseleave', hideTip);
  });

  // ---------- Период и линии ----------
  panel.querySelectorAll('[data-period]').forEach(function (b) {
    b.addEventListener('click', function () {
      state.period = b.dataset.period;
      panel.querySelectorAll('[data-period]').forEach(function (o) { o.setAttribute('aria-pressed', String(o === b)); });
      hideTip();
      draw();
      track('account_period', { period: state.period });
    });
  });

  panel.querySelectorAll('[data-series]').forEach(function (b) {
    b.addEventListener('click', function () {
      const key = b.dataset.series;
      const on = b.getAttribute('aria-pressed') !== 'true';
      const active = Object.keys(state.series).filter(function (k) { return state.series[k]; });
      if (!on && active.length === 1) return; // хотя бы одна линия остаётся
      state.series[key] = on;
      b.setAttribute('aria-pressed', String(on));
      draw();
      track('account_series', { series: key, on: on });
    });
  });

  if (window.ResizeObserver) {
    let lastW = W;
    new ResizeObserver(function () {
      const w = Math.round(svg.getBoundingClientRect().width);
      if (!w || w === lastW) return;
      lastW = w;
      layout();
      draw();
    }).observe(svg);
  }
  const scheme = window.matchMedia('(prefers-color-scheme: dark)');
  if (scheme.addEventListener) scheme.addEventListener('change', function () { readColors(); draw(); });

  const firstOpen = document.querySelector('.entry[open]');
  if (firstOpen) state.selected = Number(firstOpen.dataset.id);
  draw();
  if (state.selected !== null) select(state.selected);
})();
