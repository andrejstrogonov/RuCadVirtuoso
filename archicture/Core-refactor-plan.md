# План улучшения архитектуры RuCadVirtuoso: ядро симуляции (core-first)

## 1. Цель и границы

Привести фактический код к целевой архитектуре `ARCH_MVP_schematic.md`
(AD-01…AD-09) в части, необходимой для headless-запуска обязательного тест-набора
T1–T15 и сценариев S1–S4 (ТЗ п. 12.2). Охват фазы — **только ядро**:

- Реализуется: `rcad.core.*` (netlist → flatten/hierarchy → MNA → solver → integ → analyses),
  `rcad.devices` (контракт `DeviceModel` + встроенные модели + registry),
  `rcad.diagnostics`, расширение `rcad.schemas`, тестовая инфраструктура.
- Не реализуется (остаются skipped): Verilog-A конвейер (`rcad.veriloga`, `rcad.abi`,
  T9–T11, S2), services (`rcad.services`, S1/S3/S4), UI (`rcad.ui`, CanvasApi), CLI/упаковка.

Решение пользователя: **ядро в первую очередь**, старый код **заменить и удалить**.

## 2. Текущее состояние (результаты аудита)

| Факт | Проявление | Следствие |
|---|---|---|
| Код не соответствует документированной архитектуре | `../src/rcad/device.py`, `circuit.py`, `analyzer.py` — плоский API `iv_curve/evaluate_pulses/update_spiking_state`, `solve_kirchhoff` с фиксированным демпфированием 0.1, без MNA/Jacobian/charge-flux | Противоречит AD-02…AD-05; не может дать численно достоверный результат (цель №1 ARCH) |
| Тесты T1–T15, S1–S4 все пропускаются | `conftest.requires_core` ждёт `rcad.core.analyses`; модуля нет | Обязательный набор не исполняется; единственный зелёный — `../tests/unit/test_symbols.py` |
| Контракт тестов иной, чем у текущего кода | Тесты: `run_analysis(netlist: str, directive: str) -> Result` из `rcad.core.analyses`; `precheck`, `AnalysisError`, `flatten`, `parse`, `NetlistError`, `rcad.devices.registry`, `rcad.services.*`, `rcad.veriloga`, `rcad.ui.api` | Старый код несовместим и не используется (проверено grep: никто не импортирует `rcad.device/circuit/analyzer`) |
| Отсутствуют данные, на которые ссылаются тесты | `tests/golden/` (t04_mosfet_output.csv, t05_memristor_iv.csv), `examples/va_custom_model/*.va`, `data/models/*.lib` (`memristor_yakopcic.lib`, `memtransistor_gem.lib`, `neuristor_n1/n2.lib`) | Парсинг `.include` и golden-сверки упадут |
| Несоответствия в реестре тестов | `../tests/cases.py`: T13 → `tests/integration/test_t13_crossbar.py`, реальный файл `tests/perf/`; упомянут несуществующий `tests/unit/test_trace.py` | Реестр недостоверен |
| Нет упаковки | нет `pyproject.toml`; `../src/main.py` пуст; нет `rcad/cli.py` | `pip install .` и entry point не работают (вне фазы, но scaffolding нужен) |
| `../src/rcad/__init__.py` объявляет `__all__` из удаляемых модулей | `["device", "circuit", "analyzer"]` | Обновить при переходе |
| В сообщениях лог нет единой диагностики | нет пакета `rcad.diagnostics` | T15 требует `Diagnostic(code, object_name)`; `AnalysisError`, `NetlistError`, `ParameterRangeError` импортируются тестами |

## 3. Зафиксированные архитектурные решения фазы

1. **Контракт `DeviceModel` по AD-03**: `stamp_static(v,p,t,out)`, `stamp_dynamic(...)`,
   `eval_state(...)` + метаданные (`terminals`, `params: ParamSpec`, `n_states`).
   Встроенные модели — **аналитический Якобиан** (AD-04), проверка в unit-тестах
   центральными разностями `h=1e-8·max(|v|,1)`, допуск 1e-6.
2. **Состояние DAE в форме charge/flux** (AD-02): `f = d/dt·q(x) + i(x) + u = 0`;
   SV — «заряд» виртуальных узлов, интегрируются той же формулой, что и `q`.
3. **Разреженная структура собирается однократно** (AD-05): CSR-шаблон +
   `scipy.sparse.linalg.splu` (COLAMD), числовая сборка на каждой итерации.
