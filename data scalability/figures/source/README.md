# Figure source code

generate_figures.py produces the theory, measured-summary and module-scaling exports from the current data root. test_theoretical_links.py checks formulas, intersections, export columns and report copies. generate_current_delta_repeats.py creates the diagnostic M1 three-repeat comparison.

All scripts resolve paths from their own location. Use --data-root when evaluating another explicit dataset; history is never searched implicitly. Python bytecode is excluded from this active folder and kept in archive/generated_cache/.
