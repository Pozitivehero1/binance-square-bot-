# v11.2 — Signal Quality + Confirmed Entry

Goal: improve the chance that reach turns into qualified trading activity without sacrificing the audience engine.

- Reach learning and signal quality are now separate. Public views/ticker/hour/lane affinity still optimize distribution.
- A new bounded outcome-quality component learns only from integrity-verified closed trade plans. TP3 receives full credit, TP1/TP2 partial credit, and pure stops zero. Small samples are heavily shrunk toward the global baseline.
- Outcome quality is applied to TRADE plans; EVENT reach remains untouched so high-view event discovery is not suppressed by trade-history noise.
- Near-level setups are no longer considered entered at publication. The public post can still go live for reach, but the journal internally waits for a closed 1m breakout/breakdown beyond the outer edge of the entry zone before counting the trade as entered.
- Existing breakout/retest confirmation modes remain unchanged.
- Public plan gate is modestly stricter (TP3 R/R 1.65, public risk <=7%).
- Weak cycles are filtered a little more aggressively while preserving high-reach EVENT opportunities.
- DeepSeek remains primary, but transient OrcaRouter failure now falls back to the empirically strong Mistral path faster to protect event freshness.
- Pending entries expire after 18h and active tracking after 72h.

No revenue or trade-result guarantee is implied; this version is designed to optimize the observed funnel more conservatively.