4. **Единая точка входа**: `rcad.core.analyses.run_analysis(netlist: str, directive: str) -> Result`;
   `precheck(netlist)` — ERC-lite до решения. Тип анализа определяется директивой
   netlist (`.op/ .dc/ .tran/ .ac`); внутри — дискриминированные pydantic-спеки.
5. **`Result`**: массивы NumPy (complex для AC) + метаданные; `report` dict
   (в т.ч. `step_rejections`), API из §5 ниже.
6. **`X`-карточки с именем модели** разрешаются через `rcad.devices.registry`
   (встроенные модели) или `.subckt` (flatten); `.include "models/*.lib"` парсится,
   поиск: каталог netlist → CWD (корень репозитория при прогоне тестов) → `data/models/`.
7. **Порог точности тестов — контракт**: reltol=1e-3, abstol=1e-9 (conftest `close`);
   OP T1 — 1e-12; шаг не перескакивает фронт (T14, 1e-12 с); default `maxstep=(tstop-tstart)/100`.
8. **Серверы/UI/Verilog-A выносятся за фазу**: их тесты получают отдельные skip-маркеры,
   чтобы при появлении core они падали не «всеми функциями», а чистым skip.

## 4. Целевая структура пакета (после фазы)

```
src/rcad/
  __init__.py              # версия; __all__ = core/devices/schemas/diagnostics
  diagnostics/             # Diagnostic, DiagnosticBag, RcadError, NetlistError,
                           # AnalysisError, ParameterRangeError; стабильные коды
  schemas/                 # + analysis.py, project.py, cell.py, model.py, result.py
  core/
    netlist/               # tokens, lexer, suffix (1k/1u/1m/2p), parser, ast,
                           # .include (цикл-детект), .model/.subckt/.end, directive
    circuit/               # flatten (subckt → плоское), NodeIndex, InstanceIndex,
                           # имена путей "X1.X2.mid", erc (floating / no-DC-path)
    mna/                   # structure.py (CSR-шаблон), system.py (F/J, stamping, gmin)
    solver/                # newton, damping, gmin-stepping, source-stepping
    integ/                 # bdf1, trap, lte, breakpoints (PULSE/PWL), .ic, maxstep
    analyses/              # op, dc_sweep, tran, ac, runner, precheck, run_analysis
    devices/               # base.py (DeviceModel, ParamSpec), primitives/ (R,C,L,V,I,E,G,F,H)
  devices/                 # registry.py; mos.py, memristor_yakopcic.py, memristor_linear.py,
                           # memtransistor_gem.py, neuristor_n1.py, neuristor_n2.py
src/main.py                # не трогаем в фазе (остаётся пустым)
tests/
  unit/ test_symbols.py test_layering.py test_trace.py test_jacobian_*.py
  integration/ test_t01…t08, t12, t14, t15 (исполняются)  t09–t11 (VA, skip)
               test_s1, s3, s4 (services, skip)  s2 (VA, skip)
  perf/ test_t13_crossbar.py (исполняется, T13 ≤ 120 с)
  golden/ t04_mosfet_output.csv t05_memristor_iv.csv
data/models/ memristor_yakopcic.lib memtransistor_gem.lib neuristor_n1.lib neuristor_n2.lib
pyproject.toml               # src-layout, deps, ruff/mypy/pytest конфиг
```

## 5. Контракт API (обязательный для исполнителя)

```python
# rcad/core/analyses.py — главный вход
def run_analysis(netlist: str, directive: str, *, include_paths=...) -> Result
def precheck(netlist: str) -> None            # кидает AnalysisError
class AnalysisError(RcadError):
    diagnostic: Diagnostic                     # .code, .object_name, .line, .hint_ru

# Result
result["V(in)"] / result["@Xmem.x"] / result["I(V1)"] / result["V(out)"]  # серия
result["time"] / result["freq"]
result.names() -> list[str]                    # все ряды
result.names_minus_time() -> list[str]
result.node("mid") -> float | list[float]      # OP — скаляр; DC/TRAN — ряд
result.branch("V1") -> float | list[float]     # ток ветви источника
result.element("R1", "i") / result.element("M1", "id") / result.element("X1", "i")
result.report["step_rejections"]               # int (T8: == 0)
# AC: серии комплексные (cmath.isclose), 41 точка для `dec 10 1k 10meg`

# rcad/core/netlist/__init__.py
def parse(text: str, *, include_paths=...) -> Document   # кидает NetlistError

# rcad/core/circuit/__init__.py
def flatten(text: str) -> FlatCircuit          # .node_names (имена путей иерархии)

# rcad/diagnostics
Diagnostic(code, severity, message, hint_ru, file, line, column, object_name)
NetlistError; AnalysisError(diagnostic); ParameterRangeError

# rcad/devices/registry.py
registry.names() -> list[str]; registry.symbol_for(name)
```

