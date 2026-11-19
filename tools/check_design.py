#!/usr/bin/env python3
"""
check_design.py — кроссплатформенная проверка CSS и HTML-прототипа по правилам проекта.

Заменяет Unix-команды grep в шагах design-system, prototype и design-review:
работает одинаково на Windows (PowerShell/cmd), macOS и Linux.

Запуск (из корня проекта):
    python tools/check_design.py                     # все проверки (для design-review)
    python tools/check_design.py --scope system      # проверки для design-system
    python tools/check_design.py --scope prototype   # проверки для prototype
    python tools/check_design.py --json              # вывод в JSON
    python tools/check_design.py --strict            # код возврата 3 при наличии ошибок

Только стандартная библиотека Python 3.8+.
"""

import argparse
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

COLOR_RE = re.compile(
    r"""(?<!href=["'])(?<![&\w])#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})\b|(?:rgba?|hsla?)\s*\(""",
    re.IGNORECASE,
)
IMPORTANT_RE = re.compile(r"!important\b", re.IGNORECASE)
OUTLINE_NONE_RE = re.compile(r"\boutline\s*:\s*(?:none|0)\b", re.IGNORECASE)
INLINE_STYLE_RE = re.compile(r"\bstyle\s*=|<style\b", re.IGNORECASE)
DEAD_LINK_RE = re.compile(r"""href\s*=\s*["']#["']""", re.IGNORECASE)
IMG_TAG_RE = re.compile(r"<img\b[^>]*>", re.IGNORECASE | re.DOTALL)
ALT_ATTR_RE = re.compile(r"\balt\s*=", re.IGNORECASE)
HREF_RE = re.compile(r"""href\s*=\s*["']([^"']+)["']""", re.IGNORECASE)
SMALL_FONT_RE = re.compile(r"(?<![a-zA-Z-])font-size\s*:\s*(1[0-5]|[1-9])px\b", re.IGNORECASE)
SMALL_HEIGHT_RE = re.compile(r"(?<![a-zA-Z-])(?:min-)?height\s*:\s*([0-3][0-9]|4[0-3])px\b", re.IGNORECASE)
FORM_CONTROL_RE = re.compile(r"<(input|select|textarea)\b([^>]*)>", re.IGNORECASE | re.DOTALL)
LABEL_FOR_RE = re.compile(r"""<label\b[^>]*\bfor\s*=\s*["']([^"']+)["']""", re.IGNORECASE)
ID_ATTR_RE = re.compile(r"""\bid\s*=\s*["']([^"']+)["']""", re.IGNORECASE)
TYPE_ATTR_RE = re.compile(r"""\btype\s*=\s*["']([^"']+)["']""", re.IGNORECASE)
ARIA_LABEL_RE = re.compile(r"\baria-label(?:ledby)?\s*=", re.IGNORECASE)
CSS_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)

EXCLUDED_CSS_NAMES = {"vars.css", "admin-theme.css"}


def strip_css_comments_preserve_lines(text):
    return CSS_COMMENT_RE.sub(lambda m: "\n" * m.group(0).count("\n"), text)


def iter_files(base_dir, pattern):
    if not base_dir.exists():
        return []
    return sorted(p for p in base_dir.rglob(pattern) if p.is_file())


def rel(path, root):
    return path.relative_to(root).as_posix()


def find_line_matches(files, root, regex, strip_css_comments=False, exclude_names=None):
    hits = []
    exclude_names = exclude_names or set()
    for path in files:
        if path.name in exclude_names:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if strip_css_comments:
            text = strip_css_comments_preserve_lines(text)
        for lineno, line in enumerate(text.splitlines(), 1):
            if regex.search(line):
                hits.append({
                    "file": rel(path, root),
                    "line": lineno,
                    "snippet": line.strip()[:120],
                })
    return hits


def find_imgs_without_alt(files, root):
    hits = []
    for path in files:
        text = path.read_text(encoding="utf-8", errors="ignore")
        for m in IMG_TAG_RE.finditer(text):
            tag = m.group(0)
            if not ALT_ATTR_RE.search(tag):
                lineno = text.count("\n", 0, m.start()) + 1
                hits.append({
                    "file": rel(path, root),
                    "line": lineno,
                    "snippet": " ".join(tag.split())[:120],
                })
    return hits


def find_broken_local_links(files, root):
    hits = []
    for path in files:
        text = path.read_text(encoding="utf-8", errors="ignore")
        for m in HREF_RE.finditer(text):
            raw_href = m.group(1).strip()
            if not raw_href or raw_href.startswith(("#", "http://", "https://", "mailto:", "tel:", "javascript:")):
                continue
            target_part = urlsplit(raw_href).path
            if not target_part:
                continue
            resolved = (path.parent / target_part).resolve()
            if not resolved.exists():
                lineno = text.count("\n", 0, m.start()) + 1
                hits.append({
                    "file": rel(path, root),
                    "line": lineno,
                    "snippet": f'href="{raw_href}" (файл не найден)',
                })
    return hits


