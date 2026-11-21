# Архитектура и технологический стек MVP RuCadVirtuoso

| Поле | Значение |
|---|---|
| Документ | Архитектура решения и выбранные технологии для MVP (схемотехническая часть) |
| Источники | `documentation/TZ_MVP_schematic.md` v1.0, `documentation/REQ_MVP_schematic.md`, `documentation/REQ_parts/*.md` |
| Область | Только схемотехнический MVP по ТЗ п. 4.1 |
| Статус | Черновик для ревью; решения по технологиям зафиксированы (см. §2). Статус реализации — §0 |
| Репозиторий | Реализованы ядро (`rcad.core.*`), сервисы (`rcad.services.*`) и Qt-free `rcad.ui.api.CanvasApi`; виджеты в `rcad.ui` (S1/S3/S4 — начиная с этапа E3) |

---

## 0. Статус реализации (этап E3)

| Слой | Что реализовано | Где |
|---|---|---|
| Ядро | `rcad.core.*`: netlist, circuit, MNA, solver, integ, analyses (по core-плану) | `src/rcad/core/` |
| Диагностика | `Diagnostic`, `DiagnosticCode`, `RcadError`/`NetlistError`/`AnalysisError`/`ParameterRangeError` | `src/rcad/diagnostics/` |
| Схемы | `ProjectSchema`, `CellSchema` (+Instance/Wire/Port/Junction), `ModelEntry`/`ParamSpec`, `Op/DC/Tran/Ac`, `ResultMeta` | `src/rcad/schemas/` |
| Сервисы | `ProjectService` (create/add/save/autosave/open), `ModelManager` (Libraries+Symbols), `Netlister` (netlist_for/export/import, геометрия соединений), `ResultStore` (export_csv) | `src/rcad/services/` |
| UI-API | `CanvasApi` — Qt-free фасад: `canvas_state/place/set_params/instance_params/build_netlist` | `src/rcad/ui/api.py` |
| Виджеты | `MainWindow`, `SchematicScene/View`, `LibraryPanel`, `PropertyPanel`, `HierarchyNavigator`, `NetlistView`, `MessageLog`, `CommandPalette`, `AnalysisDialog`, `SimulatorService` (QThread), `PlotWindow` (pyqtgraph) | `src/rcad/ui/` |
| CLI / вход | `rcad.cli` (check/netlist/run/export), `src/main.py` (--cli/--headless/--project) | `src/rcad/cli.py`, `src/main.py` |

Приёмка — сценарии S1/S3/S4 через `CanvasApi`; S2 и T9–T11 — по готовности
`rcad.veriloga` (маркеры `requires_va`). Слоистая проверка — `tests/unit/test_layering.py`.
Отмена расчёта без core-флага: QThread + discard (core-level cancel-флаг отложен).

---

## 1. Цели архитектуры

1. **Численно достоверный результат** — не демонстрация интерфейса: каждая модель сверяется с независимым эталоном (аналитика, ngspice, эталонный subckt) в допусках ТЗ п. 12.
2. **Headless-first.** Любой анализ запускается через `run_analysis(circuit, spec) -> Result` без GUI (ТЗ п. 5.1, `NFR-TST-001`). UI — тонкий клиент над сервисами.
3. **Нулевой UI-импорт в ядре.** `rcad.core` / `rcad.devices` / `rcad.veriloga` не импортируют PySide6 (проверяется в CI, `NFR-TST-002`).
4. **Ни одна ошибка пользовательского ввода или модели не роняет приложение**: исключение перехватывается на границе (парсер, DLL-ABI, граница анализа).
5. **Расширяемость приборами без правки ядра**: нативная модель, Verilog-A модель и примитив реализуют один контракт вклада в систему.
6. **Однократная сборка структуры.** Разреженная структура MNA (CSR) и карта Якобиана собираются один раз при «компиляции схемы», далее только численные значения.

### 1.1 Ключевые архитектурные решения (ADR-lite)

