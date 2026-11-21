"""Точка входа: GUI / headless / CLI (ARCh §4, §10.3).

GUI-режим импортирует `rcad.ui.app` только по явному запросу (`--gui` или без
флагов) — на этапе CLI и headless-сценариев PySide6 не загружается.
"""

from __future__ import annotations

import argparse


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="RuCadVirtuoso", description="RuCadVirtuoso MVP")
    parser.add_argument("--cli", action="store_true", help="запустить командный интерфейс")
    parser.add_argument("--headless", action="store_true", help="headless-режим (без Qt)")
    parser.add_argument("--project", default=None, help="каталог проекта <name>.rcad")
    parser.add_argument("cli_args", nargs=argparse.REMAINDER, help="аргументы для rcad.cli")
    args = parser.parse_args(argv)

    if args.cli:
        from rcad.cli import main as cli_main

        raise SystemExit(cli_main(args.cli_args or None))

    if args.headless:
        print("headless: GUI не запускается (нулевый Qt-импорт обеспечен).")
        return

    # GUI по умолчанию — только если запрошен проект или флаг gui.
    if args.project:
        from rcad.ui.app import MainWindow, create_app

        app = create_app()
        window = MainWindow()
        window.open_project(args.project)
        window.show()
        app.exec()
        return

    parser.print_help()


if __name__ == "__main__":
    main()
