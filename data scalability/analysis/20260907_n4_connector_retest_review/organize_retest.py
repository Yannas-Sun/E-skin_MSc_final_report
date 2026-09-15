"""Classify the three post-reinstallation N=4 records and refresh derived indexes.

The six acquisition files and their hashes are preserved. Original summary labels
remain unchanged; the operator-confirmed condition and connector intervention are
stored only in derived indexes and review documentation.
"""
from __future__ import annotations

import csv
import hashlib
import json
import shutil
import statistics
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
DATA = ROOT / "data scalability" / "data"
RUN_IDS = (
    "20260907_115145_448767",
    "20260907_115225_490019",
    "20260907_115305_535263",
)
ORIGINAL = {"mul1_raw.bin", "packet_log.csv", "module_log.csv", "events.jsonl", "summary.json", "experiment_log.md"}
GROUP_REL = Path("DELTA/Dynamic_load/N=4/200Hz/M0_M1_M2_M3/Full_coverage_all_modules")
BATCH_REL = GROUP_REL / "Batch_after_connector_reinstallation"
SOURCE_REVIEW = HERE.name


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_csv(path: Path):
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def write_csv(path: Path, rows, preferred=()):
    rows = list(rows)
    columns = list(preferred)
    for row in rows:
        for key in row:
            if key not in columns:
                columns.append(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def sha(path: Path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def sample(values):
    values = [float(v) for v in values]
    return statistics.mean(values), statistics.stdev(values) if len(values) > 1 else "", len(values)


def summarize(rows, scope):
    first = rows[0]
    result = {key: first.get(key, "") for key in (
        "mode", "condition", "actual_load_protocol", "loading_relationship_between_modules",
        "modules", "N", "target_hz", "batch_id", "load_layers")}
    result.update(
        temporal_repeat_n=len(rows), recorded_repeat_n=len(rows), eligible_repeat_n=len(rows),
        review_required_n=0, batch_n=1, recorded_batch_n=1, statistics_scope=scope,
        statistics_basis="sample mean and SD across fixed main windows; all three independently PASS",
        primary_matrix_selected_n=0, dynamic_analysis_selected_n=3,
        statistic_run_ids=";".join(r["run_id"] for r in rows), review_required_run_ids="",
        repeat_interpretation="consecutive temporal windows after connector reinstallation; not independent assemblies",
        main_packets_total=sum(int(r["main_packets"]) for r in rows),
        main_window_seconds_total=sum(float(r["main_duration_s"]) for r in rows),
    )
    for short, long in (
        ("rate_Hz", "main_rate_Hz"), ("packet_Mbit_s", "main_packet_Mbit_s"),
        ("raw_arrival_Mbit_s", "main_raw_arrival_Mbit_s"), ("Lmean_B", "main_Lmean_B"),
        ("K_ESKD", "main_K_ESKD_mean"), ("q_ESKF", "main_q_ESKF"),
        ("q_ESKF_pct", "main_q_ESKF_pct"),
        ("equal_rate_FULL_saving_pct", "main_equal_rate_FULL_saving_pct"),
    ):
        mean, sd, n = sample(r[long] for r in rows)
        result[f"{short}_mean"] = mean
        result[f"{short}_sample_sd"] = sd
        result[f"{short}_known_n"] = n
    return result


def main():
    data_resolved = DATA.resolve()
    assert DATA.is_dir()
    assert not (HERE / "organization_verification.json").exists(), "This organization has already completed"
    audit = read_json(HERE / "raw_audit.json")
    audited = {row["run_id"]: row for row in audit["runs"]}
    assert set(audited) == set(RUN_IDS)

    # Freeze current catalogues and every source hash before moving anything.
    backup_root = HERE / "before_catalog"
    catalog_dirs = [DATA, DATA / "DELTA", DATA / "DELTA/Dynamic_load", DATA / GROUP_REL]
    for folder in catalog_dirs:
        if not folder.exists():
            continue
        for path in folder.iterdir():
            if path.is_file() and path.suffix.lower() in {".csv", ".md"}:
                destination = backup_root / path.relative_to(DATA)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, destination)

    plans = []
    for repeat, rid in enumerate(RUN_IDS, 1):
        source = DATA / rid
        destination = DATA / BATCH_REL / f"Repeat_{repeat}"
        assert source.resolve().parent == data_resolved
        assert source.is_dir() and not source.is_symlink()
        assert not destination.exists()
        destination_parent = destination.parent.resolve(strict=False)
        assert destination_parent == (DATA / BATCH_REL).resolve(strict=False)
        summary = read_json(source / "summary.json")
        assert summary["run_id"] == rid and summary["completed_requested_duration"]
        assert summary["metadata"]["target_modules"] == [0, 1, 2, 3]
        assert summary["metadata"]["target_mode"] == "DELTA"
        files = []
        for path in sorted(source.iterdir()):
            assert path.is_file() and not path.is_symlink()
            files.append({"file_name": path.name, "bytes": path.stat().st_size, "sha256": sha(path)})
        assert ORIGINAL.issubset({item["file_name"] for item in files})
        plans.append({"run_id": rid, "repeat": repeat, "source": str(source.resolve()),
                      "destination": str(destination.resolve(strict=False)), "files": files})
    write_json(HERE / "organization_plan.json", {"created_at": datetime.now().astimezone().isoformat(),
        "data_root": str(data_resolved), "batch_relative_path": BATCH_REL.as_posix(), "runs": plans,
        "policy": "No deletion or overwrite; preserve all acquisition bytes and source labels."})

    # The destinations and their containment were verified above.
    (DATA / BATCH_REL).mkdir(parents=True, exist_ok=False)
    for item in plans:
        Path(item["source"]).rename(Path(item["destination"]))
    for item in plans:
        destination = Path(item["destination"])
        assert destination.resolve().is_relative_to(data_resolved)
        for entry in item["files"]:
            assert sha(destination / entry["file_name"]) == entry["sha256"]

    old_rows = read_csv(backup_root / "run_index.csv")
    fields = list(old_rows[0])
    assert len(old_rows) == 111 and not set(RUN_IDS).intersection(r["run_id"] for r in old_rows)
    batch_id = None
    new_rows = []
    original_map, derived_map = [], []
    for item in plans:
        rid = item["run_id"]
        destination = Path(item["destination"])
        summary = read_json(destination / "summary.json")
        meta = summary["metadata"]
        main_scope = summary["scopes"]["main"]
        full_scope = summary["scopes"]["full_run"]
        independent = audited[rid]["scopes"]["main"]
        counts = independent["counts"]
        batch_id = batch_id or meta["batch_id"]
        assert meta["batch_id"] == batch_id
        assert not audited[rid]["cross_check_errors"]
        assert not audited[rid]["anomalies"]
        assert not audited[rid]["outer_sequence_discontinuities"]
        assert not audited[rid]["inner_sequence_discontinuities"]
        assert counts.get("missing_valid_expected_updates", 0) == 0
        L = independent["Lmean_valid_packet_B"]
        row = dict(
            run_id=rid, started_at=summary["started_at"], mode="DELTA", condition="large_area", N=4,
            target_hz=meta["target_hz"], modules="M0_M1_M2_M3", block=meta["block"], batch_id=batch_id,
            repeat=item["repeat"], old_relative_path=rid,
            new_relative_path=destination.relative_to(DATA).as_posix(), duration_s=summary["duration_seconds"],
            main_duration_s=main_scope["actual_duration_seconds"], main_packets=counts["valid_outer_packets"],
            main_status=main_scope["status"], full_status=full_scope["status"],
            full_review_reasons=";".join(full_scope["review_reasons"]),
            main_rate_Hz=independent["valid_outer_packet_rate_Hz"], main_Lmean_B=L,
            main_packet_Mbit_s=independent["packet_completion_Mbit_per_s"],
            main_raw_arrival_Mbit_s=main_scope["raw_arrival_Mbit_per_s"],
            main_K_ESKD_mean=independent["K_ESKD"]["mean"], main_q_ESKF=independent["q_ESKF"],
            main_q_ESKF_pct=100 * independent["q_ESKF"], main_ESKF_count=counts["ESKF"],
            main_ESKD_count=counts["ESKD"],
            source_local_firmware=meta["local_provenance"]["firmware_variant"],
            deployment_confirmed=str(meta["deployment_confirmed"]), main_eligible="True", main_review_reasons="",
            main_outer_crc_errors=0, main_outer_missing_sequence_numbers=0,
            main_missing_valid_expected_updates=0, main_interior_unassigned_raw_bytes=0,
            source_review=SOURCE_REVIEW,
            timing_note="PC completion rate is not physical scan rate; see independent audit.", replacement_batch_id="",
            primary_matrix_selected="False", selection_reason="post-reinstallation N=4 dynamic performance batch",
            pc_max_completion_gap_ms=max(x["pc_completion_gap_ms"] for x in audited[rid]["main_largest_pc_gaps"]),
            host_max_enqueue_gap_ms=max(x["bridge_host_gap_ms"] for x in audited[rid]["main_largest_bridge_gaps"]),
            host_packet_span_rate_Hz="", independent_raw_audit="PASS", load_layers="unspecified",
            load_description="四个模块同时全覆盖动态加载；connector重新安装后复测",
            independent_review_reasons="", main_inner_sequence_events=0, recorded_condition=meta["condition"],
            actual_load_protocol="full_coverage_all_modules_after_connector_reinstallation",
            loading_relationship_between_modules="simultaneous_coverage_and_loading_of_all_four_modules",
            independent_main_status="PASS", dataset_role="dynamic_performance_post_connector_reinstallation",
            main_equal_rate_FULL_saving_pct=100 * (1 - L / 4216), dynamic_batch_eligible="True",
            dynamic_analysis_selected="True", dynamic_selection_reason="complete_three_window_post_reinstallation_batch_passed",
        )
        new_rows.append(row)
        by_name = {entry["file_name"]: entry for entry in item["files"]}
        for name, entry in by_name.items():
            mapping = dict(run_id=rid, file_name=name, old_path=str(DATA / rid / name),
                new_path=str(destination / name), old_relative_path=f"{rid}/{name}",
                new_relative_path=(destination / name).relative_to(DATA).as_posix(), bytes=entry["bytes"],
                sha256=entry["sha256"], source_review=SOURCE_REVIEW)
            if name in ORIGINAL:
                original_map.append(mapping)
            else:
                derived_map.append({**mapping, "file_kind": "existing_derived"})

    for row in old_rows:
        if row["new_relative_path"].startswith(GROUP_REL.as_posix() + "/Repeat_"):
            row["replacement_batch_id"] = batch_id
            row["dataset_role"] = "dynamic_diagnostic_pre_connector_reinstallation"
            row["dynamic_analysis_selected"] = "False"
            row["dynamic_batch_eligible"] = "False"
            row["dynamic_selection_reason"] = "historical connector-contact diagnostic; replaced by post-reinstallation batch"
    all_rows = old_rows + new_rows
    selected = [r for r in all_rows if str(r.get("dynamic_analysis_selected", "")).lower() == "true"]
    assert len(all_rows) == 114 and len(selected) == 15

    group = summarize(new_rows, "complete_three_window_dynamic_batch")
    diagnostic = summarize(new_rows, "all_recorded_post_reinstallation_dynamic")
    batch = summarize(new_rows, "per_batch_eligible_with_recorded_and_CHECK_counts")

    def add_rows(path, additions, key="batch_id"):
        existing = read_csv(path)
        assert not any(r.get(key) == batch_id for r in existing)
        write_csv(path, existing + list(additions), list(existing[0]) if existing else ())

    # Root and relevant mirrored views.
    for folder, rows_here in (
        (DATA, all_rows),
        (DATA / "DELTA", [r for r in all_rows if r["mode"] == "DELTA"]),
        (DATA / "DELTA/Dynamic_load", [r for r in all_rows if r.get("condition") != "zero_load" and r["mode"] == "DELTA"]),
    ):
        old_index = read_csv(folder / "run_index.csv")
        write_csv(folder / "run_index.csv", rows_here, list(old_index[0]))
        old_paths = read_csv(folder / "path_map.csv")
        write_csv(folder / "path_map.csv", old_paths + original_map, list(old_paths[0]))
        old_derived = read_csv(folder / "derived_path_map.csv")
        write_csv(folder / "derived_path_map.csv", old_derived + derived_map, list(old_derived[0]) if old_derived else ())
        write_csv(folder / "dynamic_analysis_selected.csv", selected, fields)
        add_rows(folder / "dynamic_group_statistics.csv", [group])
        add_rows(folder / "dynamic_diagnostic_statistics.csv", [diagnostic])
        add_rows(folder / "all_runs_diagnostic_statistics.csv", [diagnostic])
        add_rows(folder / "all_pass_group_statistics.csv", [group])
        add_rows(folder / "batch_statistics.csv", [batch])

    primary = read_csv(DATA / "primary_matrix.csv")
    write_csv(DATA / "analysis_selected.csv", primary + selected, fields)
    assert len(primary) == 90 and len(primary) + len(selected) == 105

    parent = DATA / GROUP_REL
    parent_old = [r for r in old_rows if r["new_relative_path"].startswith(GROUP_REL.as_posix() + "/")]
    write_csv(parent / "run_index.csv", parent_old + new_rows, fields)
    parent_pm = read_csv(backup_root / GROUP_REL / "path_map.csv")
    parent_dm = read_csv(backup_root / GROUP_REL / "derived_path_map.csv")
    write_csv(parent / "path_map.csv", parent_pm + original_map, list(parent_pm[0]))
    write_csv(parent / "derived_path_map.csv", parent_dm + derived_map, list(parent_dm[0]) if parent_dm else ())
    write_csv(parent / "dynamic_analysis_selected.csv", new_rows, fields)
    write_csv(parent / "dynamic_group_statistics.csv", [group])
    old_parent_diag = read_csv(backup_root / GROUP_REL / "all_runs_diagnostic_statistics.csv")
    write_csv(parent / "all_runs_diagnostic_statistics.csv", old_parent_diag + [diagnostic])
    write_csv(parent / "group_statistics.csv", [group])

    batch_folder = DATA / BATCH_REL
    write_csv(batch_folder / "run_index.csv", new_rows, fields)
    write_csv(batch_folder / "path_map.csv", original_map)
    write_csv(batch_folder / "derived_path_map.csv", derived_map)
    write_csv(batch_folder / "dynamic_analysis_selected.csv", new_rows, fields)
    write_csv(batch_folder / "group_statistics.csv", [group])
    write_csv(batch_folder / "all_runs_diagnostic_statistics.csv", [diagnostic])

    correction = {
        "recorded_condition": "zero_load",
        "actual_condition": "large_area",
        "actual_load_protocol": "full_coverage_all_modules_after_connector_reinstallation",
        "operator_confirmation": "All four modules were covered and loaded simultaneously. The earlier fault was poor connector contact; reinstallation resolved it.",
        "evidence_limit": "The intervention and non-recurrence are documented observations; the batch is not a randomized connector fault experiment.",
        "source_metadata_unchanged": True,
    }
    write_json(HERE / "condition_correction.json", correction)
    write_json(batch_folder / "condition_correction.json", correction)
    mean_L, sd_L, _ = sample(r["main_Lmean_B"] for r in new_rows)
    mean_rate, sd_rate, _ = sample(r["main_rate_Hz"] for r in new_rows)
    mean_usb, sd_usb, _ = sample(r["main_packet_Mbit_s"] for r in new_rows)
    mean_k, sd_k, _ = sample(r["main_K_ESKD_mean"] for r in new_rows)
    mean_q, sd_q, _ = sample(r["main_q_ESKF_pct"] for r in new_rows)
    mean_save, sd_save, _ = sample(r["main_equal_rate_FULL_saving_pct"] for r in new_rows)
    totals = audit["totals"]["main"]
    statistics_doc = {
        "n_temporal_windows": 3, "PASS": 3, "CHECK": 0,
        "rate_Hz_mean": mean_rate, "rate_Hz_sample_sd": sd_rate,
        "Lmean_B_mean": mean_L, "Lmean_B_sample_sd": sd_L,
        "USB_Mbit_s_mean": mean_usb, "USB_Mbit_s_sample_sd": sd_usb,
        "K_ESKD_mean": mean_k, "K_ESKD_sample_sd": sd_k,
        "q_ESKF_pct_mean": mean_q, "q_ESKF_pct_sample_sd": sd_q,
        "equal_rate_FULL_saving_pct_mean": mean_save, "equal_rate_FULL_saving_pct_sample_sd": sd_save,
        "main_valid_outer_packets": totals["valid_outer_packets"],
        "main_expected_updates": totals["expected_module_update_opportunities"],
        "main_received_valid_expected_updates": totals["valid_expected_module_frames"],
        "main_ESKF": totals["ESKF"], "main_ESKD": totals["ESKD"],
        "outer_sequence_events": 0, "inner_sequence_events": 0, "CRC_or_format_errors": 0,
        "post_anchor_unapplied_frames": totals.get("unapplied_after_anchor", 0),
    }
    write_json(HERE / "statistics.json", statistics_doc)
    readme = f"""# N=4 simultaneous full-coverage retest after connector reinstallation

The operator confirmed simultaneous full-coverage loading of M0--M3. The earlier
fault was diagnosed as poor connector contact and the connector was reinstalled
before this batch. Original `zero_load` labels inside acquisition files are
preserved; `condition_correction.json` records the derived correction.

All three fixed 10--40 s main windows independently pass the raw audit. Across
the batch, {totals['valid_outer_packets']:,} valid outer packets contain
{totals['valid_expected_module_frames']:,}/{totals['expected_module_update_opportunities']:,}
expected module updates, with no CRC/layout, outer-sequence, inner-sequence,
base-chain or post-anchor reconstruction finding.

| Quantity | mean ± sample SD | n |
|---|---:|---:|
| packet rate / Hz | {mean_rate:.6f} ± {sd_rate:.6f} | 3 |
| mean MUL1 length / B | {mean_L:.6f} ± {sd_L:.6f} | 3 |
| valid USB byte rate / Mbit/s | {mean_usb:.6f} ± {sd_usb:.6f} | 3 |
| ordinary ESKD K per module frame | {mean_k:.6f} ± {sd_k:.6f} | 3 |
| ESKF fraction / % | {mean_q:.6f} ± {sd_q:.6f} | 3 |
| same-rate saving versus 4216 B FULL / % | {mean_save:.6f} ± {sd_save:.6f} | 3 |

The three windows are consecutive temporal repeats in one post-reinstallation
setup. The observed recovery supports the practical connector diagnosis but is
not a randomized hardware-causality experiment.
"""
    (batch_folder / "README.md").write_text(readme, encoding="utf-8")
    (HERE / "REVIEW_CN.md").write_text(
        "# N=4 connector 重装后复测\n\n" + readme.replace("# N=4 simultaneous full-coverage retest after connector reinstallation\n\n", ""),
        encoding="utf-8")

    # Final integrity checks.
    root_paths = read_csv(DATA / "path_map.csv")
    assert len(root_paths) == 684
    for mapping in original_map:
        assert sha(Path(mapping["new_path"])) == mapping["sha256"]
    assert not [p.name for p in DATA.iterdir() if p.is_dir() and p.name[:8].isdigit()]
    validation = {
        "status": "PASS", "all_runs": 114, "dynamic_runs": 21,
        "primary_zero_load_runs": 90, "dynamic_selected_runs": 15,
        "analysis_selected_runs": 105, "original_path_entries": 684,
        "new_batch_PASS": 3, "new_batch_CHECK": 0,
        "old_problem_batch_preserved": True,
        "moved_runs": list(RUN_IDS), "batch_id": batch_id,
        "source_files_hash_verified": len(original_map),
    }
    write_json(HERE / "organization_verification.json", validation)
    print(json.dumps(validation, indent=2))


if __name__ == "__main__":
    main()
