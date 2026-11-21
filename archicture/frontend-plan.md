# План реализации Front-End: services, UI-API, Qt-виджеты и диаграммы

## 1. Цель и границы

Реализовать Front-End RuCadVirtuoso поверх ядра моделирования (этап E3 плана,
`ARCH_MVP_schematic.md` §8) в два шага:

- **Шаг A — headless**: `rcad.services` (ProjectService, ModelManager, Netlister,
  ResultStore, SimulatorService-прокси) + `rcad.schemas` (project, cell, model,
  analysis, result) + **Qt-free** `rcad.ui.api.CanvasApi`. Приёмка — сценарии S1/S3/S4.
- **Шаг B — Qt-виджеты**: `rcad.ui` (MainWindow, SchematicScene, LibraryPanel,
  PropertyPanel, HierarchyNavigator, NetlistView, AnalysisDialog, PlotWindow,
  MessageLog, CommandPalette) + `rcad/ui/app.py` и `../src/main.py` + `rcad/cli.py`.
- **Диаграммы**: новые `29..34` в `release` и обновления
  `02/06/07/10/25` под фактический контракт; обновление `ARCH_MVP_schematic.md`.

Вне фазы: Verilog-A конвейер (`rcad.veriloga`, `rcad.abi`) — T9–T11, S2 остаются
`requires_va`-skip; упаковка PyInstaller/Inno (E4); миграции `format_version > 1`;
KLU-бэкенд. Решения пользователя: services+API → виджеты; CLI + `main.py` включить.

**Зависимость**: ядро из плана `Core-refactor-plan.md`
(`run_analysis(netlist, directive)`, `Result` с рядами `V(n)/I(inst)/@inst.x`,
`precheck`, `NetlistError/AnalysisError/ParameterRangeError`, маркеры
`requires_va/requires_services/requires_ui` в `conftest`). F1–F6 можно вести
параллельно с ядром; приёмочные S-тесты требуют готового ядра.

## 2. Контракт Front-End, выведенный из тестов и данных

| Источник | Контракт |
|---|---|
| S1/S3 (`../tests/integration`) | `ProjectService().create(path/{name}.rcad, name=...)`, `.add_cell(project, SCHEMATIC)`, `.save(project)`, `.open(path)`, `.path(project)`, `project.cell_names`, `project.cell(name).hierarchy_children`, `project.libraries` |
| S1/S3/S4 | `rcad.ui.api.CanvasApi(project)`: `canvas_state(cell)`, `place(cell, inst, master, x, y)`, `set_params(cell, inst, params)`, `instance_params(cell, inst)`, `build_netlist(cell, dc=.../tran=...)` |
| S1/S3/S4 | `rcad.services.netlister`: `netlist_for(project, cell, tran=...)`, `import_netlist(project, text, main=...)`, `export_netlist(project, cell)` |
| S1 | `rcad.services.result_store.export_csv(result, names, path)` — заголовок `time,<names>`, N+1 строк |
| S4 | `import_netlist` создаёт ячейки из `.subckt`; `export_netlist` воспроизводит `.subckt mem_cell` |
| S1/S3 | Netlist из netlister обязан давать у core ряды: `@Xmem.x`, `I(Xmem)`, `V(n)`; имена инстансов/узлов — из `CellSchema` |
| data | `data/Libraries/*.json`: `entry.netlist_card` (R/M/X/…), `entry.include` (`"models/memristor_yakopcic.lib"` или `"*"`), `entry.subckt` (`"memristor_yakopcic"`), `entry.params` (дефолты) |
| TZ/REQ | FR-PRJ-*, FR-CEL-*, FR-LIB-*, FR-PLC-*, FR-WIR-*, FR-PRP-*, FR-SEL-*, FR-GRD-*, FR-HIE-*, FR-ERC-*, FR-NLV-*, FR-SIM-*, FR-PLT-*, FR-LOG-*, FR-KBD-*, FR-PRS-* (`../documentation/REQ_parts/ui_storage.md`) |
| Схема ячейки | `{name, ports[], instances[]{name, master_cell, x, y, rotation, mirror, params}, wires[]{net, points[]}, junctions[]}` |
| Layering | `rcad.ui.api`, `rcad.services` не импортируют PySide6 (headless); виджеты — только через services |

