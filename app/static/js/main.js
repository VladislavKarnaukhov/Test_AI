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

  // ---------- «Удалить аккаунт» раскрывается, если на него ведёт ссылка из футера ----------
  function openDeleteForm() {
    const form = location.hash === '#delete' && document.getElementById('delete-form');
    if (form) form.open = true;
  }
  openDeleteForm();
  window.addEventListener('hashchange', openDeleteForm);

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

  // ---------- Шкалы: положение отметки и заливки задаёт CSS-переменная --v (0–100) ----------
  function setRange(node, v) { if (node) node.style.setProperty('--v', v); }

  // ---------- Лист последнего балла на главной (для вошедших) ----------
  function updateUserCard(r) {
    const card = document.querySelector('[data-user-card]');
    if (!card) return;
    card.querySelector('[data-uc-total]').firstChild.nodeValue = r.total;
    card.querySelector('[data-uc-total]').style.setProperty('--v', r.total);
    card.querySelector('[data-uc-summary]').textContent = r.summary;
    card.querySelector('[data-uc-date]').textContent = 'только что';
    setRange(card.querySelector('[data-uc-range] .range'), r.total);
    card.querySelectorAll('[data-uc-sphere]').forEach(function (row) {
      const k = row.dataset.ucSphere;
      row.querySelector('.row-val').textContent = r.breakdown[k];
      setRange(row.querySelector('.range'), r.breakdown[k]);
      row.classList.toggle('weakest', k === r.weakest);
    });
    const title = card.querySelector('[data-uc-tip-title]');
    if (r.focus && title) {
      title.textContent = r.focus.title;
      card.querySelector('[data-uc-tip-text]').textContent = r.focus.text;
    }
    const flag = card.querySelector('[data-uc-flag]');
    const serious = (r.flags || []).some(function (f) { return f.level !== 'info'; });
    if (flag) {
      flag.textContent = serious ? 'Есть рекомендация обратиться к специалисту' : '';
      flag.hidden = !serious;
    }
  }

  // ---------- Анкета (методика v2.0): уровни, условия показа, числовые поля ----------
  const quizForm = document.querySelector('.quiz-form');
  if (quizForm) {
    const quizError = quizForm.querySelector('.form-error');
    const steps = Array.prototype.slice.call(quizForm.querySelectorAll('.quiz-step'));
    const prevBtn = quizForm.querySelector('[data-prev]');
    const nextBtn = quizForm.querySelector('[data-next]');
    const submitBtn = quizForm.querySelector('button[type=submit]');
    const stepLabel = quizForm.querySelector('[data-step-label]');
    const stepBar = quizForm.querySelector('[data-step-bar]');
    const rail = document.querySelector('[data-rail]');
    const consent = quizForm.querySelector('input[name=health_consent]');
    const resultCard = document.querySelector('.score-card');
    const TIER_RANK = { short: 0, medium: 1, extended: 2 };
    let current = 0;

    function value(name) {
      const field = quizForm.querySelector('[name="' + name + '"]');
      if (field && field.type === 'number') return field.value === '' ? null : field.value;
      const checked = quizForm.querySelector('input[name="' + name + '"]:checked');
      return checked ? checked.value : null;
    }
    function tier() { return value('tier') || 'short'; }

    // AUDIT-C положителен: 4+ у мужчин, 3+ у женщин (Bush 1998, Bradley 2007)
    function auditPositive() {
      if (!value('a1') || value('a1') === '0') return false;
      const sum = ['a1', 'a2', 'a3'].reduce(function (s, k) { return s + Number(value(k) || 0); }, 0);
      return sum >= (value('sex') === 'male' ? 4 : 3);
    }

    function conditionMet(cond) {
      if (!cond) return true;
      if (cond.audit_positive) return auditPositive();
      const v = value(cond.q);
      if (v === null) return false;
      return cond.in ? cond.in.indexOf(v) >= 0 : cond.not_in.indexOf(v) < 0;
    }

    // вопрос виден, если входит в выбранный уровень и выполнено условие показа.
    // reveal: после ответа новые вопросы текущего шага появляются с коротким сдвигом, чтобы была видна связь
    function updateVisibility(reveal) {
      const rank = TIER_RANK[tier()];
      quizForm.querySelectorAll('.q[data-q]').forEach(function (q) {
        if (q.dataset.q === 'tier') return;
        const cond = q.dataset.cond ? JSON.parse(q.dataset.cond) : null;
        const hide = TIER_RANK[q.dataset.tier] > rank || !conditionMet(cond);
        if (reveal && q.hidden && !hide && !q.closest('.quiz-step').hidden) {
          q.classList.add('q-enter');
          q.addEventListener('animationend', function () { q.classList.remove('q-enter'); }, { once: true });
        }
        q.hidden = hide;
      });
    }

    function stepVisible(s) {
      return Array.prototype.some.call(s.querySelectorAll('.q[data-q]'), function (q) { return !q.hidden; });
    }
    function visibleSteps() { return steps.filter(stepVisible); }

    function renderRail(list) {
      if (!rail) return;
      rail.textContent = '';
      list.forEach(function (stepEl, n) {
        const li = document.createElement('li');
        li.textContent = stepEl.dataset.title;
        if (n < current) li.className = 'is-done';
        if (n === current) { li.className = 'is-current'; li.setAttribute('aria-current', 'step'); }
        rail.appendChild(li);
      });
      rail.hidden = false;
    }

    // один вопрос на экране: показ — только представление, ответы и расчёт не затрагиваются
    let curQ = null;
    function stepQs(step) { return Array.prototype.filter.call(step.querySelectorAll('.q[data-q]'), function (q) { return !q.hidden; }); }
    function applyFocus() {
      const list = visibleSteps();
      const step = list[current];
      const qs = stepQs(step);
      if (!curQ || qs.indexOf(curQ) < 0) curQ = qs[0];
      const qi = qs.indexOf(curQ);
      step.querySelectorAll('.q[data-q]').forEach(function (q) { q.classList.toggle('q-off', q !== curQ); });
      const lastInStep = qi === qs.length - 1;
      step.querySelectorAll('.consent, .terms-note').forEach(function (n) { n.classList.toggle('q-off', !lastInStep); });
      const lastStep = current === list.length - 1;
      prevBtn.hidden = current === 0 && qi === 0;
      nextBtn.hidden = lastStep && lastInStep;
      submitBtn.hidden = !(lastStep && lastInStep);
      let before = 0, total = 0;
      list.forEach(function (st, n) { const k = stepQs(st).length; if (n < current) before += k; total += k; });
      const pos = before + qi + 1;
      stepLabel.textContent = 'Вопрос ' + pos + ' из ' + total + ' · ' + step.dataset.title;
      stepBar.style.setProperty('--f', (pos / total).toFixed(3));
    }
    function focusQuestion() {
      const t = curQ && curQ.querySelector('.q-text');
      if (t) { t.tabIndex = -1; t.focus({ preventScroll: true }); }
    }

    // direction: 'forward' | 'back' | undefined (без анимации: первая отрисовка, смена уровня)
    function showStep(i, direction) {
      updateVisibility();
      const list = visibleSteps();
      current = Math.max(0, Math.min(i, list.length - 1));
      const active = list[current];
      steps.forEach(function (s) { s.hidden = s !== active; s.classList.remove('enter-forward', 'enter-back'); });
      if (direction) {
        active.classList.add(direction === 'back' ? 'enter-back' : 'enter-forward');
        active.addEventListener('animationend', function done(e) {
          if (e.target !== active) return;
          active.classList.remove('enter-forward', 'enter-back');
          active.removeEventListener('animationend', done);
        });
      }
      curQ = direction === 'back' ? stepQs(active).slice(-1)[0] : stepQs(active)[0];
      applyFocus();
      renderRail(list);
      quizError.textContent = '';
    }

    // после перехода фокус на заголовок нового шага: экранный диктор и клавиатура продолжают с него
    function focusStep() {
      const legend = visibleSteps()[current].querySelector('legend');
      if (legend) legend.focus({ preventScroll: true });
    }

    function scrollToQuiz() {
      if (quizForm.getBoundingClientRect().top < 0) quizForm.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }

    // все обязательные видимые вопросы шага отвечены, числа в допустимых границах
    function checkStep(onlyQ) {
      const step = visibleSteps()[current];
      let firstBad = null, message = 'Ответьте на все вопросы этого шага.';
      step.querySelectorAll('.q[data-q]').forEach(function (q) {
        if (q.hidden || (onlyQ && q !== onlyQ)) return;
        const v = value(q.dataset.q);
        let bad = v === null && !q.hasAttribute('data-optional');
        if (v !== null && q.dataset.kind === 'number') {
          const input = q.querySelector('input');
          const n = Number(v);
          if (isNaN(n) || n < Number(input.min) || n > Number(input.max)) {
            bad = true;
            message = 'Проверьте значения: ' + q.querySelector('.q-text').firstChild.nodeValue.trim() + ' — от ' + input.min + ' до ' + input.max + '.';
          }
        }
        q.classList.toggle('missing', bad);
        if (bad && !firstBad) firstBad = q;
      });
      if (firstBad) {
        quizError.textContent = message;
        firstBad.scrollIntoView({ behavior: 'smooth', block: 'center' });
        return false;
      }
      if (onlyQ) return true;
      if (step === steps[0] && value('age') === 'under18') {
        quizError.textContent = 'Анкета Adelina Health рассчитана на взрослых — от 18 лет.';
        return false;
      }
      if (step === steps[0] && !consent.checked) {
        consent.closest('.consent').classList.add('missing');
        quizError.textContent = 'Чтобы продолжить, дайте согласие на обработку данных о здоровье.';
        return false;
      }
      return true;
    }

    quizForm.addEventListener('change', function (e) {
      const t = e.target;
      if (t.type === 'radio' || t.type === 'number') {
        const q = t.closest('.q');
        if (q) q.classList.remove('missing');
        updateVisibility(true);
        if (t.type === 'radio') track('quiz_answer', { question: t.name, value: t.name === 'tier' ? t.value : 'set' });
      }
      if (t === consent) consent.closest('.consent').classList.toggle('missing', !consent.checked);
      quizError.textContent = '';
      if (t.name === 'tier') showStep(current); else if (t.type === 'radio' || t.type === 'number') applyFocus();
    });

    nextBtn.addEventListener('click', function () {
      const qs = stepQs(visibleSteps()[current]);
      const qi = qs.indexOf(curQ);
      if (qi < qs.length - 1) {
        if (!checkStep(curQ)) return;
        curQ = qs[qi + 1];
        applyFocus();
        quizError.textContent = '';
        focusQuestion();
        scrollToQuiz();
        return;
      }
      if (!checkStep()) return;
      track('quiz_step', { step: current + 2, tier: tier() });
      showStep(current + 1, 'forward');
      focusStep();
      scrollToQuiz();
    });
    prevBtn.addEventListener('click', function () {
      const qs = stepQs(visibleSteps()[current]);
      const qi = qs.indexOf(curQ);
      if (qi > 0) { curQ = qs[qi - 1]; applyFocus(); quizError.textContent = ''; focusQuestion(); scrollToQuiz(); return; }
      showStep(current - 1, 'back'); focusStep(); scrollToQuiz();
    });

    function el(tag, cls, text) {
      const node = document.createElement(tag);
      if (cls) node.className = cls;
      if (text) node.textContent = text;
      return node;
    }

    // красные флаги: над баллом отдельным блоком; уровень назван словом, а не только цветом
    const FLAG_LEVEL = { urgent: 'Срочно', warn: 'Важно', info: 'К сведению' };
    function renderFlags(flags) {
      const box = resultCard.querySelector('[data-flags]');
      box.textContent = '';
      flags.forEach(function (f) {
        const item = el('div', 'flag flag-' + f.level);
        item.appendChild(el('span', 'flag-level', FLAG_LEVEL[f.level] || ''));
        item.appendChild(el('b', '', f.title));
        item.appendChild(el('p', '', f.text));
        if (f.contacts) item.appendChild(el('p', 'flag-contacts', 'Если очень тяжело или есть угроза жизни — звоните 112.'));
        box.appendChild(item);
      });
      box.hidden = !flags.length;
    }

    // подробный индекс и «Тело и метаболизм» — под сферами ядра
    function renderExtra(r) {
      const box = resultCard.querySelector('[data-extra]');
      box.textContent = '';
      if (r.detailed) box.appendChild(el('p', '', 'Подробный индекс (7 сфер): ' + r.detailed.total + '/100'));
      if (r.body) box.appendChild(el('p', '', 'Тело и метаболизм: ' + r.body.score + '/100, по ' + r.body.known + ' из 4 показателей'));
      box.hidden = !box.childNodes.length;
    }

    const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
    // число растёт вместе с заполнением шкал; экранному диктору итог отдан сразу (data-total-sr)
    function countUp(node, to) {
      if (reduceMotion.matches || to === 0) { node.textContent = to; return; }
      const t0 = performance.now(), dur = 600;
      (function tick(now) {
        const p = Math.min(1, (now - t0) / dur);
        node.textContent = Math.round(to * (1 - Math.pow(1 - p, 3)));
        if (p < 1) requestAnimationFrame(tick);
      })(t0);
    }

    function showResult(r) {
      renderFlags(r.flags || []);
      renderExtra(r);
      const tierName = ({ short: 'короткий', medium: 'средний', extended: 'расширенный' })[r.tier];
      resultCard.querySelector('[data-tier-label]').textContent = tierName + ' уровень, методика v' + r.version;
      resultCard.querySelector('[data-total-sr]').textContent = r.total;
      resultCard.querySelector('[data-level]').textContent = r.level_name + '.';
      resultCard.querySelector('[data-summary]').textContent = r.summary.replace(r.level_name + '. ', '');
      setRange(resultCard.querySelector('[data-total-range] .range'), r.total);
      resultCard.querySelector('.score').style.setProperty('--v', r.total);
      const ft = r.focus.title;
      resultCard.querySelector('[data-focus-title]').textContent = ft.indexOf('Фокус недели') === 0 ? ft : 'Фокус недели: ' + ft;
      resultCard.querySelector('[data-tip]').textContent = r.focus.text;
      Object.keys(r.breakdown).forEach(function (k) {
        const row = resultCard.querySelector('[data-sphere-row="' + k + '"]');
        if (!row) return;
        row.querySelector('.row-val').textContent = r.breakdown[k];
        setRange(row.querySelector('.range'), r.breakdown[k]);
        row.classList.toggle('weakest', k === r.weakest);
      });
      const cta = resultCard.querySelector('[data-account-cta]');
      if (r.saved_to_account) {
        cta.textContent = 'Сохранено в кабинете';
        cta.href = '/account';
        updateUserCard(r);
      } else {
        // гостевые расчёты не привязываются: за одним компьютером могут быть разные люди
        cta.textContent = 'Войти и сохранять результаты';
        cta.href = '/login?next=' + encodeURIComponent('/#try');
      }
      cta.dataset.metric = r.saved_to_account ? 'quiz_open_account' : 'quiz_save_to_account';
      cta.hidden = false;
      quizForm.hidden = true;
      if (rail) rail.hidden = true;
      resultCard.hidden = false;
      resultCard.classList.remove('is-live');
      void resultCard.offsetWidth; // перезапуск анимации заполнения шкал
      resultCard.classList.add('is-live');
      countUp(resultCard.querySelector('[data-total]'), r.total);
      resultCard.focus({ preventScroll: true });
      resultCard.scrollIntoView({ behavior: reduceMotion.matches ? 'auto' : 'smooth', block: 'start' });
    }

    quizForm.addEventListener('submit', function (e) {
      e.preventDefault();
      if (!checkStep()) return;
      updateVisibility();
      const payload = { health_consent: consent.checked, tier: tier() };
      quizForm.querySelectorAll('.q[data-q]').forEach(function (q) {
        const v = value(q.dataset.q);
        if (q.dataset.q !== 'tier' && !q.hidden && v !== null) payload[q.dataset.q] = v;
      });
      quizError.textContent = '';
      const label = submitBtn.textContent;
      submitBtn.disabled = true;
      submitBtn.classList.add('is-loading');
      submitBtn.textContent = 'Считаем индекс';
      postJSON('/api/score', payload).then(function (r) {
        if (r.ok) return showResult(r.data);
        const d = r.data || {};
        if (d.error === 'age_restricted') quizError.textContent = d.fields.age;
        else if (d.error === 'health_consent_required') { showStep(0); checkStep(); }
        else quizError.textContent = 'Проверьте ответы: ' + Object.keys(d.fields || {}).length + ' вопрос(а) заполнены неверно.';
      }).catch(function () {
        quizError.textContent = 'Нет связи с сервером. Попробуйте ещё раз.';
      }).finally(function () {
        submitBtn.disabled = false;
        submitBtn.classList.remove('is-loading');
        submitBtn.textContent = label;
      });
    });

    resultCard.querySelector('.again').addEventListener('click', function () {
      const chosen = tier();
      quizForm.reset();
      quizForm.querySelector('input[name=tier][value="' + chosen + '"]').checked = true;
      quizForm.querySelectorAll('.missing').forEach(function (m) { m.classList.remove('missing'); });
      resultCard.classList.remove('is-live');
      resultCard.hidden = true;
      quizForm.hidden = false;
      showStep(0, 'back');
      focusStep();
      scrollToQuiz();
    });

    showStep(0);
  }
})();


