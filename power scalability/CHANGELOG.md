## 2026-09-13 - DATA reclassification and portable paths

- Split `DATA/` into `raw/canonical`, `raw/intake`, `analysis/current`, `analysis/retest_reviews`, `analysis/provenance`, `reference` and `archive` so raw evidence is separate from derived outputs and historical snapshots.
- Updated analysis scripts, manifests, generated documentation and package READMEs to use repository-relative paths. Refreshed JSON validity and SHA-256 fields for files whose paths or metadata changed.
- Raw measurements, photographs, report artwork and the final report PDF were not regenerated or edited. The two validation suites continue to pass.
# Power Scalability Changelog

## 2026-09-07 - Report Version 2.8, latest M0 retests and signed drop panels

- Added the five latest M0 current/voltage retests: N=1 ZERO/MAX and every N=2
  ZERO combination containing M0. Together with the earlier N=3 M0 and M3
  updates, the selected analysis contains seven targeted branch updates but no
  new complete configuration repeats.
- Selected M0 values are 18.018 mA and 3.252 V at N=1 ZERO, 19.675 mA and
  3.249 V at N=1 MAX, and N=2 ZERO branch currents 17.941/17.969/17.956 mA
  with module voltages 3.251/3.251/3.250 V. The user-confirmed M0-M1 voltage
  replaces a misassigned photograph; the excluded assignment remains recorded.
- Recomputed the N summaries. ZERO current means are 18.290, 36.253, 54.426
  and 72.513 mA for N=1--4; recorded MAX means are 20.006, 39.629, 58.849
  and 78.720 mA. N=1--3 SDs describe different configurations, and N=4 remains
  n=1. Current-prediction residuals span -1.483 to -0.256% at ZERO and
  -2.726 to +0.460% at MAX.
- Removed the mean heatmap from the report. The new combination heatmap shows
  ZERO, MAX and signed MAX-minus-ZERO change, with adaptive 25--40 mV absolute
  scaling and a symmetric -10 to +10 mV difference scale. Of 32 paired module
  cells, 21 increase, six decrease and five are unchanged.
- Frozen analysis tables are in DATA/analysis/current/report_v2_8_analysis and formal figure
  exports in DATA/analysis/current/report_v2_8_figures. Eight report figures were exported in
  vector and raster formats; figure inputs, scripts and hashes are recorded.
- Updated the report's Power methods, results, discussion, appendix, abstract,
  conclusion and claim/evidence mapping. Accepted DMM minima are 3.240 V at
  ZERO and 3.236 V at MAX. Historical readings, source values, temperatures
  and unmodified branches keep their earlier provenance.
- The 72-page Version 2.8 PDF compiled without reportable LaTeX warnings, and
  all Power result/discussion/appendix pages were visually reviewed. Loading
  distribution, repeatability, simultaneous total current, verified monitoring,
  startup peaks, ripple, switching response and thermal rise remain unresolved.

## 2026-09-07 - Version 2.4, targeted Power retests and module-count figures

- Archived the complete live 2.3 source/PDF/checklist before editing under
  report_versions/v2.3/before_power_2.4_20260907_055110. Old PDF releases,
  acquisitions and derived 2.3 analyses remain unchanged.
- Selected the M0-M1-M2 ZERO M0 current retest (18.051 mA); retained its
  previously accepted 3.241 V. Selected M1-M2-M3 MAX M3 current 19.263 mA
  and voltage 3.243 V, with SOURCE 3.276 V confirmed unchanged: 33 mV,
  compared with the earlier 44 mV. Old measurements remain documented.
- Compiled sums are 54.564 and 59.159 mA for these two conditions. Other
  branches, temperatures and source extrema keep their earlier provenance.
  The 30 condition entries and 64 selected branches do not become 32 runs;
  no complete configuration repeat or simultaneous sum is claimed.
- Updated Power methods, results, discussion, appendix, abstract and conclusion.
  Revised N3 means/SD, included a before/after table, regenerated seven
  figures, and added the module-count mean heatmap plus N1-N4 four-panel
  figure. Four separate N figures are also exported (13 figures in total).
  M3 MAX N3 differences are 32,32,33 mV: mean 32.33, sample SD 0.58 mV.
- SD describes configuration spread, not repeatability. All five historical
  MIN/MAX inconsistencies remain in the baseline; four remain in the selected
  view. Retest loading equivalence and the cause of the M3 change are unresolved.
- Updated the same Word/Markdown checklist: 20/60 checked, P05 partial.
  Dynamic supply/thermal tests remain future work. Checked 179 source hashes,
  561 protected Power files, 118 unrelated report assets, 30 condition entries,
  64 branches and 110 group rows. Shared non-Power text is unchanged.
- Final PDF: 64 pages, stable references, no missing glyphs, undefined references
  or overfull boxes. All pages rendered and reviewed; repaired one long appendix
  paragraph and brought the supplementary heading onto its first figure page.
  Version hashes, source/data/figure archives and checklist snapshot are in
  report_versions/v2.4/manifest.json. Human scientific verification remains pending.

## 2026-09-07 - M3 retest source unchanged; drop estimate 33 mV

- User confirms SOURCE is unchanged for M1-M2-M3/MAX/M3. Retained original
  source main 3.276 V is now an explicit user-confirmed reference.
- Calculated 33 mV from 3.276-3.243 V, versus original 44 mV (-11 mV).
  The source/reference and retest module photo are distinct records; no
  new source extrema, simultaneous capture or full-configuration repeat is inferred.
- Updated record revision 4, readings/comparison CSVs and notes; archived
  previous versions. Connector reinsertion remains recorded; a causal fault
  diagnosis is not asserted. Existing full-matrix figures/report remain retained.

## 2026-09-07 - Targeted M0-M1-M2 ZERO M0 current retest

- Preserved the user's current photo and independently transcribed M0
  main/MIN/MAX 18.051/18.00/18.08 mA. User confirms voltage remains 3.241 V;
  its new MIN/MAX are not supplied and stay null.
- Current increased 0.083 mA from the original 17.968 mA. New main current is
  inside its display extrema; the historical main/MIN mismatch is retained.
  Linked the prior confirmed M0 contact-fault event and separate voltage retest.
- This supplies a later M0 current observation, not a new complete N3 run.
  No new SOURCE/M1/M2 values, summed current, repeat SD or fault-free result
  is inferred. Preserved original data, complete matrix, M3 retest and report.
  Saved intake and comparison under DATA/analysis/retest_reviews/m0_zero_retest_20260907/.

## 2026-09-07 - Retest SOURCE clarified as unmeasured

- User clarifies that 3.243/3.243/3.244 V are the photographed M3 module
  values; SOURCE has not been remeasured. Resolved the candidate's identity,
  retained the clarification history and kept retest SOURCE/drop null.
- Connector reinsertion remains confirmed; the original and new module
  readings are separate. No source value, complete run, repeat SD or
  retrospective fault diagnosis is fabricated; report/figures stay unchanged.

## 2026-09-07 - M3 retest connector clarification

- User confirms M3 connector reinsertion before the retest; no cable
  replacement, matched load or causal fault diagnosis is inferred.
- The response to the SOURCE question repeats 3.243/3.243/3.244 V,
  identical to the M3 photo. Saved it as a pending measurement-point
  candidate and requested clarification; new drop stays null, not 0 mV.
- Archived the pre-clarification record and notes, updated targeted-retest
  provenance only. Original readings, full matrix and report remain retained.