## 6. Задачи (упорядоченно; каждая — с критерием приёмки)

### Этап 0 — Тестовая инфраструктура и данные
1. `../tests/cases.py`: исправить путь T13 → `tests/perf/test_t13_crossbar.py`.
2. `tests/unit/test_trace.py` (по docstring cases.py): каждый ID реестра `pytest`-маркирован
   `tcase` в указанном файле и файл существует. Приёмка: тест зелёный.
3. `../tests/conftest.py`: добавить `requires_va` (find_spec `rcad.veriloga`),
   `requires_services` (`rcad.services`), `requires_ui` (`rcad.ui`); `requires_core` оставить.
4. Проставить маркеры вне фазы: T9/T10/T11/S2 → `requires_va` (+`requires_core`, где нужен);
   S1/S3/S4 → `requires_services` (+`requires_core`/`requires_ui` по использованию).
   Приёмка: после появления core in-scope тесты бегут, out-of-scope — чистый skip с reason.
5. `data/models/*.lib`: `memristor_yakopcic.lib`, `memtransistor_gem.lib`,
   `neuristor_n1.lib`, `neuristor_n2.lib` — поясняющие комментарии (модель резолвится
   через registry); файлы обязаны парситься и существовать.
6. Golden-файлы `tests/golden/` — **после** подтверждения моделей аналитикой
   (см. Risк G): `t04_mosfet_output.csv` (id(V) выходной характеристики, точка sat),
   `t05_memristor_iv.csv` (time, i, x; 2001 строка). Ссылка на источник в шапке
   (FR-DEV-006). Приёмка: тесты T4-golden, T5-golden, T13 проходят на замороженном файле.
7. `tests/unit/test_layering.py` (ARCH «Правила зависимостей»): AST-проверка — `rcad.core.*`,
   `rcad.devices`, `rcad.diagnostics`, `rcad.schemas` не импортируют PySide6/pyqtgraph/rcad.ui;
   `rcad.core.*` не импортирует `rcad.devices` верхнего уровня (registry может импортировать core.devices).

### Этап 1 — Scaffolding
8. Папки пакета §4 с `__init__.py`; обновить `../src/rcad/__init__.py`
   (убрать `device/circuit/analyzer` из `__all__`).
9. `pyproject.toml`: src-layout, зависимости runtime (numpy≥2.0, scipy≥1.13, pydantic≥2.7),
   dev (pytest, hypothesis, ruff, mypy), конфиг ruff/mypy/pytest. Приёмка: `pip install -e .[dev]`
   и `pytest` работают из корня.
10. Удалить `../src/rcad/device.py`, `circuit.py`, `analyzer.py` (и `__pycache__`) **после**
    переноса уравнений в задачи 14–15.

### Этап 2 — Диагностика
11. `rcad/diagnostics`: `Diagnostic` (коды — контракт: `E_FLOATING`, `E_NO_DC_PATH`,
    `VA_*` (резерв), `W_STATE_CLIP`, `ConvergenceError`), `DiagnosticBag`, исключения.
    Приёмка: `../tests/integration/test_t15_floating_node.py` (после этапа 5/7) — codes и
    `object_name == "float"/"island"`.

### Этап 3 — Core: netlist
12. `rcad/core/netlist`: лексер + рекурсивный спуск. Карты R,C,L,V,I,E,G,F,H,M,X;
    `.model` (параметры MOSFET), `.subckt`/`.ends` (циклы → `NetlistError`),
    `.include` (рекурсия, цикл-детект), `.op/.dc/.tran/.ac`, `.end`,
    `.ic V(x)=...`, блочный суффикс (`1k/1u/1n/1m/2p/1meg`), параметры `name=value`,
    продолжение строк `+`. Приёмка: `parse` валидных netlists из T1–T8, T12–T15, S4-шаблонов;
    невалидные — `NetlistError`; unit-тесты суффиксов + hypothesis.
