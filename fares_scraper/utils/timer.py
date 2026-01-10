import time

class Timer:
    def __init__(self, start: bool = False):
        self._start_time = None
        self._end_time = None
        if start:
            self.start()

    def start(self):
        self._start_time = time.perf_counter()
        self._end_time = None

    def stop(self):
        self._end_time = time.perf_counter()

    @property
    def seconds_elapsed(self) -> float:
        if self._start_time is None:
            return 0.0
        if self._end_time is None:
            return time.perf_counter() - self._start_time
        return self._end_time - self._start_time