def find_unlabeled_controls(files, root):
    hits = []
    for path in files:
        text = path.read_text(encoding="utf-8", errors="ignore")
        labeled_ids = set(LABEL_FOR_RE.findall(text))
        for m in FORM_CONTROL_RE.finditer(text):
            tag_name = m.group(1).lower()
            attrs = m.group(2)
            if tag_name == "input":
                type_m = TYPE_ATTR_RE.search(attrs)
                if type_m and type_m.group(1).lower() in ("hidden", "submit", "button", "reset", "image"):
                    continue
            if ARIA_LABEL_RE.search(attrs):
                continue
            id_m = ID_ATTR_RE.search(attrs)
            if id_m and id_m.group(1) in labeled_ids:
                continue
            # Проверяем, не обёрнут ли элемент прямо в <label>...</label>
            before = text[:m.start()].lower()
            last_open = before.rfind("<label")
            last_close = before.rfind("</label")
            if last_open != -1 and last_open > last_close:
                continue
            lineno = text.count("\n", 0, m.start()) + 1
            hits.append({
                "file": rel(path, root),
                "line": lineno,
                "snippet": " ".join(m.group(0).split())[:120],
            })
    return hits


def run_checks(root, scope):
    css_dir = root / "assets" / "css"
    comp_dir = css_dir / "components"
    packs_dir = css_dir / "packs"
    proto_dir = root / "prototypes"

    all_css = iter_files(css_dir, "*.css")
    comp_pack_css = iter_files(comp_dir, "*.css") + iter_files(packs_dir, "*.css")
    proto_html = iter_files(proto_dir, "*.html")

    results = []

    def add(key, title, severity, hits):
        results.append({
            "key": key,
            "title": title,
            "severity": severity,  # "error" | "review"
            "count": len(hits),
            "hits": hits,
        })

    if scope in ("system", "all"):
        color_hits = []
        color_hits.extend(find_line_matches(all_css, root, COLOR_RE, strip_css_comments=True, exclude_names=EXCLUDED_CSS_NAMES))
        if scope == "all":
            color_hits.extend(find_line_matches(proto_html, root, COLOR_RE))
        add("hardcoded_colors", "Жёсткие цвета вне токенов", "error", color_hits)
        add("important", "Использование !important в CSS", "error", find_line_matches(all_css, root, IMPORTANT_RE, strip_css_comments=True))
        add("outline_none", "outline: none / 0 (проверить замену фокуса)", "error", find_line_matches(all_css, root, OUTLINE_NONE_RE, strip_css_comments=True))

    if scope == "prototype":
        add("hardcoded_colors_components", "Жёсткие цвета в components/ и packs/", "error",
            find_line_matches(comp_pack_css, root, COLOR_RE, strip_css_comments=True))

    if scope in ("prototype", "all"):
        add("inline_styles", "style=\"\" или <style> в страницах прототипа", "error", find_line_matches(proto_html, root, INLINE_STYLE_RE))
        add("dead_links", "Мёртвые ссылки href=\"#\"", "error", find_line_matches(proto_html, root, DEAD_LINK_RE))
        add("broken_links", "Битые локальные ссылки в прототипе", "error", find_broken_local_links(proto_html, root))
        add("img_no_alt", "Изображения <img> без атрибута alt", "error", find_imgs_without_alt(proto_html, root))

    if scope == "all":
        add("unlabeled_controls", "Поля форм без label / aria-label (проверить вручную)", "review", find_unlabeled_controls(proto_html, root))
        add("small_font", "font-size меньше 16px (проверить контекст)", "review",
            find_line_matches(all_css, root, SMALL_FONT_RE, strip_css_comments=True, exclude_names=EXCLUDED_CSS_NAMES))
        add("small_tap_target", "height/min-height меньше 44px (проверить контекст)", "review",
            find_line_matches(all_css, root, SMALL_HEIGHT_RE, strip_css_comments=True, exclude_names=EXCLUDED_CSS_NAMES))

    meta = {
        "scope": scope,
        "css_files": len(all_css),
        "prototype_html_files": len(proto_html),
        "error_checks_with_hits": sum(1 for r in results if r["severity"] == "error" and r["count"] > 0),
        "total_error_hits": sum(r["count"] for r in results if r["severity"] == "error"),
        "total_review_hits": sum(r["count"] for r in results if r["severity"] == "review"),
    }
    return meta, results


def print_text(meta, results):
    print(f"Проверка дизайна (scope: {meta['scope']})")
    print(f"Файлов проверено: CSS — {meta['css_files']}, HTML прототипа — {meta['prototype_html_files']}")
    print()
    for r in results:
        tag = "OK" if r["count"] == 0 else ("ОШИБКА" if r["severity"] == "error" else "ПРОВЕРИТЬ")
        print(f"[{tag}] {r['title']}: {r['count']}")
        for h in r["hits"][:20]:
            print(f"    {h['file']}:{h['line']} — {h['snippet']}")
        if r["count"] > 20:
            print(f"    ... и ещё {r['count'] - 20}")
    print()
    print(f"Итого: ошибок — {meta['total_error_hits']}, на ручную проверку — {meta['total_review_hits']}.")


def main():
    parser = argparse.ArgumentParser(description="Кроссплатформенная проверка CSS и HTML-прототипа")
    parser.add_argument("--root", default=".", help="корень проекта (по умолчанию текущая папка)")
    parser.add_argument("--scope", choices=("system", "prototype", "all"), default="all",
                        help="область проверки: system, prototype или all")
    parser.add_argument("--json", action="store_true", help="вывод в формате JSON")
    parser.add_argument("--strict", action="store_true", help="код возврата 3 при наличии ошибок")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    meta, results = run_checks(root, args.scope)

    if args.json:
        print(json.dumps({"meta": meta, "checks": results}, ensure_ascii=False, indent=2))
    else:
        print_text(meta, results)

    if args.strict and meta["total_error_hits"] > 0:
        sys.exit(3)


if __name__ == "__main__":
    main()
