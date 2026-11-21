"""Headless CLI (ARCh §10.3, FR-NLV-003, NFR-TST-001).

Команды:
- `check <project>` — precheck/ERC-lite текущей иерархии;
- `netlist <project> -o out.cir` — экспорт netlist ячейки;
- `run <project> --analysis {op,dc,tran,ac}` — анализ через ядро (`run_analysis`);
- `export <project> <cell> --out file.csv` — экспорт рядов.

Ошибки разбора/симуляции дают ненулевой exit-код и сообщение в stderr.
UTF-8 на выходе; никакого импорта PySide6.
"""

from __future__ import annotations

import argparse
import sys


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rcad.cli",
        description="RuCadVirtuoso headless CLI (ARCh §10.3)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_check = sub.add_parser("check", help="ERC-lite текущей иерархии")
    p_check.add_argument("project", help="каталог <name>.rcad")
    p_check.add_argument("--cell", default=None, help="имя ячейки (по умолчанию первая)")

    p_netlist = sub.add_parser("netlist", help="экспорт netlist ячейки")
    p_netlist.add_argument("project")
    p_netlist.add_argument("--cell", default=None)
    p_netlist.add_argument("-o", "--out", default=None)

    p_run = sub.add_parser("run", help="запуск анализа через ядро")
    p_run.add_argument("project")
    p_run.add_argument("--cell", default=None)
    p_run.add_argument(
        "--analysis", "-a", required=True,
        choices=["op", "dc", "tran", "ac"],
    )
    p_run.add_argument("--directive", default=None,
                       help="сырая директива (например '.tran 1m 2 0 1m'); "
                            "по умолчанию строится из --analysis")
    p_run.add_argument("--out", default=None, help="CSV с рядами (без него — имена рядов)")
    p_run.add_argument("--series", default=None, help="запятая-список рядов для export")

    p_export = sub.add_parser("export", help="экспорт результатов")
    p_export.add_argument("project")
    p_export.add_argument("cell", nargs="?", default=None)
    p_export.add_argument("--out", required=True, help="файл CSV")
    return parser


def main(argv: list[str] | None = None) -> int:
    from rcad.services.project_service import ProjectService

    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        service = ProjectService()
        project = service.open(args.project)
        cell = args.cell or next(iter(project.cell_names), None)
        if cell is None:
            print("проект не содержит ячеек", file=sys.stderr)
            return 1

        if args.command == "check":
            return _check(project, cell)
        if args.command == "netlist":
            return _netlist(project, cell, args.out)
        if args.command == "run":
            return _run(project, cell, args)
        if args.command == "export":
            return _export(project, cell, args.out)
        parser.print_help()
        return 2
    except Exception as exc:  # граница CLI: ошибка — сообщение + exit≠0
        print(f"ошибка: {exc}", file=sys.stderr)
        return 1


def _check(project, cell: str) -> int:
    text = _netlist_text(project, cell)
    try:
        from rcad.core.analyses import precheck

        precheck(text)
        print("OK")
        return 0
    except ImportError:
        # ядро ещё не реализовано (этап E0): минимальная проверка дубликатов
        errors = _erc_lite(project, cell)
        for diag in errors:
            print(f"{diag.code.value}: {diag.message}", file=sys.stderr)
        return 1 if errors else 0


def _erc_lite(project, cell: str) -> list:
    cell_schema = project.cell(cell)
    missing = []
    for inst in cell_schema.instances:
        entry = project.model_manager.entry(inst.master_cell)
        if entry is None and inst.master_cell not in project.cells:
            missing.append(
                f"E_MISSING_MASTER: мастер {inst.master_cell!r} для {inst.name!r} отсутствует"
            )
    return missing


def _netlist_text(project, cell: str) -> str:
    from rcad.services.netlister import export_netlist

    return export_netlist(project, cell)


def _netlist(project, cell: str, out: str | None) -> int:
    from rcad.services.netlister import export_netlist

    text = export_netlist(project, cell)
    if out:
        with open(out, "w", encoding="utf-8") as stream:
            stream.write(text)
        print(out)
    else:
        print(text, end="")
    return 0


def _run(project, cell: str, args) -> int:
    # Валидация директивы (spec_from_directive кидает ValueError при опечатке)
    from rcad.schemas.analysis import spec_from_directive
    from rcad.services.netlister import netlist_for

    if args.directive:
        spec_from_directive(args.directive)
        directive = args.directive if args.directive.startswith(".") else "." + args.directive
    else:
        directive = {  # минимальные значения по умолчанию
            "op": ".op",
            "dc": ".dc V1 0 5 0.01",
            "tran": ".tran 1m 1",
            "ac": ".ac dec 10 1 1k",
        }[args.analysis]
        spec_from_directive(directive)

    netlist = netlist_for(
        project, cell,
        dc=directive if args.analysis == "dc" else None,
        tran=directive if args.analysis == "tran" else None,
        ac=directive if args.analysis == "ac" else None,
    )
    from rcad.core.analyses import run_analysis

    result = run_analysis(netlist, directive)
    if args.out and args.series:
        from rcad.services.result_store import export_csv

        names = [n.strip() for n in args.series.split(",")]
        path = export_csv(result, names, args.out)
        print(path)
        return 0
    if args.out and args.analysis == "tran":
        names = [n for n in result.names() if n != "time"][:8]
        from rcad.services.result_store import export_csv

        path = export_csv(result, names, args.out)
        print(path)
        return 0
    print(", ".join(result.names_minus_time()))
    return 0


def _export(project, cell: str | None, out: str) -> int:

    raise NotImplementedError(
        "экспорт результатов требует завершённого анализа (см. команду run --out)"
    )


if __name__ == "__main__":
    raise SystemExit(main())