13. Кодировка/числовая проверка суффиксов в отдельном модуле (`suffix.py`, чистые функции).

### Этап 4 — Core: flatten/hierarchy
14. `rcad/core/circuit/flatten.py`: развёртывание `.subckt` → плоский netlist с путями
    `X1.X2.mid`; `NodeIndex`/`InstanceIndex`; ERC-lite: одиночное подключение узла →
    `E_FLOATING` (`object_name` = имя узла), отсутствие резистивного пути к узлу 0 →
    `E_NO_DC_PATH` (поиск достижимости). Приёмка: `test_t12_subckt_hierarchy.py`,
    `test_t15_floating_node.py`.

### Этап 5 — Core: контракт приборов и модели
15. `rcad/core/devices/base.py`: `ParamSpec(kind, default, bounds, ...)`, `DeviceModel`
    Protocol по AD-03, `StaticStamps(i, g)`, `DynamicStamps(q, c)`, `StateDerivs`;
    `primitives/`: R,C,L,V,I,E,G,F,H (V/I расширяют MNA — ток ветви как неизвестная).
16. `rcad/devices/`: `registry.py` (+`symbol_for`), модели по ARCH §6 таблице с **точными**
    уравнениями тестов: `mos.py` (Shichman–Hodges + body effect `VTO+GAMMA·(√(PHI+VSB)−√PHI)`,
    λ, p-канал зеркально; аналитика T4), `memristor_yakopcic.py`
    (`I = a1·x·sinh(b·V)` при V≥0, `a2` при V<0 — T5-FR-MEM-006; порог |V|<Vp/Vn — T6;
    окно-функции, `x∈[0,1]`, clip с `W_STATE_CLIP`), `memristor_linear.py`,
    `memtransistor_gem.py` (T7: ступени w, `I(VD)`, ток затвора 0), `neuristor_n1.py`/`n2.py`
    (T8: спайки, монотонность f(I), без chattering). Параметры из `../tests/unit/test_symbols.py`
    REQUIRED_PARAMS и из `data/Libraries/*.json`.
17. Unit: `tests/unit/test_jacobian_*.py` для каждой модели — аналитика vs центральные
    разности (`h=1e-8·max(|v|,1)`, допуск 1e-6). Приёмка: зелёные.

### Этап 6 — Core: MNA, решатель, интегратор
18. `rcad/core/mna`: `structure.py` — однократный CSR-шаблон по списку вкладов;
    `system.py` — сборка `F`, `J = ∂i/∂v + α·∂q/∂v` (вклад SV в виртуальные узлы), `gmin`.
19. `rcad/core/solver`: Ньютон (≤100), критерий `|Δx| ≤ reltol·|x| + abstol` (напряжения —
    vntol); демпфирование λ: 1→0.1; `gmin`-stepping (1e-3→…→1e-12); для DC — source-stepping;
    при исчерпании — `ConvergenceError` с узлом max-невязки.
20. `rcad/core/integ`: BDF1 (старт) + TRAP (далее); контроль шага по LTE (деление/удвоение);
    `maxstep` default `(tstop−tstart)/100` (T2, FR-TRAN-005), `minstep`; точки разрыва
    PULSE/PWL — обязательные метки: усечение шага до фронта в 1e-12 с (T14), BDF1-рестарт
    после фронта; `step_rejections` в `report` (T8).
21. Приёмка по аналитике (не по тестам): RC-заряд, делитель — до тестов.

### Этап 7 — Core: analyses, Result, run_analysis
22. `rcad/core/analyses/`: `op` (все режимы, глоб. узлы 0 — опора), `dc_sweep` (одна/две
    развёртки? ТЗ — одна; SV при DC фиксирован — T6), `tran`, `ac` (dec/lin/oct, complex),
    `runner` (дискриминация по директиве), `precheck`.
23. `Result` по §5: series numpy (complex для AC), `__getitem__`, `names`,
    `names_minus_time`, `node`, `branch`, `element`, `report`, метаданные.
    Согласовать семантику `element()` (см. Решение R1).
24. «Поворот выключателя»: модуль `rcad.core.analyses` существует → `requires_core`
    снимает skip с T1–T8, T12, T14, T15, T13.

### Этап 8 — Сверка и доводка
25. Прогнать `pytest tests/unit tests/integration -m "not perf"`:
    зелёные unit (symbols, trace, layering, jacobian) + T1–T8, T12, T14, T15;
    skip T9–T11, S1–S4.
