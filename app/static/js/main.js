(function () {
  'use strict';

  const METRIKA_ID = 112820979;

  // Одно событие — в Яндекс.Метрику (reachGoal) и в собственный лог /api/event
  function track(name, params) {
    params = params || {};
    if (typeof window.ym === 'function') window.ym(METRIKA_ID, 'reachGoal', name, params);
    const body = JSON.stringify({
      name: name,
      params: params,
      path: location.pathname + location.search + location.hash,
      referrer: document.referrer
    });
    try {
      if (navigator.sendBeacon && navigator.sendBeacon('/api/event', new Blob([body], { type: 'application/json' }))) return;
    } catch (e) { /* fallback ниже */ }
    fetch('/api/event', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: body, keepalive: true }).catch(function () {});
  }
  window.track = track;

  function postJSON(url, data) {
    return fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin',
      body: JSON.stringify(data)
    }).then(function (res) {
      return res.json().catch(function () { return {}; }).then(function (json) {
        return { ok: res.ok, status: res.status, data: json };
      });
    });
  }

  // ---------- Клики по data-metric, ссылкам и якорям ----------
  document.addEventListener('click', function (e) {
    const metricEl = e.target.closest('[data-metric]');
    if (metricEl) {
      const params = {};
      if (metricEl.dataset.plan) params.plan = metricEl.dataset.plan;
      track(metricEl.dataset.metric, params);
    }
    const link = e.target.closest('a[href]');
    if (link) {
      const href = link.getAttribute('href');
      const text = (link.textContent || '').trim().slice(0, 100);
      if (href.charAt(0) === '#') track('anchor_click', { href: href, text: text });
      else track('link_click', { href: link.href, text: text, external: link.origin !== location.origin });
    }
  }, true);

  window.addEventListener('hashchange', function (e) {
    track('hashchange', { hash: location.hash, from: new URL(e.oldURL).hash });
  });

  // ---------- Диалог выбора тарифа ----------
  const dialog = document.querySelector('dialog');
  const planLabel = dialog.querySelector('h2 span');
  const leadForm = dialog.querySelector('form');
  const leadMsg = dialog.querySelector('.msg');
  const leadBtn = leadForm.querySelector('button');
  let closeReason = null;

  document.querySelectorAll('.open').forEach(function (b) {
    b.addEventListener('click', function () {
      planLabel.textContent = b.dataset.plan;
      leadMsg.textContent = '';
      leadForm.reset();
      leadBtn.disabled = false;
      dialog.showModal();
      track('leadform_open', { plan: b.dataset.plan, source: b.dataset.metric });
    });
  });

  dialog.querySelector('.close').addEventListener('click', function () {
    closeReason = 'close_leadform';
    dialog.close();
  });
  dialog.addEventListener('click', function (e) {
    if (e.target === dialog) { closeReason = 'close_leadform_overlay'; dialog.close(); }
  });
  dialog.addEventListener('cancel', function () { closeReason = 'close_leadform_escape'; });
  dialog.addEventListener('close', function () {
    track(closeReason || 'close_leadform', { plan: planLabel.textContent });
    closeReason = null;
  });

  leadForm.addEventListener('submit', function (e) {
    e.preventDefault();
    const email = leadForm.querySelector('input[type=email]').value.trim();
    const plan = planLabel.textContent;
    track('submit_leadform', { plan: plan });
    leadBtn.disabled = true;
    leadMsg.textContent = 'Отправляем…';
    postJSON('/api/lead', { email: email, plan: plan }).then(function (r) {
      if (r.ok) {
        leadMsg.textContent = 'Спасибо! Мы подготовим ваш следующий шаг.';
      } else {
        const f = (r.data && r.data.fields) || {};
        leadMsg.textContent = f.email ? 'Проверьте e-mail: ' + f.email + '.' : 'Не получилось отправить. Попробуйте ещё раз.';
        leadBtn.disabled = false;
      }
    }).catch(function () {
      leadMsg.textContent = 'Нет связи с сервером. Попробуйте ещё раз.';
      leadBtn.disabled = false;
    });
  });

  // ---------- Анкета ----------
  const quizForm = document.querySelector('.quiz-form');
  const quizError = quizForm.querySelector('.form-error');
  const quizBtn = quizForm.querySelector('button[type=submit]');
  const resultCard = document.querySelector('.score-card');
  const FIELD_LABELS = { sleep: 'сон', activity: 'активность', nutrition: 'питание', stress: 'стресс' };

  quizForm.addEventListener('change', function (e) {
    if (e.target.name) {
      e.target.classList.remove('invalid');
      track('quiz_answer', { question: e.target.name, value: e.target.value });
    }
  });

  function showErrors(fields) {
    quizForm.querySelectorAll('select').forEach(function (s) {
      s.classList.toggle('invalid', Object.prototype.hasOwnProperty.call(fields, s.name));
    });
    const names = Object.keys(fields).map(function (k) { return FIELD_LABELS[k] || k; });
    quizError.textContent = names.length ? 'Ответьте на все вопросы: ' + names.join(', ') + '.' : 'Не удалось рассчитать балл.';
  }

  function showResult(r) {
    resultCard.querySelector('[data-total]').textContent = r.total;
    resultCard.querySelector('[data-summary]').textContent = r.summary;
    resultCard.querySelector('[data-bar]').style.width = r.total + '%';
    resultCard.querySelector('[data-tip]').textContent = r.tip;
    Object.keys(r.breakdown).forEach(function (k) {
      const el = resultCard.querySelector('[data-sphere="' + k + '"]');
      if (el) {
        el.textContent = r.breakdown[k];
        el.parentElement.classList.toggle('weakest', k === r.weakest);
      }
    });
    quizForm.hidden = true;
    resultCard.hidden = false;
  }

  quizForm.addEventListener('submit', function (e) {
    e.preventDefault();
    const answers = {};
    new FormData(quizForm).forEach(function (v, k) { answers[k] = v; });
    const missing = {};
    ['sleep', 'activity', 'nutrition', 'stress'].forEach(function (k) { if (!answers[k]) missing[k] = 'обязательное поле'; });
    if (Object.keys(missing).length) { showErrors(missing); return; }

    quizError.textContent = '';
    quizBtn.disabled = true;
    postJSON('/api/score', answers).then(function (r) {
      if (r.ok) showResult(r.data);
      else showErrors((r.data && r.data.fields) || {});
    }).catch(function () {
      quizError.textContent = 'Нет связи с сервером. Попробуйте ещё раз.';
    }).finally(function () { quizBtn.disabled = false; });
  });

  resultCard.querySelector('.again').addEventListener('click', function () {
    resultCard.hidden = true;
    quizForm.hidden = false;
  });
})();
