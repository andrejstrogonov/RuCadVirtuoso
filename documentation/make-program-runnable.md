# Сделать RuCadVirtuoso запускаемым: анализ ошибок и план исправлений

## 1. Цель

Довести репозиторий до состояния, когда **всё** рабочее:

- `python src/main.py` (и `python -m rcad`) открывает GUI;
- `python -m rcad.cli check/netlist/run/export` работает;
- headless-набор проходит: T1–T8, T12, T14, T15 + сценарии S1/S3/S4
  (T9–T11, S2 остаются skip — нет `rcad.veriloga`), T13 в бюджете 120 с.

Контекст: ядро и сервисы уже написаны (коммит `b54c149 "Added core"`), но содержат
функциональные ошибки, из-за которых падают обязательные тесты и не стартует GUI.

## 2. Выявленные ошибки (по результатам статического аудита)

| # | Файл | Ошибка | Эффект |
|---|---|---|---|
| E1 | `../src/rcad/core/analyses.py` (пустой файл) + `_write_analyses.py` (генератор) | Пустой `analyses.py` конфликтует с пакетом `analyses/`; генератор перезаписывает его | Хрупкий импорт `rcad.core.analyses`; мусор в VCS |
| E2 | `../src/rcad/core/circuit/flatten.py` | X-карточки, ссылающиеся на **device-**подсхемы из `.lib` (memristor_yakopcic и т.п.), разворачиваются в их тело (пустое или `B1 …` → `device_for('B')` → ValueError) | T5/T6/T7/T8, S1/S4, T13 падают ещё до расчёта |
| E3 | `../src/rcad/core/devices/mna_devices.py` | `_sin`/`_pulse` разбирают `SIN(...)`/`PULSE(...)` с обёрткой: `SIN(0 1 1)` → `['SIN(0','1','1)']` → freq=0; `per` PULSE=0 → источник постоянный | T5–T8, T14, S1/S3/S4, T13 не моделируются |
| E4 | там же + `../src/rcad/core/netlist/__init__.py` | `_parse_source_params` не понимает `DC=0`/`AC=1` (ключ=значение), только `DC 0`; `key=value` из netlister теряется | DC/AC-источники генерируют 0 |
| E5 | там же | `GEMPMemtransistor.__init__` и др.: `float(self.params.get("r_on"))` на строке `'1k'` → ValueError | T7 падает на создании прибора |
| E6 | `../src/rcad/core/analyses/run.py` | Соглашение имён рядов Result ≠ контракт: для элемента пишется `Xmem.x`, а тесты и netlister ждут `@Xmem.x`; ток элемента (`I(Xmem)`) не генерируется | KeyError в T5–T8, S1/S3/S4, T13 |
| E7 | там же `_run_dc` | id МОП-транзистора берётся из свежесозданного `MOSFET(el.params)` без `.model` и без решения → `element("M1","id")==0` | T4 не проходит |
| E8 | там же `_run_ac` | Источник не получает AC-амплитуду (stamped `DC`), RHS нулевой; ёмкость-спутник вместо `jωC` | T3 не проходит |
| E9 | `../src/rcad/core/diagnostics_utils.py` | Нет E_NO_DC_PATH (резистивная достижимость земли) | `test_t15.test_no_ground_path_is_reported` падает |
| E10 | `../src/main.py` + pyproject | GUI запускается только с `--project`; нет `--gui`/default GUI; нет `rcad/__main__.py`; нет `[project.scripts]` | `python src/main.py` печатает help и выходит |
| E11 | `tests/golden/`, `examples/` | Нет `t04_mosfet_output.csv`, `t05_memristor_iv.csv` | T4-golden/T5-golden падают (FileNotFound) |
| E12 | `../tests/cases.py` | T13 указывает на `tests/integration/test_t13_crossbar.py`, фактический — `../tests/perf` | Реестр недостоверен (не блокирует запуск) |
| E13 | `core/services` слои | `flatten.py` импортирует `rcad.services.model_manager` (core→services) и читает `.lib` как `utf-8` (возможен BOM) | нарушение слоёв (не тестируется статикой), падение чтения при BOM |

