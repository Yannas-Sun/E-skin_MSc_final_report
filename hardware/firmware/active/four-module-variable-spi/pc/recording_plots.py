"""Read-only, post-recording plots for schema-2 experiment captures.

Importing this module uses only the standard library. The CLI selects Agg in its
own process; importing this module never changes the GUI's matplotlib backend.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import sys
import textwrap
from datetime import datetime, timezone


PLOT_NAMES = ("mul1_length_over_time.png", "usb_throughput_over_time.png")
TEAL = "#7BB6BA"
FULL = "#B8442D"
MEAN = "#9D725F"
K0 = "#596073"
GRID = "#E8E4DF"
SYNC_COLORS = (TEAL, FULL, MEAN, "#D7BBA5")


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _number(value):
    try:
        result = float(value)
    except (ValueError, TypeError):
        return None
    return result if math.isfinite(result) else None


def _true(value):
    return str(value).strip().lower() == "true"


def bin_packet_bytes(packets, duration, bin_seconds=1.0):
    """Use [left, right) PC-completion bins, final right endpoint included.

    Empty bins remain zero, repeated completion timestamps remain separate
    packets, and the final partial bin uses its actual observed duration.
    Each packet is a mapping with time_s and bytes, already outer-valid.
    """
    if not math.isfinite(duration) or duration < 0 or bin_seconds <= 0:
        raise ValueError("Invalid duration or bin width")
    if duration == 0:
        return []
    count = math.ceil(duration / bin_seconds)
    bins = [{"start_s": i * bin_seconds,
             "end_s": min((i + 1) * bin_seconds, duration),
             "bytes": 0, "packets": 0} for i in range(count)]
    for packet in packets:
        t = packet["time_s"]
        if t < 0 or t > duration:
            raise ValueError("Packet completion lies outside capture duration")
        index = min(int(t / bin_seconds), count - 1)
        bins[index]["bytes"] += packet["bytes"]
        bins[index]["packets"] += 1
    for item in bins:
        item["width_s"] = item["end_s"] - item["start_s"]
        item["Mbit_per_s"] = item["bytes"] * 8 / item["width_s"] / 1e6
    return bins


def _independent_review(run_dir, run_id):
    """Look up exact run IDs in local indexes, stopping at the data root.

    An absent review is unknown, never inferred to pass from the GUI summary.
    Conflicting indexes conservatively retain any explicit CHECK / ineligible.
    """
    run_dir = Path(run_dir).resolve()
    parents = list(run_dir.parents)
    boundary = next((i for i, p in enumerate(parents) if p.name.lower() == "data"), None)
    directories = [run_dir] + (parents[:boundary + 1] if boundary is not None else [])
    matches, lookup_errors = [], []
    for directory in directories:
        index = directory / "run_index.csv"
        if not index.is_file():
            continue
        try:
            with index.open(newline="", encoding="utf-8-sig") as stream:
                rows = [r for r in csv.DictReader(stream) if r.get("run_id") == run_id]
            for row in rows:
                audit = (row.get("independent_raw_audit") or "").strip()
                eligible = (row.get("main_eligible") or "").strip()
                if not audit and not eligible:
                    continue
                matches.append({"index_path": str(index), "index_sha256": _sha256(index),
                                "independent_raw_audit": audit, "main_eligible": eligible,
                                "review_reasons": row.get("independent_review_reasons") or row.get("main_review_reasons") or ""})
        except (OSError, csv.Error, UnicodeError) as exc:
            lookup_errors.append(f"{index}: {type(exc).__name__}: {exc}")
    check = any("CHECK" in r["independent_raw_audit"].upper()
                or "FAIL" in r["independent_raw_audit"].upper()
                or r["main_eligible"].lower() == "false" for r in matches)
    passed = any(r["independent_raw_audit"].upper().startswith("PASS") for r in matches)
    return {"status": "CHECK" if check else "PASS" if passed else "unknown",
            "matches": matches, "lookup_errors": lookup_errors}


def load_plot_data(run_dir):
    """Read capture files and optional local review indexes; never rewrite them."""
    run_dir = Path(run_dir)
    with (run_dir / "summary.json").open(encoding="utf-8-sig") as stream:
        summary = json.load(stream)
    if summary.get("schema_version") != 2:
        raise ValueError("Only schema_version=2 is supported")
    duration = _number(summary.get("duration_seconds"))
    if duration is None or duration < 0:
        raise ValueError("summary.duration_seconds must be finite and non-negative")
    scopes = summary.get("scopes", {})
    main = scopes.get("main", {})
    full = scopes.get("full_run", {})
    settle = _number(summary.get("settle_seconds"))
    settle = settle if settle is not None and settle >= 0 else 10.0
    main_start = _number(main.get("start_elapsed_s"))
    main_start = settle if main_start is None else main_start
    main_end = _number(main.get("end_elapsed_s"))
    main_end = duration if main_end is None else main_end
    metadata = summary.get("metadata", {})
    warnings = []
    errors = []
    targets = metadata.get("target_modules")
    if (not isinstance(targets, list) or not targets
            or any(type(v) is not int or v < 0 for v in targets)
            or len(set(targets)) != len(targets)):
        targets = []
        warnings.append("Target modules unavailable: reference lines omitted; observed N is not substituted")
    slots = metadata.get("M", 4)
    if type(slots) is not int or slots < 1 or any(v >= slots for v in targets):
        raise ValueError("Invalid maximum slot count or target module index")
    counts = {"candidate_rows": 0, "outer_valid_complete_rows": 0,
              "invalid_candidates": 0, "outer_crc_not_true": 0,
              "length_invalid_or_incomplete": 0, "outer_valid_parse_not_ok": 0,
              "invalid_completion_time": 0, "plotted_outer_valid_packets": 0,
              "plotted_outer_valid_bytes": 0}
    valid = []
    invalid = []
    with (run_dir / "packet_log.csv").open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        required = {"elapsed_s", "received_bytes", "declared_length", "outer_crc_ok", "parse_ok", "algorithms"}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError("packet_log.csv lacks required schema-2 columns")
        for row in reader:
            counts["candidate_rows"] += 1
            t = _number(row.get("elapsed_s"))
            received = _number(row.get("received_bytes"))
            declared = _number(row.get("declared_length"))
            lengths_ok = (received is not None and received > 0 and received.is_integer()
                          and received == declared)
            crc_ok = _true(row.get("outer_crc_ok"))
            outer_valid = crc_ok and lengths_ok
            if not crc_ok:
                counts["outer_crc_not_true"] += 1
            if not lengths_ok:
                counts["length_invalid_or_incomplete"] += 1
            if outer_valid:
                counts["outer_valid_complete_rows"] += 1
                if not _true(row.get("parse_ok")):
                    counts["outer_valid_parse_not_ok"] += 1
            else:
                counts["invalid_candidates"] += 1
            if t is None or not 0 <= t <= duration:
                counts["invalid_completion_time"] += 1
                continue
            packet = {"time_s": t, "bytes": int(received) if received is not None else 0,
                      "parse_ok": _true(row.get("parse_ok")),
                      "algorithms": [a.strip() for a in row.get("algorithms", "").split(",")]}
            (valid if outer_valid else invalid).append(packet)
    counts["plotted_outer_valid_packets"] = len(valid)
    counts["plotted_outer_valid_bytes"] = sum(p["bytes"] for p in valid)
    if counts["invalid_completion_time"]:
        errors.append(f"{counts['invalid_completion_time']} candidates have missing/out-of-range PC completion time; omitted from timed plots")
    if counts["invalid_candidates"]:
        warnings.append(f"{counts['invalid_candidates']} invalid/incomplete outer candidates excluded from valid-byte statistics")
    if counts["outer_valid_parse_not_ok"]:
        warnings.append(f"{counts['outer_valid_parse_not_ok']} outer-valid packets with inner parse errors remain in byte statistics")
    if not valid:
        warnings.append("No complete outer-CRC-valid packets available")
    if not summary.get("completed_requested_duration", False):
        warnings.append("Capture stopped early; actual duration used")
    main_packets = [p for p in valid if main_start <= p["time_s"] <= main_end]
    main_bytes = sum(p["bytes"] for p in main_packets)
    main_duration = _number(main.get("actual_duration_seconds"))
    main_calculated = {
        "valid_outer_packets": len(main_packets), "valid_outer_packet_bytes": main_bytes,
        "Lmean_valid_packet_B": main_bytes / len(main_packets) if main_packets else None,
        "packet_completion_Mbit_per_s": main_bytes * 8 / main_duration / 1e6 if main_duration and main_duration > 0 else None,
    }
    for key, actual in main_calculated.items():
        expected = main.get("counts", {}).get(key) if key == "valid_outer_packets" else main.get(key)
        expected = _number(expected)
        if expected is not None and (actual is None or not math.isclose(expected, actual, rel_tol=1e-9, abs_tol=1e-8)):
            errors.append(f"Main summary/CSV mismatch: {key}, summary={expected}, CSV={actual}")
    return {"summary": summary, "duration_s": duration, "settle_s": settle,
            "main_start_s": main_start, "main_end_s": main_end,
            "main": main, "full": full, "valid": valid, "invalid": invalid,
            "counts": counts, "warnings": warnings, "errors": errors,
            "target_modules": targets, "wrapper_bytes": 24 + 4 * slots,
            "main_calculated": main_calculated,
            "independent_review": _independent_review(run_dir, summary.get("run_id")),
            "bins": bin_packet_bytes(valid, duration)}


def _setup_panel(data, ax, panel_label):
    ax.set_facecolor("white")
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(K0)
        ax.spines[side].set_linewidth(.65)
    ax.tick_params(colors=K0, labelsize=8, width=.6, length=3)
    ax.grid(True, color=GRID, linewidth=.55, alpha=.65)
    ax.set_axisbelow(True)
    ax.set_xlim(0, max(data["duration_s"], .1))
    ax.set_xlabel("PC completion time from record start (s)", fontsize=9, color=K0)
    ax.axvspan(0, min(data["settle_s"], data["duration_s"]), color=GRID,
               alpha=.14, linewidth=0, zorder=0)
    if panel_label is not None:
        ax.text(0, 1.025, str(panel_label), transform=ax.transAxes,
                ha="left", fontsize=9, color=K0)
    errors = data.get("errors", [])
    if errors:
        ax.text(.01, .985, "PLOT DATA ERROR: " + textwrap.shorten("; ".join(errors), width=140),
                transform=ax.transAxes, va="top", color=FULL, fontsize=7,
                bbox={"facecolor": "white", "edgecolor": "none", "alpha": .9}, zorder=20)


def _sync_lines(data, ax):
    for slot in range(data["summary"].get("metadata", {}).get("M", 4)):
        times = [p["time_s"] for p in data["valid"]
                 if slot < len(p["algorithms"]) and p["algorithms"][slot] == "DELTA_SYNC"]
        if times:
            # Only dash phases differ: event timestamps are never shifted.
            ax.vlines(times, 0, 1, transform=ax.get_xaxis_transform(),
                      colors=SYNC_COLORS[slot % 4], linewidth=.75,
                      linestyles=((slot % 4) * 2, (4, 4)), alpha=.22, zorder=1,
                      label=f"M{slot} ESKF")


def _right_labels(ax, references):
    """Axes-relative labels with short leaders, separated without moving data."""
    if not references:
        return
    low, high = ax.get_ylim()
    entries = sorted([(value, label, color, (value-low)/(high-low))
                      for value, label, color in references], key=lambda r: r[0])
    positions = []
    for entry in entries:
        positions.append(max(.045, entry[3], positions[-1] + .088 if positions else 0))
    if positions[-1] > .97:
        offset = positions[-1] - .97
        positions = [p - offset for p in positions]
    for (value, label, color, actual), placed in zip(entries, positions):
        ax.annotate(label, xy=(1, actual), xycoords="axes fraction",
                    xytext=(1.023, placed), textcoords="axes fraction",
                    ha="left", va="center", color=color, fontsize=9,
                    annotation_clip=False,
                    arrowprops={"arrowstyle": "-", "color": color, "lw": .65,
                                "shrinkA": 2, "shrinkB": 0,
                                "connectionstyle": "arc3,rad=0"})


def _error_markers(data, ax):
    if data["invalid"]:
        ax.scatter([p["time_s"] for p in data["invalid"]], [0] * len(data["invalid"]),
                   marker="x", s=15, linewidths=.8, color=FULL, label="Invalid outer", zorder=8)
    parse_bad = [p for p in data["valid"] if not p["parse_ok"]]
    if parse_bad:
        ax.scatter([p["time_s"] for p in parse_bad], [0] * len(parse_bad), marker="x",
                   s=15, linewidths=.8, color=MEAN, label="Inner error", zorder=8)
    if not data["valid"]:
        ax.text(.5, .5, "NO COMPLETE OUTER-VALID PACKETS", transform=ax.transAxes,
                ha="center", color=FULL, fontsize=9)


def draw_length_panel(data, ax, panel_label=None):
    """Draw one publication-style axes; caller reserves space for right labels.

    DELTA_SYNC packets are deliberately omitted from the ordinary trace, but
    remain in all numerical means, bins and per-slot vertical event markers.
    No matplotlib import or global style/backend change occurs here.
    """
    _setup_panel(data, ax, panel_label)
    _sync_lines(data, ax)
    mode = data["summary"].get("metadata", {}).get("target_mode", "")
    ordinary = [p for p in data["valid"] if "DELTA_SYNC" not in p["algorithms"]
                and (mode != "DELTA" or "DELTA" in p["algorithms"])]
    if ordinary:
        ax.plot([p["time_s"] for p in ordinary], [p["bytes"] for p in ordinary],
                color=TEAL, lw=.65, alpha=.88, zorder=3,
                label="Ordinary DELTA" if mode == "DELTA" else "FULL packets")
    references = []
    n = len(data["target_modules"])
    if n:
        full = 1044 * n + data["wrapper_bytes"]
        lower = 84 * n + data["wrapper_bytes"]
        ax.axhline(full, color=FULL, lw=1.15, label="FULL", zorder=4)
        ax.axhline(lower, color=K0, lw=1, label="K=0", zorder=4)
        references.extend([(full, f"{full:g} B", FULL), (lower, f"{lower:g} B", K0)])
    average = _number(data["main"].get("Lmean_valid_packet_B"))
    if average is not None:
        ax.hlines(average, data["main_start_s"], data["main_end_s"], color=MEAN, lw=1.15,
                  label="Mean incl. ESKF", zorder=5)
        references.append((average, f"{average:.1f} B", MEAN))
    top = max([p["bytes"] for p in ordinary] + [r[0] for r in references] + [1])
    ax.set_ylim(0, top * 1.09)
    if mode == "DELTA" and data["summary"].get("metadata", {}).get("condition") != "zero_load" and ordinary:
        peak = max(ordinary, key=lambda p: p["bytes"])
        # This maximum excludes ESKF even when a sync frame is the largest packet.
        x = peak["time_s"]
        direction = -1 if x > data["duration_s"] * .75 else 1
        ax.scatter([x], [peak["bytes"]], s=18, facecolor="#333333",
                   edgecolor="white", linewidth=.6, zorder=9)
        ax.annotate(f"max {peak['bytes']} B", (x, peak["bytes"]), xytext=(direction * 18, 10),
                    textcoords="offset points", fontsize=7, color=K0,
                    ha="right" if direction < 0 else "left",
                    arrowprops={"arrowstyle": "-", "lw": .6, "color": K0})
    _error_markers(data, ax)
    _right_labels(ax, references)
    ax.set_ylabel("MUL1 packet length (B)", fontsize=9, color=K0)
    return ax


def _draw_throughput_panel(data, ax):
    _setup_panel(data, ax, None)
    _sync_lines(data, ax)
    bins = data["bins"]
    if bins:
        edges = [b["start_s"] for b in bins] + [bins[-1]["end_s"]]
        values = [b["Mbit_per_s"] for b in bins] + [bins[-1]["Mbit_per_s"]]
        ax.step(edges, values, where="post", color=TEAL, lw=.95, zorder=3, label="PC throughput (1 s bins)")
        ax.fill_between(edges, values, step="post", color=TEAL, alpha=.12, zorder=2)
    references = []
    average = _number(data["main"].get("packet_completion_Mbit_per_s"))
    if average is not None:
        ax.hlines(average, data["main_start_s"], data["main_end_s"], color=MEAN,
                  lw=1.15, label="Mean incl. ESKF", zorder=5)
        references.append((average, f"{average:.4f} Mbit/s", MEAN))
    top = max([b["Mbit_per_s"] for b in bins] + [r[0] for r in references] + [1e-4])
    ax.set_ylim(0, top * 1.12)
    _error_markers(data, ax)
    _right_labels(ax, references)
    ax.set_ylabel("PC throughput (Mbit/s)", fontsize=9, color=K0)


def _plot(data, output, kind, plt):
    fig, ax = plt.subplots(figsize=(12.5, 4.6), facecolor="white")
    fig.subplots_adjust(left=.075, right=.855, top=.82, bottom=.29)
    if kind == "length":
        draw_length_panel(data, ax)
    else:
        _draw_throughput_panel(data, ax)
    meta = data["summary"].get("metadata", {})
    ax.set_title(f"{meta.get('target_mode', '?')} | {meta.get('condition', 'capture')} | {data['summary'].get('run_id', '')}",
                 loc="left", fontsize=10, color=K0, pad=24)
    review = data.get("independent_review", {}).get("status", "unknown")
    audit = f"GUI main: {data['main'].get('status', 'unknown')}  |  full capture: {data['full'].get('status', 'unknown')}"
    ax.text(0, 1.025, audit, transform=ax.transAxes, ha="left", fontsize=7, color=K0)
    ax.text(1, 1.025, f"independent review: {review}", transform=ax.transAxes,
            ha="right", fontsize=7, color=FULL if review == "CHECK" else K0)
    handles, labels = ax.get_legend_handles_labels()
    by_label = dict(zip(labels, handles))
    preferred = ("Ordinary DELTA", "PC throughput (1 s bins)", "FULL packets",
                 "Mean incl. ESKF", "K=0", "FULL", "M0 ESKF", "M1 ESKF", "M2 ESKF", "M3 ESKF")
    labels = [label for label in preferred if label in by_label]
    labels.extend(label for label in by_label if label not in labels)
    handles = [by_label[label] for label in labels]
    fig.legend(handles, labels, loc="lower center", bbox_to_anchor=(.48, .08),
               ncol=min(4, max(1, len(labels))), frameon=False, fontsize=7,
               labelcolor=K0, handlelength=2, columnspacing=1.35)
    c = data["counts"]
    note = (f"Mean: main window from {data['main_start_s']:g} s, ESKF included. "
            f"Outer-valid {c['plotted_outer_valid_packets']}; invalid {c['invalid_candidates']}; inner errors {c['outer_valid_parse_not_ok']}. ")
    if kind == "length":
        note += "ESKF shown as events (reason unknown); K=0 assumes all target slots ESKD, no ESKF."
    else:
        note += "Actual bin widths; empty bins retained. PC timing is not SCK; ESKF reasons unknown."
    if not data["summary"].get("completed_requested_duration", False):
        note += " EARLY STOP."
    fig.text(.075, .035, textwrap.fill(note, 175), fontsize=6.4, color=K0, va="bottom")
    try:
        fig.savefig(output, dpi=300, facecolor="white")
    finally:
        plt.close(fig)


def render_run(run_dir):
    """Render into the run directory. Call from a dedicated plotting process."""
    run_dir = Path(run_dir).resolve()
    status = {"plot_schema_version": 1, "created_at": datetime.now(timezone.utc).isoformat(),
              "run_directory": str(run_dir), "status": "ERROR", "errors": [], "warnings": [],
              "sources": {}, "outputs": {}, "definitions": {
                  "time": "packet_log.elapsed_s is PC packet-completion monotonic elapsed time",
                  "valid_bytes": "outer_crc_ok=True and received_bytes=declared_length>0, regardless of inner parse_ok",
                  "throughput": "valid completed bytes*8 / actual PC bin width / 1e6; empty bins retained",
                  "ESKF": "included in mean and throughput; omitted from ordinary trace and its maximum annotation; per-slot vertical dashed event lines; trigger cause unknown",
                  "length_trace": "ordinary DELTA packets joined across omitted ESKF events; no ESKF height spikes; no mean/bin values changed",
                  "independent_review": "exact run_id lookup in local run_index.csv files, stopping at data root; absent review is unknown",
                  "K0_reference": "all metadata.target_modules transmit ESKD with K=0 and no ESKF"}}
    try:
        for name in ("summary.json", "packet_log.csv"):
            status["sources"][name] = {"sha256": _sha256(run_dir / name), "bytes": (run_dir / name).stat().st_size}
        data = load_plot_data(run_dir)
        for key in ("counts", "warnings", "errors", "main_calculated", "bins", "target_modules", "wrapper_bytes", "independent_review"):
            status[key] = data[key]
        status["recording_status"] = {"main": data["main"].get("status"), "full_run": data["full"].get("status")}
        status["recording_review_reasons"] = {"main": data["main"].get("review_reasons", []), "full_run": data["full"].get("review_reasons", [])}
        import matplotlib
        matplotlib.use("Agg", force=True)
        import matplotlib.pyplot as plt
        for name, kind in zip(PLOT_NAMES, ("length", "throughput")):
            try:
                _plot(data, run_dir / name, kind, plt)
                status["outputs"][name] = {"status": "OK", "sha256": _sha256(run_dir / name)}
            except Exception as exc:
                status["outputs"][name] = {"status": "ERROR", "error": f"{type(exc).__name__}: {exc}"}
                status["errors"].append(f"{name}: {type(exc).__name__}: {exc}")
        status["status"] = "ERROR" if status["errors"] else "OK"
    except Exception as exc:
        status["errors"].append(f"{type(exc).__name__}: {exc}")
    finally:
        for name, source in status["sources"].items():
            try:
                source["sha256_after"] = _sha256(run_dir / name)
                source["unchanged"] = source["sha256_after"] == source["sha256"]
                if not source["unchanged"]:
                    status["errors"].append(f"Source changed during plotting: {name}")
                    status["status"] = "ERROR"
            except OSError as exc:
                status["errors"].append(f"Source verification failed: {name}: {exc}")
                status["status"] = "ERROR"
        if run_dir.is_dir():
            temporary = run_dir / "plot_status.json.tmp"
            temporary.write_text(json.dumps(status, indent=2, ensure_ascii=False), encoding="utf-8")
            temporary.replace(run_dir / "plot_status.json")
    return status


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dirs", nargs="+", type=Path)
    args = parser.parse_args(argv)
    failed = False
    for run_dir in args.run_dirs:
        status = render_run(run_dir)
        print(json.dumps({"run": str(run_dir), "status": status["status"], "errors": status["errors"]}, ensure_ascii=False))
        failed |= status["status"] != "OK"
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
