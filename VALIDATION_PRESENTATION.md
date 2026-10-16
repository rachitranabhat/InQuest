# PRISM: we test the AI's reasoning against the evidence

**CASE-18016 · synthetic data · the human investigator makes the final decision**

| BEFORE: live LLM run `INV-2f790604b4` | AFTER CHECKS: deterministic regression replay |
|---|---|
| Lead: **concern_reduced** | Same stored findings, re-checked against the case records |
| "Jackpot week explains it" | **F-13 rejected.** It read 24.3% as a share of the network; it is 9 of the subject's own 37 transactions (EV-001262). |
| "Subject is 24.3% of the network" | The burst of **12 × $250** was on **Oct 12**, after the event (Oct 10–11) ended (EV-001258). |
| "Familiar retailers, so ordinary" | Kept as a fact. It does not explain 12 identical claims in 18 minutes. |
| "No history before the window" | **F-14 rejected.** The baseline holds 49 purchases over 23 days (EV-001227). |
| "No definitive evidence of unusual behavior" | **Warning**: indicators fired (EV-001220, EV-001225). |
| — | **concern_reduced flagged for review, not overwritten.** Spend grew 17.98× for the subject against 2.01× for the network. |

**What this shows**
- 2 confirmed factual errors and 3 unsupported interpretations, all traced to evidence IDs.
- 11 of 13 findings accepted. The original run is preserved, unchanged.
- 5 regression tests built from this real run pass, with no model calls.

**What it doesn't show**
- We have not made a live AI run since the fix.
- We make no accuracy claim.
- This covers one synthetic case.