| ID | Решение | Обоснование | Альтернативы и почему отклонены |
|---|---|---|---|
| AD-01 | Слоистая архитектура **Core → Services → UI**, зависимости направлены строго вниз | Требование headless-тестируемости и независимости ядра от UI (ТЗ п. 5.1) | Монолит «UI + расчёт» — ломает CI и S-сценарии через API |
| AD-02 | **Форма DAE как charge/flux**: `f(x) = d/dt·q(x) + i(x) + u = 0` | Корректная работа с нелинейными ёмкостями мемристивных приборов и интегрирование SV «как заряд» (ТЗ п. 7.1, 7.3) | Чисто резистивная формулировка `G·v = i`: неверные производные по времени, неустойчивость на переключениях |
| AD-03 | Один контракт прибора: `stamp_static`, `stamp_dynamic`, `eval_state` + метаданные | Нативные C++-модели, Verilog-A DLL и примитивы ведут себя одинаково для ядра (ТЗ п. 7.1.2, 8.4) | Отдельные ветки `if isinstance(...)` в сборщике MNA — дублирование и расхождение семантики |
| AD-04 | **Аналитический Якобиан обязателен** для встроенных моделей; численный fallback — только для VA при неподдерживаемой конструкции, с warning | Сходимость Ньютона на жёстких мемристивных уравнениях (ТЗ п. 7.2) | Полностью численный Якобиан: `n+1` вычисление модели на итерацию, провал по времени T13 |
| AD-05 | Разреженные матрицы SciPy (`scipy.sparse` CSR + `splu`), KLU — как заменяемый бэкенд | Разреженная сборка однократно, LU с переиспользованием символической факторизации (ТЗ п. 7.4.5) | Плотные матрицы (`numpy.linalg.solve`): кубическая сложность, непригодно для 16×16 кроссбара |
| AD-06 | Verilog-A: **собственный транслятор → C++ → `cl.exe` → DLL → `ctypes`** с версионируемым ABI | Требование ТЗ п. 8.1, 8.4; контроль над семантикой `ddt`/`idt` и аналитическими производными | Интерпретатор на NumPy (медленно, нарушает п. 7.2); OpenVAF/OSDI (открытый вопрос OQ-002, не MVP) |
| AD-07 | Хранение проекта — **каталог `.rcad/` с JSON-файлами**, не один бинарный файл | Переносимость, diff-пригодность, диагностика битого файла без падения (ТЗ п. 6.1, `FR-PRJ-009…012`) | Zip/SQLite-архив: непрозрачен для ревью и VCS, сложнее восстанавливать частично |
| AD-08 | Результаты симуляции — неизменяемые **массивы NumPy + метаданные рядов** в памяти (`Result`), экспорт CSV по запросу | Быстрый просмотр, отсутствие обязательной записи на диск, детерминизм (`NFR-TST-006`) | Потоковая запись в файл: усложняет интерактивную построение графиков и повторный просмотр |
| AD-09 | Пакет `rcad/` с плоской зависимостью подпакетов, без циклических импортов; границы enforced тестом импортов | Модульность и параллельная разработка E1/E2/E3 | Разбиение на отдельные дистрибутивы-пакеты: избыточно для MVP |

---

## 2. Технологический стек

### 2.1 Сводная таблица

| Слой | Технология | Версия | Назначение | Обоснование |
|---|---|---|---|---|
| Язык | Python | 3.12 | Весь код | ТЗ п. 11; self-contained в инсталляторе |
| Численная база | NumPy | ≥ 2.0 | Векторы/матрицы приборов, массивы результатов | Обязательная зависимость (ТЗ п. 11) |
| Разреженная линейная алгебра | SciPy (`sparse`, `sparse.linalg.splu`, `optimize` для тестов) | ≥ 1.13 | CSR-сборка, LU-факторизация | Обязательная зависимость; `splu` покрывает AD-05 |
| GUI | PySide6 (Qt 6, LGPL) | ≥ 6.7 | Редактор схем, свойства, диалоги, логи | ТЗ п. 11; нативная отрисовка, DPI-awareness, QGraphicsScene для схемы |
| Графики результатов | pyqtgraph | ≥ 0.13 | Просмотрщик: панели, курсор, лог-шкалы | Согласовано; OpenGL-ускорение, лог-оси и курсор «из коробки», совместим с PySide6 |
| Валидация данных | pydantic | ≥ 2.7 | Схема проекта, `project.json`, `cells/*.json`, метаданные моделей, спека анализа | Согласовано; структурные ошибки с путём до поля, версионирование формата |
| Тесты | pytest | ≥ 8.0 | Unit / integration / golden | Согласовано; `NFR-TST-005` — одна команда в CI |
| Property-based тесты | hypothesis | ≥ 6.100 | Парсер netlist (суффиксы, выражения), Якобиан на случайных точках | Согласовано; ловит краевые случаи, которые не покроет ручной набор из 40 кейсов |
| Сборка C++ | MSVC `cl.exe` (Build Tools 2022) | 19.4x | Компиляция Verilog-A моделей в DLL | ТЗ п. 11.1; согласовано. Обнаружение через `vswhere` |
| Упаковка Python | PyInstaller | ≥ 6.6 | One-folder дистрибутив с embedded Python | Согласовано; соответствует `NFR-DIST-003` |
| Инсталлятор | Inno Setup 6 | 6.x | `installer.iss`: `[Files]`, `[Icons]`, опциональный шаг MSVC Build Tools | Согласовано; каркас уже есть |
| CI | GitHub Actions (Windows-раннер) | — | Прогон тестов headless, отчёт JUnit/CSV | `TRQ-TEST-011`, `NFR-TST-005` |
| Логирование | stdlib `logging` + `RotatingFileHandler` | — | `%APPDATA%/RuCadVirtuoso/logs/` | `NFR-LOG-001…004`; внешняя зависимость не нужна |
| Сторонний эталон | ngspice (офлайн, только генерация golden) | 4x | Создание эталонных CSV в `tests/golden/` | ТЗ п. 12.1; **не** входит в runtime-дистрибутив |

