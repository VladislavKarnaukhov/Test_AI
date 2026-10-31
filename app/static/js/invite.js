// Приглашение друга: копирование ссылки и системное «Поделиться», если браузер его поддерживает.
(function () {
  var input = document.querySelector('[data-invite-link]');
  if (!input) return;
  var copy = document.querySelector('[data-invite-copy]');
  var share = document.querySelector('[data-invite-share]');
  var status = document.querySelector('[data-invite-status]');
  function say(text) { if (status) status.textContent = text; }
  copy.addEventListener('click', function () {
    var done = function () { say('Ссылка скопирована'); };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(input.value).then(done, function () { input.select(); say('Выделите и скопируйте ссылку'); });
    } else { input.select(); say('Выделите и скопируйте ссылку'); }
  });
  input.addEventListener('focus', function () { input.select(); });
  if (navigator.share) {
    share.hidden = false;
    share.addEventListener('click', function () {
      navigator.share({ title: 'Del Health', text: 'Проверьте свой индекс здоровья: короткая анкета и один шаг на неделю.', url: input.value }).catch(function () {});
    });
  }
})();