## 3. Задачи

### F0 — Предпосылки и данные
1. Сигнальные проверки: ядро присутствует (`rcad.core.analyses.run_analysis`),
   `../tests/conftest.py` имеет `requires_va/services/ui` (иначе добавить по образцу `requires_core`).
2. `.gitignore`: `__pycache__/`, `*.pyc`, `.pytest_cache/`, `../.build`, `cache/`, `.rcad/`;
   убрать из VCS закоммиченные `.pyc` (`git rm --cached`). Приёмка: чистый `git status`.

### F1 — Schemas (`rcad/schemas`)
3. `project.py`: `ProjectSchema(name, format_version=1, libraries[])` (FR-PRJ-003).
4. `cell.py`: `CellSchema` (name, ports, instances, wires, junctions) — инстансы
   (name, master_cell, x, y, `rotation: 0/90/180/270`, `mirror: none/x/y`, params);
   enum-валидация; дубли имён инстансов и net — ошибка (FR-ERC-002, FR-PRP-005).
5. `model.py`: `ModelEntry(cell, role, netlist_card, params, include, subckt,
   pins[names])` на базе `data/Libraries/*.json`; `ParamSpec` из `rcad.core.devices` (+`bounds`).
6. `analysis.py`: `OpSpec | DcSpec | TranSpec | AcSpec` (discriminator `type`),
   им же соответствует строка директивы (`.tran tstep tstop tstart tmax` и т.д.) —
   генератор `to_directive()`.
7. `result.py`: `ResultMeta(analysis_type, rows, units, version, provenance)`.
Приёмка: unit — парсинг SCHEMATIC из S1/S3, отклонение дублей/невалидных rotation;
формат-версия (FR-PRJ-004/005).

### F2 — ProjectService (`rcad/services/project_service.py`)
8. `create(path, name)` — каталог `<name>.rcad`, `project.json` c `format_version=1`
   и библиотеками из `../data/Libraries` по умолчанию; `path(project) -> Path`.
9. `add_cell(project, schematic_dict)` — `model_validate` → `cells/<cell>.json`.
10. `save(project)` — атомарная запись каждого файла (`*.tmp` → `os.replace`,
    FR-CEL-007); без абсолютных путей машины (FR-PRJ-011); `recovery.json` удаляется.
11. `open(path)` — валидация `project.json`, миграция по `format_version` (сейчас 1);
    битый/несовместимый → `RcadError`/`Diagnostic(E_PROJECT_CORRUPT, file, field)`,
    частично читаемый проект открывается (FR-PRJ-009/012); `cache/` отсутствие — ок (FR-PRJ-007).
12. `autosave(project)` и восстановление: запись изменённых ячеек + `recovery.json`
    (для FR-PRS-001/FR-PRS-002 на сервисном уровне, таймер — в виджетах, B1.2).
Приёмка: `test_s1.test_project_saved_and_reopened`; unit FR-PRJ-002/004/009/011/012, FR-PRS.

### F3 — ModelManager (`rcad/services/model_manager.py`)
13. Загрузка `data/Libraries/*.json` + `data/Symbols/*.json` (SymbolSchema уже есть)
    в библиотеку; `params_for(master_cell) -> list[ParamSpec]`; список ячеек для панели
    (FR-LIB-001); маппинг «cell → netlist_card / include / subckt» для netlister.
14. Интеграция с `rcad.devices.registry` (модели по имени для X-карт).
Приёмка: unit — для `memristor_m1` params_for = набор a1…eta, include/subckt/карта корректны.

### F4 — Netlister (`rcad/services/netlister.py`)
15. `netlist_for(project, cell, *, dc/tran/ac=None)`: собирает текст —
    `.include` для всех задействованных `entry.include` (кроме `"*"`), `.subckt`-заглушки
    дочерних ячеек для иерархии, карты инстансов (R/C/V/I — примитивы; X — device/subckt;
    M — MOSFET с `.model`), привязку выводов к net из wires/ports, переданную директиву,
    `.end`. Имена инстансов/узлов — из CellSchema (ряды `I(Xmem)`, `@Xmem.x` приходят из ядра).
