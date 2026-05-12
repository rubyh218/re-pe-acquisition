"""
hospitality - USALI-style underwriting for hotels (economy to luxury).

ADR x Occ -> departmental P&L (Rooms / F&B / Other) -> undistributed ->
GOP -> mgmt fee -> fixed charges -> NOI (pre-reserve) -> FF&E reserve ->
NOI (cap-rate basis). PIP capex with key displacement during execution.

Reuses shared debt sizing + acquisition waterfall from the multifamily engine.
"""