## 2026-09-07 - Targeted M1-M2-M3 MAX M3 retest

- Saved the user's two unmodified photographs and a separate targeted-retest
  record: M3 V main/MIN/MAX 3.243/3.243/3.244 V; I 19.263/19.25/19.41 mA.
  Direct visual transcription was independently checked.
- Compared with original M3 3.232 V and 19.721 mA: +11 mV and -0.458 mA.
  Retest source voltage and setup/connector/load changes remain unconfirmed,
  so new drop and fault cause are not inferred. Original 44 mV is retained.
- This is one module observation set, not a complete three-module repeated run.
  Original data, 30-condition matrix, existing figures and report 2.3 remain
  unchanged. Intake and comparison are in DATA/analysis/retest_reviews/m3_max_retest_20260907/.

## 2026-09-07 - Supplementary voltage-drop means by module count

- Added DATA/analysis/current/voltage_drop_by_N_20260907 and script/Main/figures/power_drop_by_count.py.
  Six figures (mean heatmap, four-panel raw-point/mean/SD plot, four separate
  N plots) are available as PNG/PDF/SVG, with 32 summary groups and all 64
  contributing branch observations and provenance.
- Per-module n is 1/3/3/1 at N=1/2/3/4. SD describes combinations, not repeated
  trials; n=1 SD is absent. ZERO N3 M0 keeps the marked cross-record retest
  estimate. MAX N3 M3 retains 32/32/44 mV, mean 36.00 and sample SD 6.93 mV.
- Verified 158 source hashes, statistics, export dimensions/fonts and visual
  layout. Mean plots supplement the full combination heatmap; no raw input,
  existing report figure, main 2.3 PDF or version archive was modified.

## 2026-09-07 - Report Version 2.3 published

- Integrated 15 combinations per ZERO/MAX label (30 conditions, 64 branches)
  into the Version 2.2 baseline; updated seven Power figures and the methods,
  results, discussion, appendix, abstract, conclusion and system interpretation.
- Configuration SD and n=4/6/4/1 remain distinct from repeatability; every
  exact condition has one observation. Loading and monitoring gaps, five
  current-reading flags and the M0 connector fault/retest remain documented.
- Preserved raw records, frozen analyses and older PDFs. The before-edit
  source/PDF/checklist archive is in report_versions/v2.2; the new 61-page
  report and release hashes are in main 2.3.pdf and report_versions/v2.3
  at the Final directory. The same Word checklist is updated, P05 partly
  complete and unchecked. Dynamic power/thermal validation is future work.

## 2026-09-07 - Completed N=3 MAX and summarized the full Power matrix

- Added `current_temperature_supplements/n3_max_20260907.csv` and metadata for
  M0-M1-M3 and M0-M2-M3: fourteen photos (six current, eight voltage) provide
  all main/MIN/MAX readings. Recorded the user's temperatures in module-ID
  order, Teensy, regulator: 27.4/27.3/26.9/42.6/30.0 and
  27.2/26.8/26.6/42.6/29.6 degC. Prior ZERO temperatures remain unchanged.
- Branch main-current sums are 58.631 and 58.279 mA, each with a 3.275 V
  source. Output-side estimates are 192.016525 and 190.863725 mW. The clear
  photographed M0-M1-M3 M3 current 19.178 mA is retained without adjustment.
  MAX follows the ongoing full-load completion task; mass/area/distribution,
  actual timing and fault counts are unknown. No simultaneous reading or
  time average is inferred, and SOURCE labels retain their order-based basis.
- Added `summarize_all_power_20260907.py` and `DATA/analysis/current/all_power_review_20260907/`:
  fifteen physical configurations each with ZERO/MAX observations, thirty
  configuration/load conditions and sixty-four module branches. Provides
  complete voltage/current/temperature tables, per-N and filename-batch
  descriptive statistics, matching-combination load differences, independent
  N=1-reference prediction checks, quality notes and source hashes. Historical
  blocked-standby records remain separate and are not counted as new repeats.
- N=3 MAX current is 58.96375 +/- 0.616176044 mA; power estimate is
  193.1360175 +/- 2.050760870 mW. SD is across the four different configurations,
  not repeat SD. Each configuration/load condition remains n=1; N=4 SD is null.
  Across all fifteen configurations MAX current exceeds ZERO by 7.664881% to
  10.972901%, interpreted descriptively given dates and incomplete load definitions.
- Current coverage views now report ZERO 15/15 and MAX 15/15. Previous ZERO
  and N=2 MAX numeric summaries are preserved; prior coverage outputs/scripts
  are archived under `DATA/analysis/current/all_power_review_20260907_history/before_n3_max_coverage/`.
  Updated current overviews, record guidance, revision notes and experiment log.
- Original measurement YAMLs, previous supplements, M0-only voltage repair,
  frozen analysis_v2_1 and main 2.1 PDF remain unchanged. Startup peaks, ripple,
  load-switching waveforms and continuous thermal curves remain future work.
- Validation: all fourteen new photos and six supplement rows checked; independent
  QA matched 448 branch numeric fields across 64 branches and recomputed all
  110 group-statistic rows. All configuration sums and voltage/current products
  agree. Source hashes, original 19 frozen inputs and report PDF were verified.
  The eight prior ZERO/N2 MAX measurement CSVs remain byte-identical; only
  coverage/provenance descriptions changed. All 23 existing tests passed. Five
  historical ZERO main-versus-MIN/MAX inconsistencies remain flagged unchanged.

## 2026-09-07 - Completed all N=2 MAX pairs; recorded voltage, current and temperature

- Added `current_temperature_supplements/n2_max_20260907.csv` and metadata for
  M0-M2, M0-M3, M1-M2 and M1-M3. The user explicitly confirmed MAX/full load.
  Twenty photographs supply all main/MIN/MAX values for eight branch-current,
  eight module-voltage and four source-voltage observations. Recorded sixteen
  user-supplied temperature points in ascending module order, Teensy, regulator;
  normalized the final supplied `29,2` to 29.2 degC.
- Preserved photographed main-current precision: M1-M2 M1 is 19.99 mA and
  M1-M3 M1 is 20.32 mA. New branch sums are 39.357, 39.335, 39.719 and
  40.016 mA; corresponding output-side estimates are 129.012246, 128.940130,
  130.159163 and 131.132432 mW. Neither sums nor power products are simultaneous
  measurements; no repeated observations or time averages are inferred.
- Added `summarize_n2_max_20260907.py` and `DATA/analysis/current/n2_max_review_20260907/` to
  combine all six MAX pairs, compare the matching ZERO configurations and
  retain dated-batch statistics and per-source provenance. MAX current is
  39.629 +/- 0.315 mA; estimated output power is 129.891 +/- 1.020 mW.
  These are sample SDs across six different configurations, not repeat SDs.
  Each condition has one record per configuration. Load comparisons are
  descriptive; new MAX mass/area/distribution are unspecified and date effects
  cannot be separated from configuration effects.
- Updated current coverage: N=2 ZERO and MAX each 6/6; overall ZERO 15/15 and
  MAX 13/15. Only M0-M1-M3 and M0-M2-M3 lack MAX records. Dynamic/thermal
  curves remain future work. Prior ZERO values, connector correction, original
  YAMLs/CSV inputs, frozen analysis_v2_1 and published main 2.1 remain unchanged.
