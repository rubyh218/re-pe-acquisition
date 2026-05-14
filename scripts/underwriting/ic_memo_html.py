"""
ic_memo_html.py - HTML presentation renderer for IC memos.

Mirrors ic_memo.py's _dispatch but renders a single self-contained HTML deck
instead of a docx. Same payload, same engines. Each section becomes a slide,
keyboard-navigable (arrow keys / dots / space).

Aesthetic: editorial-meets-institutional. Serif display (Fraunces), serif body
(Newsreader), monospace figures (IBM Plex Mono). Bone/cream paper, oxblood
accent. Hairline rules. Tabular figures.

CLI:
    python -m scripts.underwriting.ic_memo_html deal.yaml [-o memo.html]
"""

from __future__ import annotations

import argparse
import html as _html
from pathlib import Path

import scripts  # noqa: F401

from .excel_summary import SummaryPayload
from .ic_memo import (
    CommercialMemoBlock,
    DCMemoBlock,
    InfraMemoBlock,
    MemoYearLine,
    _dispatch,
    _fmt_dollar,
    _fmt_dollar_m,
    _fmt_multiple,
    _fmt_pct,
    _fmt_per_denom,
)


# ---------------------------------------------------------------------------
# Slide builders -- each returns a string of <section class="slide">...</section>
# ---------------------------------------------------------------------------

def _esc(s: str) -> str:
    return _html.escape(str(s)) if s is not None else ""


def _slide_cover(p: SummaryPayload, slide_num: int, total: int) -> str:
    return f"""
<section class="slide slide-cover" data-slide="{slide_num}">
  <div class="cover-stamp">Private &amp; Confidential</div>
  <div class="cover-meta">
    <span>Investment Committee Memorandum</span>
    <span class="cover-meta-sep">/</span>
    <span>{_esc(p.close_date.strftime('%B %Y'))}</span>
  </div>
  <h1 class="cover-title">{_esc(p.deal_name)}</h1>
  <div class="cover-sub">
    <div class="cover-address">{_esc(p.address)}</div>
    <div class="cover-asset">{_esc(p.asset_class.upper())} &middot; {int(p.denom_value):,} {_esc(p.denom_label)}</div>
  </div>
  <div class="cover-anchor">
    <div class="cover-anchor-label">Purchase Price</div>
    <div class="cover-anchor-value">{_fmt_dollar_m(p.purchase_price)}</div>
    <div class="cover-anchor-sub">{_fmt_per_denom(p.purchase_price / p.denom_value, p.per_denom_label)}</div>
  </div>
  <div class="cover-footer">
    <span>Sponsor &middot; {_esc(p.sponsor)}</span>
    <span class="cover-meta-sep">/</span>
    <span>{_esc(p.deal_id)}</span>
  </div>
</section>
"""


def _slide_exec_summary(p: SummaryPayload, slide_num: int) -> str:
    rows = [
        ("Asset Class", _esc(p.asset_class.title())),
        (p.denom_label, f"{int(p.denom_value):,}"),
        ("Submarket", _esc(p.submarket)),
        ("Hold Period", f"{p.hold_yrs} years"),
        ("Purchase Price", _fmt_dollar(p.purchase_price)),
        ("All-In Basis", _fmt_dollar(p.all_in_basis)),
        (f"Basis {p.per_denom_label}", _fmt_per_denom(p.all_in_basis / p.denom_value, p.per_denom_label)),
        ("Going-In Cap", _fmt_pct(p.going_in_cap)),
        (f"Yr {p.stab_yr} Stab Cap (on price)", _fmt_pct(p.stabilized_cap)),
        (f"Yr {p.stab_yr} YoC (all-in basis)", _fmt_pct(p.roc_trended)),
        ("Exit Cap", _fmt_pct(p.exit_cap)),
    ]
    returns = [
        ("LP Net IRR", _fmt_pct(p.lp_irr), p.lp_irr >= 0.12),
        ("LP Net MOIC", _fmt_multiple(p.lp_moic), p.lp_moic >= 2.0),
        ("GP Net IRR", _fmt_pct(p.gp_irr), p.gp_irr >= 0.15),
        ("Loan / LTV", f"{_fmt_dollar_m(p.loan_amount)} / {_fmt_pct(p.ltv)}", True),
        ("DSCR / DY", f"{_fmt_multiple(p.dscr)} / {_fmt_pct(p.debt_yield)}", True),
    ]
    deal_rows = "".join(
        f'<tr><td class="lbl">{lbl}</td><td class="val">{val}</td></tr>'
        for lbl, val in rows
    )
    ret_rows = "".join(
        f'<tr><td class="lbl">{lbl}</td><td class="val {"good" if good else "weak"}">{val}</td></tr>'
        for lbl, val, good in returns
    )
    return f"""
<section class="slide slide-text" data-slide="{slide_num}">
  <header class="slide-head">
    <span class="slide-eyebrow">I.</span>
    <h2 class="slide-title">Executive Summary</h2>
  </header>
  <div class="grid-2col">
    <div>
      <div class="col-label">Deal Terms</div>
      <table class="ledger">{deal_rows}</table>
    </div>
    <div>
      <div class="col-label">Returns &amp; Debt</div>
      <table class="ledger">{ret_rows}</table>
    </div>
  </div>
</section>
"""


