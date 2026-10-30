"""Parse the Rostic's nutrition appendix PDF into data/menu.csv."""

import csv
import re
import sys

import pdfplumber

PDF = "rostics-menu.pdf"
OUT = "data/menu.csv"

NUM = r"(\d+(?:,\d+)?)"
ROW = re.compile(
    rf"^(?P<head>.*?) ?ТТК (?P<ttk>\S+) (?P<mass>{NUM}) "
    # per 100 g: protein, fat, carbs, kcal, kJ (missing for baskets/combos)
    rf"(?:(?P<p100>{NUM}) (?P<f100>{NUM}) (?P<c100>{NUM}) (?P<kcal100>{NUM}) (?P<kj100>{NUM}) )?"
    rf"(?P<p>{NUM}) (?P<f>{NUM}) (?P<c>{NUM}) (?P<kcal>{NUM})$"  # per serving
)
KINDS = ("БЛЮДО", "НАПИТОК", "СИРОП", "ПИВО")
SECTION = re.compile(r"^[А-ЯЁ ,\"-]{12,}$")


def num(s):
    return float(s.replace(",", ".")) if s else None


def parse(lines):
    lines = [l.strip() for l in lines]
    section = None
    rows, rejects = [], []
    for i, line in enumerate(lines):
        if SECTION.match(line):
            section = line
            continue
        if "ТТК" not in line:
            continue
        m = ROW.match(line)
        if not m:
            rejects.append(line)
            continue
        head = m["head"]
        if not head:
            # Wrapped cell: name on the line above, "НАПИТОК <size>" on the line below.
            kind, _, size = lines[i + 1].partition(" ")
            head = f"{kind} {lines[i - 1]} {size}"
        kind, _, name = head.partition(" ")
        if kind not in KINDS:
            kind, name = "НАПИТОК" if section.startswith("НАПИТКИ") else "", head
        rows.append({
            "section": section,
            "kind": kind,
            "name": name.strip(),
            "ttk": m["ttk"],
            "mass_g": num(m["mass"]),
            "protein_100g": num(m["p100"]), "fat_100g": num(m["f100"]),
            "carbs_100g": num(m["c100"]), "kcal_100g": num(m["kcal100"]),
            "kj_100g": num(m["kj100"]),
            "protein": num(m["p"]), "fat": num(m["f"]),
            "carbs": num(m["c"]), "kcal": num(m["kcal"]),
        })
    return rows, rejects


def main():
    with pdfplumber.open(PDF) as pdf:
        lines = [l for p in pdf.pages for l in (p.extract_text() or "").splitlines()]
    rows, rejects = parse(lines)
    with open(OUT, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=rows[0].keys())
        w.writeheader()
        w.writerows(rows)
    print(f"{len(rows)} rows -> {OUT}")
    if rejects:
        print(f"{len(rejects)} unparsed:", file=sys.stderr)
        for r in rejects:
            print("  ", r, file=sys.stderr)


if __name__ == "__main__":
    main()
