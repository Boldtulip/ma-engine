# Succession Radar 接班雷达

**An open-source M&A origination engine for China.** It screens private
companies, estimates which owners are approaching succession without a
successor, scores every company with checkable reasons, and drafts the
first deal documents a banker would write.

China's first generation of private entrepreneurs — the founders of the
1980s and 1990s — is reaching retirement age at the same time. Research
groups estimate that **over 3 million private companies** will face a
succession decision within ten years, and in surveys a large share of
the second generation says it does not want to take over. Japan went
through the same transition ten years earlier, and deal *sourcing* —
finding the companies before anyone else — turned out to be the
bottleneck of the entire market. This project is the sourcing layer,
open-sourced.

```
 universe of companies          signals                output
┌─────────────────────┐   ┌─────────────────┐   ┌──────────────────────┐
│ adapters/           │   │ owner age        │   │ ranked target list   │
│  dummy data (bundled)│──▶│ owner tenure     │──▶│ succession score     │
│  A-share disclosures │   │ visible heir?    │   │ + reasons            │
│  your CSV            │   │ sell pressure    │   │ buyer shortlist      │
│  QCC API (your keys) │   └─────────────────┘   │ deal dossier         │
└─────────────────────┘                          └──────────────────────┘
```

## Quickstart

```bash
git clone <this repo> && cd succession-radar
pip install -e .
radar demo
```

`radar demo` screens 200 bundled synthetic companies and prints the
ranked pipeline in seconds. No API keys, no accounts, no setup.

```
  #  score  company                    owner    signal summary
  1     68  山东凯丰五金有限公司        宋国庆   宋国庆 is the only person in the shareholder and executive records.
  2     60  山东华丰食品有限公司        刘桂英   刘桂英 is the only person in the shareholder and executive records.
  ...
```

Then write the full dossier for any company:

```bash
radar dossier --name 山东凯丰
```

The dossier contains the succession analysis, a ranked buyer shortlist
with a written rationale per buyer type, a suggested deal shape, and
the open questions a banker would verify first. With an Anthropic API
key set (`ANTHROPIC_API_KEY`), Claude writes the full analyst version;
without one, a deterministic template version is produced.

## How the scoring works

Chinese registries publish shareholder names, capital, and change
records — but **not ages**. The engine works around that gap with
signals that are all computable from public data:

| Signal | What it reads | Example reason it produces |
|---|---|---|
| Owner age | Disclosed age where it exists; otherwise the owner's **given name**. Chinese given names follow strong generational fashions: 建国 points to ~1950, 子轩 to ~2005. | "王建国 is estimated around 71 years old (given name '建国' peaks in the 1950s)." |
| Owner tenure | Legal-representative change records (变更记录), which are public. | "王建国 has been legal representative for 34 years." |
| Visible heir | Whether a younger person sharing the owner's surname appears among shareholders or executives. | "None of the 3 other people on record share the owner's surname 王." |
| Sell pressure | Equity pledges (股权出质, public) and published litigation. | "89% of the controlling stake is pledged." |

Every score decomposes into sentences like these. A signal only moves
the score as far as its confidence allows: an age estimated from a name
counts for about half of a disclosed age, and missing data pulls a
score down, never up.

The weights in `scoring/weights.yaml` are **illustrative defaults**.
Calibrating them requires outcome data — which companies actually
sold — and that data is what a practitioner accumulates over time. It
is not in this repository.

The bundled name-cohort table is a small demonstration subset. For
production use, plug in the full ChineseNames database (Bao et al.,
birth-year distributions for 1.2 billion people, 1930–2008).

## The knowledge base

The `knowledge/` folder encodes how a China M&A professional thinks,
as plain data files the LLM reads and any person can audit:

- **`buyers_china.yaml`** — who buys private SMEs in China: listed
  companies, industrial M&A funds, local state platforms, search
  funds, trade buyers, foreign strategics — each with motives,
  preferences, and constraints.
