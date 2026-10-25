// Отчёт месяца: «Сохранить в PDF» открывает системную печать, где можно выбрать PDF.
(function () {
  var btn = document.querySelector('[data-print]');
  if (btn) btn.addEventListener('click', function () { window.print(); });
})();
