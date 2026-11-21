# RuCadVirtuoso — запуск и примеры

## Требования

- Python 3.12+;
- PySide6 — только для GUI-режима;
- рабочий каталог — корень репозитория (`src/` на `PYTHONPATH`).

```powershell
$env:PYTHONPATH = "src"
```

## Примеры проектов (`examples/`)

| Проект | Ячейка | Содержимое | Анализ |
|---|---|---|---|
| `examples/demo_divider.rcad` | `divider` | делитель R1-R2 (DC 10 В) | `op`, `dc` |
| `examples/demo_rc.rcad` | `rc_charge` | заряд ёмкости через резистор | `tran` |
| `examples/demo_memristor.rcad` | `memristor_iv` | ВАХ мемристора Yakopcic (SIN 1 В, 1 Гц) | `tran` (ряды `@Xmem.x`, `I(Xmem)`) |

Перегенерировать примеры:

```powershell
python examples/make_examples.py
```

## GUI

```powershell
# Пустое окно (Файл → Открыть проект...)
python src/main.py

# С проектом
python src/main.py --project examples\demo_rc.rcad
```

Новый проект создаётся в окне через «Файл → Сохранить» (папка `<name>.rcad`
с `project.json`) либо программно — см. `examples/make_examples.py`
(`ProjectService.create` + `add_cell`).

## Headless (без Qt)

```powershell
python src/main.py --headless
```

## CLI

### Проверка проекта (ERC-lite)

```powershell
python -m rcad.cli check examples\demo_divider.rcad
```

### Экспорт netlist

```powershell
python -m rcad.cli netlist examples\demo_rc.rcad
python -m rcad.cli netlist examples\demo_divider.rcad -o divider.cir
```

### Анализ (op / dc / tran / ac)

```powershell
# OP: имена рядов результата
python -m rcad.cli run examples\demo_divider.rcad --analysis op

# DC-развёртка источника V1 (0..5 В)
python -m rcad.cli run examples\demo_divider.rcad --analysis dc

# TRAN: CSV с выбранными рядами (заголовок: ось, имена рядов)
python -m rcad.cli run examples\demo_rc.rcad --analysis tran --out rc.csv
python -m rcad.cli run examples\demo_memristor.rcad --analysis tran `
  --out memristor_iv.csv --series "I(Xmem),@Xmem.x"
```

Для `dc`/`tran` с `--out` можно указать `--series <имена через запятую>`;
без `--out --series` команда печатает имена рядов. Экспорт `op` — по именам рядов.

## Справка

```powershell
python src/main.py --help
python -m rcad.cli --help
python -m rcad.cli run --help
```
