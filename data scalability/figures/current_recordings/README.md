# Current-recording diagnostic figure

m1_large_area_repeats.png and the matching SVG compare all three 2026-09-07 M1 large-area DELTA repeats from one batch. The plot uses current raw records and marks recorded ESKF events. The first 10 seconds are shaded; the reported mean is calculated from the main window after 10 seconds and includes ESKF bytes.

These are diagnostic temporal repeats, not independent loading trials. The independent sequence review remains CHECK for this batch, so this comparison is not used as the selected dynamic performance result. The companion JSON stores source run IDs, input hashes, review status and output hashes.

Rebuild from this folder:

~~~text
python figures/source/generate_current_delta_repeats.py
~~~

The report''s embedded trace figure is maintained separately under Imperial College Individual Project Template_LaTeX/figures/data/v2_9/.