16. Автоимена net `n1, n2, …` без повторного использования номера; узел `0` не автонумеруется
    (FR-WIR-002/003); ручное переименование — сервис `validate_net_name` (WiR-004, reject/merge).
17. `export_netlist(project, cell)` — то же без директивы (NetlistView, FR-NLV-001).
18. `import_netlist(project, text, main=...)` — `subckt` → ячейки (инстансы, порты,
    провода по net), X → инстансы, `.include` сохраняется как запись библиотеки;
    ошибки → `NetlistError` с line/col, проект не меняется (FR-NLV-004/005).
Приёмка: S1 (`netlist_for` + tran даёт 2001 точку и `@Xmem.x`), S4 import/export;
unit: автоимена net, roundtrip 3-уровней.

### F5 — ResultStore (`rcad/services/result_store.py`)
19. `put/get`; `export_csv(result, names, path)` — `time,<names>` + N строк (S1: 2002).
Приёмка: `test_s1.test_both_series_are_exported_to_csv`.

### F6 — UI-API (`rcad/ui/api.py`, Qt-free)
20. `CanvasApi`: `canvas_state(cell)` (возвращает dict SCHEMATIC-формы),
    `place(cell, inst, master, x, y)` (уникальность имени — FR-PRP-005; автокопия — FR-PLC-004),
    `set_params` (валидация типа/диапазона из ParamSpec → `ParameterRangeError`, FR-PRP-002/003),
    `instance_params`, `build_netlist` (→ netlister).
21. Запрет Qt-импортов — расширение `tests/unit/test_layering.py` (AST): `rcad.ui.api`
    и `rcad.services.*` не импортируют PySide6/pyqtgraph/Qt; `rcad.ui.*` (виджеты) —
    не импортируют `rcad.core.mna/solver` напрямую.
Приёмка: S1/S3/S4 green (маркер `requires_services` перестаёт скипать), S2 остаётся skip (VA).

### F7 — CLI и точка входа
22. `rcad/cli.py`: `check` (precheck/ERC), `netlist <proj> -o out.cir`, `run <proj>
    --analysis {op,dc,tran,ac} --out csv` (ProjectService + netlister + run_analysis),
    `export`; UTF-8, exit-коды ≠ 0 при ошибке (ARCH §10.3).
23. `../src/main.py`: `argparse` (`--cli`, `--headless`, `--project`);
    GUI-режим — `rcad.ui.app` только при запросе (нулевой Qt-импорт на этапе CLI).
    Приёмка: `python -m rcad.cli --help`; check/netlist/run на примере из S1; `python src/main.py --headless --project <tmp>` не запускает Qt.

### F8 — Qt-виджеты (`rcad/ui/`)
24. `app.py`: `create_app()` (QApplication, high-DPI); `MainWindow` — доки
   (библиотека слева, сцена центр, свойства справа, логи снизу, NFR-UI-001),
   меню/тулбар, «Сохранить/Не сохранять/Отмена» при закрытии (FR-PRS-002), статус-бар.
25. `scene/` — `SchematicScene`/View: сетка 10 px + снаппинг (FR-GRD-001/002/003),
   рендер `SymbolSchema` (line/polyline/circle/arc), рисование проводов с net-именами
   (WIR-001…003), junction, выделение кликом/рамкой (SEL-001/002), поворот/зеркало
   (PLC-002/003), копирование/удаление (PLC-004/005). Каждое действие — `QUndoCommand` над
   pydantic-`CellSchema` + `scene.sync()` (инкрементальная перерисовка); история ≥50
   (SEL-003…005, per-cell). Perf: перерисовка по таймеру ≤30 fps, антиалиасинг off ≥500
   инстансов (NFR-PERF-UI).
26. `widgets/library_panel.py` — список из ModelManager (LIB-001/002), drag&drop (PLC-001);
   VA-секция скрыта, пока нет `rcad.veriloga`.
27. `widgets/property_panel.py` — QFormLayout из `ParamSpec` (тип/диапазон/единица),
   валидаторы (PRP-001…003), переименование без дублей (PRP-005), одна undo-операция (PRP-004).
