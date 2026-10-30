"""Join store prices (data/store.json) with PDF nutrition (data/menu.csv) and build site/index.html."""

import csv
import json
import re

TEMPLATE = "site/template.html"
OUT = "site/index.html"


def stems(text):
    return {w[:5] for w in re.findall(r"[а-яa-z]+", text.lower().replace("ё", "е")) if len(w) > 2}


def load_pdf():
    rows = []
    for r in csv.DictReader(open("data/menu.csv")):
        if r["kcal_100g"] and float(r["kcal_100g"]) > 0:
            mass, k100 = float(r["mass_g"]), float(r["kcal_100g"])
            pieces = re.search(r"(\d+)\s*шт", r["name"])
            rows.append({
                "name": r["name"], "mass": mass, "kcal100": k100,
                "drink": r["section"].startswith(("НАПИТКИ", "КОКТЕЙЛИ", "СЛАБОАЛКОГОЛЬНЫЕ")),
                # PDF footnotes: mass is the guaranteed minimum, per-serving values
                # are for the average real serving. The ratio is how much extra you get.
                "bonus": min(max(float(r["kcal"]) / (k100 * mass / 100), 1.0), 2.0),
                "pieces": int(pieces[1]) if pieces else None,
            })
    return rows


def match_pdf(dish, pdf):
    """Closest PDF row by kcal/100g and weight (both within 10%), tie-broken by shared name stems."""
    k, m = dish["per100"]["kcal"], dish["size"]
    if not k or not m:
        return None
    best, best_score = None, 0
    for r in pdf:
        if abs(r["kcal100"] - k) / k > 0.1 or abs(r["mass"] - m) / m > 0.1:
            continue
        overlap = len(stems(dish["title"]) & stems(r["name"]))
        score = overlap - abs(r["mass"] - m) / m - abs(r["kcal100"] - k) / k
        if overlap and score > best_score:
            best, best_score = r, score
    return best


def size_label(size, unit):
    if unit == "ml":
        return f"{size / 1000:g} л".replace(".", ",")
    return f"{size:g} г"


def build_items(store, pdf):
    items = {}
    for d in store["dishes"]:
        r = match_pdf(d, pdf)
        bonus = r["bonus"] if r else 1.0
        serving = d["size"] / 100 * bonus
        # Some drinks are listed in grams on the site; the PDF section knows better.
        unit = "ml" if d["unit"] == "ml" or (r and r["drink"]) else "g"
        items[d["id"]] = {
            "id": d["id"],
            "name": d["title"],
            "pieces": r["pieces"] if r else None,
            "flavor": d["flavor"],
            "size": size_label(d["size"], unit),
            "unit": unit,
            "cats": list(dict.fromkeys(d["cats"])),
            "variant": d["variant"],
            "orderable": d["orderable"],
            "price": d["price"],
            "oldPrice": d["oldPrice"],
            "bonus": round(bonus, 3),
            "grams": round(d["size"] * bonus) if unit == "g" else 0,
            "ml": d["size"] if unit == "ml" else 0,
            "kcal": round(d["per100"]["kcal"] * serving),
            "protein": round(d["per100"]["protein"] * serving, 1),
            "fat": round(d["per100"]["fat"] * serving, 1),
            "carbs": round(d["per100"]["carbs"] * serving, 1),
            "known": d["per100"]["kcal"] > 0,
        }
    # Tell same-titled products apart: "3 шт" for packs, flavor for burgers/rolls
    # (the site titles original and spicy identically), else the weight/volume.
    titles = {}
    for it in items.values():
        titles.setdefault(it["name"], []).append(it)
    for twins in titles.values():
        flavors = [it["flavor"] for it in twins]
        by_flavor = all(flavors) and len(set(flavors)) == len(flavors)
        for it in twins:
            it["label"] = (f"{it['pieces']} шт" if it["pieces"]
                           else it["flavor"] if len(twins) > 1 and by_flavor
                           else it["size"] if len(twins) > 1 else "")
    return items


