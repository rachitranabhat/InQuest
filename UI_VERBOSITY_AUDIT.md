# PRISM V2 — UI verbosity audit (audit only, no changes made)

**Scope:** every investigator-facing screen except AI Investigation, which was simplified separately.

**Method:**
* Read the source.
* Captured the rendered text for CASE-18007 (synthetic) at 1440×900 from the production build.
* Nothing outside the AI Investigation tab was edited.

**Priority:**
* **High**: repeated or long text that the investigator sees on every case, above the fold.
* **Medium**: noticeable clutter inside a section.
* **Low**: minor polish.

## 1. Must stay visible (do not cut)

These read like boilerplate, but they carry safety or evidence-limitation meaning. Shorten them only as noted. Never remove them.

| Text | Where | Why it stays |
|---|---|---|
| "Reasons to review, not proof of wrongdoing" | Summary header, Findings header | Core framing that a rule score is not a determination. Keep **one** instance per screen (see item S1). |
| "Prototype alert score … is not a probability of fraud" | Report overview, Queue subtitle | Stops a score being read as a probability. |
| Report disclaimer "does not establish that fraudulent activity occurred. Final determination requires human review." | `backend/config.py:237`, report footer | Required wording on an exported document. |
| "A substantiated finding … is not a legal determination of guilt … The AI never selects or submits a decision." | `InvestigationDecision.tsx` | Defines the decision before someone records it. It could be collapsed after first use, but it must stay one click away (see R2). |
| "Missing data is a limitation, not proof that something did or did not happen." | `SidePanel.tsx:94` | Interprets the evidence-completeness panel. |
| KEEP IN MIND limitations: rewards-card linkage, anonymous purchases not linked, jackpot-week context | `FindingCard.tsx` (limitations), Summary "Keep in mind" | Evidence limitations that directly weaken the finding. |
| Historical Comparison cautions: "Average vs. single peak; indicative only", "Not per day: periods of different length", "Previous active days are not in this evidence version" | `HistoryTab.tsx` rows | Each one says a specific number is not comparable. They must stay on the row they qualify. |
| "Activity during the jackpot week" scenario chip, and "Created by a copilot question (not part of a version)" | Header, Evidence drawer | Provenance and context. |
| Confirm-modal text "Once recorded, the decision cannot be edited…" | `InvestigationDecision.tsx:264` | Warns before an irreversible action. |

## 2. Findings

