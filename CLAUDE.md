# TradingView-Indicators

Pine Script v6 indicators. One `.pine` file per indicator, named `MP_<Name>_V<n>.pine`.

## Versioning convention

**Every functional update to a script increments its version number.** That means, in the same change:

1. Rename the file: `MP_<Name>_V<n>.pine` → `MP_<Name>_V<n+1>.pine`.
2. Update the `indicator("... v<n+1>", ...)` title.
3. Update any version references in the script's header comment and About/tooltip text.
4. Update the file name and version in `README.md`.

Do NOT change the `//@version=6` compiler annotation — that is the Pine Script
*language* version, unrelated to the script's own version number.

Comment-only or whitespace-only changes do not require a bump. References to
older versions inside tooltips (e.g. "v5 zones kept sliding") are historical
lineage and should be left alone.
