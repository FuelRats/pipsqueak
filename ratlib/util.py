import datetime
import time
import contextlib


__all__ = ['TimedResult', 'timed']


class TimedResult:
    __slots__ = ('delta', 'seconds', 'started', 'stopped')
    _default = object()

    def __init__(self, started=_default, stopped=None):
        self.delta = self.seconds = self.started = self.stopped = None
        if started is TimedResult._default:
            self.start()
        else:
            self.started = started
        self.stopped = stopped

    def start(self):
        self.stopped = self.delta = self.seconds = None
        self.started = time.time()
        return self.started

    def stop(self):
        self.stopped = time.time()
        if self.started is not None:
            self.seconds = self.stopped - self.started
            self.delta = datetime.timedelta(seconds=self.seconds)
        return self.seconds


@contextlib.contextmanager
def timed():
    result = TimedResult()
    yield result
    result.stop()
