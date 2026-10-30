# Tabler — сторонняя библиотека для кабинета учителя

- Пакет: `@tabler/core` **1.6.1** (npm, 2026-09-28)
- Лицензия: MIT — https://github.com/tabler/tabler/blob/main/LICENSE
- Источник: https://registry.npmjs.org/@tabler/core/-/core-1.6.1.tgz
- Integrity (sha512): `lgmR9gcxRp5JlLxcmRi9Rz85JrEvH6Bz71KnlcPVSa97wtwQNjgSs3g3fxwbAlulHyRMghhIV04QUuW3pqDsIg==`
- Взяты файлы: `dist/css/tabler.min.css`, `dist/js/tabler.min.js` — без изменений.

Версия выбрана под `tools/build_tokens.py`: имена подменяемых переменных сверены с 1.6.1.
Перед обновлением Tabler пересобрать тему (`python tools/build_admin_tokens.py`) и проверить,
что в отчёте нет строки «не найдены переменные».

Подключение в странице кабинета (порядок важен):

    <link rel="stylesheet" href="…/assets/vendor/tabler/css/tabler.min.css">
    <link rel="stylesheet" href="…/assets/css/admin-theme.css">   ← генерируется из tokens-admin.json
    <link rel="stylesheet" href="…/assets/css/admin.css">         ← поправки под правила проекта (руками)
    …
    <script src="…/assets/vendor/tabler/js/tabler.min.js" defer></script>

Не править файлы руками — цвета, шрифт и радиусы меняются через `.docs/design/tokens-admin.json`.
Иконки (Tabler Icons) — отдельный пакет, в проект не входят.
