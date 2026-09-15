# Data Scalability supporting note

This note points to the reproducible evidence package for the Data Scalability chapters. The report source remains authoritative for equations, captions and claims.

## Scope

The current campaign measures FULL and DELTA data traffic from one to four active modules at a commanded 200 Hz. It records USB application bytes, packet completion rate, packet length and integrity findings. ACC data and power measurements belong to other report sections.

## Core byte model

For the current four-slot envelope:

    L_FULL = 24 + 4M + 1044N
    L_DELTA = 24 + 4M + N(84 + 2K)

M is the configured slot count, N is the active module count and K is the ordinary DELTA mask population. The current firmware uses M=4. N>4 figures are conditional protocol-model extrapolations using M=max(4,N).

The measured zero-load FULL means are 1.736573, 3.407991, 5.076696 and 6.747828 Mbit/s for N=1-4 at 200 Hz. The selected zero-load DELTA means are 0.232562, 0.403900, 0.577646 and 0.762543 Mbit/s. Five passing dynamic batches reduce same-rate packet bytes by 65.10%-80.57%.

Use the scripts and figure source under this directory. The raw data are indexed by data/run_index.csv; data/path_map.csv records source paths and hashes. The historical pre-variable-SPI campaign under history/ is excluded from current statistics.
