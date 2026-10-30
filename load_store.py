"""Extract one store's menu (prices, sizes, nutrition, combos) from a HAR capture of rostics.ru.

In the browser: DevTools → Network, open the menu, right-click the
getMenuPassport request → Save All As HAR. Then:

    python load_store.py clickcollect.har   ->  data/store.json
"""

import json
import re
import sys

OUT = "data/store.json"


def first(d):
    """Site stores values as single-key dicts: {"gr": 84}, {"ccal": 229}."""
    return next(iter(d.values()), None) if isinstance(d, dict) else None


def rub(kopecks):
    return kopecks / 100


def find_menu(har):
    for e in har["log"]["entries"]:
        if "/api/menu/getMenuPassport/" in e["request"]["url"]:
            return e["startedDateTime"], json.loads(e["response"]["content"]["text"])["value"]
    sys.exit("no getMenuPassport response in this HAR")


def flavor(ingredients):
    """Site titles original and spicy versions identically; the chicken ingredient tells them apart."""
    text = " ".join(ingredients).lower()
    if "соус кулинарный острый" in text:
        return "суперострый"
    if re.search(r"(филе|стрипсы)[^,]*остр", text):
        return "острый"
    if re.search(r"(филе|стрипсы)[^,]*оригинал", text):
        return "оригинальный"
    return None


def main(path):
    captured, v = find_menu(json.load(open(path)))
    products = v["products"]
    ingredient_names = {i["id"]: i["title"].get("ru", "") for i in v["ingredients"]}

    cats = {}
    for c in v["categories"]["main"] + v["categories"]["coupons"]:
        for pid in c["products"]:
            cats.setdefault(str(pid), []).append(c["title"] or "Купоны")

    # A dish is orderable on its own if it's listed in a category, or is a size
    # variant of something that is (sizes are picked on the listed product's card).
    variant_of = {str(p): str(g["id"]) for g in v["variants"].values() for p in g["products"]}
    listed_variants = {variant_of[p] for p in cats if p in variant_of}

    dishes, combos = [], []
    for pid, p in products.items():
        if p["type"] == "Modifier" or p.get("stopList") or not p.get("clickCollect"):
            continue
        base = {
            "id": pid,
            "title": p["title"].strip().lstrip("﻿"),
            "cats": cats.get(pid, []),
            "price": rub(p["price"]),
            "oldPrice": rub(p.get("oldPrice", p["price"])),
        }
        if p["type"] == "Dish":
            size = first(p.get("volume")) or 0
            variant = variant_of.get(pid)
            dishes.append(base | {
                "variant": variant,
                "orderable": pid in cats or variant in listed_variants,
                "unit": "ml" if "ml" in (p.get("volume") or {}) else "g",
                "size": size,
                "flavor": flavor(ingredient_names.get(i, "") for i in p["ingredients"]),
                # per 100 g/ml; zeros mean "not published" (sauces, toppings)
                "per100": {
                    "kcal": first(p.get("energy")) or 0,
                    "protein": first(p.get("proteins")) or 0,
                    "fat": first(p.get("fats")) or 0,
                    "carbs": first(p.get("carbs")) or 0,
                },
            })
        elif p["type"] == "Combo":
            combos.append(base | {
                "short": p.get("short") or p.get("spec") or "",
                "code": p.get("code"),
                "groups": [
                    {
                        "title": g["title"].strip(),
                        "min": g["downLimit"] or 0,
                        "max": g["upLimit"],
                        "options": [
                            {"id": str(m["productId"]), "title": m["title"]["ru"].strip(), "price": rub(m["price"])}
                            for m in g["modifiers"]
                            if not m.get("stopList")
                        ],
                    }
                    for g in p["modifierGroups"]
                ],
            })

    store = {"storeId": v["storeId"], "captured": captured, "currency": v["currency"],
             "dishes": dishes, "combos": combos}
    with open(OUT, "w") as f:
        json.dump(store, f, ensure_ascii=False, indent=1)
    print(f"store {v['storeId']} @ {captured}: {len(dishes)} dishes "
          f"({sum(d['orderable'] for d in dishes)} orderable), {len(combos)} combos -> {OUT}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "clickcollect.har")
