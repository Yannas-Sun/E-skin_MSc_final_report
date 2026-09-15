"""Read one ACC-only benchmark snapshot from STM32 SRAM through pyOCD."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import struct
import subprocess
import time

from pyocd.core.helpers import ConnectHelper


SIGNATURE = 0x42434341
ACC_COUNT = 9
PROBE_UID = "LU_2022_8888"
TARGET = "stm32g474cetx"


def symbol_address(elf: Path, nm: Path) -> int:
    result = subprocess.run(
        [str(nm), "-g", "--defined-only", str(elf)],
        check=True,
        capture_output=True,
        text=True,
    )
    for line in result.stdout.splitlines():
        fields = line.split()
        if len(fields) >= 3 and fields[-1] == "g_acc_benchmark_snapshot":
            return int(fields[0], 16)
    raise RuntimeError("g_acc_benchmark_snapshot was not found in the ELF")


def decode(words: list[int]) -> dict[str, object]:
    if len(words) < 97:
        raise RuntimeError(f"short snapshot: {len(words)} words")
    if words[0] != SIGNATURE:
        raise RuntimeError(f"bad signature 0x{words[0]:08X}")
    count = words[2]
    if count > len(words) or count < 97:
        raise RuntimeError(f"invalid word count {count}")

    offset = 16
    groups: list[list[int]] = []
    for _ in range(9):
        groups.append(words[offset : offset + ACC_COUNT])
        offset += ACC_COUNT

    elapsed_seconds = words[9] / words[7]
    scans_hz = words[10] / elapsed_seconds
    online_mask = words[13]
    sensors = []
    for index in range(ACC_COUNT):
        fresh = groups[3][index]
        duplicate = groups[4][index]
        sensors.append(
            {
                "acc": index + 1,
                "online": bool(online_mask & (1 << index)),
                "who": f"0x{groups[0][index]:02X}",
                "ctrl1": f"0x{groups[1][index]:02X}",
                "ctrl4": f"0x{groups[2][index]:02X}",
                "fresh_samples": fresh,
                "fresh_hz": round(fresh / elapsed_seconds, 3),
                "duplicate_reads": duplicate,
                "status": f"0x{groups[5][index]:02X}",
                "xyz": [
                    struct.unpack("<i", struct.pack("<I", groups[6][index]))[0],
                    struct.unpack("<i", struct.pack("<I", groups[7][index]))[0],
                    struct.unpack("<i", struct.pack("<I", groups[8][index]))[0],
                ],
            }
        )
    return {
        "generation": words[3],
        "mode": "hr1344" if words[4] == 1 else "lp5376",
        "requested_ctrl1": f"0x{words[5]:02X}",
        "requested_ctrl4": f"0x{words[6]:02X}",
        "system_core_clock_hz": words[7],
        "spi_clock_hz": words[8],
        "window_seconds": round(elapsed_seconds, 9),
        "complete_nine_slot_scans": words[10],
        "complete_nine_slot_scan_hz": round(scans_hz, 3),
        "average_slot_transaction_hz": round(words[11] / elapsed_seconds, 3),
        "spi_errors": words[12],
        "online_mask": f"0x{online_mask:03X}",
        "init_error_mask": f"0x{words[14]:03X}",
        "online_count": words[15],
        "sensors": sensors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--elf", type=Path, required=True)
    parser.add_argument("--nm", type=Path, required=True)
    parser.add_argument("--probe", default=PROBE_UID)
    parser.add_argument("--target", default=TARGET)
    parser.add_argument("--frequency", type=int, default=10_000)
    parser.add_argument("--wait-seconds", type=float, default=4.0)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    address = symbol_address(args.elf.resolve(), args.nm.resolve())
    options = {
        "target_override": args.target,
        "frequency": args.frequency,
        "connect_mode": "attach",
        "resume_on_disconnect": True,
    }
    deadline = time.monotonic() + args.wait_seconds
    snapshot: dict[str, object] | None = None
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with ConnectHelper.session_with_chosen_probe(
                unique_id=args.probe, return_first=True, options=options
            ) as session:
                target = session.target
                target.halt()
                try:
                    words_again = target.read_memory_block32(address, 97)
                finally:
                    target.resume()
                if (
                    words_again[3] != 0
                    and (words_again[3] & 1) == 0
                ):
                    snapshot = decode(words_again)
                    break
        except Exception as error:  # retry across target reset/startup
            last_error = error
        time.sleep(0.05)
    if snapshot is None:
        raise RuntimeError(f"no stable snapshot before timeout: {last_error}")

    text = json.dumps(snapshot, indent=2, ensure_ascii=False)
    print(text)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
        print(f"output_file={args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