Не используются: нет C-расширений собственного производства в MVP (KLU/`scikit-sparse` — резерв по AD-05 и риску ТЗ п. 16), нет ORM/БД, нет сетевых компонентов.

### 2.2 Обоснование «почему не иначе»

| Вопрос | Выбор | Отклонено |
|---|---|---|
| Чем считать линейную систему | `scipy.sparse.linalg.splu` с предзаказом COLAMD | `numpy.linalg.solve` (плотно), `np.linalg.lstsq` (не тот класс задачи), собственная LU (не наш риск) |
| Чем строить UI | PySide6 widget-based (`QMainWindow` + `QGraphicsScene`) | QML (лишний слой), Tkinter (нет сцен-графа и DPI), веб-UI (нарушает «десктопное приложение» п. 11) |
| Чем проверять VA-синтаксис | Собственный рекурсивный спуск (приоритетный парсер) | PLY/ANTLR (тяжелее, генерация кода), `ast` от Python (не тот язык) |
| Чем дифференцировать VA-выражения | Символьное дифференцирование AST + общие подвыражения, fallback на конечные разности | Автоматическое дифференцирование в C++ (не MVP), ручные производные в .va (не в языке) |
| Где хранить скомпилированные DLL | `cache/<sha256>.dll` в каталоге проекта, вне VCS | Глобальный кэш `%APPDATA%` (затрудняет переносимость, `FR-PRJ-006`) |
| Чем сериализовать проект | JSON через pydantic `model_dump_json` | Pickle (небезопасно, нечитаемо), YAML (зависимость без выигрыша) |

---

## 3. Архитектура: слои и зависимости

```
┌──────────────────────────────────────────────────────────────────────┐
│ UI (PySide6)                                                          │
│  MainWindow │ SchematicScene │ PropertyPanel │ AnalysisDialog         │
│  PlotWindow (pyqtgraph) │ MessageLog │ ImportVaWizard                 │
└───────────────────────────────┬──────────────────────────────────────┘
                                │ вызовы сервисов + Qt-сигналы прогресса
┌───────────────────────────────▼──────────────────────────────────────┐
│ Application services                                                  │
│  ProjectService (load/save/autosave/recover)                         │
│  Netlister (cell graph → netlist)      ModelManager (библиотека)      │
│  SimulatorService (run_analysis + поток/очередь)  ResultStore         │
│  VaImportService (validate → translate → compile → register symbol)   │
└───────┬───────────────────────────────────────────────┬──────────────┘
        │                                               │
┌───────▼───────────────────────────────┐  ┌────────────▼──────────────┐
│ Core (чистый Python + NumPy/SciPy)    │  │ Device codegen (E2)        │
│  netlist: lexer, parser, ast, params  │  │  va: lexer, parser, ast,   │
│  circuit: graph, hierarchy, net names │  │  semantics, codegen_cpp,   │
│  mna: structure, stamping, jacobian   │  │  compiler (cl.exe),        │
│  solver: newton, strategies, integr.  │  │  abi_load (ctypes)         │
│  analyses: op, dc, tran, ac           │  └────────────┬──────────────┘
│  devices: contract + builtin models   │               │ DLL (C ABI)
│  diagnostics: codes, errors, logging  │               │
└───────────────────────────────────────┘               │
                              ddt/dt    ▲               │
                                        └───────────────┘
```

**Правила зависимостей (проверяются в CI):**

| Правило | Как проверяется |
|---|---|
| `rcad.core`, `rcad.devices`, `rcad.veriloga` не импортируют `PySide6`, `pyqtgraph`, `rcad.ui` | `tests/unit/test_layering.py` — анализ AST импортов |
| `rcad.ui` не импортирует внутренности `rcad.core.mna`/`solver` напрямую, только через сервисы | тот же тест (список запрещённых модулей) |
| `rcad.devices` не импортирует `rcad.analyses` (нет обратной зависимости) | тот же тест |
| json-схемы pydantic описаны в `rcad.schemas` и используются и UI, и сервисами | ревью; отдельного теста не требуется |

---

## 4. Структура каталогов

