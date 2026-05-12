# 08 — Close & Handoff to Asset Management

Final settlement reconciliation and structured handoff to the asset-management skill.

## Closing reconciliation
1. **Settlement statement** — review HUD-1 / closing disclosure for:
   - Purchase price ties to PSA
   - Prorations (rent, RE tax, OpEx, insurance) calculated correctly
   - Tenant security deposits transferred (credit to buyer)
   - Lender fees, title insurance, recording, transfer tax allocated per PSA
2. **Wire confirmations** — equity wire and lender wire reconciled
3. **Final basis** — purchase price + closing costs + day-1 reserves = total basis

## Day-1 deliverables
- Recorded deed
- Loan docs (note, mortgage, loan agreement, environmental indemnity)
- Title policy (received within 30 days post-close)
- Assigned leases + estoppels
- Service contract assignments
- Insurance binder + COI
- Bank account opened in property entity name
- Property management agreement signed

## Handoff package to AM skill
A structured manifest the AM skill ingests:

```
handoff/{property-id}/
├── manifest.json          # property metadata, basis, debt terms, partners
├── pro-forma.xlsx         # final underwriting (becomes "Underwriting Plan" in AM)
├── ic-memo.docx           # for reference
├── business-plan.md       # year-by-year action items
├── leases/                # PDFs + abstracts
├── debt/                  # loan docs + amortization schedule
├── insurance/             # COI + policy
└── partners/              # JV agreement, fund commitment letters
```

The AM skill's `references/quarterly-asset-review.md` consumes this manifest to seed Q1 actuals comparison.

## Deliverable
- `closing-recon.xlsx` — settlement statement reconciliation, basis build
- `handoff/` directory ready for AM skill ingestion

## Scripts
- TBD — likely a `scripts/handoff.py` that validates the manifest schema and copies artifacts into the AM skill's expected layout
