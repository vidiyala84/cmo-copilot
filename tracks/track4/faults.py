"""H3-3 — failure injection + retrying execution (Track 4).

`--inject-fault api500|timeout` makes the sandbox ad-API call fail. The executor
retries twice; if the fault persists (it does), execution is abandoned and the
pipeline exits `failed_safe` — never half-executed silently.
"""


class FaultError(RuntimeError):
    pass


class Fault:
    """Persistent fault injector. `check(attempt)` raises on every attempt for
    the active mode, forcing the retry loop to exhaust and fail safe."""

    MODES = ("api500", "timeout")

    def __init__(self, mode=None):
        if mode not in (None,) + self.MODES:
            raise ValueError(f"unknown fault mode {mode!r}")
        self.mode = mode
        self.attempts_seen = 0

    @property
    def active(self):
        return self.mode is not None

    def check(self, attempt):
        if not self.active:
            return
        self.attempts_seen += 1
        if self.mode == "api500":
            raise FaultError("ad platform API returned HTTP 500 mid-call")
        if self.mode == "timeout":
            raise FaultError("ad platform API call timed out")


class ExecutionFailed(RuntimeError):
    def __init__(self, cause, attempts):
        self.cause = cause
        self.attempts = attempts
        super().__init__(f"execution failed after {attempts} attempts: {cause}")


def execute_with_retries(apply_fn, args, fault=None, max_retries=2):
    """Call apply_fn(**args), retrying up to max_retries on injected faults.
    Returns (result, attempts_used). Raises ExecutionFailed if all attempts fail."""
    attempts = 0
    last = None
    while attempts <= max_retries:
        try:
            if fault is not None:
                fault.check(attempts)
            result = apply_fn(**args)
            return result, attempts
        except FaultError as e:
            last = e
            attempts += 1
    raise ExecutionFailed(last, attempts)