```
src/
  main.py                    # точка входа: argparse (--headless/--project/--cli) → ui.app или cli
  rcad/
    __init__.py              # версия; __all__ = diagnostics/schemas/services/ui
    schemas/                 # project, cell, symbol, model, analysis, result
    diagnostics/             # коды, Diagnostic, DiagnosticBag, RcadError/NetlistError/…
    core/                    # netlist, circuit, mna, solver, integ, analyses, devices (по core-плану)
    devices/                 # builtin: mos, memristor_yakopcic, …, neuristor_n1/n2 (по core-плану)
    services/                # project_service, model_manager, netlister, result_store
    ui/
      api.py                 # CanvasApi — Qt-free фасад (нет PySide6)
      app.py                 # create_app() + MainWindow (доки, меню, автосохранение)
      scene/                 # SchematicScene / View (сетка 10 px, undo/redo)
      widgets/               # library_panel, property_panel, hierarchy, netlist_view,
                             # message_log, command_palette
      dialogs/               # analysis, simulator_service (QThread)
      plots/                 # plot_window (pyqtgraph)
    cli.py                   # check / netlist / run / export (UTF-8, exit≠0 при ошибке)
tests/
  unit/ integration/ golden/ perf/ ui_smoke/
  unit/test_layering.py
data/
  Symbols/ Libraries/        # JSON-символы и технологические библиотеки (с заглавных букв)
examples/
archicture/                  # этот документ, схемы (diagrams/release — канон)
pyproject.toml README.md environment.yml .gitignore
```

---

## 5. Ядро моделирования

### 5.1 Контракт прибора (основа всего ядра)

```python
# rcad/core/devices/base.py  (эскиз, не финальный код)
@dataclass(frozen=True)
class ParamSpec:
    name: str
    kind: Literal["real", "int", "choice"]
    default: float
    unit: str | None
    bounds: tuple[float, float] | None   # из "from (0:inf)"
    description_ru: str
    description_en: str

class DeviceModel(Protocol):
    name: str
    terminals: tuple[str, ...]           # ("D","G","S","B")
    params: tuple[ParamSpec, ...]
    n_states: int                        # внутренние SV

    def stamp_static(self, v, p, t, out: StaticStamps) -> None: ...   # i_el, G = ∂i/∂v
    def stamp_dynamic(self, v, p, t, out: DynamicStamps) -> None: ... # q_el, C = ∂q/∂v
    def eval_state(self, v, p, x, out: StateDerivs) -> None: ...      # dx/dt = f(...)

@dataclass
class StaticStamps:
    i: np.ndarray          # (n_terminals,) резистивные токи
    g: np.ndarray          # (n,n) аналитический Якобиан
```

- **Примитивы** R/C/L/V/I/E/G/F/H реализуют тот же протокол; источник напряжения даёт вклад в MNA-расширение (доп. неизвестное — ток ветви).
- **Verilog-A модели** — объект `VaDevice` поверх `VaModel` из `rcad.abi`: `ctypes`-вызов `va_eval_static/dynamic/state` в буферы NumPy (`np.ctypeslib`), ошибка ≠ 0 → `VaRuntimeError` (граница DLL защищена от исключений).
- **Регистр моделей** `registry.py`: имя → класс модели, по имени `.model` в netlist и по `master_cell` символа в UI. `ModelManager` дополняет регистр импортированными VA-моделями.

### 5.2 Сборка MNA и Якобиан

| Шаг | Что делает | Где |
|---|---|---|
| 1. Компиляция схемы | Разворачивание subckt, назначение глобальных номеров узлов (`X1.Xmem.top`), сборка `NodeIndex`, проверка ERC-lite и сингулярности | `circuit/flatten.py`, `mna/structure.py` |
| 2. Шаблон структуры | Однократная сборка `csr_indptr/csr_indices` и списка «строчных вкладов» приборов (кто куда пишет) | `mna/structure.py` |
| 3. Численная сборка | На каждой итерации обнуление `data`, вызовы `stamp_*`, `gmin` по диагонали | `mna/system.py` |
| 4. Якобиан | `J = ∂i/∂v + (1/Δt·α)·∂q/∂v` для текущего шага интегрирования; вклад SV — прямо в диагональ виртуальных узлов | `solver/newton.py` |
| 5. Решение | `splu(A)`; численная факторизация повторно используется при неизменном Якобиане | `solver/newton.py` |

Требование AD-04 проверяется тестом `FR-DEV-003` (сверка с центральными разностями `h = 1e-8·max(|v|,1)`, точность 1e-6) для каждой встроенной модели в `tests/unit/test_jacobian_*.py`.

### 5.3 Решатель и стратегии устойчивости

Порядок применения (ТЗ п. 7.4, `FR-SOLVE-004…008`):

1. Ньютон–Рафсон, критерий `|Δx| ≤ reltol·|x| + abstol` (напряжения — `vntol`), максимум 100 итераций.
2. При расходимости — `gmin`-stepping (1e-3 → 1e-6 → 1e-9 → 1e-12 См), демпфирование `λ: 1 → 0.1`.
3. Для DC/OP — source stepping, затем pseudo-transient (временный интегратор до установления).
4. Исчерпание — `ConvergenceError` с именем узла максимальной невязки (код + узел + итерация).

### 5.4 Интегрирование по времени