def _slide_property(p: SummaryPayload, slide_num: int) -> str:
    return f"""
<section class="slide slide-text" data-slide="{slide_num}">
  <header class="slide-head">
    <span class="slide-eyebrow">II.</span>
    <h2 class="slide-title">Property Overview</h2>
  </header>
  <div class="prop-block">
    <h3 class="prop-name">{_esc(p.property_name)}</h3>
    <div class="prop-addr">{_esc(p.address)}</div>
    <hr class="hair">
    <table class="ledger ledger-wide">
      <tr><td class="lbl">Asset Class</td><td class="val">{_esc(p.asset_class.title())}</td></tr>
      <tr><td class="lbl">Submarket</td><td class="val">{_esc(p.submarket)}</td></tr>
      <tr><td class="lbl">{_esc(p.denom_label)}</td><td class="val">{int(p.denom_value):,}</td></tr>
      <tr><td class="lbl">Pricing {p.per_denom_label}</td><td class="val">{_fmt_per_denom(p.purchase_price / p.denom_value, p.per_denom_label)}</td></tr>
      <tr><td class="lbl">Basis {p.per_denom_label}</td><td class="val">{_fmt_per_denom(p.all_in_basis / p.denom_value, p.per_denom_label)}</td></tr>
    </table>
  </div>
</section>
"""


def _slide_sources_uses(p: SummaryPayload, slide_num: int) -> str:
    uses = [
        ("Purchase Price", p.purchase_price),
        ("Closing Costs", p.closing_costs),
        ("Initial Capex", p.initial_capex),
        ("Value-Add Capex Schedule", p.value_add_capex_total),
        ("Day-One Reserves", p.day_one_reserves),
    ]
    total_uses = sum(v for _, v in uses)
    use_rows = "".join(
        f'<tr><td class="lbl">{lbl}</td><td class="val">{_fmt_dollar(v)}</td><td class="pct">{(v/total_uses*100):.1f}%</td></tr>'
        for lbl, v in uses if v > 0
    )
    equity_check = total_uses - p.loan_amount
    sources = [
        ("Senior Debt", p.loan_amount, _fmt_pct(p.ltv) + " LTV"),
        ("Equity", equity_check, _fmt_pct(equity_check / total_uses) + " of total"),
    ]
    src_rows = "".join(
        f'<tr><td class="lbl">{lbl}</td><td class="val">{_fmt_dollar(v)}</td><td class="pct">{note}</td></tr>'
        for lbl, v, note in sources
    )
    return f"""
<section class="slide slide-text" data-slide="{slide_num}">
  <header class="slide-head">
    <span class="slide-eyebrow">III.</span>
    <h2 class="slide-title">Sources &amp; Uses</h2>
  </header>
  <div class="grid-2col">
    <div>
      <div class="col-label">Uses of Capital</div>
      <table class="ledger ledger-3col">{use_rows}
        <tr class="total"><td class="lbl">Total</td><td class="val">{_fmt_dollar(total_uses)}</td><td class="pct">100.0%</td></tr>
      </table>
    </div>
    <div>
      <div class="col-label">Sources of Capital</div>
      <table class="ledger ledger-3col">{src_rows}
        <tr class="total"><td class="lbl">Total</td><td class="val">{_fmt_dollar(total_uses)}</td><td class="pct">100.0%</td></tr>
      </table>
      <div class="constraint">
        Loan binding constraint: <em>{_esc(p.binding_constraint)}</em>
        <br>DSCR {_fmt_multiple(p.dscr)} &middot; DY {_fmt_pct(p.debt_yield)} &middot; Rate {_fmt_pct(p.rate)} &middot; {p.term_yrs}-yr term
      </div>
    </div>
  </div>
</section>
"""


def _slide_pro_forma(p: SummaryPayload, years: list[MemoYearLine], revenue_label: str, slide_num: int) -> str:
    # Build columns
    year_cols = "".join(f'<th>Yr {y.year}</th>' for y in years)
    rev_row = "".join(f'<td>{_fmt_dollar_m(y.revenue)}</td>' for y in years)
    opex_row = "".join(f'<td>({_fmt_dollar_m(y.opex)[1:]})</td>' for y in years)
    noi_row = "".join(f'<td>{_fmt_dollar_m(y.noi)}</td>' for y in years)
    nu_row = "".join(f'<td>{_fmt_dollar_m(y.ncf_unlevered)}</td>' for y in years)
    nl_row = "".join(f'<td>{_fmt_dollar_m(y.ncf_levered)}</td>' for y in years)
    # Sparkline (NOI trajectory)
    nois = [y.noi for y in years]
    spark = _sparkline(nois, width=320, height=44)
    return f"""
<section class="slide slide-text" data-slide="{slide_num}">
  <header class="slide-head">
    <span class="slide-eyebrow">IV.</span>
    <h2 class="slide-title">Operating Pro Forma</h2>
  </header>
  <div class="proforma-spark">
    <div class="spark-label">NOI trajectory &middot; {_fmt_dollar_m(min(nois))} &rarr; {_fmt_dollar_m(max(nois))}</div>
    {spark}
  </div>
  <table class="pro-forma">
    <thead><tr><th class="lbl"></th>{year_cols}</tr></thead>
    <tbody>
      <tr><td class="lbl">{_esc(revenue_label)}</td>{rev_row}</tr>
      <tr><td class="lbl">Operating Expenses</td>{opex_row}</tr>
      <tr class="total"><td class="lbl">NOI</td>{noi_row}</tr>
      <tr><td class="lbl">NCF Unlevered</td>{nu_row}</tr>
      <tr class="emphasis"><td class="lbl">NCF Levered</td>{nl_row}</tr>
    </tbody>
  </table>
</section>
"""


