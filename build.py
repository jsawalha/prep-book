#!/usr/bin/env python3
"""
Prep Book builder.

Reads recipes.md (Instagram captions pasted under "# Recipe Name" headings),
parses each one into structured data, and writes a single self-contained
index.html you can open on your phone.

    python build.py            # writes index.html
    python build.py --serve    # builds, then serves on your Wi-Fi at :8000

Only uses the Python standard library.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path

HERE = Path(__file__).parent
RECIPES_FILE = HERE / "recipes.md"
GUIDE_FILE = HERE / "guide.md"            # the Plan tab
TEMPLATE_FILE = HERE / "template.html"
OUT_FILE = HERE / "index.html"          # full standalone page (GitHub Pages, local)
FRAGMENT_FILE = HERE / "artifact.html"  # same page without <html>/<head> wrapper (claude.ai)

# --------------------------------------------------------------------------
# Units
# --------------------------------------------------------------------------
# Every spelling you might see -> one canonical unit.
UNIT_ALIASES = {
    "tsp": "tsp", "tsps": "tsp", "teaspoon": "tsp", "teaspoons": "tsp",
    "tbsp": "tbsp", "tbsps": "tbsp", "tbs": "tbsp", "tablespoon": "tbsp", "tablespoons": "tbsp",
    "cup": "cup", "cups": "cup",
    "lb": "lb", "lbs": "lb", "pound": "lb", "pounds": "lb",
    "oz": "oz", "ounce": "oz", "ounces": "oz",
    "g": "g", "gram": "g", "grams": "g",
    "kg": "kg", "kgs": "kg",
    "ml": "ml", "l": "l", "liter": "l", "litre": "l", "liters": "l", "litres": "l",
    "clove": "clove", "cloves": "clove",
    "can": "can", "cans": "can",
    "slice": "slice", "slices": "slice",
    "scoop": "scoop", "scoops": "scoop",
    "pinch": "pinch", "dash": "dash",
    "second": "second", "seconds": "second", "sec": "second",
    "bunch": "bunch", "bunches": "bunch",
    "head": "head", "heads": "head",
    "stalk": "stalk", "stalks": "stalk",
    "packet": "packet", "packets": "packet", "pack": "packet",
    "handful": "handful", "handfuls": "handful",
    "block": "block", "blocks": "block",
    "leaf": "leaf", "leaves": "leaf",
    "piece": "piece", "pieces": "piece",
}
# "4 large leaves of cabbage": a size word sitting in front of a unit.
SIZE_WORDS = {"small", "medium", "large", "big", "heaping", "level"}
# Amounts in these units are left alone when you scale (1 second of spray oil is 1 second).
NO_SCALE_UNITS = {"second", "pinch", "dash"}

# Grocery-store aisle for the shopping list. First keyword hit wins; edit freely.
AISLES = [
    ("Skip", ["water", "ice water"]),       # never put these on the shopping list
    ("Sauces & oils", ["soy sauce", "vinegar", "oil", "sauce", "gochujang", "doenjang", "miso", "sambal",
                       "paste", "mirin", "mayo", "ketchup", "mustard", "honey", "syrup", "sriracha",
                       "broth", "stock", "salsa", "dressing"]),
    ("Spices & pantry", ["sugar", "salt", "black pepper", "white pepper", "peppercorn", "gochugaru", "seed",
                         "paprika", "cumin", "powder", "bouillon", "flake", "seasoning", "flour", "cornstarch",
                         "oregano", "cinnamon", "spice", "canned", "tuna"]),
    ("Meat & seafood", ["beef", "ribeye", "steak", "chuck", "eye of round", "chicken", "turkey", "pork",
                        "sirloin", "salmon", "shrimp", "fish", "lamb", "bacon", "sausage", "ground", "brisket",
                        "thigh", "breast"]),
    ("Produce", ["onion", "cucumber", "garlic", "ginger", "pepper", "chili", "jalapeno", "lettuce", "cabbage",
                 "carrot", "tomato", "lime", "lemon", "cilantro", "parsley", "basil", "potato", "avocado",
                 "broccoli", "spinach", "mushroom", "enoki", "zucchini", "scallion", "kimchi", "corn",
                 "bean sprout", "edamame"]),
    ("Dairy, eggs & tofu", ["egg", "milk", "cheese", "yogurt", "butter", "cream", "tofu"]),
    ("Grains & bread", ["rice", "rice cake", "noodle", "pasta", "tortilla", "bread", "bun", "oat", "quinoa"]),
]

# Words dropped from an ingredient name when matching it inside a cooking step.
DESCRIPTORS = {
    "thinly", "thickly", "finely", "sliced", "minced", "diced", "chopped", "grated", "shredded",
    "medium", "large", "small", "fresh", "raw", "cooked", "extra", "boneless", "skinless", "lean",
    "whole", "uncooked", "peeled", "light", "pan", "fried",
}

UNICODE_FRACTIONS = {"½": 1 / 2, "⅓": 1 / 3, "⅔": 2 / 3, "¼": 1 / 4, "¾": 3 / 4,
                     "⅛": 1 / 8, "⅜": 3 / 8, "⅝": 5 / 8, "⅞": 7 / 8}

# --------------------------------------------------------------------------
# Data model
# --------------------------------------------------------------------------
@dataclass
class Ingredient:
    id: int
    section: str
    raw: str                 # the line exactly as written
    qty: float | None        # None = no number ("salt to taste")
    qty_max: float | None    # for ranges like 2-3
    unit: str | None         # canonical unit or None for counts ("24 green onions")
    name: str                # "thinly sliced ribeye raw"
    note: str                # text in parentheses / after a comma
    core: str                # "ribeye" (used for step matching)
    key: str                 # singular core name, used to merge the shopping list
    aisle: str
    scalable: bool


@dataclass
class Step:
    n: int
    text: str
    tip: bool
    uses: list[int] = field(default_factory=list)   # ingredient ids mentioned in this step


@dataclass
class Recipe:
    slug: str
    title: str
    link: str
    tags: list[str]
    servings: float
    macros: dict[str, float]
    sections: list[str]
    ingredients: list[Ingredient]
    steps: list[Step]
    warnings: list[str]
    keeps: str = ""                                       # "keeps:" line (storage)
    notes: list[str] = field(default_factory=list)        # your own "### ..." notes
    advice: list[str] = field(default_factory=list)       # "> ..." prep advice lines


# --------------------------------------------------------------------------
# Parsing helpers
# --------------------------------------------------------------------------
QTY_RE = re.compile(
    r"^(?P<a>\d+\s+\d+/\d+|\d+/\d+|\d*\.\d+|\d+)?(?P<uf>[½⅓⅔¼¾⅛⅜⅝⅞])?"
    r"(?:\s*(?:-|–|to)\s*(?P<b>\d+\s+\d+/\d+|\d+/\d+|\d*\.\d+|\d+))?\s*"
)


def to_number(s: str) -> float:
    s = s.strip()
    if " " in s:                       # mixed number "1 1/2"
        whole, frac = s.split()
        return float(whole) + to_number(frac)
    if "/" in s:
        n, d = s.split("/")
        return float(n) / float(d)
    return float(s)


def slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-") or "recipe"


def singular(word: str) -> str:
    if word.endswith("ies") and len(word) > 4:
        return word[:-3] + "y"
    if word.endswith(("oes", "shes", "ches")):
        return word[:-2]
    if word.endswith("s") and not word.endswith("ss") and len(word) > 3:
        return word[:-1]
    return word


def core_name(name: str) -> str:
    words = [w for w in re.findall(r"[a-zA-Z']+", name.lower()) if w not in DESCRIPTORS]
    return " ".join(words) or name.lower()


def aisle_for(name: str) -> str:
    for aisle, keywords in AISLES:
        if any(re.search(rf"\b{re.escape(k)}(?:s|es)?\b", name, re.I) for k in keywords):
            return aisle
    return "Other"


def parse_ingredient(line: str, section: str, idx: int) -> Ingredient:
    text = re.sub(r"^\s*[-•*–]\s*", "", line).strip()
    note = ""
    m = re.search(r"\(([^)]*)\)", text)
    if m:
        note = m.group(1).strip()
        text = (text[: m.start()] + text[m.end():]).strip()
    text = re.sub(r"\s{2,}", " ", text)
    if "," in text:                      # "14 oz chicken thighs, skinless, boneless, raw"
        text, _, extra = text.partition(",")
        note = ", ".join(x for x in (extra.strip(), note) if x)

    qty = qty_max = None
    m = QTY_RE.match(text)
    if m and (m.group("a") or m.group("uf")):
        qty = (to_number(m.group("a")) if m.group("a") else 0) + UNICODE_FRACTIONS.get(m.group("uf") or "", 0)
        if m.group("b"):
            qty_max = to_number(m.group("b"))
        text = text[m.end():]

    unit = None
    first, _, rest = text.partition(" ")
    nxt = rest.partition(" ")[0].lower()
    if first.lower() in SIZE_WORDS and nxt in UNIT_ALIASES and nxt not in ("g", "l"):
        note = ", ".join(x for x in (first.lower(), note) if x)
        first, _, rest = rest.partition(" ")
    if first.lower().rstrip(".") in UNIT_ALIASES and rest:
        unit = UNIT_ALIASES[first.lower().rstrip(".")]
        text = rest
    text = re.sub(r"^of\s+", "", text.strip())

    return Ingredient(
        id=idx, section=section, raw=line.strip().lstrip("-•* ").strip(),
        qty=qty, qty_max=qty_max, unit=unit, name=text, note=note,
        core=core_name(text), key=" ".join(core_name(text).split()[:-1] + [singular(core_name(text).split()[-1])]) if core_name(text).split() else text.lower(),
        aisle=aisle_for(text),
        scalable=qty is not None and unit not in NO_SCALE_UNITS,
    )


def term_pattern(core: str) -> re.Pattern:
    """Regex matching an ingredient's core name, singular or plural."""
    words = core.split()
    words[-1] = re.escape(singular(words[-1])) + r"(?:s|es)?"
    body = r"\s+".join([re.escape(w) for w in words[:-1]] + [words[-1]])
    return re.compile(rf"\b{body}\b", re.I)