| Метод | Роль | Формула дискретизации (`d/dt·q`) |
|---|---|---|
| BDF1 | Старт, резерв, обработка разрывов | `q(x_k) − q(x_{k−1})` / `Δt` |
| TRAP | По умолчанию | `2·(q_k − q_{k−1})/Δt − (dq/dt)_{k−1}` |
| BDF2 | Could (`FR-TRAN-003`) | 3-точечная формула, включается при звоне TRAP |

- SV интегрируются **той же** формулой, что и заряды (`FR-SV-002`) — `x` входит в вектор `q` как «заряд» виртуального узла.
- Контроль шага — LTE: шаг делится/удваивается; `maxstep` по умолчанию `(tstop − tstart)/100`; `minstep` — нижняя граница.
- Точки разрыва (`PULSE`/`PWL`) передаются интегратору как «обязательные» временные метки: шаг усекается так, чтобы попасть в фронт точно (`T14`, допуск 1e-12 с), после фронта — перезапуск BDF1.
- Результат — `Result` с исходными точками интегрирования и линейной интерполяцией для просмотрщика.

### 5.5 Анализы и `Result`

```python
AnalysisSpec = OpSpec | DcSpec | TranSpec | AcSpec   # pydantic, дискриминатор по type
Result: ряды (name, unit, complex?) + ось (sweep/time/freq) + метаданные (спека, версия, диаграмма)
```

`run_analysis(circuit, spec) -> Result` — единственная точка входа для UI, CLI и тестов (`NFR-TST-001`). UI вызывает её через `SimulatorService`, который запускает расчёт в `QThread` и передаёт прогресс/диагностики сигналами — без `Qt` в ядре.

---

## 6. Библиотека приборов

| Прибор | Модуль | Терминалы | SV | Якобиан | Эталон |
|---|---|---|---|---|---|
| MOSFET (n/p), Shichman-Hodges + body effect + λ + `ISUB` | `devices/mos.py` | D,G,S,B | — | аналитический, по областям с плавными переходами | T4, golden |
| Мемристор M1 Yakopcic | `devices/memristor_yakopcic.py` | ±, опц. SV-узел | `x∈[0,1]` | аналитический (`G(V)`, `F(V,x)`, `sinh`) | T5, T6, T13 |
| Мемристор M2 линейный дрейф | `devices/memristor_linear.py` | ± | `x∈[0,1]` | аналитический | golden |
| Мемристор M3 VTEAM | `examples/.../vteam.va` | ± | `w` | из транслятора VA | S2 |
| Мемтранзистор GEM | `devices/memtransistor_gem.py` | D,G,S | `w∈[w_off,w_on]` | аналитический, ветви по `vgs` | T7 |
| Нейристор N1 (volatile TS) | `devices/neuristor_n1.py` | ± | `s` + таймер | сигмоида шириной `V_smooth` (непрерывна) | T8 |
| Нейристор N2 (гистерезисная) | `devices/neuristor_n2.py` | ± | `s∈[0,1]` | аналитический | T8 |
| Примитивы R,C,L,V,I,E,G,F,H | `core/devices/primitives/` | по типу | — | точный | T1–T3, T14 |

Единый шаблон модуля модели: `ParamSpec`-таблица (13 параметров у MOSFET/M1, 16 у GEM и т.д. — ровно по перечню ТЗ, `FR-MOS-006`, `FR-MEM-007`), уравнения в `stamp_*`, символ в `data/symbols/<name>.json`, эталонный netlist и golden-CSV в `tests/` / `tests/golden/`.

Ограничение состояния — **внутри модели** (в `F`, окнах `wp/wn`, `g_off/g_on` GEM); ядро SV не обрезает, а фиксирует выход за границы как `W_STATE_CLIP` в debug-режиме (`FR-DEV-008`).

---

## 7. Verilog-A: транслятор и ABI

### 7.1 Конвейер

```
my_rram.va ──lexer──► tokens ──parser──► AST ──semantics──► typed AST
      │ проверка: один module, один analog, подмножество §8.2
      ▼
codegen_cpp ──► <tmp>/my_rram.cpp ──cl.exe /LD /O2──► cache/<sha256>.dll
      │ sha256 = hash(.va + VA_ABI_VERSION + версия транслятора)
      ▼
abi.Loader (ctypes.CDLL) ──► VaModel: metadata + eval_static/dynamic/state
      │
      ▼
ModelManager: регистрация модели, авто-символ по портам, форма параметров из метаданных
```

### 7.2 C ABI (стабильный, версионируемый)

Структура и функции — в точности по ТЗ п. 8.4 (`va_model_info`, `va_eval_static`, `va_eval_dynamic`, `va_eval_state`, `va_init`, `va_get_info`, `va_get_error`, `VA_ABI_VERSION`). Архитектурные добавления к ТЗ:

