-- Отчёты Adelina Health. Запуск:  sqlite3 instance/vitascore.db < reports.sql
-- Учитываются только посетители, согласившиеся на аналитические cookie (таблица visitors).
.headers on
.mode column

.print
.print === Посетители и заявки по источникам ===
SELECT v.source,
       count(DISTINCT v.visitor_id) AS visitors,
       count(DISTINCT l.id) AS leads,
       round(100.0 * count(DISTINCT l.visitor_id) / count(DISTINCT v.visitor_id), 1) AS conv_pct
FROM visitors v LEFT JOIN leads l ON l.visitor_id = v.visitor_id
GROUP BY v.source ORDER BY leads DESC, visitors DESC;

.print
.print === Заявки по UTM-кампаниям ===
SELECT coalesce(v.utm_campaign, '-') AS campaign, v.utm_source, coalesce(v.utm_medium, '-') AS medium,
       count(l.id) AS leads,
       sum(l.plan = 'Start') AS start,
       sum(l.plan = 'Balance') AS balance
FROM leads l JOIN visitors v ON v.visitor_id = l.visitor_id
WHERE v.utm_source IS NOT NULL
GROUP BY 1, 2, 3 ORDER BY leads DESC;

.print
.print === Устройства ===
SELECT v.device_type, v.os, v.browser,
       count(DISTINCT v.visitor_id) AS visitors,
       count(DISTINCT l.id) AS leads
FROM visitors v LEFT JOIN leads l ON l.visitor_id = v.visitor_id
GROUP BY 1, 2, 3 ORDER BY visitors DESC;

.print
.print === Страны (примерно: по часовому поясу и языку браузера) ===
SELECT coalesce(v.country, '?') AS country,
       count(DISTINCT v.visitor_id) AS visitors,
       count(DISTINCT l.id) AS leads
FROM visitors v LEFT JOIN leads l ON l.visitor_id = v.visitor_id
GROUP BY 1 ORDER BY visitors DESC;

.print
.print === Анкета по источникам ===
SELECT v.source, count(s.id) AS quizzes, round(avg(s.total), 1) AS avg_score
FROM score_results s JOIN visitors v ON v.visitor_id = s.visitor_id
GROUP BY v.source ORDER BY quizzes DESC;

.print
.print === Заявки без данных об источнике (не приняли cookie) ===
SELECT count(*) AS leads_total,
       sum(visitor_id IS NULL OR visitor_id NOT IN (SELECT visitor_id FROM visitors)) AS without_source
FROM leads;
