// Настройки: подключение Health Connect через мост приложения Android (window.DelHealthNative)
(function () {
  'use strict';
  var root = document.querySelector('[data-health-sync]');
  var bridge = window.DelHealthNative;
  if (!root || !bridge) return; // в обычном браузере остаётся подсказка про приложение

  var csrf = root.dataset.csrf;
  var connected = root.dataset.connected === 'true';
  var statusEl = root.querySelector('[data-hs-status]');
  var consent = root.querySelector('[data-hs-consent]');
  var connectBtn = root.querySelector('[data-hs-connect]');
  var syncBtn = root.querySelector('[data-hs-sync]');
  root.querySelector('[data-hs-web]').hidden = true;
  root.querySelector('[data-hs-app]').hidden = false;

  function say(text) { statusEl.textContent = text; }

  function post(url, body) {
    return fetch(url, {
      method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf },
      body: JSON.stringify(body)
    }).then(function (r) { return r.json().then(function (j) { j.status = r.status; return j; }); });
  }

  window.onDelHealthNative = function (event, data) {
    if (event === 'status') {
      if (!data.available) {
        say(data.state === 'NEEDS_INSTALL_OR_UPDATE' ? 'Нужно установить или обновить Health Connect.' : 'На этом устройстве Health Connect недоступен.');
        if (data.state === 'NEEDS_INSTALL_OR_UPDATE') bridge.installHealthConnect();
      } else if (!data.granted) bridge.requestHealthAccess();
      else bridge.getHealthSummary(7);
    } else if (event === 'permission') {
      if (data.granted) bridge.getHealthSummary(7); else say('Доступ к данным не разрешён.');
    } else if (event === 'summary') {
      say('Отправляем данные…');
      post('/api/health-sync', { days: data.days }).then(function (res) {
        if (res.ok) { say('Готово: обновлено дней — ' + res.saved + '.'); setTimeout(function () { location.reload(); }, 800); }
        else say('Не удалось сохранить данные. Обновите страницу и попробуйте ещё раз.');
      }).catch(function () { say('Нет соединения с сервером.'); });
    } else if (event === 'error') {
      say(data.message === 'no_access' ? 'Нет доступа к данным Health Connect.' : 'Ошибка чтения данных.');
    }
  };

  if (consent && connectBtn) {
    consent.addEventListener('change', function () { connectBtn.disabled = !consent.checked; });
    connectBtn.addEventListener('click', function () {
      connectBtn.disabled = true;
      post('/api/health-sync/connect', { consent: true, source: 'health_connect' }).then(function (res) {
        if (res.ok) { say('Проверяем доступ…'); bridge.getHealthStatus(); }
        else { say('Не удалось подключить. Обновите страницу.'); connectBtn.disabled = false; }
      });
    });
  }
  if (syncBtn) syncBtn.addEventListener('click', function () { say('Читаем данные…'); bridge.getHealthStatus(); });
})();