| # | Tab / component (file) | Current content (example) | Why simplify | Suggested replacement | Priority |
|---|---|---|---|---|---|
| S1 | Case Summary + Evidence → Findings (`features/summary/SummaryView.tsx:67`, `features/findings/KeyFindings.tsx:48`) | "2 of 6 indicators stood out. These are reasons to review, not proof of wrongdoing." It appears again on every expanded finding card: "Worth a closer look. This is a reason to review, not proof of wrongdoing." (`backend/services/findings.py:24` `ATTENTION`) | The same disclaimer shows up 3+ times per case. Repetition trains people to skip it. | Keep it once in the case header strip: "2 of 6 indicators stood out — reasons to review, not proof." Remove the per-card `ATTENTION` line, or reduce it to the strength badge. | High |
| S2 | Case Summary, Q2 "Why was the case flagged?" (`SummaryView.tsx` ~l.88) | Two rule lines, then "Prototype alert score 26.4 is in the Low band.", then "2 indicator(s) fired, consistent with the score band." | The last two lines restate the header (Score: Low 26.4) and Q3. | Keep only the rules that fired, each with its threshold. | Medium |
| S3 | Case Summary, Q4 "What should be checked next?" (`SummaryView.tsx:96-100`) | "Check the 6 records behind 'unusual transaction frequency'. Open records" for each finding, then "Generate the report in Review for cited suggested checks." | These are generic, one line per finding, and duplicate Q3's "View evidence" buttons. The useful checks only exist in the report. | Show the report's top 2 suggested checks when a report exists. Otherwise show a single line: "Generate a report for cited next checks." | Medium |
| S4 | Case Summary layout (`SummaryView.tsx`) | The header strip (Alert, Subject, Score, Recent period, Alert time, Priority, Scenario), then the case ID, priority and alert type repeated, then a headline, then Q1–Q4 | The case ID, priority and alert type are repeated directly under the header. | Drop the repeated ID/priority/alert line and start with the headline. | Low |
| E1 | Evidence → finding card, expanded "Details" (`features/findings/FindingCard.tsx` DetailsLevel) | Previous 23 days 1.33 / Recent 7 days 6 / "4.5× the previous level" (already on the collapsed card), then WHAT WAS MEASURED, BEFORE, RECENTLY (restating the same numbers in sentences), then WHY IT MAY MATTER (thresholds plus an ordinary reason), then ATTENTION, then KEEP IN MIND | The numbers are shown three times: collapsed line, bars and BEFORE/RECENTLY. WHY IT MAY MATTER mixes scoring thresholds with interpretation. | Use the bars plus one sentence for what was measured. Move the thresholds ("counts from 1.5×, full points at 5×") into Technical details. Keep the ordinary-reason clause and KEEP IN MIND visible. | High |
| E2 | Evidence → Findings header (`KeyFindings.tsx:35`) | "Wording verified" badge plus the S1 sentence | Fine as is, but it competes with the S1 duplicate. | Keep the badge. Fold the sentence into S1. | Low |
| E3 | Evidence → Transactions (`features/evidence/TransactionsTab.tsx`) | "Transactions in the recent period. Select a transaction ID to open its record." The SUPPORTS column says "None" on most rows. | The instruction is obvious from the link styling. A column full of "None" is noise. | Remove the sentence. Leave the cell blank, or show "—", when a row supports nothing. | Medium |
| H1 | Historical Comparison header (`features/evidence/HistoryTab.tsx`) | "Previous activity — The subject's own records in the 23 days before the recent period. Technical term: Baseline." | In the rendered text these definitions are `sr-only` Term tooltips, so sighted users don't see them. **No change needed.** Listed so nobody "fixes" them by removing the accessible definitions. | — | Low |
| H2 | Historical Comparison table (`HistoryTab.tsx`) | Row labels with units repeated: "Transactions per day per day", "Retailers used retailers", "Cities cities" | The unit is concatenated onto a label that already contains it, so it reads as a bug. | "Transactions / day", "Retailers used", "Cities". Put units in a small column, or drop them when the label already says it. | High |
| H3 | Historical Comparison footer (`HistoryTab.tsx:79`) | "Rates are per day so periods of different length compare fairly. Shares change in percentage points (pp). A change is a reason to look closer, not a conclusion." + "Recent = count ÷ 7 days; previous = count ÷ 23 days." + the "How these are calculated" disclosure | Three explanations of the same normalisation. The "not a conclusion" sentence is the S1 disclaimer again. | One line: "Per-day rates (recent ÷ 7 days, previous ÷ 23 days); shares in percentage points." Keep the disclosure. | Medium |
| H4 | Historical Comparison charts (`HistoryTab.tsx`) | The daily chart, then a full data table with EV-IDs listed underneath, then the hour chart, then an hourly table of 12+ rows | The visible tables repeat the charts. The ID list is long. | Put the tables in a collapsed "Show data" disclosure (keep them for screen readers via a caption or the table itself). Keep one "Open evidence" chip per chart. | Medium |
| R1 | Review → report body (`features/workspace/ReportPanel.tsx`, `ClaimRow.tsx`, `backend/services/report_writer.py`) | 41 statements, each followed by a "Verified" badge plus chips. Prefixes such as "SYSTEM STATUS", "SUGGESTED CHECK". The overview repeats the score caveat. | When every row says "Verified", the badge carries no signal. The header already says "41 of 41 statements checked". | Show the badge only on failed or unverified rows; the header count covers the rest. Collapse sections other than "Key findings", "Other possible explanations", "Missing information" and "Suggested next checks" by default. Keep the per-row chips. | High |
| R2 | Review → decision panel (`InvestigationDecision.tsx`, `ReviewPanel.tsx:95`) | "You decide; the AI does not. Actions record the report version and evidence fingerprint on screen." + the 3-sentence "A substantiated finding is…" paragraph + "Start the review to record a decision." | Several sentences sit before any action, on every visit. | Keep a short line: "You decide; the AI doesn't." Show the full substantiated-finding definition in the decision modal, where it applies, plus an ⓘ tooltip. Move the fingerprint note into the confirm modal (which already lists the report version). | Medium |
| R3 | Review → Evidence completeness (`SidePanel.tsx`) | Eight rows, then "Show details & sources", then the limitation sentence | Fine. The row list is the content. | Optionally collapse rows marked "Available" behind "+5 available" so Partial and Missing rows stand out. Keep the sentence. | Low |
| R4 | Review → Investigation checklist (`SidePanel.tsx:140`) | "Optional. Steps tick themselves as you work; you can also tick them." | Instructional text shown on every visit. | Change it to "Optional" as a subtitle. | Low |
| D1 | Evidence drawer (`features/workspace/EvidenceDrawer.tsx`) | The DATA SOURCES heading followed by "WHERE A PIECE OF EVIDENCE CAME FROM AND HOW IT WAS CALCULATED. TECHNICAL TERM: PROVENANCE.", then "Evidence version — A fixed, fingerprinted copy… Technical term: Snapshot." | The definition is set in eyebrow style (uppercase), which makes a long sentence hard to read. The Evidence version definition is visible prose, unlike the Term tooltips. | Heading "Data sources" with an ⓘ tooltip for the definition. "Evidence version: SNP-000007" with a tooltip. | Medium |
| D2 | Evidence drawer source list (`EvidenceDrawer.tsx:147`) | "Highlighted in Transactions and the timeline. Select one to open the original record." + 41 TXN chips + footer "41 records highlighted in the timeline and graph." + "Esc closes · records stay highlighted" | The highlight message appears twice. 41 chips push the provenance details far down. | Show the first 12 chips plus "+29 more". Keep one highlight note, in the footer. | Medium |
| D3 | Evidence drawer values (`EvidenceDrawer.tsx`) | "Relationship: rewards_card_attribution" | A raw enum is shown to investigators. | "Relationship: Rewards-card scan". Keep the raw value under Technical details. | Low |
| C1 | Copilot panel (`CopilotPanel.tsx:67,73`) | "Answers use only this case's records; every statement is cited and checked." + "Ask about this case. The copilot never decides whether fraud occurred." | Two subtitles when the panel is empty. | Merge into one line: "Answers cite this case's records only. It never decides whether fraud occurred." | Low |
| Q1 | Queue (`features/queue/QueuePage.tsx:82,159`) | "Simulated monitoring alerts. Scores are prototype rule scores, not fraud probabilities." + table caption "Investigation cases. Select a case ID to open its workspace; tick two cases to compare them." | The caption is instructional; the score caveat must stay. | Keep the subtitle. Make the caption `sr-only`, or shorten it to "Tick two to compare." | Low |
| M1 | Data & Methodology (`features/methodology/DataMethodologyPage.tsx:27,109`) | Long explanatory paragraphs | This is a reference page, so long text is expected here. | No change. Possibly add section anchors. | Low |
| G1 | Guide panel (`GuidePanel.tsx:65`) | "Explains pages, terms and the review workflow. It has no access to case records…" | The second sentence is a useful limitation. | No change. | Low |

## 3. Suggested order if this is taken up later

1. **H2**: duplicated units. This is a display bug and the fix is trivial.
2. **S1 + E1**: one disclaimer per screen, and leaner finding details.
3. **R1**: Verified badge only on exceptions, and a collapsed report.
4. **E3, H3, H4, D1, D2, R2**.
5. The Low items.

**Detection rules, scores and validators would not need changing for any of these.**
* S1/E1 involve backend display strings (`findings.py` `ATTENTION`, the explanation fields). Removing the per-card disclaimer means changing what the backend sends or what the card renders.
* The report's canonical wording would stay as it is (`report_writer.py`, `config.py`).