# Words too generic to identify an ingredient on their own.
GENERIC_WORDS = {"leaf", "leaves", "sauce", "oil", "paste", "powder", "seed", "seeds", "broth", "juice",
                 "sugar", "pepper", "peppers", "water", "taste", "stock", "flakes", "chili"}
PROTEIN_WORDS = {"chicken", "beef", "turkey", "salmon", "steak", "pork", "tuna", "shrimp", "fish", "tofu"}


def match_terms(ing: Ingredient) -> list[str]:
    """Names to look for in step text: the full core name, then shorter fallbacks
    ("atlantic farm raised salmon" -> "salmon", "firm tofu" -> "tofu")."""
    words = ing.core.split()
    terms = [ing.core]
    if len(words) > 1 and words[-1] not in GENERIC_WORDS:
        terms.append(words[-1])
    if ing.aisle in ("Meat & seafood", "Dairy, eggs & tofu"):     # "raw chicken" -> chicken thighs
        terms += [w for w in words[:-1] if w in PROTEIN_WORDS]
    return terms


def link_steps(steps: list[Step], ingredients: list[Ingredient]) -> None:
    """Figure out which ingredients each step mentions.

    When a name appears in several components (soy sauce in the salad AND the
    marinade), pick the component that has the most other matches in that step.
    """
    by_core: dict[str, list[Ingredient]] = {}
    for ing in ingredients:
        by_core.setdefault(ing.core, []).append(ing)
    # (term, core) pairs, longest term first so "green onions" wins over "onions"
    pairs = sorted({(t, ing.core) for ing in ingredients for t in match_terms(ing)},
                   key=lambda p: (-len(p[0]), p[0] != p[1]))

    for step in steps:
        # Skip tips and plating steps ("plate half your rice"): full-batch amounts there would mislead.
        if step.tip or re.search(r"\bhalf\b", step.text, re.I):
            continue
        text = re.sub(r"rice cooker('s)?", lambda m: " " * len(m.group()), step.text, flags=re.I)
        taken: list[tuple[int, int]] = []
        found: list[str] = []
        for term, core in pairs:
            if core in found:
                continue
            for m in term_pattern(term).finditer(text):
                if any(m.start() < e and s < m.end() for s, e in taken):
                    continue
                taken.append((m.start(), m.end()))
                found.append(core)
                break
        section_hits: dict[str, int] = {}
        for core in found:
            for ing in by_core[core]:
                section_hits[ing.section] = section_hits.get(ing.section, 0) + 1
        for core in found:
            best = max(by_core[core], key=lambda i: section_hits[i.section])
            step.uses.append(best.id)
        # "add your sliced meat" -> link the recipe's meat even though the name differs
        if re.search(r"\b(meat|protein)\b", text, re.I):
            for ing in ingredients:
                if ing.aisle == "Meat & seafood" and ing.id not in step.uses:
                    step.uses.append(ing.id)
        step.uses.sort()