28. `widgets/hierarchy.py` — дерево ячеек, вход/выход в master с сохранением масштаба
   (HIE-001/002/003), порты, метка «отсутствующий мастер» (HIE-005).
29. `widgets/netlist_view.py` — read-only `QPlainTextEdit`, обновление при изменении схемы
   (NLV-001/002), экспорт/импорт + ошибки импорта в лог (NLV-003/004/005).
30. `dialogs/analysis.py` — вкладки OP/DC/TRAN/AC, поля развёртки (SIM-001), выбор величин
   (узлы/токи/SV) (SIM-002), валидация до запуска (SIM-003), запуск через SimulatorService.
31. `dialogs/simulator_service.py` — `QThread` + сигналы progress/finished/failed,
   отмена (дропнутый воркер; UI отзывчив, SIM-004), ошибки → MessageLog без падения (SIM-005).
   Отметка: core-level cancel-флаги — отложено (см. Риски).
32. `plots/plot_window.py` — pyqtgraph: мультипанели (PLT-002), курсор (PLT-003),
   лог-оси по X/Y (PLT-004), экспорт PNG/CSV (PLT-005), несколько окон (PLT-006).
33. `widgets/message_log.py` — QTableView + proxy: уровни/фильтр/очистка (LOG-001/002),
   en+ru (LOG-003), клик по диагностике выделяет объект сцены (ERC-007, LOG-004).
34. ShortcutMap/CommandPalette (KBD-001…003): ротация, зеркало, копия, удалить, анализ, save,
   Ctrl+Z/Y; в фокусе полей ввода комбинации не перехватываются (KBD-002).
35. `tests/ui_smoke/` (pytest-qt, `QT_QPA_PLATFORM=offscreen`): старт приложения, открытие
   проекта, размещение инстанса, TRAN через AnalysisDialog, PlotWindow открыт, нет падений.
Приёмка: UI-smoke зелёный в CI (offscreen); ручной запуск `python src/main.py --project <tmp>`.

### F9 — Диаграммы («допиши diagrams»)
36. **Новые** (канон — `release`, затем синхронизировать копии в
    `diagrams`):
   - `29_act_edit_schematic.puml` — activity: размещение/провод/net-имена (WIR-002/003)/
     свойства (PRP) → QUndoCommand → scene.sync → dirty → автосохранение; ошибки → MessageLog;
     decision-table ветки валидации (PRP-002/003, WIR-004 reject/merge).
   - `30_stm_document_state.puml` — state-машина: Clean → Dirty → Autosaved(+Dirty) →
     Saving (tmp→rename) → Closing (Save/Discard/Cancel) → Recovering (recovery.json); FR-PRS, F-CEL-007.
   - `31_act_run_analysis_ui.puml` — AnalysisDialog (SIM-001…003) → SimulatorService(QThread,
     progress/cancel) → Result → PlotWindow (панели/курсор/лог-оси/экспорт), failure → MessageLog (SIM-005).
   - `32_seq_undo_redo.puml` — действие → QUndoStack → UndoCommand.redo/undo → CellSchema →
     scene.sync → автосохранение; per-cell история (SEL-003…005).
   - `33_act_netlist_import_export.puml` — NLV-001…005: вью (актуальное автообновление),
     экспорт, импорт с разбором subckt→ячейки, ошибки file:line → лог.
   - `34_class_schemas_doc.puml` — классы pydantic: ProjectSchema, CellSchema
     (→ InstanceSchema/WireSchema/PortSchema), ModelEntry, AnalysisSpec (Op/Dc/Tran/Ac),
     ResultMeta; отношения агрегации.
37. **Обновить существующие** под контракт тестов и Qt-free CanvasApi:
   - `diagrams/06_class_ui_services.puml`: netlister — module-функции `import_netlist/export_netlist/
     netlist_for` вместо методов класса; `ResultStore.export_csv(result, names, path)`;
     `ui.api.CanvasApi` (Qt-free facade); ProjectService.add_cell/path/cell_names.
   - `diagrams/10_components_ui.puml`: добавить узлы `CanvasApi` и `CommandPalette`; стрелки
     Scene/Props/Hier → PS/MM через модульные функции; отметить Qt-free.
   - `diagrams/07_packages.puml`: `ui.api` — примечание «не импортирует Qt»; запрет
     `ui/api, services → PySide6`; `cli → services` уже есть.
   - `diagrams/02_containers.puml`: `SVC --> CORE : run_analysis(netlist, directive)`, добавить
     `precheck`; UI-API стрелка.
   - `diagrams/25_usecase_acceptance.puml`: S1–S4 как use-cases через CanvasApi, если не покрыто.
