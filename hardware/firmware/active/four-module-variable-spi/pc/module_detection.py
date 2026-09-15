"""Recent, successfully decoded slot activity; never a physical board UID."""
from collections import deque


class ModuleDetector:
    def __init__(self, window_seconds=1.5, min_span_seconds=1.0, stale_seconds=0.5):
        self.window_seconds = float(window_seconds)
        self.min_span_seconds = float(min_span_seconds)
        self.stale_seconds = float(stale_seconds)
        self.samples = deque()

    def observe(self, packet, now):
        modes = {}
        for module, status in enumerate(packet.statuses):
            algorithm = packet.algorithms[module]
            error = packet.errors[module] if module < len(packet.errors) else None
            if status == 0 and packet.updated_mask & (1 << module) and algorithm and not error:
                if algorithm == 'FULL':
                    modes[module] = 'FULL'
                elif algorithm.startswith('DELTA'):
                    modes[module] = 'DELTA'
        self.samples.append((float(now), modes))
        return self.snapshot(now)

    def snapshot(self, now):
        now = float(now)
        while self.samples and self.samples[0][0] < now - self.window_seconds:
            self.samples.popleft()
        modes = {}
        last_success = {}
        for timestamp, sample in self.samples:
            modes.update(sample)
            last_success.update({m: timestamp for m in sample})
        last_packet = self.samples[-1][0] if self.samples else None
        span = last_packet - self.samples[0][0] if self.samples else 0.0
        fresh = last_packet is not None and 0 <= now - last_packet <= self.stale_seconds
        mode_set = set(modes.values())
        mode = next(iter(mode_set)) if len(mode_set) == 1 else None
        ready = bool(fresh and span >= self.min_span_seconds and len(self.samples) >= 3
                     and modes and mode is not None)
        return {
            'source': 'recent_successful_protocol_slots_not_board_uids',
            'ready': ready, 'modules': sorted(modes), 'mode': mode,
            'slot_modes': {str(m): value for m, value in modes.items()},
            'slot_last_success_monotonic': {str(m): t for m, t in last_success.items()},
            'last_packet_monotonic': last_packet, 'observed_at_monotonic': now,
            'window_span_seconds': span, 'window_seconds': self.window_seconds,
            'stale_seconds': self.stale_seconds, 'packet_count': len(self.samples),
            'limitation': 'No response cannot establish whether a board is physically attached. '
                          'The recent union can retain a briefly missing slot; recording freezes the set.',
        }


def require_ready(snapshot, now):
    """Check freshness again when Record is pressed or reaches the worker."""
    if not snapshot or not snapshot.get('ready'):
        raise ValueError('Waiting for automatic module detection: allow 2 seconds of valid data')
    timestamp = snapshot.get('last_packet_monotonic')
    if timestamp is None or not 0 <= float(now) - timestamp <= snapshot.get('stale_seconds', 0.5):
        raise ValueError('Module detection is stale: wait for fresh serial data')
    return snapshot