- **`fit_criteria.yaml`** — what makes a target good, and the red
  flags that kill deals in diligence.
- **`deal_structures.yaml`** — the deal shapes that fit succession
  sales, from majority-with-transition to fund SPV structures.
- **`origination_playbook.yaml`** — how professional sourcing works:
  buyer-list tiering, seller-intent signals, documented outreach
  funnel benchmarks, and the canonical teaser and target-profile
  formats.
- **`valuation_heuristics.yaml`** — SME multiples by size, the size
  discount, key-man discounts, and standard structure parameters
  (rollover, seller notes, earnouts).
- **`seller_economics.yaml`** — what the founder actually walks away
  with: the 20% individual income tax on share transfers, when the
  authorities assess the price themselves, who withholds, and the
  asymmetry that decides post-closing risk — a performance
  undertaking given by the founder personally is fully enforceable,
  while one given by the company often is not.

Every number in these files carries a confidence tag — well-sourced,
medium, or heuristic — so the model and the reader both know how much
weight it deserves.

Nothing is hidden in a prompt that is not also in these files. Extend
them like data, not like code.

## Bring your own data

The engine is open. The fuel is yours:

- **Bundled synthetic data** — works instantly, every name fictional.
- **A-share disclosures** — `radar score --ashare`. Listed companies
  must publish their chairman's exact age, so this is the one segment
  where the most important signal is a fact rather than an estimate.
  Free, public, no credentials. See below.
- **Your CSV** — `radar score --csv yourfile.csv` with your own
  research.
- **QCC official API** (`adapters/qcc.py`) — the private-company path.
  Requires your own corporate-verified credentials on openapi.qcc.com
  (or qcckyc.com outside mainland China).

### The A-share adapter

```bash
pip install -e ".[ashare]"
radar score --ashare --limit 200        # try it on a slice first
radar score --ashare                    # the whole market, ~20-40 min
```

It reads four public sources: the listed-company universe, the
chairman's disclosed age and appointment date, the actual controller
(实际控制人), and the weekly equity-pledge file. It then keeps only the
privately controlled companies — ownership type is not published as a
field anywhere, so it is inferred from the controller's name, the same
convention the academic databases use.

Real output from a live run:

```
  #  score  company        owner     signal summary
  1     52  丽珠集团        朱保国     朱保国 is 64 years old (disclosed).
  2     50  深华发A         李中秋     李中秋 is 62 years old (disclosed).
  3     40  胜利股份        许铁良     许铁良 is 63 years old (disclosed).
```

**One implementation note worth knowing if you work from outside
China.** These endpoints are not geo-blocked, but opening a new TLS
connection to them from abroad costs around forty seconds, while
reusing an open one costs a fraction of a second. The adapter keeps
one persistent session per worker thread. This is also why the obvious
library wrappers appear to hang from abroad: they open a fresh
connection for every call.

## Legal and ethical boundaries

This project draws a hard line, on purpose:

1. **No scraping.** Chinese courts have issued criminal convictions
   for scraping registry and platform data behind anti-bot measures,
   and rejected "it was already public" as a defense. The only
   private-company data path this project supports is the official,
   licensed API — with your own credentials.
2. **Estimates are labeled as estimates.** An age inferred from a name
   is a probability, not a fact, and every output says so.
3. **Scores are screening aids, not claims about people.** The engine
   ranks where a professional should *look first*. It never asserts
   that a named individual intends to sell, retire, or anything else.

## Roadmap

- [x] A-share adapter reading live public disclosures
- [ ] Ship the scored dataset of listed private companies
- [ ] Resolve controllers held through intermediate holding companies
      (today those fall into "other legal person" rather than being
      traced up the chain)
- [ ] Full ChineseNames cohort integration
- [ ] QCC adapter reference implementation
- [ ] Buyer-side matching against a real acquirer universe

## License

MIT.
