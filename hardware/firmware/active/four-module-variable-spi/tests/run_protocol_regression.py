"""Compile and execute the real C/C++ firmware with native MSVC, without hardware."""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import zlib

sys.dont_write_bytecode = True

TESTS = Path(__file__).resolve().parent
CANDIDATE = TESTS.parent
BASELINE = CANDIDATE.parent / "four-module-full-scan"


def native_environment():
    if shutil.which("cl"):
        return os.environ.copy()
    vswhere = Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)")) / "Microsoft Visual Studio/Installer/vswhere.exe"
    install = subprocess.check_output([str(vswhere), "-latest", "-products", "*", "-requires", "Microsoft.VisualStudio.Component.VC.Tools.x86.x64", "-property", "installationPath"], text=True).strip()
    if not install:
        raise RuntimeError("MSVC C/C++ tools not found; run from an x64 Developer Command Prompt")
    setup = Path(install) / "Common7/Tools/VsDevCmd.bat"
    # Fixed setup invocation; no user data or file operations enter this shell command.
    output = subprocess.check_output(f'"{setup}" -no_logo -arch=x64 >nul && set', shell=True).decode("utf-8", errors="replace")
    env = os.environ.copy()
    for line in output.splitlines():
        if "=" in line and not line.startswith("="):
            key, value = line.split("=", 1)
            env[key.upper()] = value
    if "VCTOOLSINSTALLDIR" in env:
        compiler_bin = Path(env["VCTOOLSINSTALLDIR"]) / "bin/Hostx64/x64"
        env["PATH"] = str(compiler_bin) + os.pathsep + env.get("PATH", "")
    return env