- Repaired references after twenty historical N=2 ZERO photos moved into each
  pair's `zero_load` folder. All hashes match the earlier source manifest.
  `photo_source_paths.py` accepts only registered exact relocations and checks
  hashes; current outputs retain actual and original paths. Stored the migration
  manifest and prior scripts/derived files in `DATA/analysis/provenance/path_relocation_20260907/`.
  The raw historical references remain intact; no new MAX photo is substituted.
- Subsequently resolved fourteen moved N=3 ZERO photographs (eight voltage,
  six current) by the same recorded-hash rule: 34 relocations in total.
  Refreshed the ZERO coverage view to 13/15 MAX without changing any ZERO
  numerical result; linked the latest N=2 MAX review. The earlier YAML-only
  voltage view has its narrower scope documented separately.
- Validation: independent photo/temperature and Decimal arithmetic checks
  agree with the new supplement and six-pair summary. All 23 existing tests
  passed. The original 19 frozen inputs and published PDF hashes still match;
  migration checks preserve all ZERO measurements and the connector correction.

## 2026-09-07 - Added N=3 ZERO currents and temperatures; completed main-reading coverage

- Added six photographed branch currents for M0-M1-M3 and M0-M2-M3, linked
  to the existing voltage-only records. Main currents are respectively
  18.005/18.110/18.044 mA and 17.993/18.069/18.068 mA in module-ID order.
  Main sums are 54.159 and 54.130 mA; source-output estimates are
  177.479043 and 177.329880 mW using the earlier corresponding source voltage.
- Recorded the user's five temperatures per combination: M0-M1-M3
  27.4/26.7/26.9/42.7/29.6 degC; M0-M2-M3 27.4/26.6/26.6/42.6/29.2 degC.
  Order is three STM32 points in ascending module ID, Teensy, regulator.
- Created the combined `DATA/analysis/current/zero_power_review_20260907/` with all 15 ZERO
  configurations and 32 module branches, per-source provenance, N-specific
  and filename-date-batch statistics, plus a four-combination N=3 table.
  N=3 mean +/- sample SD is 54.405 +/- 0.337 mA and 178.245 +/- 1.091 mW.
  These are descriptive differences between configurations, not repeat SD.
- The M0-M1-M3 M0 photo's decoded lower portion does not expose MIN. The user
  subsequently confirmed MIN 18.00 mA during this intake; provenance identifies
  that confirmation separately from photograph-read main 18.005 mA and MAX
  18.03 mA. All 32 ZERO branches now have main/MIN/MAX values; original
  main-versus-extrema inconsistencies elsewhere remain flagged unchanged.
- Preserve all original YAMLs/photos, the historical M0-M1-M2 current and
  temperature readings, the M0-only voltage correction and connector event.
  The six supplemented configurations use separate current/voltage records;
  no simultaneous measurement, additional repeat or zero-fault result is inferred.
- MAX remains 9/15 configurations. Startup peaks, ripple, load-switching
  waveforms and continuous thermal curves remain future work as requested.
  Data notes/log updated; report PDF and frozen analysis_v2_1 are unchanged.
- Validation: six new branch readings and temperatures match the photographs
  and user values; both confirmed MIN values retain explicit provenance.
  Independent arithmetic agrees for the four N=3 configurations and all N-level
  current means/SD. Verified all 68 analysis-source hashes, the original 19
  frozen inputs and unchanged PDF; 189 protected files were unchanged during
  generation. Five historical main/MIN/MAX inconsistencies remain flagged;
  the six new branches have no such inconsistency. Existing N=2 values agree.

## 2026-09-07 - Deferred dynamic and thermal curves to future work

- Following the user's explicit scope decision, classify startup peak current,
  supply ripple, load-switching waveforms and continuous temperature-rise curves
  as future work, outside this round's required Power data completion. Mark
  them unvalidated rather than completed; existing point readings remain usable
  within their stated scope.
- Clarified incomplete fault-monitoring evidence: historical default-zero
  counters lack a verified observation method/window or event log. This alone
  establishes neither a fault nor its absence. Distinguish observed absence,
  unmonitored events and documented faults; retain the M0 connector event.
- Updated the measurement-plan scope, revision/future-work notes, record
  guidance and experiment log. No raw measurements, statistics, checklist
  completion marks or published report PDFs were changed.

## 2026-09-07 - User confirmed M0-M3 M3 minimum current

- Filled the previously unreadable M0-M3 M3 MIN with the user's 17.89 mA
  confirmation. Main 17.922 mA and MAX 18.05 mA are unchanged. Photo glare
  remains, so provenance is user confirmation rather than visual transcription.
- Regenerated branch/QC coverage and source hashes: all 12 N=2 ZERO branches
  now have main/MIN/MAX values. The separate old M0-M1 M1 main/MIN mismatch
  remains flagged. All current sums, power estimates and aggregate statistics
  are unchanged; no extra measurement repetition is counted.
- Updated the supplement, metadata, analysis script and current documentation.
  Preserved the previous eight input/derived/code files under
  `DATA/analysis/current/n2_zero_review_20260907/history/before_user_MIN_confirmation/`.
  This supersedes the missing-MIN status in the earlier entry below.
  Published report 2.1 and original photographs/YAMLs remain unchanged.

## 2026-09-07 - Completed N=2 ZERO current and temperature coverage

- Transcribed eight new DC-current photographs for M0-M2, M0-M3, M1-M2 and
  M1-M3, assigning branches in the user-confirmed ascending module order.
  Used the latest temperature message: regulator readings are respectively
  29.3, 29.2, 29.1 and 28.8 degC. The earlier incomplete message is superseded.
- Added `DATA/raw/canonical/power_experiment_records/current_temperature_supplements/`
  with a CSV and source/condition metadata. Link these later measurements to
  the existing voltage-only configurations without rewriting their raw YAMLs
  or counting voltage/current acquisitions as independent complete-run repeats.
- Added `script/Main/pipeline/summarize_n2_zero_20260907.py` and the six-configuration,
  twelve-branch review in `DATA/analysis/current/n2_zero_review_20260907/`. Branch-current sums
  span 35.907-36.561 mA; across-combination mean +/- sample SD is
  36.263 +/- 0.265 mA (CV 0.731%). Source-output power estimates are
  118.907 +/- 0.848 mW. Four estimates use earlier source-voltage readings;
  they are labelled cross-record estimates and exclude Teensy/regulator losses.
- Corresponding N=1 reference predictions give residuals -1.786% to -0.595%.
  Six configurations share four modules and two filename-date batches; this
  descriptive SD is not within-condition repeatability. Each pair has one
  recorded current observation per branch. Batch-specific statistics are retained.
- M0-M3 M3 current MIN is unreadable under glare and remains null. Main
  17.922 mA and MAX 18.05 mA are retained. The pre-existing M0-M1 M1 main
  18.055 mA versus MIN 18.06 mA mismatch is flagged without changing either.
- Recorded temperature ranges: module STM32 26.3-27.3 degC, Teensy
  42.5-43.1 degC, regulator 28.8-29.3 degC. These are point readings with
  no verified ambient temperature or thermal settling time.
- Generated per-source SHA256 provenance and verified 177 protected existing
  files unchanged during analysis. Published main 2.1, frozen analysis_v2_1,
  original voltage/current YAMLs and all photographs remain unchanged.
- Validation: all 23 existing power/voltage review tests passed; independent
  arithmetic agrees for six current sums, six power estimates and descriptive
  statistics. Verified all 32 new-analysis sources and 19 frozen original
  source hashes, the missing M3 MIN, and unavailable repeat SD fields.

