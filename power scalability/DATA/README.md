# Power data

Power evidence is separated by provenance and processing state.

| Directory | Role |
|---|---|
| `raw/canonical/` | Immutable source records, photographs, retests and `power_raw.csv`. |
| `raw/intake/` | Dated voltage supplements and intake notes. |
| `analysis/current/` | Current reviews, tables and report figure exports. |
| `analysis/retest_reviews/` | Pointwise retest analysis. |
| `analysis/provenance/` | Relocation and hash manifests. |
| `reference/` | Earlier analyses retained by current provenance. |
| `archive/` | Superseded preview material. |

Current report inputs are under `raw/canonical/` and `analysis/current/`. Do not edit raw records; regenerate derived outputs with scripts in `../script/Main/`.
