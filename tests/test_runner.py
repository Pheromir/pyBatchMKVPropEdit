import sys
import threading
import time

from bmpe.core.command import FilePlan
from bmpe.core.runner import BatchRunner, RunStatus


class FakeRunner(BatchRunner):
    """Runs a Python snippet instead of mkvpropedit."""

    def __init__(self, code: str, plans, **kw):
        super().__init__("unused", plans, **kw)
        self.code = code

    def _command(self, option_file: str) -> list[str]:
        return [sys.executable, "-c", self.code]


def plans(anime_file, n=1):
    out = []
    for i in range(n):
        f = anime_file.model_copy(deep=True)
        f.path = f"C:\\x\\file{i}.mkv"
        out.append(FilePlan(file=f, args=["--edit", "info", "--delete", "title"]))
    return out


def test_exit_codes_and_output(anime_file):
    runner = FakeRunner("print('hello'); raise SystemExit(1)", plans(anime_file))
    result = runner.run()[0]
    assert (result.status, result.exit_code, result.output) == (RunStatus.WARNING, 1, "hello")
    assert runner.running() == {}


def test_stop_file_ends_a_hanging_process(anime_file):
    """A process that never finishes can be ended for one file; the following files still run."""
    todo = plans(anime_file, 2)
    hanging, normal = todo[0].file.path, todo[1].file.path
    runner = FakeRunner("import time; print('started', flush=True); time.sleep(120)", todo, workers=1)
    started = threading.Event()
    runner.on_output = lambda path, line: started.set()

    # the second file gets a command that ends on its own
    original = runner._command
    runner._command = lambda opt: original(opt) if not started.is_set() else [sys.executable, "-c", "print('ok')"]

    results = []
    thread = threading.Thread(target=lambda: results.extend(runner.run()))
    thread.start()
    assert started.wait(20)
    assert list(runner.running()) == [hanging]
    assert runner.running()[hanging] >= 0
    assert not runner.stop_file(normal)  # not running yet
    begin = time.monotonic()
    assert runner.stop_file(hanging)
    thread.join(20)
    assert not thread.is_alive() and time.monotonic() - begin < 15

    assert [r.status for r in results] == [RunStatus.STOPPED, RunStatus.OK]
    assert "Stopped on request" in results[0].output
    assert runner.running() == {}
