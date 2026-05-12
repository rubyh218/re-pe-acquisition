"""
infrastructure -- Energy infrastructure underwriting engine.

Models renewable / storage / merchant generation assets where revenue is the
sum of one or more contracted or merchant streams against a generation profile:

  - PPA            : long-dated $/MWh off-take (e.g., utility, corporate)
  - Availability   : $/MW-month capacity payment (capacity-only generation, BESS)
  - Merchant       : spot price ($/MWh) per ISO/market, applied to remaining
                     generation after contracted allotments

A single asset can blend any mix of streams (e.g., 80% PPA + 20% merchant tail
for a solar plant; capacity + arbitrage for a standalone BESS).

Acquisition / Debt / Equity / Exit reuse the multifamily schemas verbatim
(institutional waterfall + sizing conventions are asset-class agnostic).
"""
