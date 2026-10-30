#!/usr/bin/env python3
"""
build_admin_tokens.py — собирает тему Tabler для кабинета из отдельного файла токенов.

Зачем: build_tokens.py строит vars.css (публичная часть) и admin-theme.css (Tabler) из одного
набора цветов. Если у кабинета своя палитра (например, лендинг тёмный, а кабинет светлый),
её описывают в отдельном файле, а этот скрипт собирает только тему Tabler.

Читает:   .docs/design/tokens-admin.json
Создаёт:  assets/css/admin-theme.css              (подмена переменных Tabler; НЕ править руками)
          .docs/design/tokens-report-admin.md     (контраст и производные цвета кабинета)
НЕ трогает: assets/css/base/vars.css — его по-прежнему собирает build_tokens.py.

Запуск (из корня проекта):
    python tools/build_admin_tokens.py
    python tools/build_admin_tokens.py --strict     # код возврата 3, если есть пары ниже порога

Вся логика (производные цвета, контраст, имена переменных Tabler) — из build_tokens.py.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_tokens as bt  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description="Сборка темы Tabler для кабинета")
    parser.add_argument("--root", default=".", help="корень проекта (по умолчанию текущая папка)")
    parser.add_argument("--tokens", default=".docs/design/tokens-admin.json")
    parser.add_argument("--tabler-css", default=None, help="путь к tabler.min.css для проверки имён переменных")
    parser.add_argument("--strict", action="store_true", help="код возврата 3, если есть пары ниже порога")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    data, colors, defaulted = bt.load_tokens(root / args.tokens)
    derived = bt.derive(colors)
    checks = bt.contrast_checks(colors, derived)

    overrides = bt.tabler_overrides(data, colors, derived)
    admin_path = root / "assets/css/admin-theme.css"
    admin_path.parent.mkdir(parents=True, exist_ok=True)
    admin_path.write_text(bt.admin_css(overrides).replace(
        "Источник: .docs/design/tokens.json",
        "Источник: %s · сборка: python tools/build_admin_tokens.py" % args.tokens), encoding="utf-8")

    tabler_path = bt.find_tabler_css(root, Path(args.tabler_css) if args.tabler_css else None)
    tabler_missing = []
    if tabler_path:
        css = tabler_path.read_text(encoding="utf-8", errors="ignore")
        tabler_missing = [k for k in overrides if (k + ":") not in css]

    report, bad_count = bt.build_report(data, colors, derived, checks, defaulted,
                                        tabler_missing, tabler_path, True)
    report = report.replace("# Отчёт по токенам", "# Отчёт по токенам — кабинет (Tabler)", 1).replace(
        "Сгенерирован `tools/build_tokens.py`.",
        "Сгенерирован `tools/build_admin_tokens.py` из `%s`." % args.tokens, 1)
    report_path = root / ".docs/design/tokens-report-admin.md"
    report_path.write_text(report, encoding="utf-8")

    print("Готово. Создано:")
    for p in (admin_path, report_path):
        print("  - %s" % p.relative_to(root))
    print("Контраст: проверено %d пар, ниже порога %d." % (len(checks), bad_count))
    if tabler_missing:
        print("Внимание: в Tabler не найдены переменные: %s" % ", ".join(tabler_missing))
    if args.strict and bad_count:
        sys.exit(3)


if __name__ == "__main__":
    main()
