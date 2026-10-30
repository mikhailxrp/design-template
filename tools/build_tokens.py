#!/usr/bin/env python3
"""
build_tokens.py — собирает CSS из токенов дизайна и проверяет контраст.

Читает:   .docs/design/tokens.json              (единственный источник правды)
Создаёт:  assets/css/base/vars.css              (переменные :root; НЕ править руками)
          assets/css/admin-theme.css            (подмена переменных Tabler; если meta.admin = true)
          .docs/design/tokens-report.md         (контраст, производные цвета, предупреждения)

Запуск (из корня проекта):
    python tools/build_tokens.py
    python tools/build_tokens.py --root путь/к/проекту
    python tools/build_tokens.py --strict         # код возврата 3, если есть пары ниже порога

Только стандартная библиотека Python 3.8+.

Что считает сам (в tokens.json этого писать не нужно):
    <цвет>-hover, <цвет>-active   оттенки для наведения и нажатия
    on-<цвет>                     цвет текста на кнопке этого цвета (белый или почти чёрный)
    <цвет>-text                   тот же цвет, подтянутый по светлоте до контраста 4.5:1 с фоном,
                                  чтобы им можно было красить ссылки и текст
    <цвет>-soft                   лёгкая подложка (12% цвета на фоне) для бейджей и уведомлений
"""

import argparse
import colorsys
import json
import re
import sys
from pathlib import Path

BRAND = ["primary", "secondary", "accent", "success", "warning", "danger", "info"]
NEUTRAL = ["bg", "surface", "text", "text-muted", "border"]
NEAR_BLACK = (17, 17, 17)
WHITE = (255, 255, 255)

DEFAULTS = {
    "text": {
        "base": "16px",
        "scale": {"xs": "12px", "sm": "14px", "base": "16px", "lg": "18px",
                  "xl": "20px", "2xl": "24px", "3xl": "30px", "4xl": "36px"},
        "line-height": {"tight": "1.2", "base": "1.5", "loose": "1.7"},
        "weight": {"regular": 400, "medium": 500, "bold": 700},
    },
    "space": {"unit": "8px"},
    "radius": {"sm": "4px", "md": "8px", "lg": "12px", "full": "9999px"},
    "shadow": {"sm": "0 1px 2px rgba(0,0,0,.06)", "md": "0 4px 12px rgba(0,0,0,.08)",
               "lg": "0 12px 32px rgba(0,0,0,.12)"},
    "motion": {"fast": "120ms", "base": "200ms", "slow": "320ms"},
    "breakpoints": {"sm": "480px", "md": "768px", "lg": "1024px", "xl": "1280px"},
}
SPACE_STEPS = [0, 1, 2, 3, 4, 5, 6, 8, 10, 12, 16, 20, 24]


# ---------- цвет ----------

def parse_hex(value, where):
    m = re.fullmatch(r"#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})", str(value).strip())
    if not m:
        raise ValueError("%s: ожидается HEX вида #RRGGBB, получено %r" % (where, value))
    h = m.group(1)
    if len(h) == 3:
        h = "".join(ch * 2 for ch in h)
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def to_hex(c):
    return "#%02X%02X%02X" % tuple(c)