38. `ARCH_MVP_schematic.md`: обновить статус (§0 «Код отсутствует» → «реализованы core и
    сервисы/UI-API»), §8 — фактический инвентарь (`rcad/ui/api.py` Qt-free, виджеты/диалоги),
    §4 структура каталогов — фактическая (rcad.services, ui.api, cli.py, data/models).
39. Рендер: `plantuml -tsvg` для всех новых/изменённых; при отсутствии plantuml — пометить
    SVGs устаревшими, источник правды `.puml`.
Приёмка: `plantuml -check` без ошибок; SVGs синхронны с release и верхним каталогом.

### F10 — Гигиена и связность
40. Убрать pyc из git; `.gitignore`; `test_layering` расширен (запреты §F6);
    регрессия ядра (T1–T8, T12, T14, T15 green; T9–T11, S2 skip; T13 perf в бюджете);
    `ruff check src && mypy src`.

## 4. Определение готовности фазы

- S1, S3, S4 зелёные (services + ui.api + core); T9–T11, S2 — чистый skip (VA);
  регрессия T1–T8/T12/T14/T15 без сбоев.
- `python -m rcad.cli check/netlist/run` работает; `../src/main.py` запускает GUI и headless.
- Widgets: UI-smoke (offscreen) зелёный; ручной сценарий S1 в редакторе не падает.
- Диаграммы 29–34 созданы, 02/06/07/10/25 обновлены, SVGs синхронны, `plantuml -check` ок.
- В VCS нет `__pycache__/`/`*.pyc`; ruff/mypy чисты; ARCH-документ отражает фактическое состояние.

## 5. Риски и решения

- **Имена рядов (`I(Xmem)`, `@Xmem.x`)** — контракт ядра; netlister гарантирует соответствие
  имён инстансов в CellSchema → X-карте. Сверяется в S1/S3.
- **S1 2001 точка / 2002 строки CSV** — зависит от TRAN-сетки ядра (`tstep 1m` по [0,2]);
  если ядро ещё не готово, S-тесты остаются skip до перехода ядра.
- **Отмена расчёта без core-флага**: в фазе — QThread + discard результата; core-level
  cancel-флаг отложен (помечено в ARCH).
- **CanvasApi headless**: запрет Qt-импортов enforced тестом (F6.21); CanvasApi не требует
  QApplication.
- **Объём SchematicView** больше всех остальных виджетов: ограничить до обязательных жестов
  (FR-PLC/GRD/SEL); сложную верстку символов оставить после MVP.
- **Golden/данные**: netlister полагается на `data/Libraries/*.json` (уже верны по
  test_symbols) и `data/models/*.lib` из core-плана.
- **Синхронизация диаграмм**: дублирующиеся наборы `diagrams/` и `diagrams/release/`;
  release — канонический, копии синхронизируются вручную в задаче 36.

## 6. Вне охвата

Verilog-A UI (полный ImportVaWizard — когда появится `rcad.veriloga`), S2,
undо между ячейками (FR-SEL-005 — только per-cell стеки), расширенный редактор портов,
миграции формата, PyInstaller/Inno/E4, KLU, сетевые/подписочные функции.

## 7. Порядок валидации

1. `pytest tests/unit -m "not perf"` — schemas, layering, services, model manager.
2. `pytest tests/integration/test_s1_memristor_iv.py tests/integration/test_s3_neuristor_neuron.py tests/integration/test_s4_crossbar_4x4.py`.
3. `pytest tests/integration -m "not perf"` — полный набор (T-core зелёные, VA/S2 skip).
4. `QT_QPA_PLATFORM=offscreen pytest tests/ui_smoke`.
5. `python -m rcad.cli check/netlist/run/export` на примере S1; `python src/main.py --help`.
6. `ruff check src tests && mypy src`; `git status` без pyc/cache.
