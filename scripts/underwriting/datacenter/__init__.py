"""
datacenter -- Data center underwriting engine.

Single subpackage that supports two product types under one roof:

  - DCWholesaleDeal  : MW-priced lease model (hyperscaler / enterprise wholesale).
                       Analog of the commercial lease-by-lease engine, but the
                       denominator is critical MW (not SF) and rents are
                       $/kW/mo (not $/SF/yr). Longer 10-15 yr terms, minimal
                       TI/LC, simpler escalation (annual, no mid-year drift).

  - DCColoDeal       : Cabinet / cage MRR model (retail colocation).
                       Analog of the multifamily unit_mix engine, but with
                       cabinet types instead of floorplans. Per-cabinet MRR
                       plus cross-connect revenue and churn-driven lease-up.

Acquisition / Debt / Equity / Exit reuse the multifamily schemas verbatim
(institutional conventions are asset-class agnostic).
"""