META_KEYS = ("link", "tags", "servings", "source", "keeps")


def clean_title(t: str) -> str:
    t = t.strip().rstrip(".,;: ")
    return t[:1].upper() + t[1:] if t else "Untitled"


def parse_recipe(title: str, body: str) -> Recipe:
    warnings: list[str] = []
    meta: dict[str, str] = {}
    notes: list[str] = []
    advice: list[str] = []
    lines: list[str] = []

    for line in body.splitlines():
        s = line.strip()
        mm = re.match(rf"^({'|'.join(META_KEYS)})\s*:\s*(.+)$", s, re.I)
        if mm and not lines:                         # meta only counts above the caption
            meta[mm.group(1).lower()] = mm.group(2).strip()
        elif s.startswith("###"):                    # your own note
            notes.append(s.lstrip("#").strip())
        elif s.startswith(">"):                      # prep advice
            advice.append(s.lstrip(">").strip())
        elif re.match(r"^#\w", s):                   # hashtags
            continue
        else:
            if s or lines:
                lines.append(line)
    text = "\n".join(lines)

    macros = {}
    for key in ("protein", "carbs", "fat", "calories"):
        m = re.search(rf"\b{key}\b\s*:?\s*(\d+(?:\.\d+)?)", text, re.I)
        if m:
            macros[key] = float(m.group(1))
    if len(macros) < 4:
        warnings.append("Some macros were not found")

    servings = None
    if "servings" in meta:
        servings = float(meta["servings"])
    else:
        m = re.search(r"\b(?:makes|serves|yields?)\s+(\d+(?:\.\d+)?)", text, re.I) \
            or re.search(r"(\d+(?:\.\d+)?)\s+(?:servings|meal preps|portions)", text, re.I)
        if m:
            servings = float(m.group(1))
    if not servings:
        servings = 1
        warnings.append("Serving count not found; assumed 1 (add 'servings: N' under the title)")

    ingredients: list[Ingredient] = []
    sections: list[str] = []
    steps: list[Step] = []
    section = "Ingredients"
    in_ingredients = False
    in_steps = False
    for line in lines:
        s = line.strip()
        if not s:
            continue
        if re.match(r"^how to make|^instructions|^directions|^method", s, re.I):
            in_steps = True
            continue
        step_m = re.match(r"^(\d+)[.)]\s+(.*)", s)
        if step_m:
            in_steps = True
            stext = step_m.group(2).strip()
            tip = bool(re.match(r"^(pro\s*)?tip\b", stext, re.I))
            if tip:
                stext = re.sub(r"^(pro\s*)?tip\s*:?\s*", "", stext, flags=re.I)
            stext = stext[:1].upper() + stext[1:]
            steps.append(Step(n=len(steps) + 1, text=re.sub(r"\s+([.,!])", r"\1", stext), tip=tip))
            continue
        if in_steps:
            continue
        if re.match(r"^ingredients\b", s, re.I):
            in_ingredients = True
            continue
        sec_m = re.match(r"^\[(.+)\]$", s) or re.match(r"^\*\*(.+)\*\*:?$", s) or re.match(r"^for the (.+?):?$", s, re.I)
        if not sec_m and in_ingredients and len(s) <= 40 and not re.search(r"\d|:$", s) \
                and not re.match(r"^[-•*–]", s):
            sec_m = re.match(r"^(.+)$", s)            # plain header line like "Chili Sauce"
        if sec_m:
            section = sec_m.group(1).strip().rstrip(":")
            continue
        if re.match(r"^[-•*–]\s+", s):
            ing = parse_ingredient(s, section, len(ingredients))
            ingredients.append(ing)
            if section not in sections:
                sections.append(section)

    # Tips are numbered like steps in the captions; keep them out of the numbering.
    n = 0
    for st in steps:
        if not st.tip:
            n += 1
            st.n = n
        else:
            st.n = 0

    if not ingredients:
        warnings.append("No ingredient lines found (they should start with '- ')")
    if not steps:
        warnings.append("No numbered steps found")
    link_steps(steps, ingredients)

    title = clean_title(title)
    return Recipe(
        slug=slugify(title), title=title, link=meta.get("link") or meta.get("source", ""),
        tags=[t.strip().lower() for t in meta.get("tags", "").split(",") if t.strip()],
        servings=servings, macros=macros, sections=sections,
        ingredients=ingredients, steps=steps, warnings=warnings,
        keeps=meta.get("keeps", ""), notes=notes, advice=advice,
    )