def _sparkline(values: list[float], width: int = 320, height: int = 44) -> str:
    if not values or len(values) < 2:
        return ""
    lo, hi = min(values), max(values)
    if hi == lo:
        hi = lo + 1
    pad_x, pad_y = 4, 6
    w_inner = width - 2 * pad_x
    h_inner = height - 2 * pad_y
    pts = []
    for i, v in enumerate(values):
        x = pad_x + i * w_inner / (len(values) - 1)
        y = pad_y + h_inner * (1 - (v - lo) / (hi - lo))
        pts.append((x, y))
    path = " ".join(f"{'M' if i == 0 else 'L'} {x:.1f} {y:.1f}" for i, (x, y) in enumerate(pts))
    area = f"M {pts[0][0]:.1f} {height - pad_y:.1f} " + " ".join(f"L {x:.1f} {y:.1f}" for x, y in pts) + f" L {pts[-1][0]:.1f} {height - pad_y:.1f} Z"
    dots = "".join(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="2" />' for x, y in pts)
    return f"""<svg class="sparkline" viewBox="0 0 {width} {height}" width="{width}" height="{height}">
  <path class="spark-area" d="{area}" />
  <path class="spark-line" d="{path}" />
  {dots}
</svg>"""


def _slide_returns(p: SummaryPayload, slide_num: int) -> str:
    rows_irr = [
        ("Project", p.project_irr, p.project_moic),
        ("LP (net)", p.lp_irr, p.lp_moic),
        ("GP (co-inv + promote)", p.gp_irr, p.gp_moic),
    ]
    irr_rows = "".join(
        f'<tr><td class="lbl">{lbl}</td><td class="val">{_fmt_pct(irr)}</td><td class="val">{_fmt_multiple(m)}</td></tr>'
        for lbl, irr, m in rows_irr
    )
    tier_rows = "".join(
        f'<tr><td class="lbl">{_esc(t.label)}</td>'
        f'<td class="val">{_fmt_pct(t.hurdle_irr)}</td>'
        f'<td class="val">{_fmt_pct(t.promote_pct)}</td>'
        f'<td class="val">{_fmt_dollar_m(t.lp_total)}</td>'
        f'<td class="val">{_fmt_dollar_m(t.gp_total)}</td></tr>'
        for t in p.tiers
    )
    return f"""
<section class="slide slide-text" data-slide="{slide_num}">
  <header class="slide-head">
    <span class="slide-eyebrow">V.</span>
    <h2 class="slide-title">Returns &amp; Waterfall</h2>
  </header>
  <div class="returns-headline">
    <div class="ret-box">
      <div class="ret-label">LP Net IRR</div>
      <div class="ret-value">{_fmt_pct(p.lp_irr)}</div>
      <div class="ret-sub">{_fmt_multiple(p.lp_moic)} MOIC</div>
    </div>
    <div class="ret-box">
      <div class="ret-label">GP Net IRR</div>
      <div class="ret-value">{_fmt_pct(p.gp_irr)}</div>
      <div class="ret-sub">{_fmt_multiple(p.gp_moic)} MOIC</div>
    </div>
    <div class="ret-box">
      <div class="ret-label">Project IRR</div>
      <div class="ret-value">{_fmt_pct(p.project_irr)}</div>
      <div class="ret-sub">{_fmt_multiple(p.project_moic)} MOIC</div>
    </div>
  </div>
  <div class="col-label">Multi-Tier Waterfall &middot; {_fmt_pct(p.gp_coinvest_pct)} GP co-invest</div>
  <table class="ledger ledger-5col">
    <thead><tr><th class="lbl">Tier</th><th>Hurdle IRR</th><th>Promote</th><th>LP Total</th><th>GP Total</th></tr></thead>
    <tbody>{tier_rows}</tbody>
  </table>
</section>
"""


def _slide_exit(p: SummaryPayload, slide_num: int) -> str:
    rows = [
        ("Exit Year", f"Yr {p.exit_year}"),
        (f"Exit NOI ({p.exit_noi_basis})", _fmt_dollar(p.exit_noi)),
        ("Exit Cap", _fmt_pct(p.exit_cap)),
        ("Gross Sale", _fmt_dollar(p.gross_sale)),
        ("Cost of Sale", f"({_fmt_dollar(p.cost_of_sale)[1:]})"),
        ("Loan Payoff", f"({_fmt_dollar(p.loan_payoff)[1:]})"),
        ("Net Proceeds to Equity", _fmt_dollar(p.net_proceeds)),
    ]
    body = "".join(
        f'<tr class="{"total" if lbl=="Net Proceeds to Equity" else ""}"><td class="lbl">{lbl}</td><td class="val">{val}</td></tr>'
        for lbl, val in rows
    )
    return f"""
<section class="slide slide-text" data-slide="{slide_num}">
  <header class="slide-head">
    <span class="slide-eyebrow">VI.</span>
    <h2 class="slide-title">Exit Analysis</h2>
  </header>
  <table class="ledger ledger-wide">{body}</table>
</section>
"""


def _slide_risks(p: SummaryPayload, slide_num: int) -> str:
    # Generic risk stubs -- IC analyst fills in
    risks = [
        ("Market", "Submarket rent growth and absorption assumptions versus broker forecast."),
        ("Operations", "Stabilization timing and value-add execution risk."),
        ("Capital Markets", "Refinance / exit cap environment at {} year hold.".format(p.hold_yrs)),
        ("Sponsor", "Sponsor track record on similar value-add executions."),
        ("Concentration", "Single-asset / single-market exposure within fund."),
    ]
    body = "".join(
        f'<li><span class="risk-cat">{cat}</span><span class="risk-body">{body}</span></li>'
        for cat, body in risks
    )
    return f"""
<section class="slide slide-text" data-slide="{slide_num}">
  <header class="slide-head">
    <span class="slide-eyebrow">VII.</span>
    <h2 class="slide-title">Risks &amp; Mitigants</h2>
  </header>
  <ul class="risk-list">{body}</ul>
  <div class="risk-note">Analyst to populate mitigants per IC review.</div>
</section>
"""


def _slide_recommendation(p: SummaryPayload, slide_num: int) -> str:
    # Heuristic verdict based on returns
    lp_target = 0.12
    if p.lp_irr >= lp_target:
        verdict = "Proceed"
        verdict_class = "verdict-pass"
        verdict_note = f"Returns meet institutional benchmark ({_fmt_pct(p.lp_irr)} LP net vs. {_fmt_pct(lp_target)} target)."
    elif p.lp_irr >= 0.08:
        verdict = "Review"
        verdict_class = "verdict-review"
        verdict_note = f"Returns below institutional value-add target ({_fmt_pct(p.lp_irr)} LP net vs. {_fmt_pct(lp_target)} target). Consider re-bid."
    else:
        verdict = "Pass"
        verdict_class = "verdict-fail"
        verdict_note = f"Returns materially below target ({_fmt_pct(p.lp_irr)} LP net vs. {_fmt_pct(lp_target)} target)."

    return f"""
<section class="slide slide-cover slide-verdict" data-slide="{slide_num}">
  <div class="cover-stamp">Investment Committee</div>
  <div class="verdict-eyebrow">Recommendation</div>
  <div class="verdict-stamp {verdict_class}">{verdict.upper()}</div>
  <div class="verdict-note">{verdict_note}</div>
  <div class="verdict-grid">
    <div><span class="vg-label">LP Net IRR</span><span class="vg-val">{_fmt_pct(p.lp_irr)}</span></div>
    <div><span class="vg-label">LP MOIC</span><span class="vg-val">{_fmt_multiple(p.lp_moic)}</span></div>
    <div><span class="vg-label">Going-In Cap</span><span class="vg-val">{_fmt_pct(p.going_in_cap)}</span></div>
    <div><span class="vg-label">Yr {p.stab_yr} YoC (all-in)</span><span class="vg-val">{_fmt_pct(p.roc_trended)}</span></div>
  </div>
</section>
"""


# ---------------------------------------------------------------------------
# Asset-class specific slides
# ---------------------------------------------------------------------------

def _slide_commercial(block: CommercialMemoBlock, slide_num: int) -> str:
    top = "".join(
        f'<tr><td class="lbl">{_esc(t)}</td><td class="val">{sf:,}</td>'
        f'<td class="val">{_fmt_dollar(rent)}</td><td class="val">{_fmt_pct(pct, 1)}</td></tr>'
        for t, sf, rent, pct in block.top_tenants
    )
    rollover = "".join(
        f'<tr><td class="lbl">Yr {yr}</td><td class="val">{sf:,}</td>'
        f'<td class="val">{_fmt_pct(pct_rba, 1)}</td><td class="val">${ip:.2f}/SF</td>'
        f'<td class="val">${mkt:.2f}/SF</td><td class="val {("good" if mtm>=0 else "weak")}">{_fmt_pct(mtm, 1)}</td></tr>'
        for yr, sf, pct_rba, ip, mkt, mtm in block.rollover
    )
    return f"""
<section class="slide slide-text" data-slide="{slide_num}">
  <header class="slide-head">
    <span class="slide-eyebrow">II.a</span>
    <h2 class="slide-title">Tenancy &amp; Rollover</h2>
  </header>
  <div class="col-label">WALT: {block.walt_yrs:.2f} years (rent-weighted)</div>
  <div class="grid-2col">
    <div>
      <div class="col-label">Top Tenants by Rent</div>
      <table class="ledger ledger-4col">
        <thead><tr><th class="lbl">Tenant</th><th>SF</th><th>Annual Rent</th><th>% Total</th></tr></thead>
        <tbody>{top}</tbody>
      </table>
    </div>
    <div>
      <div class="col-label">Rollover Schedule</div>
      <table class="ledger ledger-6col">
        <thead><tr><th class="lbl">Year</th><th>SF</th><th>% RBA</th><th>In-Place</th><th>Market @ Roll</th><th>MTM</th></tr></thead>
        <tbody>{rollover}</tbody>
      </table>
    </div>
  </div>
</section>
"""


# ---------------------------------------------------------------------------
# Top-level renderer
# ---------------------------------------------------------------------------

CSS = """
@import url('https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght,SOFT,WONK@9..144,300..900,0..100,0..1&family=Newsreader:ital,opsz,wght@0,6..72,200..800;1,6..72,200..800&family=IBM+Plex+Mono:wght@300;400;500;600&display=swap');

* { box-sizing: border-box; margin: 0; padding: 0; }

:root {
  --paper: #F2EDE3;
  --paper-2: #EAE3D5;
  --ink: #1C1814;
  --ink-soft: #4B433A;
  --ink-faint: #8A7F70;
  --oxblood: #6B1518;
  --oxblood-soft: #8F2A2D;
  --sage: #5A6B4E;
  --hair: rgba(28, 24, 20, 0.55);
  --hair-faint: rgba(28, 24, 20, 0.18);
}

html, body {
  background: var(--paper);
  color: var(--ink);
  font-family: 'Newsreader', Georgia, serif;
  font-size: 16px;
  line-height: 1.5;
  font-feature-settings: 'tnum' 1, 'lnum' 1;
  min-height: 100vh;
  overflow-x: hidden;
}

body::before {
  content: '';
  position: fixed; inset: 0;
  pointer-events: none;
  z-index: 100;
  background-image: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='200' height='200'><filter id='n'><feTurbulence type='fractalNoise' baseFrequency='0.85' numOctaves='2' stitchTiles='stitch'/><feColorMatrix values='0 0 0 0 0.11  0 0 0 0 0.09  0 0 0 0 0.08  0 0 0 0.045 0'/></filter><rect width='100%25' height='100%25' filter='url(%23n)'/></svg>");
  opacity: 0.6;
  mix-blend-mode: multiply;
}

.deck {
  width: 100vw;
  min-height: 100vh;
  display: flex;
  flex-direction: column;
}

.slide {
  width: 100vw;
  min-height: 100vh;
  padding: 80px 96px 100px;
  position: relative;
  display: none;
  flex-direction: column;
  page-break-after: always;
  break-after: page;
}

.slide.active { display: flex; }

@media print {
  .slide { display: flex !important; }
  body::before { display: none; }
  .nav, .progress { display: none !important; }
}

/* ============== COVER ============== */

.slide-cover {
  background: var(--paper);
  justify-content: space-between;
  padding: 64px 96px 64px;
}

.slide-cover::before {
  content: '';
  position: absolute;
  inset: 32px 48px;
  border: 1px solid var(--hair);
  pointer-events: none;
}

.cover-stamp {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 11px;
  letter-spacing: 0.35em;
  text-transform: uppercase;
  color: var(--oxblood);
  border: 1px solid var(--oxblood);
  padding: 6px 14px;
  align-self: flex-end;
  font-weight: 500;
}

.cover-meta {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 12px;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  color: var(--ink-soft);
  margin-top: 48px;
}

.cover-meta-sep { color: var(--ink-faint); margin: 0 12px; }

.cover-title {
  font-family: 'Fraunces', Georgia, serif;
  font-variation-settings: 'opsz' 144, 'SOFT' 30, 'WONK' 0;
  font-weight: 400;
  font-size: clamp(56px, 8vw, 128px);
  line-height: 0.95;
  letter-spacing: -0.025em;
  color: var(--ink);
  margin-top: 36px;
  margin-bottom: 24px;
  max-width: 11ch;
}

.cover-sub {
  font-family: 'Newsreader', Georgia, serif;
  margin-top: 8px;
}

.cover-address {
  font-size: 22px;
  font-style: italic;
  color: var(--ink-soft);
  letter-spacing: 0.005em;
}

.cover-asset {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 11px;
  letter-spacing: 0.25em;
  text-transform: uppercase;
  color: var(--oxblood);
  margin-top: 16px;
}

.cover-anchor {
  margin-top: auto;
  margin-bottom: 24px;
  padding-top: 32px;
  border-top: 1px solid var(--hair);
  display: flex;
  flex-direction: column;
  align-items: flex-start;
}

.cover-anchor-label {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 11px;
  letter-spacing: 0.25em;
  text-transform: uppercase;
  color: var(--ink-faint);
  margin-bottom: 8px;
}

.cover-anchor-value {
  font-family: 'Fraunces', Georgia, serif;
  font-variation-settings: 'opsz' 144, 'SOFT' 0, 'WONK' 1;
  font-weight: 500;
  font-size: clamp(48px, 6vw, 88px);
  letter-spacing: -0.02em;
  line-height: 1;
  color: var(--oxblood);
  font-feature-settings: 'tnum' 1, 'lnum' 1, 'ss01' 1;
}

.cover-anchor-sub {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 14px;
  color: var(--ink-soft);
  margin-top: 8px;
  letter-spacing: 0.04em;
}

.cover-footer {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 11px;
  letter-spacing: 0.2em;
  text-transform: uppercase;
  color: var(--ink-soft);
  display: flex;
  align-items: center;
}

/* ============== TEXT SLIDE ============== */

.slide-head {
  display: flex;
  align-items: baseline;
  gap: 28px;
  padding-bottom: 24px;
  border-bottom: 1px solid var(--hair);
  margin-bottom: 40px;
}

.slide-eyebrow {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 13px;
  font-weight: 500;
  letter-spacing: 0.15em;
  color: var(--oxblood);
  min-width: 40px;
}

.slide-title {
  font-family: 'Fraunces', Georgia, serif;
  font-variation-settings: 'opsz' 72, 'SOFT' 20, 'WONK' 0;
  font-weight: 400;
  font-size: 56px;
  letter-spacing: -0.015em;
  line-height: 1;
  color: var(--ink);
}

.grid-2col {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 64px;
  margin-bottom: 32px;
}

.col-label {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 11px;
  letter-spacing: 0.25em;
  text-transform: uppercase;
  color: var(--oxblood);
  border-bottom: 1px solid var(--hair-faint);
  padding-bottom: 10px;
  margin-bottom: 18px;
}

/* ============== LEDGER (key-value tables) ============== */

.ledger {
  width: 100%;
  border-collapse: collapse;
  font-family: 'Newsreader', Georgia, serif;
}

.ledger tr { border-bottom: 1px dotted var(--hair-faint); }
.ledger tr:last-child { border-bottom: none; }

.ledger td {
  padding: 11px 0;
  font-size: 16px;
  vertical-align: baseline;
}

.ledger td.lbl {
  color: var(--ink-soft);
  font-style: italic;
  font-size: 15px;
}

.ledger td.val {
  text-align: right;
  font-family: 'IBM Plex Mono', monospace;
  font-weight: 500;
  font-size: 15px;
  color: var(--ink);
  letter-spacing: -0.005em;
}

.ledger td.pct {
  text-align: right;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 13px;
  font-weight: 400;
  color: var(--ink-faint);
  padding-left: 24px;
  width: 80px;
}

.ledger tr.total { border-top: 1.5px solid var(--ink); border-bottom: none; }
.ledger tr.total td { padding-top: 14px; font-weight: 600; }
.ledger tr.total td.lbl { font-style: normal; color: var(--ink); }

.ledger td.val.good { color: var(--sage); }
.ledger td.val.weak { color: var(--oxblood); }

.ledger-3col td.lbl { width: 55%; }
.ledger thead th {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 10px;
  font-weight: 500;
  letter-spacing: 0.2em;
  text-transform: uppercase;
  color: var(--ink-faint);
  text-align: right;
  padding: 8px 0;
  border-bottom: 1px solid var(--hair);
}

.ledger thead th.lbl { text-align: left; }

/* ============== PRO FORMA ============== */

.proforma-spark {
  margin-bottom: 32px;
  padding: 16px 0;
  border-top: 1px solid var(--hair-faint);
  border-bottom: 1px solid var(--hair-faint);
}

.spark-label {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 11px;
  letter-spacing: 0.2em;
  text-transform: uppercase;
  color: var(--ink-faint);
  margin-bottom: 8px;
}

.sparkline .spark-line { fill: none; stroke: var(--oxblood); stroke-width: 1.5; stroke-linejoin: round; }
.sparkline .spark-area { fill: var(--oxblood); opacity: 0.08; }
.sparkline circle { fill: var(--oxblood); }

.pro-forma {
  width: 100%;
  border-collapse: collapse;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 13px;
}

.pro-forma th, .pro-forma td {
  padding: 10px 14px;
  text-align: right;
  border-bottom: 1px dotted var(--hair-faint);
}

.pro-forma th {
  font-size: 10px;
  letter-spacing: 0.2em;
  text-transform: uppercase;
  color: var(--ink-faint);
  border-bottom: 1px solid var(--hair);
  font-weight: 500;
}

.pro-forma td.lbl, .pro-forma th.lbl {
  text-align: left;
  font-family: 'Newsreader', Georgia, serif;
  font-style: italic;
  font-size: 15px;
  color: var(--ink-soft);
  padding-left: 0;
}

.pro-forma tr.total { border-top: 1.5px solid var(--ink); }
.pro-forma tr.total td { padding-top: 14px; font-weight: 600; }
.pro-forma tr.total td.lbl { font-style: normal; color: var(--ink); }
.pro-forma tr.emphasis td { color: var(--oxblood); font-weight: 500; }
.pro-forma tr.emphasis td.lbl { color: var(--ink); font-style: normal; }

/* ============== PROPERTY ============== */

.prop-block {
  max-width: 720px;
}

.prop-name {
  font-family: 'Fraunces', Georgia, serif;
  font-variation-settings: 'opsz' 72, 'SOFT' 20;
  font-weight: 400;
  font-size: 44px;
  line-height: 1.05;
  letter-spacing: -0.015em;
}

.prop-addr {
  font-style: italic;
  color: var(--ink-soft);
  font-size: 19px;
  margin-top: 8px;
}

.hair { border: none; border-top: 1px solid var(--hair); margin: 32px 0; }

/* ============== RETURNS HEADLINE ============== */

.returns-headline {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  gap: 32px;
  margin-bottom: 48px;
}

.ret-box {
  padding: 24px 28px;
  border: 1px solid var(--hair);
  background: var(--paper-2);
  position: relative;
}

.ret-box::before {
  content: '';
  position: absolute;
  top: -1px; left: -1px;
  width: 14px; height: 14px;
  border-top: 2px solid var(--oxblood);
  border-left: 2px solid var(--oxblood);
}

.ret-label {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 10px;
  letter-spacing: 0.25em;
  text-transform: uppercase;
  color: var(--ink-soft);
  margin-bottom: 12px;
}

.ret-value {
  font-family: 'Fraunces', Georgia, serif;
  font-variation-settings: 'opsz' 144, 'SOFT' 0, 'WONK' 1;
  font-weight: 500;
  font-size: 52px;
  line-height: 1;
  letter-spacing: -0.02em;
  color: var(--oxblood);
  font-feature-settings: 'tnum' 1;
}

.ret-sub {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 13px;
  color: var(--ink-soft);
  margin-top: 8px;
}

.constraint {
  font-style: italic;
  font-size: 14px;
  color: var(--ink-soft);
  margin-top: 16px;
  padding: 12px 0;
  border-top: 1px dotted var(--hair-faint);
}

.constraint em {
  font-style: normal;
  color: var(--oxblood);
  font-weight: 500;
}

/* ============== RISKS ============== */

.risk-list {
  list-style: none;
  margin-top: 16px;
}

.risk-list li {
  padding: 22px 0;
  border-bottom: 1px dotted var(--hair-faint);
  display: grid;
  grid-template-columns: 180px 1fr;
  gap: 32px;
  align-items: baseline;
}

.risk-cat {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 11px;
  letter-spacing: 0.2em;
  text-transform: uppercase;
  color: var(--oxblood);
  font-weight: 500;
}

.risk-body {
  font-size: 17px;
  font-style: italic;
  color: var(--ink-soft);
}

.risk-note {
  margin-top: 32px;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 11px;
  color: var(--ink-faint);
  letter-spacing: 0.15em;
  text-transform: uppercase;
}

/* ============== VERDICT ============== */

.slide-verdict {
  align-items: center;
  text-align: center;
  justify-content: center;
}

.slide-verdict .cover-stamp {
  align-self: center;
  margin-top: 32px;
}

.verdict-eyebrow {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 12px;
  letter-spacing: 0.3em;
  text-transform: uppercase;
  color: var(--ink-soft);
  margin-top: 48px;
}

.verdict-stamp {
  font-family: 'Fraunces', Georgia, serif;
  font-variation-settings: 'opsz' 144, 'SOFT' 0, 'WONK' 1;
  font-weight: 600;
  font-size: clamp(120px, 18vw, 240px);
  line-height: 1;
  letter-spacing: -0.04em;
  margin-top: 24px;
  padding: 0 48px;
  position: relative;
  display: inline-block;
}

.verdict-stamp::before, .verdict-stamp::after {
  content: '';
  position: absolute;
  top: 50%;
  width: 120px;
  height: 1px;
  background: currentColor;
}
.verdict-stamp::before { right: 100%; margin-right: 24px; }
.verdict-stamp::after { left: 100%; margin-left: 24px; }

.verdict-pass { color: var(--sage); }
.verdict-review { color: #B07C2A; }
.verdict-fail { color: var(--oxblood); }

.verdict-note {
  font-family: 'Newsreader', Georgia, serif;
  font-style: italic;
  font-size: 22px;
  color: var(--ink-soft);
  margin-top: 32px;
  max-width: 60ch;
  line-height: 1.4;
}

.verdict-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 40px;
  margin-top: 64px;
  padding-top: 32px;
  border-top: 1px solid var(--hair);
  width: 80%;
  max-width: 900px;
}

.verdict-grid > div {
  display: flex;
  flex-direction: column;
  align-items: center;
}

.vg-label {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 10px;
  letter-spacing: 0.2em;
  text-transform: uppercase;
  color: var(--ink-faint);
  margin-bottom: 8px;
}

.vg-val {
  font-family: 'Fraunces', Georgia, serif;
  font-variation-settings: 'opsz' 72, 'SOFT' 0, 'WONK' 1;
  font-weight: 500;
  font-size: 32px;
  letter-spacing: -0.015em;
  color: var(--ink);
  font-feature-settings: 'tnum' 1;
}

/* ============== NAV ============== */

.nav {
  position: fixed;
  bottom: 32px;
  left: 50%;
  transform: translateX(-50%);
  display: flex;
  gap: 8px;
  z-index: 200;
  align-items: center;
  background: var(--paper-2);
  padding: 8px 16px;
  border: 1px solid var(--hair-faint);
}

.nav-dot {
  width: 8px;
  height: 8px;
  background: transparent;
  border: 1px solid var(--ink-faint);
  border-radius: 50%;
  cursor: pointer;
  transition: all 0.2s;
  padding: 0;
}

.nav-dot.active {
  background: var(--oxblood);
  border-color: var(--oxblood);
  transform: scale(1.3);
}

.nav-arrow {
  background: none;
  border: none;
  color: var(--ink);
  font-family: 'IBM Plex Mono', monospace;
  font-size: 14px;
  cursor: pointer;
  padding: 4px 10px;
}

.nav-arrow:disabled { opacity: 0.3; cursor: not-allowed; }

.progress {
  position: fixed;
  top: 0; left: 0;
  height: 2px;
  background: var(--oxblood);
  z-index: 300;
  transition: width 0.3s ease;
}

.page-num {
  position: absolute;
  bottom: 32px;
  right: 96px;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 11px;
  letter-spacing: 0.2em;
  color: var(--ink-faint);
}
"""

JS = """
const slides = document.querySelectorAll('.slide');
const dots = document.querySelectorAll('.nav-dot');
const progress = document.querySelector('.progress');
const prev = document.querySelector('.nav-prev');
const next = document.querySelector('.nav-next');
let current = 0;

function show(i) {
  current = Math.max(0, Math.min(slides.length - 1, i));
  slides.forEach((s, idx) => s.classList.toggle('active', idx === current));
  dots.forEach((d, idx) => d.classList.toggle('active', idx === current));
  progress.style.width = ((current + 1) / slides.length * 100) + '%';
  prev.disabled = current === 0;
  next.disabled = current === slides.length - 1;
  history.replaceState(null, '', '#' + (current + 1));
}

document.addEventListener('keydown', (e) => {
  if (e.key === 'ArrowRight' || e.key === ' ' || e.key === 'PageDown') { e.preventDefault(); show(current + 1); }
  if (e.key === 'ArrowLeft' || e.key === 'PageUp') { e.preventDefault(); show(current - 1); }
  if (e.key === 'Home') show(0);
  if (e.key === 'End') show(slides.length - 1);
});

dots.forEach((d, i) => d.addEventListener('click', () => show(i)));
prev.addEventListener('click', () => show(current - 1));
next.addEventListener('click', () => show(current + 1));

const startHash = parseInt((location.hash || '#1').slice(1), 10);
show(isNaN(startHash) ? 0 : startHash - 1);
"""


def write_ic_memo_html(
    payload: SummaryPayload,
    years: list[MemoYearLine],
    out: Path,
    *,
    revenue_label: str = "EGI",
    commercial: CommercialMemoBlock | None = None,
    datacenter: DCMemoBlock | None = None,
    infrastructure: InfraMemoBlock | None = None,
) -> int:
    """Write a self-contained HTML presentation deck for an IC memo."""
    slides_html: list[str] = []
    n = 1
    slides_html.append(_slide_cover(payload, n, 0))  # total filled below
    n += 1
    slides_html.append(_slide_exec_summary(payload, n)); n += 1
    slides_html.append(_slide_property(payload, n)); n += 1
    if commercial is not None:
        slides_html.append(_slide_commercial(commercial, n)); n += 1
    slides_html.append(_slide_sources_uses(payload, n)); n += 1
    slides_html.append(_slide_pro_forma(payload, years, revenue_label, n)); n += 1
    slides_html.append(_slide_returns(payload, n)); n += 1
    slides_html.append(_slide_exit(payload, n)); n += 1
    slides_html.append(_slide_risks(payload, n)); n += 1
    slides_html.append(_slide_recommendation(payload, n)); n += 1

    total = len(slides_html)
    dots = "".join(f'<button class="nav-dot" aria-label="Go to slide {i+1}"></button>' for i in range(total))

    body_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>{_esc(payload.deal_name)} - IC Memo</title>
<style>{CSS}</style>
</head>
<body>
<div class="progress" style="width:0%"></div>
<div class="deck">
{''.join(slides_html)}
</div>
<div class="nav">
  <button class="nav-arrow nav-prev" aria-label="Previous">&larr;</button>
  {dots}
  <button class="nav-arrow nav-next" aria-label="Next">&rarr;</button>
</div>
<script>{JS}</script>
</body>
</html>"""

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(body_html, encoding="utf-8")
    return total


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.underwriting.ic_memo_html",
        description="Generate an HTML presentation IC memo from a deal YAML.",
    )
    parser.add_argument("deal", help="Path to deal YAML.")
    parser.add_argument("-o", "--output", help="Output HTML path (default: outputs/<deal_id>-ic-memo.html).")
    args = parser.parse_args(argv)

    payload, years, revenue_label, commercial, datacenter, infrastructure = _dispatch(args.deal)
    out = Path(args.output) if args.output else Path("outputs") / f"{payload.deal_id}-ic-memo.html"

    total = write_ic_memo_html(
        payload, years, out,
        revenue_label=revenue_label,
        commercial=commercial,
        datacenter=datacenter,
        infrastructure=infrastructure,
    )

    bar = "-" * 72
    print(bar)
    print(f"  {payload.deal_name}  -  IC Memo (HTML)")
    print(bar)
    print(f"  Asset class:     {payload.asset_class}")
    print(f"  Purchase Price:  {_fmt_dollar(payload.purchase_price)}")
    print(f"  LP Net IRR:      {_fmt_pct(payload.lp_irr)}")
    print(f"  GP IRR:          {_fmt_pct(payload.gp_irr)}")
    print(f"  Slides:          {total}")
    print(bar)
    print(f"  Deck written to: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