def run_program(directory, env, label, source, includes, cpp=False):
    unit = directory / (label + (".cpp" if cpp else ".c"))
    unit.write_text(source, encoding="utf-8")
    binary = directory / (label + ".exe")
    compiler = shutil.which("cl.exe", path=env.get("PATH"))
    if not compiler:
        raise RuntimeError("MSVC setup did not provide cl.exe in PATH")
    command = [compiler, "/nologo", "/W3", "/Od", "/Zi", "/EHsc" if cpp else "/TC", "/std:c++17" if cpp else "/std:c11"]
    command += [f"/I{path}" for path in includes]
    command += [str(unit), f"/Fe:{binary}", f"/Fo:{directory / (label + '.obj')}", f"/Fd:{directory / (label + '.pdb')}"]
    result = subprocess.run(command, cwd=directory, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
    if result.returncode:
        raise RuntimeError(result.stdout + result.stderr)
    result = subprocess.run([str(binary)], cwd=directory, capture_output=True, timeout=30)
    if result.returncode:
        raise RuntimeError(f"{label} exited {result.returncode}: " + result.stderr.decode(errors="replace"))
    print(result.stderr.decode().strip())
    return result.stdout


def include(path):
    return f'#include "{path.as_posix()}"\n'


def validate_encoder(blob):
    assert len(blob) % 1046 == 0
    lengths = []
    for offset in range(0, len(blob), 1046):
        length = struct.unpack_from("<H", blob, offset)[0]
        frame = blob[offset + 2: offset + 2 + length]
        assert frame[:4] in (b"ESKF", b"ESKD") and frame[4] == 4
        assert struct.unpack_from("<H", frame, 6)[0] == length
        assert zlib.crc32(frame[:-4]) == struct.unpack_from("<I", frame, length - 4)[0]
        if frame[:4] == b"ESKD":
            assert length == 84 + 2 * sum(byte.bit_count() for byte in frame[16:80])
        lengths.append(length)
    # The exact capacity boundary must preserve all 480 values, then fall back at 481.
    assert blob[8 * 1046 + 2:8 * 1046 + 6] == b"ESKD"
    assert blob[9 * 1046 + 2:9 * 1046 + 6] == b"ESKF"
    return {"frames": len(lengths), "logical_lengths": sorted(set(lengths))}


def validate_packets(blob):
    offset = 0
    packets = 0
    while offset < len(blob):
        size = struct.unpack_from("<H", blob, offset)[0]
        packet = blob[offset + 2: offset + 2 + size]
        assert packet[:4] == b"MUL1" and packet[4:6] == bytes([2, 4])
        assert struct.unpack_from("<H", packet, 8)[0] == size
        assert zlib.crc32(packet[:-4]) == struct.unpack_from("<I", packet, size - 4)[0]
        cursor = 20
        for module in range(4):
            assert packet[cursor] == module
            length = struct.unpack_from("<H", packet, cursor + 2)[0]
            cursor += 4 + length
        assert cursor == size - 4
        packets += 1
        offset += size + 2
    assert packets == 2
    return {"packets": packets, "four_slot_order_and_crc": True}


def validate_pc_encoder(blob):
    # Exercise the actual PC application against bytes emitted by actual STM32 C.
    # Use a headless renderer; no serial device or GUI is opened.
    os.environ.setdefault("MPLBACKEND", "Agg")
    modules = []
    for name, root in (("baseline_pc", BASELINE), ("candidate_pc", CANDIDATE)):
        spec = importlib.util.spec_from_file_location(name, root / "pc/four-module-fsr-monitor.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        modules.append(module)
    states = [module.ProtocolState() for module in modules]
    flags_seen = set()
    for offset in range(0, len(blob), 1046):
        length = struct.unpack_from("<H", blob, offset)[0]
        frame = blob[offset + 2:offset + 2 + length]
        flags_seen.add(frame[5])
        assert states[0].apply(frame) == states[1].apply(frame)
        assert (states[0].fsr1 == states[1].fsr1).all()
        assert (states[0].fsr2 == states[1].fsr2).all()
        assert states[0].last_sequence == states[1].last_sequence
    assert flags_seen == {0x13, 0x33}
    print("PC: parsed all 212 actual STM32 frames; old/new reconstructed matrices equal")
    return {"stm32_generated_frames": len(blob) // 1046,
            "flags": sorted(flags_seen), "reconstructed_matrices_equal": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, help="Optional JSON test report")
    args = parser.parse_args()
    env = native_environment()
    results = {}
    with tempfile.TemporaryDirectory(prefix="eskin-native-regression-") as temporary:
        work = Path(temporary)
        for suite in ("encoder", "teensy"):
            outputs = []
            for name, root in (("baseline", BASELINE), ("candidate", CANDIDATE)):
                source = "#define BASELINE 1\n" if name == "baseline" else ""
                if suite == "encoder":
                    core = root / "stm32/combined-system/Core"
                    source += include(core / "Src/data_scalability_protocol.c")
                    source += include(TESTS / "encoder_harness.c")
                    includes = [core / "Inc"]
                else:
                    source += '#include "Arduino.h"\n#include "SPI.h"\n'
                    if name == "baseline":
                        source += 'void fillCommand(uint8_t*, bool, bool);\n'
                    source += include(root / "teensy/four_module/four_module.ino")
                    source += include(TESTS / "teensy_harness.cpp")
                    includes = [TESTS / "mocks"]
                outputs.append(run_program(work, env, f"{suite}_{name}", source, includes, suite == "teensy"))
            assert outputs[0] == outputs[1], f"{suite}: baseline/candidate bytes differ"
            results[suite] = (validate_encoder if suite == "encoder" else validate_packets)(outputs[1])
            results[suite]["baseline_byte_equality"] = True
            results[suite]["sha256"] = hashlib.sha256(outputs[1]).hexdigest()
            print(f"{suite}: baseline and candidate byte-for-byte equal")
            if suite == "encoder":
                results["pc_end_to_end"] = validate_pc_encoder(outputs[1])
        core = CANDIDATE / "stm32/combined-system/Core"
        source = include(core / "Src/data_scalability_protocol.c")
        source += include(core / "Src/combined_acquisition.c")
        source += include(TESTS / "dma_harness.c")
        run_program(work, env, "dma_candidate", source, [TESTS / "mocks", core / "Inc"])
        results["dma"] = {"pipeline_rounds": 5, "completion_failure_scenarios": 6,
                          "buffer_ownership_and_encoded_lengths": True,
                          "partial_nss_abort_and_cs_low_pause": True}
    if args.report:
        args.report.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
