"""Cooperative RSS ceiling for this process and its descendants."""
import threading
import psutil

_active_guard = None


def check_memory():
    if _active_guard is not None:
        _active_guard.check()


class MemoryLimitExceeded(RuntimeError):
    pass


class MemoryGuard:
    def __init__(self, limit_gb=40, interval=0.1):
        if not 0 < limit_gb <= 40:
            raise ValueError("Memory limit must be in (0, 40] GB")
        self.limit = int(limit_gb * 1_000_000_000)
        self.interval = interval
        self.peak_rss = 0
        self.exceeded = False
        self.stop_event = threading.Event()
        self.process = psutil.Process()

    def _sample(self):
        processes = [self.process] + self.process.children(recursive=True)
        total = 0
        for p in processes:
            try:
                total += p.memory_info().rss
            except psutil.NoSuchProcess:
                pass
        self.peak_rss = max(self.peak_rss, total)
        self.exceeded |= total > self.limit

    def _watch(self):
        while not self.stop_event.wait(self.interval):
            self._sample()

    def check(self):
        self._sample()
        if self.exceeded:
            raise MemoryLimitExceeded(f"RSS exceeded {self.limit / 1e9:g} GB; peak {self.peak_rss / 1e9:.3f} GB")

    def __enter__(self):
        global _active_guard
        self.check()
        self.previous_guard = _active_guard
        _active_guard = self
        self.thread = threading.Thread(target=self._watch, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *args):
        global _active_guard
        self.stop_event.set()
        self.thread.join(timeout=1)
        _active_guard = self.previous_guard
        if args[0] is None:
            self.check()
