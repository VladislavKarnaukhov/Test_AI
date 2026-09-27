(function () {
  'use strict';

  const METRIKA_ID = 112820979;

  // ---------- Согласие на cookie ----------
  const CONSENT_COOKIE = 'vs_consent';
  const CONSENT_VERSION_COOKIE = 'vs_consent_v';
  const POLICY_VERSION = document.documentElement.dataset.policyVersion;

  function readCookie(name) {
    const m = document.cookie.match(new RegExp('(?:^|;\\s*)' + name + '=([^;]*)'));
    return m ? decodeURIComponent(m[1]) : null;
  }
  // Выбор, сделанный для прошлой версии политики, не считается — баннер спросит заново
  function getConsent() {
    return readCookie(CONSENT_VERSION_COOKIE) === POLICY_VERSION ? readCookie(CONSENT_COOKIE) : null;
  }
  function analyticsAllowed() { return getConsent() === 'all'; }

  // Запись в собственный лог /api/event — только при согласии на аналитику
  function logEvent(name, params) {
    if (!analyticsAllowed()) return;
    const body = JSON.stringify({
      name: name,
      params: params || {},
      path: location.pathname + location.search + location.hash,
      referrer: document.referrer
    });
    try {
      if (navigator.sendBeacon && navigator.sendBeacon('/api/event', new Blob([body], { type: 'application/json' }))) return;
    } catch (e) { /* fallback ниже */ }
    fetch('/api/event', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: body, keepalive: true }).catch(function () {});
  }

  // Одно событие — в Яндекс.Метрику (reachGoal) и в собственный лог
  function track(name, params) {
    if (!analyticsAllowed()) return;
    params = params || {};
    if (typeof window.ym === 'function') window.ym(METRIKA_ID, 'reachGoal', name, params);
    logEvent(name, params);
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

  // ---------- Уведомления ----------
  const flashes = document.querySelector('.flashes');
  if (flashes) setTimeout(function () { flashes.classList.add('gone'); }, 6000);

  // ---------- Контекст посетителя: источник, язык, часовой пояс, экран ----------
  function sendVisitorContext() {
    if (!analyticsAllowed()) return;
    const params = new URLSearchParams(location.search);
    const ctx = {
      landing_path: location.pathname,
      referrer: document.referrer,
      language: navigator.language || '',
      screen: screen.width + 'x' + screen.height
    };
    try { ctx.timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || ''; } catch (e) { /* старый браузер */ }
    ['utm_source', 'utm_medium', 'utm_campaign', 'utm_content', 'utm_term'].forEach(function (k) {
      if (params.get(k)) ctx[k] = params.get(k);
    });
    postJSON('/api/visitor', ctx).catch(function () {});
  }

  // ---------- Баннер cookie ----------
  const banner = document.querySelector('.cookie-banner');

  function deleteMetrikaCookies() {
    const host = location.hostname.split('.');
    document.cookie.split(';').forEach(function (c) {
      const name = c.split('=')[0].trim();
      if (name.indexOf('_ym') !== 0) return;
      for (let i = 0; i < host.length - 1; i++) {
        const domain = host.slice(i).join('.');
        document.cookie = name + '=; Max-Age=0; path=/; domain=' + domain;
        document.cookie = name + '=; Max-Age=0; path=/; domain=.' + domain;
      }
      document.cookie = name + '=; Max-Age=0; path=/';
    });
  }

  function saveConsent(choice) {
    const previous = getConsent();
    return postJSON('/api/consent', { choice: choice }).catch(function () {
      // сервер недоступен — запоминаем выбор хотя бы в браузере
      document.cookie = CONSENT_COOKIE + '=' + choice + '; Max-Age=31536000; path=/; SameSite=Lax';
      document.cookie = CONSENT_VERSION_COOKIE + '=' + POLICY_VERSION + '; Max-Age=31536000; path=/; SameSite=Lax';
    }).then(function () {
      banner.hidden = true;
      if (choice === 'all') {
        if (typeof window.vsLoadMetrika === 'function') window.vsLoadMetrika();
        logEvent('cookie_consent', { choice: choice });
        // сервер не записал page_view при загрузке — согласия ещё не было
        if (previous !== 'all') logEvent('page_view');
        sendVisitorContext();
      } else {
        // могли остаться от согласия с прошлой версией политики
        deleteMetrikaCookies();
        // Метрику, уже загруженную на страницу, не выгрузить — перезагружаем
        if (previous === 'all') location.reload();
      }
    });
  }

  sendVisitorContext();

  if (banner) {
    if (!getConsent()) banner.hidden = false;
    banner.querySelectorAll('[data-consent]').forEach(function (b) {
      b.addEventListener('click', function () { saveConsent(b.dataset.consent); });
    });
    document.querySelectorAll('[data-cookie-settings]').forEach(function (b) {
      b.addEventListener('click', function () { banner.hidden = false; });
    });
  }

  // ---------- Диалог выбора тарифа ----------
  const dialog = document.querySelector('dialog');
  if (dialog) {
    const planLabel = dialog.querySelector('h2 span');
    const leadForm = dialog.querySelector('form');
    const leadMsg = dialog.querySelector('.msg');
    const leadBtn = leadForm.querySelector('button[type=submit]');
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
      const consent = leadForm.querySelector('input[name=consent]').checked;
      const plan = planLabel.textContent;
      track('submit_leadform', { plan: plan });
      leadBtn.disabled = true;
      leadMsg.textContent = 'Отправляем…';
      postJSON('/api/lead', { email: email, plan: plan, consent: consent }).then(function (r) {
        if (r.ok) {
          leadMsg.textContent = 'Спасибо! Мы подготовим ваш следующий шаг.';
        } else {
          const f = (r.data && r.data.fields) || {};
          leadMsg.textContent = f.email ? 'Проверьте e-mail: ' + f.email + '.'
            : f.consent ? 'Отметьте согласие на обработку персональных данных.'
            : 'Не получилось отправить. Попробуйте ещё раз.';
          leadBtn.disabled = false;
        }
      }).catch(function () {
        leadMsg.textContent = 'Нет связи с сервером. Попробуйте ещё раз.';
        leadBtn.disabled = false;
      });
    });
  }

  // ---------- Анкета ----------
  const quizForm = document.querySelector('.quiz-form');
  if (quizForm) {
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
      const cta = resultCard.querySelector('[data-account-cta]');
      if (r.saved_to_account) {
        cta.textContent = 'Сохранено в кабинете →';
        cta.href = '/account';
      } else {
        // гостевые расчёты не привязываются: за одним компьютером могут быть разные люди
        cta.textContent = 'Войти и сохранять результаты';
        cta.href = '/login?next=' + encodeURIComponent('/#try');
      }
      cta.dataset.metric = r.saved_to_account ? 'quiz_open_account' : 'quiz_save_to_account';
      cta.hidden = false;
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
  }
})();
