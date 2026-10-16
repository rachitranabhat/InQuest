# Demo script (about 5 minutes)

Curated cases are created on first start with stable IDs.

| Case | Scenario | Shows |
|---|---|---|
| CASE-18001 | Account-based deposit anomaly | Online account channel; deposit → minimal play → withdrawal; playthrough factor |
| CASE-18002 | Repeated identical prize claims | Prize-claim alert type; repeated amounts |
| CASE-18003 | Unusual lottery purchase frequency | Burst vs. the player's own baseline; timeline highlighting |
| CASE-18004 | Incomplete customer attribution | Missing evidence stated explicitly (anonymous sales are not attributed) |
| CASE-18005 | Two players at the same retailer | Co-presence is **not** a relationship; graph shows no player-player edge |
| CASE-18006 | Ambiguous multi-retailer pattern | Alternative explanations; low priority |
| CASE-18007 | Activity during the jackpot week | Network-wide context event as a contradicting factor |
| CASE-18008 | High-volume player activity | Busy but consistent player; a good "close — no further action" example |

## Walkthrough

1. **Queue** — sort by priority; point out that priority, prototype score (not a probability) and evidence completeness are separate.
2. Pick a **simulated reviewer** in the top bar (labelled Simulated; not authentication).
3. Open **CASE-18003** → **Generate report** (Demo mode, no key needed). Show "N of N claims verified".
4. Click a citation chip → the evidence drawer opens, source transactions highlight in the timeline; **Back to report** returns focus to the chip.
5. **Ask the copilot** "Which retailers were involved?", "What happened on October 11?", then "And the next day?" — cited answers that keep conversation context.
6. Ask "Is the player guilty?" — the copilot declines to decide.
7. **Start review** → **Escalate** with a note (too-short notes are rejected). The report is now locked.
8. **Export PDF**; open **Reports & history** to show the audit row with report version and evidence hash.
9. Open **CASE-18005 → Relationship explorer** to show recorded-only edges and the table view.
10. **Scenario lab** → run a scenario to show a fresh case being generated and alerted live.