## 2026-09-07 - Clarified that only the M0 connector was affected

- The user confirmed SOURCE/M1/M2 voltage points were unaffected and retain
  their original values. Revised the event to scope the fault to the original
  M0 voltage point only; the earlier whole-run exclusion was an over-broad
  interpretation and is superseded by this clarification.
- Accept the corrected M0-M1-M2 ZERO voltage configuration as SOURCE 3.276 V,
  M0 3.241 V from the retest, M1 3.250 V and M2 3.246 V from the original
  record. Preserve all raw values and per-point provenance. This is one
  corrected configuration, not a new simultaneous acquisition or extra repeat.
- Retain the old M0 3.224 V / 52 mV difference as fault history. The corrected
  M0 difference is estimated as 35 mV using the user-confirmed unchanged source;
  label this separately from differences measured within one record. The raw
  retest source remains null. No current or temperature values were invented.
- Accepted ZERO voltage coverage is 15/15 subsets (4+6+4+1), consisting of
  14 complete original configurations and one pointwise-corrected configuration.
  Raw review retains 51 module points, excludes only old M0, and accepts the
  other 50 points. The previous 14-complete/1-partial conclusion no longer
  describes accepted configuration coverage.
- Archived the previous event, manifest, review and code under
  `DATA/raw/intake/voltage_additions_20260907/history/before_M0_only_scope_clarification/`.
  Updated the event, voltage review and current explanatory notes; published
  main 2.1, its frozen analysis, all original YAMLs and photographs are unchanged.
- Validation: eleven updated voltage-review tests and twelve historical-analysis
  tests passed. Intake replay preserved the clarification byte-for-byte. The
  corrected four-point configuration and 15/15 ZERO coverage were independently
  inspected; original record/photo and published PDF hashes remain unchanged.

## 2026-09-07 - Added N=3 ZERO combinations and recorded a supply-contact fault

The whole-run exclusion and partial-coverage interpretation in this earlier
entry are superseded by the subsequent M0-only clarification above.

- Transcribed source and three module voltages for M0+M1+M3 and M0+M2+M3,
  keeping main/MIN/MAX values and per-photo provenance. Added a separate
  M0-only retest in the M0+M1+M2 configuration: main/MIN/MAX all 3.241 V.
  Three new VOLTAGE_ONLY YAMLs cover nine photographed points. Unknown
  source voltage for the partial retest, currents, temperatures and timing
  remain null; no old source voltage is reused to calculate a repaired drop.
- The user explicitly identified the earlier 3.224 V M0 reading as a supply
  wire/connector contact issue. It is an actual abnormal supply condition,
  not a probe/instrument measurement error. Preserved the original run and
  recorded the cause, hashes and retest relationship in
  `DATA/raw/canonical/power_experiment_records/quality_events/supply_contact_M0_20260907.json`.
- The original affected run is separated from summaries of connections without
  a reported contact fault. The repair retest measures only M0; original
  source/M1/M2 voltages and currents are not revalidated after repair. Fault
  and repaired readings are not pooled as equivalent-condition repetitions.
- Added a batch summary in `DATA/raw/intake/voltage_additions_20260907/` and a separate
  voltage review in `DATA/analysis/current/voltage_review_20260907/`. All four N=3 ZERO subsets
  have historical coverage, but M0+M1+M2 has only a partial post-repair voltage
  record; it is not a complete new normal-connection run.
- The historical Power 2.1 reproducer skips seven voltage-only supplements,
  discloses the subsequent contact event and warns against interpreting its
  unfiltered old tables as a current normal-connection analysis. The published
  PDF and `DATA/reference/analysis_v2_1/` remain unchanged pending report integration.
- Voltage review preserves 25 runs / 51 module points, classifying three points
  from the known fault run separately. The remaining 48 points have recorded
  minima of 3.234 V at ZERO and 3.231 V at MAX/overall; these are not transient
  bounds or proof that no other fault occurred. The old 3.224 V / 52 mV drop
  remains in historical/fault output. The old 89 mV value is headroom above
  3.135 V, not voltage drop.
- Validation: twelve historical-analysis checks and nine voltage-review checks
  passed. Independent photo/record review and input/output hash checks verified
  the new records, preserved old readings and unchanged published PDF.

## 2026-09-06 - Added four ZERO voltage-only two-module combinations

- Transcribed twelve photographs for M0+M2, M0+M3, M1+M2 and M1+M3:
  four source-voltage points and eight module-voltage points. The user
  confirmed ascending module order. The first photograph in each group is
  assigned to the source using the established sequence; this assignment is
  explicitly marked as inferred because the probe endpoint is not identifiable.
- Added one `zero_load/*VOLTAGE_R1.yaml` per combination with photo mappings,
  hashes and `measurement_scope: VOLTAGE_ONLY`. Main, MIN and MAX readings
  remain separate; unknown currents, temperatures, timing and fault counts
  are null. Capture-filename dates are kept separate from experiment times.
- Added `DATA/raw/intake/voltage_additions_20260906/` with the twelve-point CSV, source
  manifest and Chinese summary. ZERO voltage coverage for N=2 is now six
  combinations out of six, across the original and new record batches.
  Loaded coverage and repeat counts have not increased.
- The combined voltage/current analysis now explicitly excludes VOLTAGE_ONLY
  supplements and records their paths. Missing current in an unmarked record
  remains an error. Published report 2.1 and its derived outputs are unchanged;
  the voltage supplement has not yet been incorporated into report figures.
- Validation: all eleven combined-analysis regression checks passed; an
  independent transcription review matched all four YAML/CSV records. SHA-256
  checks passed for the four new YAMLs and twelve source photographs, and the
  published 2.1 PDF and its analysis source manifest remain unchanged.

## 2026-09-06 - Report 2.1 analysis of existing continuous-read records

- Added `analyze_power_revision.py` and `DATA/reference/analysis_v2_1/` for 18 FULL,
  configured-200-Hz continuous-USB records and 13 separately grouped legacy
  blocked-standby records. Eleven standby YAML mappings are duplicates, not
  additional experiments. Raw inputs and `DATA/analysis/` remain unchanged.
- Correctly mapped the N=1 module0 measurement columns to the recorded
  module label; retained each multi-module subset and each load condition.
- Added independent-single-module predictions, paired load differences,
  provenance and explicit QC flags. N=4 ZERO/MAX totals are 72.513/78.720 mA;
  minimum continuous-read module MIN is 3.224 V. Five minor representative
  current versus MIN/MAX inconsistencies were flagged without changing values.
- Regenerated seven report figures using the new analysis, with individual
  combinations and load states visible. No repeat SD is inferred from DMM
  ranges or differences between module combinations. Nine regression checks
  passed and all 21 PDF/PNG/SVG exports have recorded hashes.
- Updated the main report to Version 2.1 and the original Word checklist in
  place. Added `POWER_REVISION_2.1_CN.md` with evidence limits and future work.
  Revised P-H1 is a descriptive cross-configuration prediction check; P-H2
  concerns recorded voltage readings. Neither establishes fault-free operation,
  a worst-case load, thermal equilibrium or verified supply capacity.
- Archived the pre-revision report, checklist and Power support files under
  `../report_versions/v2.0/before_power_2.1_resumed_20260906_215540/`.
  This is an analysis/documentation revision, not a new experiment date.