def luminance(c):
    def f(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (f(v) for v in c)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    la, lb = luminance(a), luminance(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def mix(a, b, t):
    """t — доля цвета b."""
    return tuple(round(a[i] * (1 - t) + b[i] * t) for i in range(3))


def shift_lightness(c, delta):
    h, l, s = colorsys.rgb_to_hls(*(x / 255 for x in c))
    l = min(1.0, max(0.0, l + delta))
    return tuple(round(v * 255) for v in colorsys.hls_to_rgb(h, l, s))


def ensure_contrast(c, bg, target):
    """Сдвигает светлоту цвета c минимально, пока контраст с bg не достигнет target."""
    if contrast(c, bg) >= target:
        return c
    sign = -1 if luminance(bg) > 0.5 else 1
    cur = c
    for _ in range(100):
        cur = shift_lightness(cur, sign * 0.01)
        if contrast(cur, bg) >= target:
            break
    return cur


def rgb_triplet(c):
    return "%d, %d, %d" % tuple(c)


# ---------- токены ----------

def load_tokens(path):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise SystemExit("Не найден %s. Сначала запусти /design-tokens." % path)
    except json.JSONDecodeError as exc:
        raise SystemExit("tokens.json: ошибка JSON — %s" % exc)

    defaulted = []
    for section, default in DEFAULTS.items():
        if section not in data:
            data[section] = default
            defaulted.append(section)
        elif isinstance(default, dict):
            for key, val in default.items():
                if key not in data[section]:
                    data[section][key] = val
                    defaulted.append("%s.%s" % (section, key))

    errors = []
    colors = {}
    for name in BRAND + NEUTRAL:
        raw = data.get("color", {}).get(name)
        if raw is None:
            errors.append("color.%s: не задан" % name)
            continue
        try:
            colors[name] = parse_hex(raw, "color.%s" % name)
        except ValueError as exc:
            errors.append(str(exc))
    for role in ("heading", "body"):
        fam = data.get("font", {}).get(role, {}).get("family")
        if not fam:
            errors.append("font.%s.family: не задан" % role)
    if errors:
        raise SystemExit("tokens.json содержит ошибки:\n  - " + "\n  - ".join(errors))
    return data, colors, defaulted


def derive(colors):
    bg = colors["bg"]
    derived = {}
    for name in BRAND:
        c = colors[name]
        dark_base = luminance(c) <= 0.18
        derived[name + "-hover"] = mix(c, WHITE if dark_base else (0, 0, 0), 0.12)
        derived[name + "-active"] = mix(c, WHITE if dark_base else (0, 0, 0), 0.20)
        derived["on-" + name] = max((WHITE, NEAR_BLACK), key=lambda x: contrast(x, c))
        derived[name + "-text"] = ensure_contrast(c, bg, 4.5)
        derived[name + "-soft"] = mix(bg, c, 0.12)
    return derived


def contrast_checks(colors, derived):
    bg, surface = colors["bg"], colors["surface"]
    checks = [
        ("text на bg", colors["text"], bg, 4.5),
        ("text на surface", colors["text"], surface, 4.5),
        ("text-muted на bg", colors["text-muted"], bg, 4.5),
        ("text-muted на surface", colors["text-muted"], surface, 4.5),
        ("border на bg (элемент интерфейса)", colors["border"], bg, 3.0),
        ("primary на bg (кнопка, фокус)", colors["primary"], bg, 3.0),
    ]
    for name in ("primary", "secondary", "success", "warning", "danger", "info"):
        checks.append(("on-%s на %s (текст на кнопке)" % (name, name),
                       derived["on-" + name], colors[name], 4.5))
    for name in ("primary", "danger", "success"):
        checks.append(("%s-text на bg (ссылка, ошибка)" % name,
                       derived[name + "-text"], bg, 4.5))
    return checks


# ---------- CSS ----------

def css_vars(data, colors, derived):
    d = data
    lines = [
        "/* ==========================================================",
        "   GENERATED FILE — не править вручную.",
        "   Источник: .docs/design/tokens.json",
        "   Пересборка: python tools/build_tokens.py",
        "   ========================================================== */",
        "",
        ":root {",
        "  /* Цвета */",
    ]
    for name in NEUTRAL:
        lines.append("  --color-%s: %s;" % (name, to_hex(colors[name])))
    for name in BRAND:
        lines.append("  --color-%s: %s;" % (name, to_hex(colors[name])))
        lines.append("  --color-%s-rgb: %s;" % (name, rgb_triplet(colors[name])))
        for suffix in ("hover", "active", "text", "soft"):
            lines.append("  --color-%s-%s: %s;" % (name, suffix, to_hex(derived[name + "-" + suffix])))
        lines.append("  --color-on-%s: %s;" % (name, to_hex(derived["on-" + name])))
    lines.append("  --focus-ring: 0 0 0 3px rgba(%s, 0.35);" % rgb_triplet(colors["primary"]))

    lines += ["", "  /* Шрифты (файлы шрифтов подключаются через @font-face в base.css) */"]
    for role in ("heading", "body"):
        f = d["font"][role]
        fallback = f.get("fallback", "system-ui, sans-serif")
        lines.append('  --font-%s: "%s", %s;' % (role, f["family"], fallback))

    lines += ["", "  /* Размеры текста */"]
    for key, val in d["text"]["scale"].items():
        lines.append("  --text-%s: %s;" % (key, val))
    for key, val in d["text"]["line-height"].items():
        lines.append("  --leading-%s: %s;" % (key, val))
    for key, val in d["text"]["weight"].items():
        lines.append("  --weight-%s: %s;" % (key, val))

    unit = d["space"]["unit"]
    m = re.fullmatch(r"([\d.]+)(px|rem)", unit.strip())
    if not m:
        raise SystemExit("space.unit: ожидается значение вида 8px или 0.5rem, получено %r" % unit)
    step = float(m.group(1)) / 2
    suffix = m.group(2)
    lines += ["", "  /* Отступы: space-N = N × (unit / 2); space-2 = unit */",
              "  --space-unit: %s;" % unit]
    for n in SPACE_STEPS:
        value = n * step
        text = ("%g" % round(value, 4)) + (suffix if value else "")
        lines.append("  --space-%d: %s;" % (n, text))

    lines += ["", "  /* Радиусы */"]
    for key, val in d["radius"].items():
        lines.append("  --radius-%s: %s;" % (key, val))
    lines += ["", "  /* Тени */"]
    for key, val in d["shadow"].items():
        lines.append("  --shadow-%s: %s;" % (key, val))
    lines += ["", "  /* Движение */"]
    for key, val in d["motion"].items():
        lines.append("  --duration-%s: %s;" % (key, val))
        lines.append("  --transition-%s: %s ease;" % (key, val))
    lines += ["", "  /* Брейкпоинты (в @media подставляются числом; здесь для справки и JS) */"]
    for key, val in d["breakpoints"].items():
        lines.append("  --bp-%s: %s;" % (key, val))
    lines += ["}", ""]
    return "\n".join(lines)


def tabler_overrides(data, colors, derived):
    """Подмена переменных Tabler 1.6.x на наши токены. Имена сверены с tabler.min.css 1.6.1."""
    d = data
    body_font = '"%s", %s' % (d["font"]["body"]["family"],
                              d["font"]["body"].get("fallback", "system-ui, sans-serif"))
    o = {}
    for name in ("primary", "secondary", "success", "warning", "danger", "info"):
        o["--tblr-%s" % name] = to_hex(colors[name])
        o["--tblr-%s-rgb" % name] = rgb_triplet(colors[name])
    o["--tblr-primary-fg"] = to_hex(derived["on-primary"])
    o["--tblr-link-color"] = to_hex(derived["primary-text"])
    o["--tblr-link-color-rgb"] = rgb_triplet(derived["primary-text"])
    o["--tblr-link-hover-color"] = to_hex(derived["primary-active"])
    o["--tblr-body-bg"] = to_hex(colors["bg"])
    o["--tblr-body-bg-rgb"] = rgb_triplet(colors["bg"])
    o["--tblr-body-color"] = to_hex(colors["text"])
    o["--tblr-body-color-rgb"] = rgb_triplet(colors["text"])
    o["--tblr-heading-color"] = to_hex(colors["text"])
    o["--tblr-secondary-color"] = to_hex(colors["text-muted"])
    o["--tblr-muted"] = to_hex(colors["text-muted"])
    o["--tblr-bg-surface-primary"] = to_hex(colors["surface"])
    o["--tblr-border-color"] = to_hex(colors["border"])
    o["--tblr-border-radius"] = d["radius"]["md"]
    o["--tblr-border-radius-sm"] = d["radius"]["sm"]
    o["--tblr-border-radius-lg"] = d["radius"]["lg"]
    o["--tblr-font-sans-serif"] = body_font
    o["--tblr-body-font-size"] = d["text"]["base"]
    o["--tblr-body-line-height"] = d["text"]["line-height"]["base"]
    return o


def admin_css(overrides):
    lines = [
        "/* ==========================================================",
        "   GENERATED FILE — не править вручную.",
        "   Подмена переменных Tabler на токены проекта.",
        "   Подключать ПОСЛЕ tabler.min.css.",
        "   Источник: .docs/design/tokens.json",
        "   ========================================================== */",
        "",
        ":root {",
    ]
    for key, val in overrides.items():
        lines.append("  %s: %s;" % (key, val))
    lines += ["}", ""]
    return "\n".join(lines)


def find_tabler_css(root, explicit):
    candidates = [explicit] if explicit else [
        root / "public/assets/vendor/tabler/css/tabler.min.css",
        root / "assets/vendor/tabler/css/tabler.min.css",
        root / "prototypes/assets/vendor/tabler/css/tabler.min.css",
    ]
    for c in candidates:
        if c and Path(c).is_file():
            return Path(c)
    return None


# ---------- отчёт ----------

def build_report(data, colors, derived, checks, defaulted, tabler_missing, tabler_path, admin):
    ok = [c for c in checks if contrast(c[1], c[2]) >= c[3]]
    bad = [c for c in checks if contrast(c[1], c[2]) < c[3]]
    L = ["# Отчёт по токенам", "",
         "Сгенерирован `tools/build_tokens.py`. Не править вручную.", "",
         "## Сводка", "",
         "- Проверено пар по контрасту: **%d**, проходят: **%d**, ниже порога: **%d**"
         % (len(checks), len(ok), len(bad)),
         "- Значения по умолчанию подставлены для: %s" % (", ".join(defaulted) if defaulted else "—"),
         "- Админка (Tabler): %s" % ("да" if admin else "нет"), ""]
    L += ["## Контраст", "", "| Пара | Контраст | Порог | Результат |", "|---|---|---|---|"]
    for label, fg, bgc, thr in checks:
        r = contrast(fg, bgc)
        L.append("| %s (%s на %s) | %.2f | %.1f | %s |" % (
            label, to_hex(fg), to_hex(bgc), r, thr, "✅" if r >= thr else "⚠️ ниже порога"))
    L += ["", "Пороги: 4.5 — обычный текст (WCAG AA), 3.0 — крупный текст и элементы интерфейса.", ""]
    if bad:
        L += ["### Что исправить", "",
              "Не меняй `primary` (цвет бренда). Подстрой `text`, `text-muted`, `border`, "
              "`bg`, `surface` минимально и запиши правку в `meta.adjustments`.", ""]
        for label, fg, bgc, thr in bad:
            L.append("- %s: %s на %s = %.2f, нужно ≥ %.1f" % (label, to_hex(fg), to_hex(bgc), contrast(fg, bgc), thr))
        L.append("")
    L += ["## Производные цвета", "",
          "| Цвет | hover | active | on- | -text | -soft |", "|---|---|---|---|---|---|"]
    for name in BRAND:
        L.append("| %s %s | %s | %s | %s | %s | %s |" % (
            name, to_hex(colors[name]), to_hex(derived[name + "-hover"]), to_hex(derived[name + "-active"]),
            to_hex(derived["on-" + name]), to_hex(derived[name + "-text"]), to_hex(derived[name + "-soft"])))
    L.append("")
    if admin:
        L += ["## Tabler", ""]
        if tabler_path is None:
            L.append("⚠️ `tabler.min.css` не найден — имена подменяемых переменных не проверены. "
                     "Указать путь: `--tabler-css путь/к/tabler.min.css`.")
        elif tabler_missing:
            L.append("⚠️ В `%s` не найдены переменные (версия Tabler могла измениться): %s"
                     % (tabler_path, ", ".join(tabler_missing)))
        else:
            L.append("✅ Все подменяемые переменные найдены в `%s`." % tabler_path)
        L.append("")
    L += ["## Метаданные", "",
          "Допущения (из tokens.json): %s" % ("; ".join(data.get("meta", {}).get("assumptions", [])) or "—"),
          "Правки контраста (из tokens.json): %s" % ("; ".join(data.get("meta", {}).get("adjustments", [])) or "—"), ""]
    return "\n".join(L), len(bad)


def main():
    parser = argparse.ArgumentParser(description="Сборка CSS из токенов дизайна")
    parser.add_argument("--root", default=".", help="корень проекта (по умолчанию текущая папка)")
    parser.add_argument("--tokens", default=".docs/design/tokens.json")
    parser.add_argument("--tabler-css", default=None, help="путь к tabler.min.css для проверки имён переменных")
    parser.add_argument("--strict", action="store_true", help="код возврата 3, если есть пары ниже порога")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    data, colors, defaulted = load_tokens(root / args.tokens)
    derived = derive(colors)
    checks = contrast_checks(colors, derived)
    admin = bool(data.get("meta", {}).get("admin"))

    vars_path = root / "assets/css/base/vars.css"
    vars_path.parent.mkdir(parents=True, exist_ok=True)
    vars_path.write_text(css_vars(data, colors, derived), encoding="utf-8")
    written = [vars_path]

    tabler_missing, tabler_path = [], None
    if admin:
        overrides = tabler_overrides(data, colors, derived)
        admin_path = root / "assets/css/admin-theme.css"
        admin_path.write_text(admin_css(overrides), encoding="utf-8")
        written.append(admin_path)
        tabler_path = find_tabler_css(root, Path(args.tabler_css) if args.tabler_css else None)
        if tabler_path:
            css = tabler_path.read_text(encoding="utf-8", errors="ignore")
            tabler_missing = [k for k in overrides if (k + ":") not in css]

    report, bad_count = build_report(data, colors, derived, checks, defaulted,
                                     tabler_missing, tabler_path, admin)
    report_path = root / ".docs/design/tokens-report.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8")
    written.append(report_path)

    print("Готово. Создано:")
    for p in written:
        print("  - %s" % p.relative_to(root))
    print("Контраст: проверено %d пар, ниже порога %d." % (len(checks), bad_count))
    if admin and tabler_missing:
        print("Внимание: в Tabler не найдены переменные: %s" % ", ".join(tabler_missing))
    if args.strict and bad_count:
        sys.exit(3)


if __name__ == "__main__":
    main()
