"""Wire-format negative checks and independent exported-result identities."""
from collections import Counter
import json
from pathlib import Path
import struct
import unittest
import zlib
import raw_audit as audit


def add_crc(data):
    return data+struct.pack("<I", zlib.crc32(data))


def envelope(payload):
    n = 40+len(payload)
    header = b"MUL1"+bytes([2,4,1,0])+struct.pack("<HHII",n,0,77,12345)
    descriptors = struct.pack("<BBH",0,0,len(payload))+payload
    descriptors += b"".join(struct.pack("<BBH",slot,0x85,0) for slot in (1,2,3))
    return add_crc(header+descriptors)


def delta(mask, values, flags=0x33):
    return add_crc(struct.pack("<4sBBHII",b"ESKD",4,flags,84+len(values),8,7)+mask+values)


class WireChecks(unittest.TestCase):
    def test_mask_and_acquisition_status_bits(self):
        mask = bytes([3])+bytes(31)+bytes([1])+bytes(31)
        decoded = audit.decode(envelope(delta(mask,struct.pack("<HHH",11,12,13))))
        self.assertEqual(decoded["errors"],[])
        self.assertEqual((decoded["modules"][0]["K"],decoded["modules"][0]["K1"],decoded["modules"][0]["K2"]),(3,2,1))
        self.assertEqual(decoded["modules"][0]["flags"],0x33)

    def test_inner_corruption_remains_visible_with_valid_outer_crc(self):
        payload = bytearray(delta(bytes(64),b"")); payload[17] ^= 1
        decoded = audit.decode(envelope(bytes(payload)))
        self.assertTrue(decoded["outer_crc_valid"])
        self.assertIn("M0:inner_crc",decoded["errors"])
        self.assertFalse(decoded["modules"][0]["valid"])

    def test_outer_corruption_is_not_repaired(self):
        data = bytearray(envelope(delta(bytes(64),b""))); data[16] ^= 1
        decoded = audit.decode(data)
        self.assertFalse(decoded["outer_crc_valid"])
        self.assertIn("outer_crc",decoded["errors"])

    def test_valid_crc_does_not_hide_invalid_mask_length(self):
        decoded = audit.decode(envelope(delta(bytes([1])+bytes(63),b"")))
        self.assertIn("M0:delta_mask_length",decoded["errors"])
        self.assertFalse(decoded["modules"][0]["valid"])

    def test_full_sync_is_valid_delta_mode(self):
        payload = add_crc(struct.pack("<4sBBHII",b"ESKF",4,0x33,1044,8,0xFFFFFFFF)+bytes(1024))
        decoded = audit.decode(envelope(payload))
        self.assertEqual(decoded["errors"],[])
        self.assertEqual(decoded["modules"][0]["mode"],"DELTA")

    def test_full_base_requires_the_sentinel_even_with_valid_crcs(self):
        payload = add_crc(struct.pack("<4sBBHII",b"ESKF",4,0x33,1044,8,7)+bytes(1024))
        decoded = audit.decode(envelope(payload))
        self.assertTrue(decoded["outer_crc_valid"])
        self.assertIn("M0:full_base_sentinel",decoded["errors"])
        self.assertFalse(decoded["modules"][0]["valid"])

    def test_exported_window_and_byte_identities(self):
        output = json.loads((Path(__file__).parent/"raw_audit.json").read_text(encoding="utf-8"))
        self.assertEqual(output["snapshot_run_ids"],list(audit.SNAPSHOT))
        for run in output["runs"]:
            full,initial,main = [run["scopes"][n]["counts"] for n in ("full_run","initial","main")]
            for key in set(full)|set(initial)|set(main):
                self.assertEqual(full.get(key,0),initial.get(key,0)+main.get(key,0),(run["run_id"],key))
            for scope in run["scopes"].values():
                c = scope["counts"]; frames = c["valid_module_frames"]
                self.assertEqual(c["ESKF"]+c["ESKD"],frames)
                self.assertAlmostEqual(scope["q_ESKF"],c["ESKF"]/frames)
                # Exact ordinary-ESKD bytes use the observed histogram, not mean-packet inversion.
                delta_k_sum = sum(int(k)*v for m in scope["modules"].values() for k,v in m["K_histogram"].items())
                inner_bytes = 1044*c["ESKF"]+84*c["ESKD"]+2*delta_k_sum
                self.assertEqual(inner_bytes,c["valid_module_payload_bytes"])
                self.assertEqual(40*c["valid_outer_packets"]+inner_bytes+c.get("diagnostic_payload_bytes",0),c["valid_outer_packet_bytes"])
            for boundary in run["start_boundaries"]:
                if boundary["evidence"] != "unavailable_prefix": self.assertTrue(boundary["verified"])


if __name__ == "__main__": unittest.main(verbosity=2)