## 2026-09-05 - Completed N=3 zero-load record transcription

- Transcribed source voltage, module voltages and branch currents from the
  photographs in module-number test order for M0-M1-M2 and M1-M2-M3.
- Retained the STM32, regulator and Teensy temperatures supplied separately.
- Marked the two zero-load records as `MEASURED` with `INCOMPLETE` quality;
  full-load records and unsupported metadata remain blank.
- Preserved the displayed values where the main reading and MAX/MIN differ
  slightly because of display precision.

## 2026-09-05 - Added N=2 M2-M3 temperature records

- Added the M2/M3 STM32 temperatures and the Teensy and regulator temperatures
  for the zero-load and full-load records.
- Marked both records as `MEASURED` with `INCOMPLETE` quality because the
  corresponding voltage, current and full-load metadata are not available.

## 2026-09-05 - Completed N=2 M0-M1 transmission record transcription

- Assigned the earlier photographs to M0 and the later photographs to M1.
- Transcribed source voltage, both module voltages and both branch-current readings
  for the zero-load and full-load records.
- Added the STM32, regulator and Teensy temperatures supplied in the desktop note.
- Marked both records as `MEASURED` with `INCOMPLETE` quality because full-load
  metadata and other run metadata remain unavailable.
- Preserved the displayed Zero-load M1 current values, including the 18.055 mA
  main reading and 18.06 mA displayed minimum; the 0.005 mA difference is a
  display-precision effect.

## 2026-09-05 - Completed N=1 transmission record transcription

- Transcribed the new M1/M2 voltage readings from the experiment photographs.
- Transcribed STM32, regulator and Teensy temperatures for the M1, M2 and M3
  zero-load/full-load records from the desktop measurement note.
- Marked the six updated records as `MEASURED` with `INCOMPLETE` quality because
  optional load metadata and run metadata remain unavailable.
- Kept the canonical `power_raw.csv` unchanged; continuous-USB records are not
  mixed into the legacy blocked-standby analysis until the analysis grouping is
  updated.

## 2026-09-04 - Set default fault counters in experiment templates

- Set `reset_count`, `current_limit_count`, `brownout_count`, `data_stop_count`,
  `data_gap_count` and `other_fault` to `0` in all 36 concrete run templates.
- Kept the completely blank master template unchanged; observed events should
  replace the relevant default count.

## 2026-09-04 - Set default run timing in experiment templates

- Set all 36 concrete run templates to `warmup_duration_s: 30` and
  `measurement_duration_s: 10`.
- Kept the completely blank master template unchanged.

## 2026-09-04 - Added structured Power experiment record templates

- Created `DATA/raw/canonical/power_experiment_records/` with a complete blank template and
  36 pre-parameterised run templates.
- Organised templates as `transmission` and `no_transmission`, then `n=1`--`4`,
  module combinations, and `zero_load`/`full_load` folders.
- Pre-filled only fixed run conditions; direct measurements and observations
  remain blank, while derived quantities are intentionally omitted for script
  calculation.

## 2026-09-04 - Marked existing Power records as blocked standby

- Added `host_usb_polling_state` to `DATA/raw/canonical/power_raw.csv` and marked all 13
  existing records as `BLOCKED_STANDBY_NO_CONTINUOUS_USB_READ`.
- Reserved `CONTINUOUS_USB_READ` for the new measurements with continuous USB
  consumption; all measured values remain unchanged.

## 2026-09-04 - Removed the rawdata archive on request

- Deleted `DATA/rawdata/`, including the M3 diagnostic record, the unfilled
  M1+M2+M3 template and the legacy N=4 CSV backup.
- Preserved `DATA/raw/canonical/power_raw.csv`, all derived analysis and current figures.

## 2026-09-04 - Documented host-side USB polling states in the report Method

- Added the closed-GUI and open-but-idle GUI states to the Method measurement
  boundary for 200 Hz FULL power measurements.
- Recorded that GUI state affects host polling and communication continuity,
  while the Teensy remains USB-powered and module current is measured only on
  the external 3.3 V branch.
- No power source data or Result text was changed.

## 2026-09-04 - Corrected N=1 Module 3 voltage record

- Corrected `PS01_N1_F200_ZERO_M3_R1` in `DATA/raw/canonical/power_raw.csv` to
  `V_module_avg=3.265 V`, `V_module_min=3.264 V` and `V_module_max=3.266 V`.
- Regenerated the derived Power analysis and figures; no current, temperature,
  fault or other module values were changed.

## 2026-09-04 - Added N=3 M1+M2+M3 steady-state record

- Added `PS01_N3_F200_ZERO_M1_M2_M3_R1` to `DATA/raw/canonical/power_raw.csv` using the
  supplied voltage and branch-current measurements.
- Recorded source average current as the sum of all three branch averages:
  `8.359 + 8.790 + 7.761 = 24.910 mA`; the unsynchronised minimum and maximum
  estimates are `24.470 mA` and `46.450 mA`.
- Set unreported fault counters to zero. Temperature fields use the original
  M1/M2/M3 reference records and are labelled as non-simultaneous inherited
  values; the run remains `INCOMPLETE` because timing and source-current
  extrema were not supplied.
- Regenerated the derived analysis and figures so the N=3 summary now includes
  both M0+M1+M2 and M1+M2+M3 combinations; report text was left unchanged.

## 2026-09-04 - Rescaled Figure 4.6 to the measured range

- Changed Figure 4.6's colour scale from a fixed `0-60 mV` range to the
  observed minimum-to-maximum voltage-drop range (`10-53 mV` for the current
  data).
- Changed the minimum-value colour to pure white while retaining the existing
  teal endpoint; missing module combinations remain separately masked.
- Kept all source values, calculations, cell labels and missing-data handling
  unchanged.

## 2026-09-04 - Added M1+M2+M3 joint-test template

- Added the fillable single-run template
  `DATA/rawdata/PS01_N3_F200_ZERO_M1_M2_M3_TEMPLATE.yaml` for
  `PS01_N3_F200_ZERO_M1_M2_M3_R1`.
- Fixed the test boundary to 200 Hz, `FULL`, `ZERO`, external regulated 3.3 V,
  Teensy connected and running with stable USB power, and STM32 SWD disconnected.
- Recorded that source average current is the sum of the three module branch
  averages; unobserved fault counters are entered as zero.
- Kept the template outside `power_raw.csv` and the derived analysis until a
  completed measurement is supplied.
- Marked the unfilled record as `TEMPLATE / NOT_RUN` so it cannot be confused
  with measured evidence.

## 2026-09-04 - Added N=2 M2+M3 steady-state record

- Added `PS01_N2_F200_ZERO_M2_M3_R1` to `DATA/raw/canonical/power_raw.csv`.
- Recorded source average current as the sum of all module branch averages:
  `8.808 + 7.838 = 16.646 mA`; missing fault counters were recorded as zero.
- Filled temperature fields from the original M2/M3 reference records and
  labelled them as non-simultaneous inherited values; the run remains
  `INCOMPLETE` because timing, source-current extrema and stable branch maxima
  were not supplied.
- Regenerated the derived power analysis and report figures so the N=2 point
  includes both M0+M1 and M2+M3 combinations.

## 2026-09-04 - Replaced active N=4 source for Results figures

