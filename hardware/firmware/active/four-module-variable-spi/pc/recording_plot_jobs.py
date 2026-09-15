"""Launch plots of closed recordings without waiting in the serial worker."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

_children = []


def launch_recording_plots(run_dirs):
    paths = [Path(path).resolve() for path in run_dirs]
    if not paths:
        return
    script = Path(__file__).with_name("recording_plots.py")
    if not script.is_file():
        raise OSError(f"Plot script not found: {script}")
    for path in paths:
        if not (path / "summary.json").is_file() or not (path / "packet_log.csv").is_file():
            raise OSError(f"Closed recording files not found: {path}")
    # Keep handles until they can be reaped, but never wait for plot completion.
    _children[:] = [child for child in _children if child.poll() is None]
    flags = 0
    if os.name == "nt":
        flags = subprocess.CREATE_NO_WINDOW | subprocess.BELOW_NORMAL_PRIORITY_CLASS
    env = dict(os.environ, MPLBACKEND="Agg", PYTHONDONTWRITEBYTECODE="1")
    log_path = paths[0] / "plot_generation.log"
    with log_path.open("a", encoding="utf-8") as log:
        log.write("\nGenerating plots for closed recordings:\n" + "\n".join(map(str, paths)) + "\n")
        log.flush()
        child = subprocess.Popen(
            [sys.executable, "-B", str(script), *map(str, paths)],
            cwd=str(script.parent), env=env, stdin=subprocess.DEVNULL,
            stdout=log, stderr=subprocess.STDOUT, creationflags=flags,
        )
    _children.append(child)