/* Кольцо балла на карточке вошедшего: значение берём из самого числа */
(function () {
  const el = document.querySelector('[data-uc-total]');
  if (el && !el.style.getPropertyValue('--v')) el.style.setProperty('--v', parseInt(el.textContent, 10) || 0);
})();

/* Разбор сфер: вкладки с управлением стрелками (без JS все панели видны списком) */
(function () {
  'use strict';
  const root = document.querySelector('[data-tabs]');
  if (!root) return;
  const tabs = Array.from(root.querySelectorAll('[role=tab]'));
  const panels = tabs.map(function (t) { return document.getElementById(t.getAttribute('aria-controls')); });
  function select(i, focus) {
    tabs.forEach(function (t, k) {
      const on = k === i;
      t.setAttribute('aria-selected', on ? 'true' : 'false');
      t.tabIndex = on ? 0 : -1;
      panels[k].hidden = !on;
    });
    if (focus) tabs[i].focus();
  }
  root.setAttribute('data-ready', '');
  tabs.forEach(function (t, i) {
    t.addEventListener('click', function () { select(i, false); });
    t.addEventListener('keydown', function (e) {
      const k = { ArrowDown: 1, ArrowRight: 1, ArrowUp: -1, ArrowLeft: -1 }[e.key];
      if (k) { e.preventDefault(); select((i + k + tabs.length) % tabs.length, true); }
      else if (e.key === 'Home') { e.preventDefault(); select(0, true); }
      else if (e.key === 'End') { e.preventDefault(); select(tabs.length - 1, true); }
    });
  });
  select(0, false);
})();