# Combo slots that point at modifier-only products ("2 Оригинальных Ножки") carry the
# combo price split across its parts, not a real price. Resolve them to real packs.
PIECE_FAMILIES = [
    (r"(\d+)\s+оригинальн\w*\s+ножк", "Ножки Оригинальные"),
    (r"(\d+)\s+остр\w*\s+крылыш", "Острые Крылышки"),
    (r"(\d+)\s+оригинальн\w*\s+стрипс", "Стрипсы Оригинальные"),
    (r"(\d+)\s+остр\w*\s+стрипс", "Стрипсы Острые"),
    (r"наггетсы\s+(\d+)", "Наггетсы"),
]
# title fragment -> (dish title, which size: 0 = smallest)
FIXED = [
    ("картофель фри малый", ("Картофель фри", 0)),
    ("картофель фри стандартный", ("Картофель фри", 1)),
    ("байтсы из куриного филе", ("Байтсы", 0)),
]


def cheapest_cover(packs, n):
    """Cheapest way to buy at least n pieces from (pieces, price) packs, any number of each."""
    top = n + max(p for p, _ in packs)
    best = [0.0] + [float("inf")] * top
    for i in range(1, top + 1):
        for pieces, price in packs:
            best[i] = min(best[i], best[max(i - pieces, 0)] + price)
    return min(best[n:])


def resolve_option(opt, items):
    nutrition = ("kcal", "protein", "fat", "carbs", "grams", "ml")
    if opt["id"] in items:
        it = items[opt["id"]]
        label = f" · {it['label']}" if it["variant"] else ""
        return {"name": it["name"] + label, "standalone": it["price"], "approx": False,
                **{k: it[k] for k in nutrition}, "known": it["known"]}

    title = opt["title"].lower().replace("ё", "е")
    orderable = [it for it in items.values() if it["orderable"]]
    for pattern, family in PIECE_FAMILIES:
        m = re.search(pattern, title)
        if m:
            n = int(m[1])
            packs = sorted((it for it in orderable if it["name"] == family and it["pieces"]),
                           key=lambda it: it["pieces"])
            unit = packs[0]
            per = {k: unit[k] / unit["pieces"] for k in nutrition}
            return {"name": opt["title"], "standalone": cheapest_cover([(p["pieces"], p["price"]) for p in packs], n),
                    "approx": False, **{k: round(per[k] * n, 1) for k in nutrition}, "known": True}
    for fragment, (family, rank) in FIXED:
        if fragment in title:
            sizes = sorted((it for it in orderable if it["name"] == family), key=lambda it: it["grams"])
            it = sizes[min(rank, len(sizes) - 1)]
            return {"name": opt["title"], "standalone": it["price"], "approx": True,
                    **{k: it[k] for k in nutrition}, "known": True}
    # Mini muffins, syrups: no standalone equivalent on the menu.
    return {"name": opt["title"], "standalone": None, "approx": True,
            **{k: 0 for k in nutrition}, "known": False}


def build_combos(store, items):
    combos = []
    for c in store["combos"]:
        cats = list(dict.fromkeys(c["cats"]))
        combos.append({
            "id": c["id"],
            "name": c["title"],
            "short": c["short"],
            "code": c["code"] if c["title"].startswith("Купон") else None,
            "cats": cats,
            "price": c["price"],
            "oldPrice": c["oldPrice"],
            "groups": [
                {"title": g["title"], "pick": g["max"],
                 "options": [resolve_option(o, items) for o in g["options"]]}
                for g in c["groups"]
            ],
        })
    return combos


def main():
    store = json.load(open("data/store.json"))
    pdf = load_pdf()
    items = build_items(store, pdf)
    combos = build_combos(store, items)
    data = {
        "storeId": store["storeId"],
        "captured": store["captured"],
        "items": [it for it in items.values() if it["orderable"]],
        "combos": combos,
    }
    html = open(TEMPLATE).read().replace("/*DATA*/null", json.dumps(data, ensure_ascii=False))
    open(OUT, "w").write(html)
    print(f"{len(data['items'])} items, {len(combos)} combos -> {OUT}")


if __name__ == "__main__":
    main()
