# Prep Book

Paste Instagram recipe captions into `recipes.md`, push to GitHub, and get a phone-friendly recipe app. It has serving scaling, a step-by-step cook mode, a combined shopping list and a prep guide.

## Files

| File | What it is | Edit it? |
|---|---|---|
| `recipes.md` | Your recipes (pasted captions plus prep advice) | Yes, all the time |
| `guide.md` | The "Prep guide" tab | Yes |
| `build.py` | Parses everything and builds the page. Standard library only | To change parsing, units or grocery aisles |
| `template.html` | Page design and in-browser logic (scaling, shopping list, cook mode) | To change the look |
| `.github/workflows/pages.yml` | Rebuilds and publishes the site on every push | Rarely |
| `index.html` | Generated: the app itself | No, it's rebuilt every time |

## Put it on GitHub Pages (one-time setup)

1. Create a new repo on GitHub, e.g. `prep-book`, and push this folder to the `main` branch:
   ```bash
   cd prep-book
   git init -b main
   git add .
   git commit -m "Prep Book"
   git remote add origin https://github.com/<you>/prep-book.git
   git push -u origin main
   ```
2. In the repo, go to **Settings → Pages → Build and deployment → Source** and choose **GitHub Actions**.
3. Open the **Actions** tab. The "Build and deploy Prep Book" run takes about a minute. When it finishes, the site is at `https://<you>.github.io/prep-book/`.
4. On your iPhone, open that address in Safari, tap **Share → Add to Home Screen**, and it opens like an app.

Free GitHub accounts can only publish Pages from **public** repos. The recipes are public on Instagram anyway, but keep that in mind if you add personal notes.

After that, the workflow is: **edit `recipes.md` → commit → push.** GitHub runs `build.py` for you, so you don't even need to build locally. Running `python build.py` locally is still handy to check for parser warnings before you push.

## Adding a recipe

Start each recipe with a `# Title` (or `## Title`) line, add optional settings, then paste the whole caption. Junk like "Comment PREP…", "📩 Save this…" and hashtags is ignored.

```
# Chicken Shawarma Rice Bowl
link: https://www.instagram.com/p/XXXX/
tags: rice cooker, chicken
keeps: Fridge 3–4 days.
servings: 2        <- only needed if the caption has no "makes N" / "N servings"

### A note to yourself shows as "Your note" at the top of the recipe
> Lines starting with > show up under "Prep advice"

...paste the caption here...
```

What the parser picks up from the caption:

- `Protein:` / `Carbs:` / `Fat:` / `Calories:` for macros (per serving)
- `makes 2` / `per 2 servings` / `serves 4` for the batch size
- Section headers, either `[Bulgogi]` or a plain short line like `Chili Sauce` under the "Ingredients" line
- Ingredients: lines starting with `- `. Text after a comma or in brackets becomes a small note (`- 14 oz chicken thighs, skinless, boneless`)
- Steps: lines starting with `1.` `2.` … A step starting with "Pro tip:" becomes a tip box

`python build.py` prints a ✓ per recipe and a ⚠ if something is missing. `python build.py --json` shows exactly what was parsed.

## The Prep guide tab (`guide.md`)

Plain markdown with a few extras:

- `## Heading`, `- bullets`, `1. lists`, `**bold**`
- `[[Exact Recipe Title]]` becomes a link to that recipe
- `{{cut_table}}` is replaced with an auto-generated table ranking recipes by protein per 100 calories. It updates as you add recipes

## How scaling works

- Macros are per serving and stay the same. "This batch" multiplies them by your serving count.
- Ingredient amounts are treated as totals for the stated batch (even when the caption says "per serving", the amounts are clearly for the whole batch). Changing servings multiplies everything by `new ÷ original`.
- **Start from what you have:** enter, for example, 1.2 kg of ribeye, and it works out the servings and every other amount.
- Amounts round to sizes you can measure (¼, ⅓, ½, ⅔, ¾) and convert when that's easier (12 tbsp → ¾ cup). Weights also show kg/g.
- `second`, `pinch` and `dash` amounts don't scale (1 second of spray oil stays 1 second).
- In the cook view, each step lists the ingredients it uses with scaled amounts. Plating steps ("take half your rice…") don't, because the batch totals would be misleading there.

## Shopping list

Add recipes from their pages at the servings you want. Matching ingredients are combined, converted (e.g. 5 tbsp + ¼ cup soy sauce) and grouped by aisle. Water is left off. "Copy list" puts it on your clipboard for Notes or Reminders.

Checked items, servings and the shopping list are saved in your phone's browser, so each device keeps its own.

## Things to tweak

- **Grocery aisles:** `AISLES` in `build.py`. The first matching keyword wins, so order matters. Anything in the `Skip` aisle is left off the shopping list.
- **Units:** `UNIT_ALIASES`, `NO_SCALE_UNITS` in `build.py`.
- **Step-ingredient matching:** `link_steps()` / `match_terms()` in `build.py`.
- **Colours and fonts:** the `:root` block at the top of `template.html`.
- **Rounding:** `FRACS` and `tidy()` in `template.html`.

## Run it without GitHub

- `python build.py --serve` serves it on your Wi-Fi and prints the address to open on your phone.
- Or AirDrop `index.html` to your phone and open it from Files.
