"""Abstract base class for benchmark suites."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class RunResult:
    iteration_times: list[float] = field(default_factory=list)  # per-iteration ms
    compile_time: float = -1.0  # ms, -1 if N/A
    raw_output: str = ""  # full stdout+stderr
    exit_code: int = 0


class BenchmarkSuite(ABC):
    @classmethod
    def detect_jar(cls) -> str:
        """Auto-detect the suite jar. Override in subclasses."""
        raise FileNotFoundError(
            f"No jar auto-detection for {cls.__name__}. Use --jar to specify the path."
        )

    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def available_benchmarks(self) -> list[str]: ...

    @abstractmethod
    def validate_setup(self) -> None:
        """Check that jar exists, java works, etc. Raises on failure."""
        ...

    @abstractmethod
    def run_cold(self, benchmark: str, n_iters: int) -> RunResult:
        """Run without profile — baseline measurement."""
        ...

    @abstractmethod
    def run_profiling(
        self, benchmark: str, n_iters: int, profile_path: str
    ) -> RunResult:
        """Run to create a .mdox profile file."""
        ...

    @abstractmethod
    def run_warm(self, benchmark: str, n_iters: int, profile_path: str) -> RunResult:
        """Run loading a profile + eager compile."""
        ...