## 3. Что НЕ трогаем (вне охвата)

- Verilog-A (`rcad.veriloga`, `rcad.abi`, compiler cl.exe) — T9–T11, S2 остаются skip.
- Рефакторинг legacy `device.py/circuit.py/analyzer.py` (исключены из линта и не импортируются).
- Внедрение разреженной MNA/KLU (AD-05) — при условии, что T13 укладывается в 120 с.

## 4. Задачи (порядок важен)

### T1. Очистка пакета core.analyses
- Удалить `../src/rcad/core/analyses.py` (пустой) и `src/rcad/core/_write_analyses.py`.
- Оставить пакет `../src/rcad/core/analyses` (реальный код в `run.py`).
- Приёмка: `import rcad.core.analyses` даёт `run_analysis/precheck/Result/AnalysisError`.

### T2. Flatten: не разворачивать device-подсхемы
- В `flatten_netlist` разделить subsckts на «inline (проектные)» и «загруженные из `.include`-библиотек» (например, отдельное множество `lib_subckts`).
- X-карточку разворачивать **только** если модель — inline/project-подсхема (T12, S4 `mem_cell`).
- X с именем модели из библиотеки/реестра устройств оставить элементом `X` → `device_for` создаст Yakopcic/GEM/Neuristor.
- Безопасно читать `.lib`: `read_text(encoding="utf-8-sig")`.
- Приёмка: T5/T7/T8/S4/T13 больше не падают с `ValueError: неподдерживаемая карта прибора: B`; T12 по-прежнему разворачивает 3 уровня.

### T3. Источники: корректный разбор функций и key=value
- `VoltageSource`/`CurrentSource` (`mna_devices.py`): в `_parse_numbers` снимать обёртку `FUNC(...)` (до `(` и после `)`), разбирать параметры SIN/PULSE/PWL/EXP/SFFM/AM; `per=0` → периодический расчёт по модели.
- `_parse_source_params` в `core/netlist`: принимать и `DC 0`, и `DC=0`, `AC=1`, `SIN(...)` как один токен.
- Приёмка: unit-проверка `VoltageSource(SIN(0 1 1))._value_at(t)` даёт sin-форму; PULSE коммутирует; memristor T5 образует петлю.

### T4. Устойчивые параметры приборов
- Во всех устройствах (`MOSFET`, `YakopcicMemristor`, `GEMPMemtransistor`, `NeuristorN1/N2`) читать параметры через `suffix_float` (или `float` после нормализации), не падать на `'1k'`, `'2p'`, `10n`.
- Приёмка: T7 (r_on=1k, C_par=2p) создаёт прибор без ValueError.

### T5. Контракт имён рядов Result
- в `Result` (и `_run_tran`/`_run_dc`/`_run_op`/`_run_ac`):
  - элемент-параметр → `@<inst>.<port>` (например `@Xmem.x`, `@XMT.w`);
  - ток через элемент/V-ветвь → `I(<inst>)` (например `I(V1)`, `I(Xmem)`, `I(VD)`);
  - узел → `V(<node>)`; время → `time`; частота → `freq`.
- `element(name, port)` возвращает ряд (скаляр/список) по `(name, port)`, как сейчас; поиск по ключам серий обобщается.
- Приёмка: `result["@Xmem.x"]`, `result["I(Xmem)"]`, `result["V(top)"]`, `result["time"]` — в `names()`.

