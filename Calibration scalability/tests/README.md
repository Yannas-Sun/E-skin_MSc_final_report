# Tests

These software checks cover the current shared-endpoint workflow:

- test_endpoint_calibration.py — shared endpoints, dynamic U, provenance, and incomplete captures.
- test_calibration_comparison.py — source identity, ranges, plateaus, and comparison plotting.
- test_gui_shared_endpoints.py — acquisition interlocks, queue handling, module switching, and endpoint saving.

Additional evaluation tests live beside the production modules in script/Main/Evaluation/ and cover current capture, grouping, error, dispersion, Shared LUT, and refresh behavior. They use synthetic fixtures and do not replace hardware loading validation.
