# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tabelle: je Einstellung Größe, CER (alle / schwierige Kategorien) und SSIM gegen die saubere Vorlage."""
import json
import sys
from collections import defaultdict

r = json.load(open(sys.argv[1]))
HARD = ("5 pt", "6 pt", "Dünne", "Sehr hellgrau", "Hellblau", "Dunkelblau 7")
for dpi in (200, 300):
    print(f"\n=== {dpi} dpi ===")
    print(f"{'Variante':10s} {'KB':>6s} {'CER alle':>9s} {'CER schwer':>11s} {'SSIM alle':>10s} {'SSIM schwer':>12s}")
    for key, v in r.items():
        if not key.endswith(f"@{dpi}"):
            continue
        rows = v["rows"]
        hard = [x for x in rows if any(h in x["cat"] for h in HARD)]
        mean = lambda xs, f: sum(x[f] for x in xs) / max(len(xs), 1)
        print(f"{key.split('@')[0]:10s} {v['size'] // 1024:6d} {mean(rows, 'cer') * 100:8.2f}% {mean(hard, 'cer') * 100:10.2f}%"
              f" {mean(rows, 'ssim'):10.3f} {mean(hard, 'ssim'):12.3f}")
if len(sys.argv) > 2:  # Kategorien im Detail für eine Variante
    for dpi in (200, 300):
        agg = defaultdict(list)
        for x in r[f"{sys.argv[2]}@{dpi}"]["rows"]:
            agg[x["cat"].replace(" (Ziffern)", "")].append(x)
        print(f"\n{sys.argv[2]}@{dpi}")
        for c, xs in agg.items():
            print(f"  {c:34s} CER {sum(x['cer'] for x in xs) / len(xs) * 100:6.2f}%  SSIM {sum(x['ssim'] for x in xs) / len(xs):.3f}")