- `va_get_error()` возвращает `const char*` из thread-local буфера этой модели — потокобезопасно при параллельных прогонах.
- `va_eval_*` возвращают ненулевой код; ядро не пробрасывает исключения C++ через границу DLL (`catch (...)` внутри `va_runtime`).
- `gmat`/`cmat` плотные `n×n` с аналитическими производными; `out`-буферы выделяет вызывающая сторона (`NFR-RES-002`: без утечек между прогонами).
- При несовпадении `VA_ABI_VERSION` DLL не загружается; .va перекомпилируется автоматически (кэш инвалидируется по hash).

### 7.3 Семантика `ddt`/`idt`

| Конструкция | Результат |
|---|---|
| `I(p,n) <+ ddt(e)` | вклад в `q_el`, производная `∂e/∂v` в `cmat` |
| `I(p,n) <+ idt(e)` | внутренняя переменная `dx/dt = e` (SV), уравнение невязки в ядре |
| `dt(e)` внутри `q` | ошибка трансляции (`FR-VA-SEM-002`) |
| `ddx(...)` | ошибка «not supported in MVP» с подсказкой |

Производные в codegen — символьное дифференцирование AST с вынесением общих подвыражений; при неподдерживаемой конструкции — генерация конечных разностей + warning в лог (ТЗ п. 7.2).

### 7.4 Компилятор

- Поиск `cl.exe`: настройка пользователя → `vswhere` → путь по умолчанию; отсутствие — диалог с инструкцией и кнопкой «Указать вручную» (`FR-VA-ERR-003`).
- Вызов — `subprocess` с окружением MSVC (`vcvars64.bat` разбирается однократно и кэшируется в `settings.json`), лог `cl.exe` — в `%APPDATA%/RuCadVirtuoso/logs/compile_<hash>.log`, из UI — ссылка.
- Целевое время компиляции ≤ 10 с (`FR-VA-PERF-001`), инкрементальная сборка без изменений — ≤ 10 % первичной.
- MSVC Build Tools — **опциональный шаг инсталлятора**; встроенные модели в нём не нуждаются (риск ТЗ п. 16).

---

## 8. Редактор схем (UI)

### 8.0 Qt-free UI-API

`rcad/ui/api.py` — `CanvasApi(project)` предоставляет программный контракт сцены
без PySide6 (NFR-TST-001): `canvas_state(cell)`, `place(inst, master, x, y)`,
`set_params(cell, inst, params)` (валидация через `ParamSpec` → `ParameterRangeError`),
`instance_params(cell, inst)`, `build_netlist(cell, dc/tran/ac)`. На нём исполняются
S1/S3/S4 и строятся виджеты; `tests/unit/test_layering.py` запрещает Qt-импорт в
`rcad.services` и `rcad.ui.api` (AD-01).

### 8.1 Компоненты и их зона ответственности

| Компонент | Технология | Ответственность |
|---|---|---|
| `MainWindow` | `QMainWindow`, `QDockWidget` | Раскладка: библиотека слева, сцена в центре, свойства справа, логи снизу (`NFR-UI-001`) |
| `LibraryPanel` | `QListWidget` + drag&drop | Примитивы, приборы из ModelManager; обновление после импорта (VA-секция скрыта до `rcad.veriloga`) |
| `SchematicScene` | `QGraphicsScene` / `QGraphicsView` | Инстансы, провода, порты, сетка 10 px, снаппинг, выделение, undo/redo (`QUndoStack`, ≥ 50) |
| `PropertyPanel` | `QFormLayout` + валидаторы | Имя инстанса, параметры из `ParamSpec` (тип/диапазон/единица), значения источников |
| `HierarchyNavigator` | `QTreeView`/`QTreeWidget` | Cell-иерархия, вход/выход, порты, метка «отсутствующий мастер» |
| `NetlistView` | `QPlainTextEdit` (read-only) | Текстовый netlist текущей иерархии, автообновление, экспорт/импорт (`Netlister`) |
| `AnalysisDialog` | `QDialog` | Тип анализа, развёртка (OP/DC/TRAN/AC), выбор величин: узел, ток прибора, SV `@inst.x` |
| `SimulatorService` | `QThread` + сигналы | Запуск анализа, progress/finished/failed, отмена (discard воркера; core-флаг отложен) |
| `PlotWindow` | **pyqtgraph** `GraphicsLayoutWidget` | Панели, курсор, лог-оси X/Y, экспорт PNG/CSV, несколько окон |
| `MessageLog` | `QTableView` | info/warning/error, коды, фильтр, очистка, en+ru |
| `CommandPalette`/`Shortcuts` | `QShortcut` | Ротация, зеркало, копирование, удаление, анализ, save, Ctrl+Z/Y (KBD-002 — не в полях ввода) |

### 8.2 Модель документа и undo/redo