- Archived the previous `N=4` row as
  `DATA/rawdata/PS01_N4_F200_ZERO_R1_legacy_20260904.csv` and replaced the
  active row in `DATA/raw/canonical/power_raw.csv` with the new `PS01_M3DROP_A_R1` values.
- Regenerated the derived power analysis and used the new N=4 values for the
  Results figures: current/power, supply voltage and voltage drop.
- Kept the report text unchanged as requested; the previous row remains an
  excluded historical record rather than an active measurement.

## 2026-09-04 - Added M3 voltage-drop raw record and fixed power-test boundary

- Saved the new four-module diagnostic record `PS01_M3DROP_A_R1` under
  `DATA/rawdata/PS01_M3DROP_A_R1.yaml`.
- Recorded that all power experiments use the Teensy connected to the modules
  and running the acquisition/control code, with stable USB power for the
  Teensy and no SWD connection to the STM32 boards.
- Kept the new diagnostic record outside `power_raw.csv` and existing plots
  because its duration, temperatures and status counts are missing, and the
  supplied M3 voltage minimum/maximum order was initially inconsistent and was
  corrected in the following entry.
- Recompiled the report after the Method update; `build/main.pdf` remains a
  49-page PDF.

## 2026-09-04 - Corrected M3 voltage extrema order

- Swapped the M3 source values in `PS01_M3DROP_A_R1.yaml` so that
  `V_module3_min_V=3.259` and `V_module3_max_V=3.262`.
- Updated the derived lower-limit headroom from 127 mV to 124 mV.
- Existing `power_raw.csv`, derived analysis files, figures and report results
  were left unchanged because this diagnostic record remains outside the formal
  analysed dataset.

## 2026-09-03 - Label all measured points in Figure 4.4

- Added direct numeric labels to every measured current and output-power point
  in Figure 4.4.
- Fits, extrapolations, measurements and calculations were unchanged.

## 2026-09-03 - Matched lowest-module labels to their curve

- Figure 4.5 now uses the same dark-charcoal colour for the `Lowest module
  mean` line, markers and numeric labels.
- Measurements, calculations and other figure encodings were unchanged.

## 2026-09-03 (revised project palette)

- Replaced the shared figure colours with `#596073`, `#7BB6BA`, `#DBD4CC`,
  `#D7BBA5`, `#9D725F` and `#B8442D`.
- Kept the source-versus-lowest-module comparison high-contrast using teal
  against dark charcoal; module series retain separate marker encodings.
- Preserved all measurements, calculations, axes and scientific meanings.

## 2026-09-03 (unified scientific figure palette)

- Replaced the previous mixed-color series with the shared muted teal
  scientific palette used by the final report.
- Standardised charcoal axes/text, pale grid and region fills, publication
  export settings, and the continuous heatmap palette.
- Preserved power measurements, calculations, axes, ranges, labels and output
  meanings.

## 2026-09-03 (higher-contrast comparison encodings)

- Separated `Source mean` and `Lowest module mean` with teal-cyan and slate
  blue respectively; the meanings and line/marker encodings are unchanged.
- Increased visual separation between mean-current and separately captured
  maximum bars using the palette's lavender fill and hatch.

## 2026-09-02 (direct voltage-point labels)

- Added a voltage label to every blue source-mean point.
- Added a `M0/M1/M2/M3: value` label to every orange worst-module point, using the module that produced that minimum.
- Added `worst_module_id` to the derived scaling summary only; raw measurements and estimators remain unchanged.
- Updated the report caption and regenerated the report figure exports.

## 2026-09-02 (remove minimum-voltage curve)

- Removed the black `Lowest module minimum` curve from the voltage-scaling figure.
- Kept the Module 3 minimum as an in-plot reference annotation and clarified the averaging/lowest-value rules in the report caption.
- Regenerated all figure exports and preserved the raw and derived CSV files unchanged.

## 2026-09-02 (clean report figures)

- Removed visible titles, subtitles, divider lines, footer notes and redundant panel titles from all seven generated power figures.
- Kept axes, legends, data encodings and essential in-plot numeric annotations; moved fit equations, conditions, sample basis and limitations into the report captions.
- Regenerated the PNG/PDF/SVG outputs and recopied the seven PDF figures used by the report; raw and derived measurement CSV files were not changed.

## 2026-09-02 (integration into final report template)

- Added Power Methods and Results to `../Final Report/`, following MSc booklet pages 10-12; Discussion is an outline only.
- Reused three core and four supplementary PDF figures without alteration; raw CSV and analysis outputs were not changed.
- Documented missing dynamic tests, repetitions, measurement metadata, temperature-field reconciliation and actual supply-board capacity.
- Kept report source/claim checks, completion notes and compilation outputs with the report rather than adding measurements to this dataset.

## 2026-09-02 (scientific figure refresh)

- Refreshed all seven charts using the scientific-visualization and matplotlib skills: consistent 180 mm layout, English labels, readable typography, and color-plus-marker encodings.
- Separated the measured range from model-only extrapolation; retained the original fits and exposed the limited sample basis.
- Replaced truncated branch-current bars with aligned dot plots and voltage-drop lines with an annotated matrix that explicitly marks absent module/run combinations.
- Displayed the full voltage acceptance band and separated temperature records into point-only panels; labelled non-synchronous maxima sums without implying a guaranteed transient bound.
- Added `power_figures.py`, `power_report.mplstyle`, and reproducible PNG (300 dpi), PDF, and SVG exports; retained the original PNG filenames for report compatibility.
- Added a figure index, source/export hashes, a validation script, and validation results. Inspected all seven PNGs for clipping and overlap.
- Corrected the default CSV input and documentation links to `DATA/raw/canonical/power_raw.csv`; the raw CSV and all five derived CSVs remain byte-for-byte unchanged.
- Updated report captions and the experiment log. No new measurement, raw-value correction, or fit change was introduced.

## 2026-09-01 (source-data analysis and folder organisation)

- Added an explicit scope statement: current N<=4 measurements show large supply-current capacity headroom, while scan-reduction spatial algorithms are excluded from this report and reserved for a separate Data Scalability evaluation.
- Added `README.md` and organised reproducible outputs under `DATA/analysis/` and the analysis code under `script/Main/`.
- Added `analyze_power_scalability.py` and `script/requirements.txt`; the script leaves `power_raw.csv` unchanged.
- Generated run, scaling, branch, thermal, anomaly, and JSON summaries plus seven power-scalability figures.
- Added a concise source-data analysis to `Power_Scalability_Measurement_Plan_CN.md`, including current/power fits, voltage margin, branch balance, temperature limitations, and named anomalies.
- Identified Module3's 53 mV average branch drop at N=4, Module2's 8.988 mA single-module current, Module1's N=4 current increase, non-monotonic Teensy temperature, and historical Module1 temperature-field conflict.
- Marked the N=4 64.72 mA value as a non-synchronous conservative upper estimate rather than a measured total-current peak.
- Corrected the planned PS-01 count from 27 to 9, the overall PS-01/PS-02 count from 45 to 27, and the PS-02 run IDs from `MAX` to the fixed `ZERO` load condition.

## 2026-08-31 (LM2596 supply documentation)

- Added the TI LM2596 datasheet to `hardware/new/docs/datasheet/LM2596_datasheet_TI.pdf`.
- Recorded the LM2596 3 A output rating and 3.6/4.5/6.9 A chip-level peak current-limit range in the power plan.
- Distinguished the chip protection limit from the actual current-limit setting of the assembled module.
- Added the LM2596 supply metadata and the unresolved module current-limit setting to `power_raw.csv`.

