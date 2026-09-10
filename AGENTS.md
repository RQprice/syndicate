# SYNDICATE: карта проекта для Codex

Перед задачей сначала определи её зону по карте ниже. Читай релевантный модуль,
его прямые зависимости и соответствующие тесты; не просматривай весь репозиторий
без необходимости.

| Зона | Основные файлы |
| --- | --- |
| Запуск и совместимость | `app.py` |
| Главное окно и адаптивная компоновка | `syndicate/application.py` |
| Сценарий розыгрыша, победители, подготовка MP4 | `syndicate/draw_workflow.py` |
| Отрисовка колеса и кадров результата | `syndicate/wheel_rendering.py` |
| Участники и правая панель | `syndicate/participants_ui.py` |
| Импорт скриншотов и замены ников | `syndicate/import_ui.py` |
| История и календарь | `syndicate/history_ui.py` |
| Общие UI-компоненты | `syndicate/widgets.py` |
| Вероятности и выбор победителя | `syndicate/probabilities.py` |
| Модели и чистые вычисления | `syndicate/models.py` |
| `data.json` и `draw_log.json` | `syndicate/storage.py` |
| Кодирование MP4 | `syndicate/video.py` |
| Windows, пути, масштаб, clipboard | `syndicate/platform.py` |
| Палитра и дизайн-константы | `syndicate/theme.py` |
| OCR участников и наград | `ocr_import.py` |

Подробности: `docs/architecture.md`.

Правила изменений:

- `app.py` — тонкий фасад; не возвращай в него прикладную логику.
- Без явной задачи не меняй UI, формулу вероятностей и форматы `data.json` /
  `draw_log.json`.
- Не трогай OCR участников при задаче только про OCR наград.
- Сохраняй пользовательские файлы данных. EXE собирай только по явной просьбе.
- Новые тесты располагай рядом с существующей группой тестов соответствующей
  зоны.

Проверка перед завершением:

```powershell
py -m compileall -q app.py ocr_import.py syndicate
py -m unittest discover -s tests -v
```