def parse_file(path: Path) -> list[Recipe]:
    """Each recipe starts with a '# Title' or '## Title' line ('###' lines are your notes)."""
    content = path.read_text(encoding="utf-8")
    chunks = re.split(r"^#{1,2}[ \t]+", content, flags=re.M)
    recipes = []
    seen = set()
    for chunk in chunks[1:]:
        title, _, body = chunk.partition("\n")
        r = parse_recipe(title, body)
        base, i = r.slug, 2
        while r.slug in seen:
            r.slug = f"{base}-{i}"
            i += 1
        seen.add(r.slug)
        recipes.append(r)
    return recipes


# --------------------------------------------------------------------------
# Plan page (guide.md -> HTML)
# --------------------------------------------------------------------------
def inline_md(t: str) -> str:
    t = html.escape(t)
    t = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", t)
    t = re.sub(r"\[\[(.+?)\]\]", lambda m: f'<a href="#r-{slugify(m.group(1))}">{m.group(1)}</a>', t)
    return t


def cut_table(recipes: list[Recipe]) -> str:
    """Recipes ranked by protein per 100 calories (higher = better for a cut)."""
    rows = [r for r in recipes if r.macros.get("calories")]
    rows.sort(key=lambda r: r.macros.get("protein", 0) / r.macros["calories"], reverse=True)
    out = ['<div class="tbl"><table><thead><tr><th>Recipe</th><th>Score</th><th>Cal</th><th>Prot.</th>'
           '</tr></thead><tbody>']
    for r in rows:
        m = r.macros
        out.append(f'<tr><td><a href="#r-{r.slug}">{html.escape(r.title)}</a></td><td><b>{m.get("protein", 0) / m["calories"] * 100:.1f}</b></td>'
                   f'<td>{m["calories"]:g}</td><td>{m.get("protein", 0):g}g</td></tr>')
    out.append("</tbody></table></div>")
    return "".join(out)


