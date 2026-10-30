#!/usr/bin/env python3
"""
palette.py — измеряет цвета на скриншоте-референсе.

Зачем: цвета "на глаз" по картинке получаются приблизительными. Скрипт берёт
реальные пиксели и выдаёт HEX, долю площади и контраст с фоном, а также
предположение о ролях (фон, поверхность, текст, акцент).

Запуск:
    python tools/palette.py путь/к/скриншоту.png
    python tools/palette.py путь/к/скриншоту.png --json
    python tools/palette.py путь/к/скриншоту.png --top 16

Нужен Pillow:  pip install pillow

Ограничения (честно):
  - Фотографии и градиенты "пачкают" палитру: для фото-обложек лучше
    сначала обрезать скриншот до интерфейса.
  - Роли (фон/текст/акцент) — эвристика, а не истина. Проверяй глазами.
  - Тонкий текст занимает мало пикселей, поэтому его цвет определяется
    приблизительно.
"""

import argparse
import colorsys
import json
import sys

try:
    from PIL import Image
except ImportError:
    sys.stderr.write("Нужен Pillow. Установи: pip install pillow\n")
    sys.exit(2)

MAX_SIDE = 300        # сжимаем картинку для скорости
BUCKET = 8            # шаг группировки каналов (0..255)
MERGE_DISTANCE = 12   # цвета ближе этого расстояния считаются одним
MIN_TEXT_SHARE = 0.2  # минимальная доля (%) для кандидатов в текст
MIN_ACCENT_SHARE = 0.1  # минимальная доля (%) для кандидатов в акцент


def to_hex(c):
    return "#%02X%02X%02X" % c


def luminance(c):
    def f(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (f(v) for v in c)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def distance(a, b):
    return sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5


def saturation_value(c):
    _, s, v = colorsys.rgb_to_hsv(*(x / 255 for x in c))
    return s, v


def load_pixels(path):
    img = Image.open(path)
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        img = img.convert("RGBA")
        base = Image.new("RGBA", img.size, (255, 255, 255, 255))
        base.alpha_composite(img)
        img = base
    img = img.convert("RGB")
    img.thumbnail((MAX_SIDE, MAX_SIDE))
    colors = img.getcolors(maxcolors=img.width * img.height)
    return img.size, colors


def build_clusters(colors):
    # 1. группируем близкие оттенки в корзины, считая среднее настоящих цветов
    buckets = {}
    for count, (r, g, b) in colors:
        key = (r // BUCKET, g // BUCKET, b // BUCKET)
        item = buckets.setdefault(key, [0, 0, 0, 0])
        item[0] += count
        item[1] += r * count
        item[2] += g * count
        item[3] += b * count
    merged = []
    for count, sr, sg, sb in buckets.values():
        merged.append((count, (round(sr / count), round(sg / count), round(sb / count))))
    merged.sort(key=lambda x: -x[0])

    # 2. склеиваем корзины, близкие по цвету
    clusters = []  # [count, sumR, sumG, sumB, (r, g, b)]
    for count, color in merged:
        for cl in clusters:
            if distance(cl[4], color) < MERGE_DISTANCE:
                cl[0] += count
                cl[1] += color[0] * count
                cl[2] += color[1] * count
                cl[3] += color[2] * count
                cl[4] = (round(cl[1] / cl[0]), round(cl[2] / cl[0]), round(cl[3] / cl[0]))
                break
        else:
            clusters.append([count, color[0] * count, color[1] * count, color[2] * count, color])
    clusters.sort(key=lambda x: -x[0])
    return [(cl[0], cl[4]) for cl in clusters]


def guess_roles(clusters, total):
    share = lambda c: c[0] * 100 / total
    bg = clusters[0][1]
    roles = {"background": to_hex(bg)}

    # поверхность: ближайший по светлоте к фону, но заметно отличающийся
    surface = None
    for c in clusters[1:]:
        d = distance(c[1], bg)
        if 6 <= d <= 80 and share(c) >= 1.0:
            surface = c[1]
            break
    roles["surface"] = to_hex(surface) if surface else None

    # текст: максимальный контраст с фоном среди заметных цветов
    text_pool = [c for c in clusters if share(c) >= MIN_TEXT_SHARE]
    text = max(text_pool, key=lambda c: contrast(c[1], bg), default=None)
    roles["text"] = to_hex(text[1]) if text else None

    # приглушённый текст: серый, контраст 3..7
    muted = None
    for c in text_pool:
        s, _ = saturation_value(c[1])
        ratio = contrast(c[1], bg)
        if s < 0.25 and 3 <= ratio <= 7 and (not text or c[1] != text[1]):
            muted = c[1]
            break
    roles["text_muted"] = to_hex(muted) if muted else None

    # акценты: насыщенные цвета, по убыванию доли
    accents = []
    for c in clusters:
        s, v = saturation_value(c[1])
        if s >= 0.35 and v >= 0.25 and share(c) >= MIN_ACCENT_SHARE:
            accents.append(c[1])
    roles["primary"] = to_hex(accents[0]) if accents else None
    roles["accent"] = to_hex(accents[1]) if len(accents) > 1 else None
    return roles, bg


def main():
    parser = argparse.ArgumentParser(description="Измерение цветов на скриншоте")
    parser.add_argument("image", help="путь к PNG/JPG/WebP")
    parser.add_argument("--json", action="store_true", help="вывод в JSON")
    parser.add_argument("--top", type=int, default=12, help="сколько цветов показать")
    args = parser.parse_args()

    try:
        size, colors = load_pixels(args.image)
    except FileNotFoundError:
        sys.stderr.write("Файл не найден: %s\n" % args.image)
        sys.exit(1)
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write("Не удалось открыть изображение: %s\n" % exc)
        sys.exit(1)

    total = sum(count for count, _ in colors)
    clusters = build_clusters(colors)
    roles, bg = guess_roles(clusters, total)

    rows = []
    for count, color in clusters[: args.top]:
        s, _ = saturation_value(color)
        rows.append({
            "hex": to_hex(color),
            "share_percent": round(count * 100 / total, 2),
            "contrast_vs_background": round(contrast(color, bg), 2),
            "saturation": round(s, 2),
        })

    result = {
        "image": args.image,
        "analyzed_size": list(size),
        "guess": roles,
        "colors": rows,
        "note": "Роли — эвристика. Фото и градиенты искажают палитру. Помечай значения как [измерено].",
    }

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    print("Файл: %s  (анализ %dx%d)" % (args.image, size[0], size[1]))
    print("\nПредположение о ролях:")
    for key, value in roles.items():
        print("  %-11s %s" % (key, value or "—"))
    print("\nЦвета (по доле площади):")
    print("  %-8s %8s %10s %10s" % ("HEX", "доля %", "контраст", "насыщ."))
    for row in rows:
        print("  %-8s %8.2f %10.2f %10.2f" % (
            row["hex"], row["share_percent"], row["contrast_vs_background"], row["saturation"]))
    print("\n" + result["note"])


if __name__ == "__main__":
    main()
