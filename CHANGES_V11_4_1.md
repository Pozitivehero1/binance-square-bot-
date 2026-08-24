# v11.4.1 Text Integrity

Patch release for malformed AI text observed in production.

- Rejects AI candidates containing leaked prompt/template artifacts such as `exactly`, `X%`/`Y%`, TODO/TBD, replacement characters, long symbol runs and angle-bracket garbage.
- Explicitly instructs both TRADE and EVENT AI writers to return clean plain text only.
- Removes presentation-only Markdown markers before the final Square API call without changing prices or trade facts.
- Adds a final publisher hard gate so unsafe text cannot reach Binance Square even if an upstream validator misses it.
- Keeps the v11.3 cashtag protection: `$BTC:` is normalized to `$BTC —`.
- Adds `text_integrity_test.py` to the standard offline regression suite.

Trading selection, Entry/SL/TP logic, confirmed-entry handling and outcome policy are unchanged.
