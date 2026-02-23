"""DaCapo benchmark suite adapter using the modified jar with profilecheckpoint hooks."""

import re
import subprocess
from pathlib import Path

from .base import BenchmarkSuite, RunResult
from config import BASE_JVM_ARGS

KNOWN_BENCHMARKS = [
    "avrora", "batik", "biojava", "eclipse", "fop",
    "graphchi", "h2", "jme", "kafka",
]

WARMUP_PATTERN = re.compile(r"completed warmup \d+ in (\d+) msec")
FINAL_PATTERN = re.compile(r"PASSED in (\d+) msec")
COMPILE_TIME_PATTERN = re.compile(r"ProfileCheckpoint: load\+compile took (\d+) ms")


def _parse_latencies(output: str) -> list[float]:
    latencies = []
    for line in output.split("\n"):
        m = WARMUP_PATTERN.search(line)
        if m:
            latencies.append(float(m.group(1)))
            continue
        m = FINAL_PATTERN.search(line)
        if m:
            latencies.append(float(m.group(1)))
    return latencies


def _parse_compile_time(output: str) -> float:
    m = COMPILE_TIME_PATTERN.search(output)
    return float(m.group(1)) if m else -1.0


class DaCapoSuite(BenchmarkSuite):
    def __init__(self, java_path: str, jar_path: str):
        self.java_path = java_path
        self.jar_path = jar_path

    def name(self) -> str:
        return "dacapo"

    def available_benchmarks(self) -> list[str]:
        return list(KNOWN_BENCHMARKS)

    def validate_setup(self) -> None:
        if not Path(self.java_path).exists():
            raise FileNotFoundError(f"Java binary not found: {self.java_path}")
        if not Path(self.jar_path).exists():
            raise FileNotFoundError(f"DaCapo jar not found: {self.jar_path}")
        # Quick version check
        result = subprocess.run(
            [self.java_path, "-version"],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            raise RuntimeError(f"Java binary failed: {result.stderr}")

    def _run(self, benchmark: str, n_iters: int, extra_jvm_args: list[str] = None) -> RunResult:
        cmd = [self.java_path] + list(BASE_JVM_ARGS)
        if extra_jvm_args:
            cmd.extend(extra_jvm_args)
        cmd.extend(["-jar", self.jar_path, "-n", str(n_iters), "-s", "small", benchmark])

        print(f"  Running: {' '.join(cmd)}")
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=1800,
        )
        output = result.stdout + "\n" + result.stderr
        return RunResult(
            iteration_times=_parse_latencies(output),
            compile_time=_parse_compile_time(output),
            raw_output=output,
            exit_code=result.returncode,
        )

    def run_cold(self, benchmark: str, n_iters: int) -> RunResult:
        return self._run(benchmark, n_iters)

    def run_profiling(self, benchmark: str, n_iters: int, profile_path: str) -> RunResult:
        return self._run(benchmark, n_iters, [
            f"-Ddacapo.profilecheckpoint.file={profile_path}",
        ])

    def run_warm(self, benchmark: str, n_iters: int, profile_path: str) -> RunResult:
        return self._run(benchmark, n_iters, [
            f"-Ddacapo.profilecheckpoint.file={profile_path}",
            "-Ddacapo.profilecheckpoint.loadafter=0",
            "-XX:+EagerCompileAfterLoad",
        ])
