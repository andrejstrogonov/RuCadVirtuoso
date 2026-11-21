# RuCadVirtuoso — запуск и примеры

## Подготовка

Установите `PYTHONPATH`, чтобы модуль `rcad` находился:

```powershell
$env:PYTHONPATH = "src"
```

## GUI

```powershell
python src/main.py --project <name>.rcad
```

## Headless (без Qt)

```powershell
python src/main.py --headless
```

## CLI — примеры

```powershell
# Проверка проекта
python src/main.py --cli check <project>

# Экспорт netlist
python src/main.py --cli netlist <project> -o out.cir

# Запуск анализа
python src/main.py --cli run <project> --analysis tran --out result.csv

# Экспорт результатов
python src/main.py --cli export <project> <cell> --out out.csv
```

## Справка

```powershell
python src/main.py --help
python src/main.py --cli --help
```
```
\ No newline at end of file