## 2026-08-31 (200 Hz run preparation)

- Started preparation for `PS01_N1_F200_ZERO_M0_R1`.
- Kept Module 0, `FULL`, `ZERO`, LM2596 3.3 V supply, and mA current range unchanged; only the frequency changes to 200 Hz.
- Left measurement fields pending until the hardware readings are available.

## 2026-08-31 (100 Hz module voltage correction)

- Corrected the Module 0 input voltage in `power_raw.csv` for `PS01_N1_F100_ZERO_M0_R1` to `3.267 V` average, `3.266 V` minimum, and `3.267 V` maximum.

## 2026-08-31 (200 Hz measurement)

- Added the measured `PS01_N1_F200_ZERO_M0_R1` row to `power_raw.csv`.
- Recorded that all available values matched the 100 Hz Module 0 run after changing only the frequency to 200 Hz.
- Left the measurement start time blank because it was not provided.
- Added the preliminary observation that frequency had no obvious supply-data impact for the current single-module, no-load comparison; this is not yet a general conclusion.

## 2026-08-31 (200 Hz start time correction)

- Set `measurement_start_time` for `PS01_N1_F200_ZERO_M0_R1` to `2026-08-31 17:00`.
- Separated the 16:54 preparation time from the actual measurement start time in the experiment log.

## 2026-08-31 (200 Hz maximum-load run)

- Started `PS01_N1_F200_MAX_M0_R1` at `2026-08-31 17:02`.
- Kept Module 0, `FULL`, LM2596 3.3 V supply, and mA current range unchanged; changed the load from `ZERO` to `MAX`.
- Added a pending CSV row for the run; measurement values remain blank until collected.

## 2026-08-31 (200 Hz maximum-load result)

- Completed `PS01_N1_F200_MAX_M0_R1` in `power_raw.csv` with the same measured values as the 100 Hz and 200 Hz `ZERO` runs.
- Recorded the preliminary observation that load change had no visible supply-data effect in the single-module comparison.
- Kept the conclusion incomplete pending repeat runs and additional module counts.
- Removed the temporary `STARTED` placeholder so the CSV contains one authoritative row for this run.

## 2026-08-31 (Module 1 baseline verification)

- Started `PS01_N1_F200_ZERO_M1_R1` at `2026-08-31 17:08` after replacing Module 0 with Module 1.
- Kept 200 Hz, `FULL`, `ZERO`, LM2596 3.3 V, and mA range fixed to verify the preliminary frequency/load conclusion.
- Added a pending CSV row; the fixed baseline will be adopted only after the Module 1 comparison is complete.

## 2026-08-31 (CSV encoding fix)

- Re-saved `power_raw.csv` as UTF-8 with BOM so Excel and VS Code correctly decode the Chinese fields and notes.

## 2026-08-31 (CSV language simplification)

- Replaced the Chinese text inside `power_raw.csv` with English while keeping all values and field meanings unchanged.

## 2026-08-31 (current remeasurement)

- Corrected the Module 0, 100 Hz, `FULL`, `ZERO` current values after reconnecting the meter in the mA configuration.
- Replaced the previous current readings with `8.13 mA` average, `8.112 mA` minimum, and `14.5 mA` maximum for the single-module record.
- Marked the `14.5 mA` value as a short transient peak requiring repeat confirmation.
- Standardized the CSV current value columns to A (`0.00813`, `0.008112`, `0.0145`); retained `DMM_current_range` as `mA`.

## 2026-08-31 (current unit normalization)

- Standardized the current fields and stored values in `power_raw.csv` to mA.
- Renamed current columns from `_A` to `_mA` and stored `8.13`, `8.112`, and `14.5`.
- Added the mA-to-A conversion rule before power calculations.

## 2026-08-31 (data and log separation)

- Moved the completed Module 0 measurement values into `power_raw.csv`.
- Reduced `Power_Scalability_Experiment_Log_CN.md` to experiment actions, timestamps, run IDs, and document changes.
- Updated the measurement plan to identify `power_raw.csv` as the source for collected values.

## 2026-08-31 (temperature measurement update)

- Removed ambient temperature from the direct measurement list.
- Added Teensy temperature to the temperature measurement points.
- Changed the temperature-rise reference from ambient temperature to each measurement point's run-start temperature.

## 2026-08-31 (measurement scope update)

- Removed connector-temperature measurement.
- Removed separate Teensy/Host current measurement.
- Defined source current as the external 3.3 V module-supply current, excluding the Teensy USB supply branch.
- Simplified the total-current and theoretical-current equations accordingly.
- Clarified that steady-state ripple uses a stable-run window, while power-on minimum voltage uses the complete startup transient window.

## 2026-08-31 (static measurement scope)

- Limited the plan to steady-state measurements after a fixed 30 s stabilization period.
- Removed ripple, power-on inrush, recovery-time, waveform, and long-term dynamic measurements.
- Removed the PS-02 and PS-03 experiments; the plan now contains 72 PS-01 runs.
- Changed voltage, current, and temperature fields to stable readings and removed peak/minimum transient requirements.

## 2026-08-31 (dynamic module transition scope)

- Kept PS-01 as the 72-run steady-state measurement.
- Added PS-02 for controlled module add/remove transitions while the remaining system is operating.
- Defined six transition types at 200 Hz and `MAX`, repeated three times, for 18 dynamic-event runs.
- Added healthy-module impact, event minimum voltage, recovery time, reset, current-limit, and data-gap checks.
- Added behavior-to-measurement tables for the PS-01 steady-state and PS-02 module-transition procedures.

## 2026-08-31 (experiment log)

- Added `Power_Scalability_Experiment_Log_CN.md` for the first formal run.
- Recorded the initial condition as Module 0, 100 Hz, `FULL`, `ZERO`, with a separate DMM voltage/current measurement sequence.
- Moved the detailed PS-01 and PS-02 operating procedures, wiring, instrument steps, and run-record templates into the experiment log.
- Reorganised the power plan to match the concise calibration-document structure: motivation, method, measurements, calculations, Evaluation, and outputs.
- Recorded the measured voltage, current, temperature, timestamp, and no-fault status for `PS01_N1_F100_ZERO_M0_R1`.
- Added pending experiment record `PS01_N1_F200_ZERO_M0_R1`, changing only the scan frequency from 100 Hz to 200 Hz.
- Confirmed that the recorded current values use amperes (A); retained the separately reported DMM range information.

## 2026-08-31 (stable summary values)

- Restored average, minimum, and maximum readings for basic voltage and current measurements.
- Defined these three values as readings within the stabilized measurement window, excluding startup transients, inrush, and ripple waveforms.
- Updated the first-run log fields and average-value power/drop calculations.

## 2026-08-31

- Reorganised the plan as a power-only scalability experiment.
- Fixed the test path to FSR-only `FULL` mode; removed ACC and data-algorithm comparisons.
- Added the complete experiment count: 72 main runs, 4 inrush groups with 20 power-on events, and 3 long-term runs.
- Replaced the obsolete ACC term in the theoretical current model.
- Added explicit run IDs, execution order, power-scaling model, pass criteria, and theory-versus-measurement outputs.
- Recorded the actual FNIRSI 2C53P instrument and its DMM/shunt-oscilloscope measurement procedures.
- Corrected the 2C53P DMM description: it supports maximum/minimum values and a time-variation curve; shunt-plus-oscilloscope is reserved for faster transient verification.

