# MA Engine

[![tests](https://github.com/Boldtulip/ma-engine/actions/workflows/tests.yml/badge.svg)](https://github.com/Boldtulip/ma-engine/actions/workflows/tests.yml)
[![license: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

MA Engine is an open-source engine for predictive deal sourcing. It
ranks companies by how likely the owner is to sell, and writes out the
reason behind every score.

It takes a list of companies with their shareholders, officers and
headline financials. Each company runs through a set of signals: the
owner's age, how long they have held the company, whether a successor
is visible in the records, and signs of financial pressure. Each
signal returns a value, a confidence and one sentence. The score is
their weighted sum, and the sentences are kept, so a ranking can be
read back as a list of statements that can be checked one by one. The
engine then matches each company against buyer types held in an
editable knowledge base and drafts a dossier.

**Strengths.** Every score decomposes into its reasons, so a ranking
can be argued with rather than taken on trust. The adapters, signals,
weights and knowledge base are separate and replaceable, so pointing
the engine at another market means writing an adapter and a config,
not changing the engine.

**Limitations.** It cannot know whether an owner wants to sell. The
signals are proxies, and a high score means a company is worth
looking at, not that it is for sale. Nothing here is calibrated: no
outcome data ships with the repository, so the weights and the curves
are judgment until you fit them to a record of real sales. Where an
age is not disclosed it is estimated from the owner's given name,
which is a probability and is labelled as one in the output. The
engine ranks and drafts; it does not value a company or replace
diligence.

The version in this repository is set up for one example market,
China, and runs on synthetic data. The founders who started China's
private companies in the 1980s and 1990s are reaching retirement age
at the same time. Estimates put the number of private companies facing
a succession decision in the next ten years at over three million, and
in surveys a large share of the second generation says it does not
want to take over. Japan went through the same transition about ten
years earlier, and there the hard part was finding the companies
before anyone else did.

<p align="center">
  <img src="docs/demo.svg" alt="Terminal output of ma-engine demo: a ranked list of fictional companies with a succession score and a one-line reason for each" width="880">
</p>

## Quickstart

```bash
git clone https://github.com/Boldtulip/ma-engine && cd ma-engine
pip install -e .
ma-engine demo
```

The demo scores 200 fictional companies and prints the ranking. It
needs no API key or account.

```
  #  score  company                  owner    signal summary
  1     59  江苏利昌包装有限公司     萧玉珍   萧玉珍 is the only person in the shareholder and executive records.
  2     58  上海威威电子有限公司     傅解放   傅解放 is the only person in the shareholder and executive records.
  ...
```

To see the full dossier for one company:

```bash
ma-engine dossier --name 上海威威
```

The dossier contains the succession analysis, a ranked list of buyer
types with the reasoning for each, notes on deal structure and on the
seller's position, and the points we check before spending more time
on a company. If `ANTHROPIC_API_KEY` is set, Claude writes the
dossier; if not, a template version is produced from the same facts.

## Data

**This repository ships synthetic data only.** Every company and
person in the bundled data is invented, and nothing about real
companies or people is committed here.

The engine can read real company data through its adapters. If you
do that, you are responsible for complying with the data-protection
and other rules that apply to you and to the data, in whatever market
you are working in. For the Chinese sources described below that
includes the Personal Information Protection Law and the rules on
moving data across borders. Any table the engine produces from real
data names living individuals next to a score, and it belongs on the
machine that generated it.

### Adapters

All adapters produce the same records, so the scoring does not care
where the data came from. Four are included:

- **Synthetic demo data.** Bundled with the repository.
- **Your own CSV.** `ma-engine score --csv yourfile.csv`. The expected
  columns are documented in `adapters/csv_adapter.py`. This is the
  simplest way to use the engine on any market.
- **A-share disclosures.** `ma-engine score --ashare`. An example
  adapter for one real source: companies listed in China must publish
  their chairman's age, so for them the most important signal is a
  disclosed fact rather than an estimate. Free, no credentials.
  Details below.
- **QCC official API.** `adapters/qcc.py`. The shape of an adapter for
  unlisted Chinese companies. It needs your own corporate-verified
  credentials on openapi.qcc.com, or on qcckyc.com from outside
  mainland China.

To add a market, write an adapter that returns the `Company` records
defined in `adapters/base.py`.

### The A-share adapter

```bash
pip install -e ".[ashare]"
ma-engine score --ashare --limit 200      # a first slice
ma-engine score --ashare                  # the whole market, 20 to 40 minutes
ma-engine export --ashare                 # write a CSV and a ranked watchlist
```

The adapter reads four public sources: the list of listed companies,
each chairman's disclosed age and appointment date, the actual
controller (实际控制人), and the weekly equity-pledge file. It keeps
only privately controlled companies. Whether a company is private or
state-owned is not published as a field anywhere, so it is inferred
from the controller's name, which is how the academic databases do it
too.

One thing to know if you run this from outside mainland China. The
endpoints are not blocked, but opening a new connection to them from
abroad takes about forty seconds, while a connection that is already
open answers in a fraction of a second, so the adapter keeps one
persistent session per worker thread. This is also why common Python
wrappers for the same endpoints appear to hang from abroad: they open
a new connection for every call.

## How the scoring works

The engine runs a set of signals over each company. A signal reads one
thing about the company and returns a number between 0 and 1, a
confidence between 0 and 1, and one sentence saying what it found. The
score is a weighted sum of the signals, and the sentences are kept, so
every score can be read back as a short list of things to check. A
signal only moves the score as far as its confidence allows, and
missing data lowers a score rather than raising it.

Which signals run, what parameters they use, and how much each one
weighs is set in one file, `scoring/config.yaml`. To use your own,
set `MA_ENGINE_SCORING_CONFIG` to its path.

### The bundled signals are an example

The four signals in the bundled config are written for the China
case, where the public records give shareholder names, registered
capital and change records, but not ages:

| Signal | What it reads | Example of the reason it writes |
|---|---|---|
| Owner age | The disclosed age where there is one. Otherwise the owner's given name: Chinese given names follow strong generational fashions, so 建国 points to a birth around 1950 and 子轩 to around 2005. | "王建国 is estimated around 71 years old (given name '建国' peaks in the 1950s)." |
| Owner tenure | Change records for the legal representative, which are public. | "王建国 has held the role for 34 years (since 1992)." |
| Visible heir | Whether a younger person with the owner's surname appears among the shareholders or executives. | "None of the 3 other people on record share the owner's surname 王." |
| Sell pressure | Pledged equity (股权出质, public) and published litigation. | "89% of the controlling stake is pledged." |

Every number behind them is in the config: the age curve, the tenure
thresholds, the generation gap used to spot an heir, the weights. The
age curve is the one worth explaining.

The age curve does not simply rise with age. An owner still running
the company at 82 has shown over many years that he does not intend to
sell, and by then the succession has usually been settled one way or
another. The owner most likely to actually sell is in his sixties:
past the statutory retirement age, still in good health, with a
business that is still easy to hand over. So the curve rises through
the fifties, peaks between about 63 and 72, and declines after that
without reaching zero.

An age estimated from a name is given about half the confidence of a
disclosed age, so it moves the score half as far. The bundled table of
names and birth cohorts is a small demonstration subset; for serious
use, replace it with the full ChineseNames database (Bao et al.,
birth-year distributions covering 1.2 billion people, 1930-2008).

None of these numbers is calibrated. The way to improve them is to
compare them against a record of which companies actually sold, and
that record is built up deal by deal; it is not part of this
repository.

### Writing your own signal

A signal is a function that takes a company and a dictionary of
parameters and returns a `Signal`. Register it under a name, list its
module in the config, and give it a weight:

```python
from ma_engine.signals import Signal, signal

@signal("concentrated_ownership")
def concentrated_ownership(company, params):
    owner = company.controller()
    pct = owner.ownership_pct if owner else 0
    return Signal("concentrated_ownership", min(pct / 67, 1.0), 0.8,
                  f"{owner.name} holds {pct:.0f}% of the company.")
```

```yaml
signals:
  concentrated_ownership:
    weight: 0.2
plugins:
  - my_signals
```

`examples/custom_signals.py` and `examples/scoring_config.yaml` are a
complete working version of this, which also drops two of the bundled
signals and reshapes the age curve. Run it with
`MA_ENGINE_SCORING_CONFIG=examples/scoring_config.yaml ma-engine demo`
from the repository root.

### Fitting the config to outcomes

Everything in the config is a number, so the whole scoring step can be
treated as a small model and fitted. The score is a sum over signals
of weight times confidence times a curve or threshold applied to one
feature. That is an additive model: each signal is a shape function of one
feature, and the weights are its coefficients. There are no
interactions between features and no hidden layer, so every term can
be read off and checked. Fitting only the weights, and leaving the
curves as they are, is logistic regression on the signal values.

What it needs is a record of outcomes: which companies actually
changed hands. That record is yours. Put it in a CSV with two columns,
`company` (the name, or the source id such as `ashare:000001`) and
`sold` (1 or 0), then:

```bash
pip install -e ".[tune]"
ma-engine evaluate --labels outcomes.csv --csv companies.csv
ma-engine tune --labels outcomes.csv --csv companies.csv --trials 200 --out tuned.yaml
```

`evaluate` reports AUC, precision at the top of the list, and lift
(how many times more often a sale appears in the top k than at
random) for the current config. `tune` searches the weights, curve
points and thresholds with Optuna to maximise AUC on held-out folds,
reports before and after, and writes the fitted config. Judging on
held-out folds means the result is measured on companies it was not
fitted to.

Twenty labelled companies with five sales is the minimum the command
accepts; a few hundred with a few dozen sales is where the numbers
start to mean something.

## The knowledge base

The `knowledge/` folder holds what the engine knows about M&A in the
example market, as YAML files that the language model reads and that
anyone can open and check. The matching module and the dossier use
them, and nothing is in a prompt that is not also in these files.

- `buyers_china.yaml` describes who buys private companies in China
  (listed companies, industrial M&A funds, local state platforms,
  search funds, trade buyers, foreign strategics), what each of them
  wants, and what constrains them.
- `fit_criteria.yaml` lists what makes a company a good target and the
  problems that end deals in due diligence.
- `deal_structures.yaml` covers the deal structures that suit a
  succession sale.
- `origination_playbook.yaml` covers how we source deals: how buyer
  lists are built and ranked, what tells us a seller is serious,
  published outreach benchmarks, and the standard formats for a teaser
  and a target profile.
- `valuation_heuristics.yaml` gives multiples for small and mid-sized
  companies by size, and typical terms for rollover equity, seller
  notes and earnouts.
- `seller_economics.yaml` covers what the founder actually receives:
  the 20% individual income tax on share transfers, when the tax
  authority sets the price itself, who withholds the tax, and the fact
  that a performance undertaking given by the founder personally is
  enforceable while one given by the company often is not.

Every number in these files carries a confidence tag (well-sourced,
medium, or heuristic) so that the reader and the model both know how
much weight to give it.

For another market, write your own set of files in the same shape and
set `MA_ENGINE_KNOWLEDGE_DIR` to that folder.

## Rules the project follows

1. **Synthetic data only in this repository.** Nothing about real
   companies or people is distributed here.
2. **Real data is the user's responsibility.** Whoever runs the engine
   on real company data must comply with the rules that apply to them
   and to that data. The project does not do this for you.
3. **No scraping.** For the Chinese example, courts there have
   convicted people for scraping registry and platform data from
   behind anti-bot measures, and have rejected the argument that the
   data was already public. The only route to unlisted-company data
   that this project supports is an official API, with the user's own
   credentials.
4. **Estimates are marked as estimates.** An age inferred from a name
   is a probability, and every output says so.
5. **Scores are not claims about people.** A score says where to look
   first. It does not say that anyone intends to sell, retire, or
   anything else.

## Roadmap

- [ ] Resolve controllers held through intermediate holding companies.
      Today these are classed as "other legal person" instead of being
      traced up the chain.
- [ ] Integrate the full ChineseNames cohort database.
- [ ] Reference implementation of the QCC adapter.
- [ ] Match against a real universe of acquirers, not only buyer types.
- [ ] A second example market.

## License

MIT.
