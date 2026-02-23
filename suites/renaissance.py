"""Renaissance benchmark suite adapter."""

import json
import re
import subprocess
import tempfile
from pathlib import Path

from .base import BenchmarkSuite, RunResult
from config import BASE_JVM_ARGS, detect_renaissance_jar

# Full benchmark list from renaissance 0.16.x (--raw-list output).
# Excludes the dummy-* test benchmarks.
KNOWN_BENCHMARKS = [
    # apache-spark
    "als", "chi-square", "dec-tree", "gauss-mix", "log-regression",
    "movie-lens", "naive-bayes", "page-rank",
    # concurrency
    "akka-uct", "fj-kmeans", "reactors",
    # database
    "db-shootout", "neo4j-analytics",
    # functional
    "future-genetic", "mnemonics", "par-mnemonics", "rx-scrabble", "scrabble",
    # scala
    "dotty", "philosophers", "scala-doku", "scala-kmeans", "scala-stm-bench7",
    # web
    "finagle-chirper", "finagle-http",
]

COMPILE_TIME_PATTERN = re.compile(r"ProfileCheckpoint: load\+compile took (\d+) ms")


def _parse_latencies_from_json(json_path: str, benchmark: str) -> list[float]:
    """Parse per-iteration wall-clock times (ms) from Renaissance's --json output."""
    try:
        with open(json_path) as f:
            data = json.load(f)
        results = (
            data.get("benchmarks", {})
                .get(benchmark, {})
                .get("results", [])
        )
        # duration_ns is present in Renaissance >= 0.14; convert to ms.
        times = [r["duration_ns"] / 1_000_000 for r in results if "duration_ns" in r]
        if times:
            return times
        # Older format used duration_ms directly.
        return [r["duration_ms"] for r in results if "duration_ms" in r]
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        return []


def _parse_compile_time(output: str) -> float:
    m = COMPILE_TIME_PATTERN.search(output)
    return float(m.group(1)) if m else -1.0


class RenaissanceSuite(BenchmarkSuite):
    def __init__(self, java_path: str, jar_path: str):
        self.java_path = java_path
        self.jar_path = jar_path

    @classmethod
    def detect_jar(cls) -> str:
        return detect_renaissance_jar()

    def name(self) -> str:
        return "renaissance"

    def available_benchmarks(self) -> list[str]:
        """Return benchmarks supported by the JAR, falling back to the static list."""
        try:
            result = subprocess.run(
                [self.java_path, "-jar", self.jar_path, "--raw-list"],
                capture_output=True, text=True, timeout=60,
            )
            lines = [l.strip() for l in result.stdout.splitlines() if l.strip()]
            # Filter out dummy benchmarks used only for harness testing.
            benchmarks = [b for b in lines if not b.startswith("dummy-")]
            if benchmarks:
                return benchmarks
        except Exception:
            pass
        return list(KNOWN_BENCHMARKS)

    def validate_setup(self) -> None:
        if not Path(self.java_path).exists():
            raise FileNotFoundError(f"Java binary not found: {self.java_path}")
        if not Path(self.jar_path).exists():
            raise FileNotFoundError(f"Renaissance jar not found: {self.jar_path}")
        result = subprocess.run(
            [self.java_path, "-version"],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            raise RuntimeError(f"Java binary failed: {result.stderr}")

    def _run(
        self,
        benchmark: str,
        n_iters: int,
        extra_jvm_args: list[str] | None = None,
    ) -> RunResult:
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tf:
            json_out = tf.name

        cmd = [self.java_path] + list(BASE_JVM_ARGS)
        if extra_jvm_args:
            cmd.extend(extra_jvm_args)
        cmd.extend([
            "-jar", self.jar_path,
            "-r", str(n_iters),
            "--json", json_out,
            benchmark,
        ])

        print(f"  Running: {' '.join(cmd)}")
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=1800,
        )
        output = result.stdout + "\n" + result.stderr

        latencies = _parse_latencies_from_json(json_out, benchmark)
        try:
            Path(json_out).unlink(missing_ok=True)
        except Exception:
            pass

        return RunResult(
            iteration_times=latencies,
            compile_time=_parse_compile_time(output),
            raw_output=output,
            exit_code=result.returncode,
        )

    def run_cold(self, benchmark: str, n_iters: int) -> RunResult:
        return self._run(benchmark, n_iters)

    def run_profiling(self, benchmark: str, n_iters: int, profile_path: str) -> RunResult:
        # Same JVM-level profile checkpoint flags as DaCapo; the modified JDK
        # reads these properties regardless of which benchmark suite is running.
        return self._run(benchmark, n_iters, [
            f"-Ddacapo.profilecheckpoint.file={profile_path}",
        ])

    def run_warm(self, benchmark: str, n_iters: int, profile_path: str) -> RunResult:
        return self._run(benchmark, n_iters, [
            f"-Ddacapo.profilecheckpoint.file={profile_path}",
            "-Ddacapo.profilecheckpoint.loadafter=0",
            "-XX:+EagerCompileAfterLoad",
        ])