def render_guide(path: Path, recipes: list[Recipe]) -> str:
    """Tiny markdown subset: ## / ### headings, - bullets, 1. lists, paragraphs, **bold**,
    [[Recipe Title]] links, and {{cut_table}} for the auto-generated ranking."""
    if not path.exists():
        return ""
    out: list[str] = []
    lst = None
    para: list[str] = []

    def flush():
        nonlocal lst
        if para:
            out.append(f"<p>{inline_md(' '.join(para))}</p>")
            para.clear()
        if lst:
            out.append(f"</{lst}>")
            lst = None

    for raw in path.read_text(encoding="utf-8").splitlines():
        s = raw.strip()
        if not s:
            flush()
            continue
        if s == "{{cut_table}}":
            flush(); out.append(cut_table(recipes)); continue
        h = re.match(r"^(#{1,3})\s+(.*)", s)
        if h:
            flush()
            lvl = min(len(h.group(1)) + 1, 4)
            out.append(f"<h{lvl}>{inline_md(h.group(2))}</h{lvl}>")
            continue
        b = re.match(r"^[-*]\s+(.*)", s)
        o = re.match(r"^\d+[.)]\s+(.*)", s)
        if b or o:
            kind = "ul" if b else "ol"
            if para:
                out.append(f"<p>{inline_md(' '.join(para))}</p>"); para.clear()
            if lst != kind:
                if lst:
                    out.append(f"</{lst}>")
                out.append(f"<{kind}>")
                lst = kind
            out.append(f"<li>{inline_md((b or o).group(1))}</li>")
            continue
        if lst:
            out.append(f"</{lst}>"); lst = None
        para.append(s)
    flush()
    return "\n".join(out)