## 2026-08-31 (single-module screening closure)

- Confirmed that the recorded 200 Hz Module 0 `ZERO` and `MAX` runs produced identical available measurements.
- Stopped additional single-module frequency/load screening; retained all historical single-module rows, including the incomplete Module 1 baseline row.
- Fixed the formal scalability experiment conditions to 200 Hz, `FULL`, `ZERO`, and changed the steady-state matrix to start at `N=2`.
- Updated the power plan from a frequency/load matrix to a module-count scalability model and changed the formal steady-state total from 72 planned runs to 27.

## 2026-08-31 (Module 1 screening records completed)

- Added `PS01_N1_F200_ZERO_M1_R1` and `PS01_N1_F200_MAX_M1_R1` to `power_raw.csv`.
- Recorded both runs with the same supplied measurements as `PS01_N1_F100_ZERO_M1_R1`.
- Kept both runs `INCOMPLETE` because the module-voltage statistics are internally inconsistent and module-current, measurement-start-time, and supply-limit fields remain unavailable.

## 2026-08-31 (Module 2 and Module 3 baseline runs)

- Added pending `PS01_N1_F200_ZERO_M2_R1` and `PS01_N1_F200_ZERO_M3_R1@ rows for 200 Hz `FULL` `ZERO` reference measurements.
- Kept the formal scalability matrix unchanged; these are module-to-module baseline checks before the `N=2` multi-module runs.

## 2026-08-31 (Module 2 measurement)

- Updated `PS01_N1_F200_ZERO_M2_R1` from `STARTED` to `MEASURED` in `power_raw.csv`.
- Recorded the supplied Module 2 voltage, source-current, and temperature values; stored current in mA and marked the 16.99 mA value as an instantaneous peak.
- Kept the run `INCOMPLETE` because module branch current, measurement-start time, and the power-supply current-limit setting were not supplied.

## 2026-08-31 (Module 1 and Module 2 temperature correction)

- Swapped the regulator and Teensy temperature fields for `PS01_N1_F200_ZERO_M1_R1` and `PS01_N1_F200_ZERO_M2_R1@ after identifying a recording error.
- Kept the voltage, current, and other temperature values unchanged.

## 2026-08-31 (Module 1 voltage maximum correction)

- Updated `V_module0_max_V` to `3.271 V` for `PS01_N1_F100_ZERO_M1_R1`, `PS01_N1_F200_ZERO_M1_R1`, and `PS01_N1_F200_MAX_M1_R1`.
- Removed the related average-greater-than-maximum data-quality warning; all other values remain unchanged.

## 2026-08-31 (two-module power measurement)

- Extended `power_raw.csv` with Module 1 voltage/current fields, calculated total-current fields, per-module STM32 temperature fields, measurement duration, and the separate-branch current method.
- Added `PS01_N2_F200_ZERO_R1` for the Module 0 + Module 1 measurement.
- Calculated total average current as `16.267 mA`; minimum and maximum totals are unsynchronized branch-sum estimates of `16.238 mA` and `32.40 mA`.

## 2026-08-31 (three-module power measurement)

- Extended `power_raw.csv` with Module 2 voltage/current fields and Module 2 STM32 temperature.
- Added `PS01_N3_F200_ZERO_R1` for the Module 0 + Module 1 + Module 2 measurement.
- Calculated total average current as `25.179 mA`; minimum and maximum totals are unsynchronized branch-sum estimates of `24.779 mA` and `48.53 mA`.
- Kept the run `INCOMPLETE` because Module 0 voltage minimum and maximum were supplied in reverse order and measurement metadata remain incomplete.

## 2026-08-31 (three-module Module 0 voltage correction)

- Corrected the `V_module0_min_V` and `V_module0_max_V@ positions in `PS01_N3_F200_ZERO_R1` to `3.262 V` and `3.264 V`.
- Removed the related data-quality warning; all other three-module values remain unchanged.

## 2026-08-31 (four-module power measurement)

- Extended `power_raw.csv` with Module 3 voltage/current fields and Module 3 STM32 temperature.
- Added `PS01_N4_F200_ZERO_R1` for the Module 0 + Module 1 + Module 2 + Module 3 measurement.
- Calculated total average current as `33.134 mA`; minimum and maximum totals are unsynchronized branch-sum estimates of `32.505 mA` and `64.72 mA`.
- Kept the run `INCOMPLETE` because Module 1 maximum voltage was supplied as `2.254 V` while its average and minimum were about `3.253 V`, and measurement metadata remain incomplete.

## 2026-08-31 (four-module Module 1 voltage correction)

- Corrected `V_module1_max_V` in `PS01_N4_F200_ZERO_R1` from `2.254 V` to `3.254 V`.
- Removed the related data-quality warning; all other four-module values remain unchanged.

## 2026-08-31 (Module 3 measurement)

- Updated `PS01_N1_F200_ZERO_M3_R1` from `STARTED` to `MEASURED` in `power_raw.csv`.
- Recorded the supplied Module 3 voltage, source-current, and temperature values; stored current in mA and marked the 16.30 mA value as an instantaneous peak.
- Kept the run `INCOMPLETE` because module branch current, measurement-start time, and the power-supply current-limit setting were not supplied.

## 2026-08-31 (Module 1 baseline frequency correction)

- Changed the pending Module 1 baseline run from 200 Hz to 100 Hz before measurement.
- Renamed it to `PS01_N1_F100_ZERO_M1_R1` and set the corrected measurement start time to `2026-08-31 17:10`.
- Kept the previously recorded Module 0 runs unchanged; no 200 Hz Module 1 measurement data was retained.

## 2026-08-31 (Module 1 100 Hz zero-load measurement)

- Recorded `PS01_N1_F100_ZERO_M1_R1` in `power_raw.csv` as the completed 100 Hz `FULL` `ZERO` Module 1 run.
- Stored source voltage as `3.281/3.281/3.282 V` and source current as `8.119/8.112/15.98 mA` for average/minimum/maximum; the peak was marked as instantaneous.
- Stored the supplied module voltage and temperature readings; normalized the current fields to mA.
- Kept the run `INCOMPLETE` because the supplied module voltage average (`3.271 V`) exceeds its supplied maximum (`3.270 V`) and module current/start-time data are unavailable.

## 2026-08-28

- Corrected LaTeX escaping in the measurement and calculation formulas.
- Limited the FSR frequency test points to 240 Hz, the current hardware maximum.
- Added the required measurement-tool list and mapped each tool to the corresponding measurements.
- Corrected the power-scalability frequency ceiling from 240 Hz to 200 Hz, the current maximum combined-system frequency.

- Added `Power_Scalability_Measurement_Plan_CN.md`.
- Recorded the test matrix, direct measurements, calculated quantities, and output files for subsequent power-scalability experiments.
- Updated Figure 4.7's voltage-drop matrix gradient from #DBD4CC to #0F9EA8; data, scale and missing-value encoding are unchanged.
- Changed Figure 4.8 to a vertical two-panel layout; individual-cell traces now use thinner #7BB6BA lines. Data, measurement points, fitted lines and axes are unchanged.
- Updated Figure 4.10 calibration-dispersion colours: FIT PRESS uses #7BB6BA and LINEAR uses #8B84A3; NORM CAL, data and axes are unchanged.
- Updated Figure 4.8 measured points to #45728F; cell traces, connected mean/model lines, data and layout are unchanged.
