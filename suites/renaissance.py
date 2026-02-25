"""Renaissance benchmark suite adapter."""

import glob
import json
import re
import subprocess
import tempfile
from pathlib import Path

from .base import BenchmarkSuite, RunResult
from config import BASE_JVM_ARGS, detect_renaissance_jar

# Plugin class shipped with the custom Renaissance build
PLUGIN_CLASS = "org.renaissance.plugins.profilecheckpoint.ProfileCheckpointPlugin"
PLUGIN_JAR_GLOB = "plugins/profile-checkpoint/target/plugin-profile-checkpoint-assembly-*.jar"

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
        # Format v6+: timings live under data[benchmark]["results"]
        # Older format had them under benchmarks[benchmark]["results"]
        container = data.get("data") or data.get("benchmarks") or {}
        results = (
            container.get(benchmark, {})
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


def _find_plugin_jar(renaissance_jar: str) -> str | None:
    """Locate the profile-checkpoint plugin jar relative to the Renaissance repo root."""
    # The Renaissance jar lives at <repo>/target/renaissance-gpl-*.jar
    repo_root = Path(renaissance_jar).resolve().parent.parent
    matches = sorted(glob.glob(str(repo_root / PLUGIN_JAR_GLOB)))
    return matches[-1] if matches else None


class RenaissanceSuite(BenchmarkSuite):
    def __init__(self, java_path: str, jar_path: str):
        self.java_path = java_path
        self.jar_path = jar_path
        self.plugin_jar = _find_plugin_jar(jar_path)

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
        if not self.plugin_jar:
            print("WARNING: profile-checkpoint plugin jar not found. "
                  "Profile/warm runs will not produce checkpoint files.")
        else:
            print(f"Plugin: {self.plugin_jar}")
        result = subprocess.run(
            [self.java_path, "-version"],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            raise RuntimeError(f"Java binary failed: {result.stderr}")

    def _plugin_harness_args(self) -> list[str]:
        """Return Renaissance harness args to load the profile-checkpoint plugin."""
        if not self.plugin_jar:
            return []
        return ["--plugin", f"{self.plugin_jar}!{PLUGIN_CLASS}"]

    def _run(
        self,
        benchmark: str,
        n_iters: int,
        extra_jvm_args: list[str] | None = None,
        extra_harness_args: list[str] | None = None,
    ) -> RunResult:
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tf:
            json_out = tf.name

        cmd = [self.java_path] + list(BASE_JVM_ARGS)
        if extra_jvm_args:
            cmd.extend(extra_jvm_args)
        cmd.extend([
            "-jar", self.jar_path,
        ])
        if extra_harness_args:
            cmd.extend(extra_harness_args)
        cmd.extend([
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
        return self._run(
            benchmark, n_iters,
            extra_jvm_args=[
                f"-Drenaissance.profilecheckpoint.file={profile_path}",
            ],
            extra_harness_args=self._plugin_harness_args(),
        )

    def run_warm(self, benchmark: str, n_iters: int, profile_path: str) -> RunResult:
        return self._run(
            benchmark, n_iters,
            extra_jvm_args=[
                f"-Drenaissance.profilecheckpoint.file={profile_path}",
                "-Drenaissance.profilecheckpoint.loadafter=1",
                "-XX:+EagerCompileAfterLoad",
            ],
            extra_harness_args=self._plugin_harness_args(),
        )