# --------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------
FULL_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="Prep Book">
<meta name="apple-mobile-web-app-status-bar-style" content="default">
<style>:root{{padding-top:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bottom,0px)}}
body{{margin:0}} [hidden]{{display:none!important}} img{{max-width:100%}}</style>
</head>
<body>
{content}
</body>
</html>
"""


def build(recipes: list[Recipe]) -> None:
    data = {"recipes": [asdict(r) for r in recipes], "guide": render_guide(GUIDE_FILE, recipes)}
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    fragment = TEMPLATE_FILE.read_text(encoding="utf-8").replace("__RECIPES_JSON__", payload)
    FRAGMENT_FILE.write_text(fragment, encoding="utf-8")
    OUT_FILE.write_text(FULL_PAGE.format(content=fragment), encoding="utf-8")


def report(recipes: list[Recipe]) -> None:
    for r in recipes:
        print(f"✓ {r.title}  ({len(r.ingredients)} ingredients, "
              f"{sum(not s.tip for s in r.steps)} steps, makes {r.servings:g})")
        for w in r.warnings:
            print(f"    ⚠ {w}")
    print(f"\nWrote {OUT_FILE.name} ({len(recipes)} recipes)")


def serve(port: int) -> None:
    import http.server
    import socket
    import socketserver
    import os

    os.chdir(HERE)
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
    except OSError:
        ip = "your-computer-ip"
    print(f"\nOn your iPhone (same Wi-Fi) open:  http://{ip}:{port}/index.html")
    print("Ctrl+C to stop.")
    with socketserver.TCPServer(("0.0.0.0", port), http.server.SimpleHTTPRequestHandler) as httpd:
        httpd.serve_forever()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--serve", action="store_true", help="serve the page on your local network")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--json", action="store_true", help="print the parsed recipes as JSON and exit")
    args = ap.parse_args()

    recipes = parse_file(RECIPES_FILE)
    if not recipes:
        sys.exit("No recipes found. Each recipe in recipes.md should start with a line like '# Recipe Name'.")
    if args.json:
        print(json.dumps([asdict(r) for r in recipes], indent=2, ensure_ascii=False))
        return
    build(recipes)
    report(recipes)
    if args.serve:
        serve(args.port)


if __name__ == "__main__":
    main()