- Документ в памяти — pydantic-модели `schemas.cell` (не «живые» объекты Qt). Сцена — её представление; любое действие пользователя — `QUndoCommand` над моделью, затем `scene.sync()`.
- Предел undo — ≥ 50 шагов (`FR-SEL-005`), хранение — снапшоты изменённых полей, а не полные копии схемы.
- Автосохранение каждые 5 мин: атомарная запись (`*.tmp` → `os.replace`) + `recovery.json`; при старте после падения — предложение восстановить (`FR-PRS-*`).
- Производительность отрисовки: перерисовка по таймеру не чаще 30 fps; при ≥ 500 инстансов антиалиасинг отключается (настраиваемо) (`NFR-PERF-UI-*`).

### 8.3 Потоки

- Расчёт — в рабочем `QThread` (`SimulatorService`), обмен только через сигналы; отмена — флаг в ядре (проверяется между шагами).
- ERC-lite (`Check`) выполняется в ядре (`circuit/erc.py`) до запуска; ошибки блокируют анализ и подсвечивают объекты на сцене.

---

## 9. Формат проекта и персистентность

```
<project>.rcad/
  project.json          # имя, версия формата, список библиотек, настройки (pydantic Project)
  cells/<cell>.json     # инстансы, координаты, поворот/зеркало, соединения, порты, свойства
  symbols/<cell>.json   # символ; отсутствует → авто-генерация по портам
  models/<name>.json    # .model-параметры встроенных моделей
  veriloga/<file>.va    # исходники
  cache/<sha256>.dll    # + <sha256>.json метаданные; в VCS не входит
  recovery.json         # автопереключение при падении; удаляется после успешного сохранения
```

- Версионирование: `format_version` в `project.json`; миграции на уровне `rcad.schemas` (по одной функции на шаг версии). Несовпадение старшей версии — отказ с диагностикой, без потери данных.
- Битый `project.json`/`cells/*.json` — диагностика с путём и полем, приложение остаётся работоспособным (`FR-PRJ-009…012`).
- Переносимость: при отсутствии `cache/` VA-модели пересобираются из `.va`; если компилятор недоступен — предупреждение с перечнем моделей (`FR-PRJ-005…008`).

---

## 10. Сквозные механизмы

### 10.1 Диагностика и логи

Единый `Diagnostic(code, severity, file, line, column, message_en, hint_ru, context)`.

- Парсер netlist/VA возвращает структуру `{file, line, column, code, message}`; при ошибке парсера симуляция не стартует, проект остаётся валидным.
- Коды — часть контракта (стабильны, `NFR-LOC-003`): `W_STATE_CLIP`, `W_DC_DISCONTINUITY`, `VA_PARAM_RANGE`, `VA_RUNTIME_ERROR`, `ConvergenceError`.
- Сообщения симулятора — английский текст + русская подсказка в UI (ТЗ п. 11).
- Логи — `logging` + `RotatingFileHandler` в `%APPDATA%/RuCadVirtuoso/logs/`, метки времени, фильтр путей пользователя и секретов (`NFR-LOG-003`).

### 10.2 Надёжность (границы перехвата)

| Граница | Как защищено |
|---|---|
| Парсер netlist / VA | Рекурсивный спуск с восстановлением, все ошибки — `Diagnostic`; никаких `assert` на пользовательских данных |
| Вызов DLL | `ctypes` в обёртке: `try/except` вокруг загрузчика, коды возврата, `va_get_error`; C++ исключения не пересекают ABI |
| Вызов анализа | `SimulatorService` перехватывает `RcadError` и любые непредвиденные исключения, помещая их в лог и диалог |
| Загрузка проекта | pydantic-валидация + миграции; частично читаемый проект открывается с диагностикой |
| Поток расчёта | отмена и таймаут шага; результат возвращается только целиком |

### 10.3 Headless API и CLI

```bash
python -m rcad.cli check   examples/crossbar_4x4/crossbar.rcad
python -m rcad.cli netlist examples/crossbar_4x4/crossbar.rcad -o crossbar.cir
python -m rcad.cli run     examples/crossbar_4x4/crossbar.rcad --analysis tran --out csv
```

Тот же путь используют интеграционные тесты S1–S4 и замеры производительности `tests/perf/` (`TRQ-ACC-001`, `NFR-PERF-*`).

---

## 11. Развёртывание

| Шаг | Инструмент | Результат |
|---|---|---|
| 1. Сборка wheel/оверхеда | `pip install .` в чистый venv | Пакет `rcad` |
| 2. Заморозка | PyInstaller, one-folder, embedded Python 3.12 | `dist/RuCadVirtuoso/` с `RuCadVirtuoso.exe` |
| 3. Инсталлятор | Inno Setup (`installer.iss`: `[Files]`, `[Icons]`, `[Run]`) | `RuCadVirtuoso-1.0-setup.exe` ≤ 350 МБ |
| 4. Опциональный шаг | Inno: загрузка/проверка MSVC Build Tools (`vswhere`) | Компилятор только для Verilog-A |
| 5. CI | GitHub Actions (`windows-latest`, headless) | Тесты + артефакты (JUnit/CSV) |

Требования: холодный старт ≤ 5 с, RAM ≤ 1 ГБ на схеме до 1000 инстансов, отсутствие внешних зависимостей у встроенных моделей.

