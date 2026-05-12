"""
commercial — Lease-by-lease underwriting engine for office / industrial / retail.

Parallels scripts/underwriting/ (multifamily) but models tenants individually:
rent roll with escalations, free rent, recoveries (NNN / BYS / gross),
re-leasing rollover with renewal probability, TI / LC, downtime.

Reuses shared debt sizing + waterfall from the parent package.
"""