### T6. OP/DC-TRAN-AC: расчёт величин
- `_run_op`: для всех карт заполнять element-токи/параметры (R: `i`, M: `id`, X: `i`/`x`).
- `_run_dc`: для M брать ток из **решения** слиянием `lookup_model_params` + `el.params` (а не из unstamped-копии); заполнять ряды `@name.*`/`I(name)` по каждой точке развёртки.
- `_run_ac`: строить комплексную систему корректно — применять AC-амплитуду источника из `params['AC']`, ёмкость/индуктивность как `jωC`/`1/(jωL)` **без** спутник-компаньона, выход комплексный.
- Приёмка: T1–T4, T3 (резонанс ±1 %, Q ±2 %), T4-golden.

### T7. ERC: E_NO_DC_PATH
- `precheck_erc`: после проверки висящих узлов — поиск резистивной достижимости до узла `0` (R/M — резистивные; C/L/источники — нет). Недостижимый узел → `AnalysisError(E_NO_DC_PATH, object_name=<node>)`.
- Приёмка: T15 (E_FLOATING с `object_name=="float"`, E_NO_DC_PATH с `"island"`, валидный netlist без ошибок).

### T8. Точки запуска (GUI/CLI)
- `../src/main.py`: default — GUI (`create_app()` + `MainWindow()` и `show()`), флаги `--gui` (явно), `--cli`, `--headless`, `--project`. Без аргументов открывать окно.
- Добавить `src/rcad/__main__.py` → `from rcad.cli import main; raise SystemExit(main())`.
- `../pyproject.toml`: `[project.scripts] rucadvirtuoso = "rcad.cli:main"` (или в `src/main.py` через консольный скрипт); при необходимости `pythonpath` для запуска из корня.
- Приёмка: `python -m rcad --help`, `python src/main.py` (GUI, оффскрин smoke), `python -m rcad.cli check ...`.

### T9. Golden-данные и согласование тестов
- Сгенерировать и зафиксировать `tests/golden/t04_mosfet_output.csv` и `tests/golden/t05_memristor_iv.csv` (после подтверждения моделей аналитикой по формулам внутри T4/T5), ссылку на источник в шапке.
- `tests/integration/test_t04_mosfet.py.test_region_current`: привести к ряду (брать значение в строке развёртки, где `V(g)` = номинал региона) — решение R1 core-плана, задокументировать в коммите.
- `../tests/cases.py`: T13 → `tests/perf/test_t13_crossbar.py`.
- Приёмка: T4-golden/T5-golden зелёные; реестр совпадает с файлами.

### T10. Валидация и линтеры
- `pytest tests/unit tests/integration -m "not perf"` (skip T9–T11/S2 — VA).
- `pytest tests/perf/test_t13_crossbar.py` (≤120 с).
- `QT_QPA_PLATFORM=offscreen pytest tests/ui_smoke`.
- `ruff check src tests` и `mypy src` — без ошибок.
- Вручную: `python -m rcad.cli check/netlist/run --analysis dc/tran` на примере из S1.

## 5. Риски

- **Сходимость/точность ядра**: уравнения в `mna_devices.py` — упрощённые (плотный MNA, нет gmin/source-stepping). Если T2/T3/T4-golden не сойдутся в допуске — добавить в `NewtonSolver` демпфирование/`gmin` (`../src/rcad/core/solver/__init__.py`).
- **T13 бюджет**: при 256 мемристорах и 10000 точках плотный `np.linalg.solve` может не уложиться в 120 с; резерв — сборка разреженной MNA (AD-05), замер до/после.
- **AC-серия complex**: `export_csv`/`plot_window` должны корректно обрабатывать complex (для T3 не экспортируется — допускается).
- **Первым шагов**: зафиксировать регрессию до изменений (список падающих тестов), затем чинить по T1→T10.

## 6. Определение готовности

- `python src/main.py` открывает GUI; CLI команды работают; `main.py --headless` не импортирует Qt.
- T1–T8, T12, T14, T15 и S1/S3/S4 зелёные; T9–T11/S2 — skip; T13 ≤120 с.
- `ruff`/`mypy` чисты; нет `__pycache__`/`*.pyc` в git; реестр тестов достоверен.