---

## 12. Тестовая архитектура

| Уровень | Инструмент | Содержание |
|---|---|---|
| Unit | pytest + hypothesis | Парсер netlist (≥ 40 кейсов + property-based на суффиксы/выражения), AST VA, codegen, Якобиан приборов (аналитика vs `h=1e-8·max(|v|,1)`, 1e-6), интегратор на линейных цепях |
| Golden | pytest + CSV в `tests/golden/` | Сверка с ngspice/эталонным subckt, `reltol=1e-3, abstol=1e-9`; правка эталона — только с ссылкой на источник (`FR-DEV-006`) |
| Integration | pytest через `run_analysis` | S1–S4: мемристор I–V, импорт VA, LIF-нейрон, кроссбар 4×4 |
| Perf | pytest-benchmark/`time.perf_counter` | T13, OP 100 инстансов, DC 1000 точек, компиляция VA, открытие проекта |
| Layering | pytest + AST | Запрет UI-импортов ядра (`NFR-TST-002`) |
| UI smoke (Should) | pytest-qt | Запуск приложения, открытие проекта, импорт VA, запуск анализа |

Реестр T1–T15 из ТЗ п. 12.2 закрывается этими уровнями без изменения критериев и допусков.

---

## 13. Порядок реализации (по этапам ТЗ п. 15.1)

| Этап | Архитектурное содержание | Выход |
|---|---|---|
| E0 (2 нед.) | `schemas`, `diagnostics`, netlist-парсер, `circuit` (flatten), MNA-структура, `splu`, OP/DC/TRAN на линейных цепях, `run_analysis`, CLI, CI | T1–T3 зелёные |
| E1 (3 нед.) | Контракт `DeviceModel`, SV-механизм, MOSFET, M1, M2, GEM, N1, N2, primitives E/G/F/H, golden-эталоны | T4–T8, T13 |
| E2 (4 нед.) | VA lexer/parser/semantics, codegen C++, `va_runtime`, ABI + `ctypes` loader, `ModelManager`, диагностика компиляции | T9–T11 |
| E3 (3 нед.) | Scene/undo, свойства, иерархия, ERC-lite, netlist-view, диалог анализа, pyqtgraph-просмотрщик, логи | S1–S4 |
| E4 (1 нед.) | Проект/автосохранение/восстановление, авто-перекомпиляция VA, PyInstaller + Inno Setup, отчёт приёмки | MVP целиком (DoD п. 4.3) |

Параллелизм: E2 и E3 могут идти одновременно после E1 при разграничении по `ModelManager`/`SimulatorService`.

---

## 14. Риски архитектуры и их снятие

| Риск | Проявление | Архитектурная мера |
|---|---|---|
| Жёсткие уравнения мемристивных моделей | Расходимость Ньютона, звон TRAP | Сигмоиды/окна внутри моделей, BDF1-перезапуск, `maxstep`, pseudo-transient (AD-02, §5.3–5.4) |
| Производительность Python на кроссбаре | T13 > 120 с | Однократная CSR-структура, `splu`, векторизованные `stamp`, профилирование уже в E1; заменяемый бэкенд KLU (`solver/backends`) |
| Транслятор VA разрастается | E2 выходит за срок | Жёсткое подмножество §8.2 с ошибкой «not supported in MVP» вместо частичной поддержки |
| Отсутствие MSVC у пользователя | Нельзя импортировать `.va` | Встроенные модели нативные; MSVC — опциональный шаг; понятный диалог `FR-VA-ERR-003` |
| Расхождение с эталоном | «Подгонка» модели под тест | Golden-файлы с обязательной ссылкой на источник, CI-гейт (`FR-DEV-006`, `TRQ-TEST-012`) |
| Утечки и рост памяти между прогонами | `NFR-RES-002` | `Result` неизменяем, буферы DLL переиспользуются на прогон, факторизация освобождается с анализатором |

---

## 15. Открытые вопросы, влияющие на архитектуру

Все пять вопросов ТЗ п. 17 остаются за заказчиком; архитектура их переживает без переделки ядра:

| OQ | Влияние на архитектуру, если ответ «да» |
|---|---|
| OQ-001 (SPICE-netlist как контракт) | Добавляется режим импорта в `core/netlist` (без смены AST) |
| OQ-002 (BSIM4 через OSDI/OpenVAF) | `rcad/abi` получает второй загрузчик OSDI; `DeviceModel`-контракт не меняется |
| OQ-003 (`$limit`/`bound_step`) | Новый интерфейс «модель → ограничение шага» в интеграторе (`integ/limits.py`) |
| OQ-004 (тепловая подмодель нейристора) | Дополнительный SV + параметры в моделях N1/N2; ядро не меняется |
| OQ-005 (уровень MOSFET) | Замена модуля `devices/mos.py`; контракт и T4-эталон переписываются |