26. Perf: `pytest tests/perf/test_t13_crossbar.py` — T13 ≤ 120 с, SV в [0,1], непрерывны.
    При провале — векторизация stamp/через CSR, замер распределения времени
    (AD-05; резерв — смена бэкенда в `solver/backends`).
27. `ruff check src` и `mypy src` — без ошибок; включить проверку слоёв из задачи 7.

## 7. Определение готовности фазы

- Зелёные: `tests/unit/*`, `tests/integration/test_t{01..08,12,14,15}`,
  `tests/integration/test_s1,s3,s4` — **skip** (services/UI), `s2`, `t09–t11` — **skip** (VA);
  `../tests/perf/test_t13_crossbar.py` — зелёный в бюджете 120 с.
- `cases.py` / `test_trace.py` согласованы; данные `tests/golden/`, `data/models/` в VCS.
- `pip install -e .` из корня работает; `ruff`/`mypy` чисты; `main.py` не задействован.
- Старые модули `device.py/circuit.py/analyzer.py` удалены; `__init__.__all__` корректен.

## 8. Риски и решения для исполнителя (требуют внимания)

- **R1 (семантика `element` при .dc)**. `test_t04.region_current` берёт
  `abs(result.element("M1","id"))` как скаляр, а `test_t04_golden` итерирует
  «element("M1","id")» как ряд. Рекомендация: `element()` возвращает ряд (скаляр для OP/
  одиночной точки); тест region_current приводится к ряду — берётся значение в строке
  sweep-сетки, где `V(g) == номинал региона` (0.2/1.8 лежат в сетке .dc VG 0 3.3 0.01).
  Правка теста — минимальная и задокументированная в коммите.
- **G (golden chicken-and-egg)**. `t05_memristor_iv.csv` и `t04_mosfet_output.csv`
  создаются собственным прогоном **после** подтверждения моделей независимой аналитикой
  (уравнения внутри тестов T5/FR-MEM-006 и формулы T4); файл замораживается, правка —
  только с ссылкой на источник (FR-DEV-006).
- **`.include` в тестах**. Прогон pytest из корня репозитория; резолвер ищет
  `models/*.lib` в CWD, затем в `data/models`. `S4` использует `crossbar4.dummy` (skip-тест,
  но `parse`/`flatten` не должны падать на его .include — обеспечивается этапом 3).
- **T2 и T14 против maxstep**. Default `maxstep=(tstop−tstart)/100` (5m/100=50u для T14,
  10u/100=1e-7 для T2) сильнее tstep → интегратор адаптивный; обязательны breakpoints
  PULSE/PWL в сетке результата (1e-12 с).
- **T2 «первая точка = 0»**: `.ic V(out)=0` и старт из OP; первая точка ряда времени — t=0.
- **T8 `report.step_rejections == 0`**: спайк должен обрабатываться шагом, а не откатами;
  фронты PULSE как явные breakpoint'ы.
- **Потеря чисел из старого кода**: уравнения GEM/нейристора/мемристора переносятся из
  `device.py` (источник параметров), но приводятся к контракту `stamp_*` и уравнениям тестов
  (мемристор — SINH, не `V/R`).

## 9. Вне охвата фазы (маркеры уже подготовлены)

- Verilog-A: `rcad.veriloga`, `rcad.abi`, codegen C++, cl.exe, ABI (T9–T11, S2).
- Services/UI: `rcad.services`, `rcad.ui` (S1, S3, S4); CLI `rcad/cli.py`
  (после фазы — привязка к `run_analysis`); PyInstaller/Inno (E4); миграции `schemas`
  (нужны на E4). `../src/main.py` остаётся пустым.
- BSIM4/OpenVAF, KLU-бэкенд (резерв AD-05), `integ/limits.py` (OQ-003).

## 10. Порядок валидации

1. `pip install -e .[dev]` с `../environment.yml`/venv (python 3.12).
2. `pytest tests/unit -m "not perf"` — unit-слой.
3. `pytest tests/integration -m "not perf"` — T1–T8, T12, T14, T15 зелёные; skip-список T9–T11/S1–S4.
4. `pytest tests/perf/test_t13_crossbar.py` — бюджет 120 с.
5. `ruff check src tests && mypy src`.
6. Подтверждённые golden-файлы в VCS; `git status` без `__pycache__`.
