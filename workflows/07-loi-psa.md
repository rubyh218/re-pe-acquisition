# 07 — LOI & PSA

## LOI (Letter of Intent)

Non-binding offer. Signals serious interest, sets terms before legal spend.

### Standard LOI terms
- Buyer entity (typically newly-formed SPV)
- Purchase price + earnest money deposit (EMD) schedule
- Due diligence period (typically 30–60 days)
- Closing period (typically 30 days post-DD)
- Financing contingency (or all-cash)
- Inspection contingency
- Title contingency
- Assignment language
- Broker / commission allocation
- Confidentiality + exclusivity period

### Process
1. Draft LOI from template, populate from underwriting + business plan
2. Internal review (deal lead → head of acquisitions)
3. Submit through broker
4. Negotiate price + terms (often 1–3 rounds)
5. Execute → triggers Phase B due diligence

### Deliverable
- `loi.docx` — executed LOI

### Script
- `scripts/memos/loi.py` — populates template from deal parameters

## PSA (Purchase & Sale Agreement)

Binding contract. Drafted by attorneys; this skill produces the **review checklist**, not the contract itself.

### Review checklist (legal works the doc; we work the business terms)
- [ ] Purchase price + adjustments (prorations, credits) match underwriting
- [ ] EMD amount + escrow agent + release conditions
- [ ] DD period length + extension rights
- [ ] Closing date + extension rights
- [ ] Reps & warranties — survival period (typically 6–12 months), cap, basket
- [ ] Indemnification structure
- [ ] Casualty / condemnation thresholds (when buyer can walk)
- [ ] Operating covenants between signing and close (no new leases, no material capex without approval)
- [ ] Estoppel and SNDA delivery requirements
- [ ] Tenant deposit / prepaid rent transfer
- [ ] Assignment rights to affiliated entity
- [ ] Default remedies (specific performance vs. liquidated damages)

### Deliverable
- `psa-review.md` — markup notes for legal counsel + business-term confirmations
