"""DaCapo benchmark suite adapter using the modified jar with profilecheckpoint hooks."""

import re
import subprocess
from pathlib import Path

from .base import BenchmarkSuite, RunResult
from config import BASE_JVM_ARGS, detect_jar as _detect_dacapo_jar

KNOWN_BENCHMARKS = [
    "avrora", "batik", "biojava", "eclipse", "fop",
    "graphchi", "h2", "jme", "kafka", "luindex",
    "lusearch", "pmd", "sunflow", "tomcat", "xalan",
]

WARMUP_PATTERN = re.compile(r"completed warmup \d+ in (\d+) msec")
FINAL_PATTERN = re.compile(r"PASSED in (\d+) msec")
PROCESSED_PATTERN = re.compile(r"processed \d+ requests in (\d+) msec")
COMPILE_TIME_PATTERN = re.compile(r"ProfileCheckpoint: load\+compile took (\d+) ms")


def _parse_latencies(output: str) -> list[float]:
    """Parse iteration times from DaCapo output.

    Some benchmarks (kafka, h2, jme) report both a "completed warmup" time
    (which includes server setup/teardown overhead) and a "processed N requests
    in X msec" time (actual workload). When the processed-requests line is
    present, use it instead since it measures the real workload performance.
    """
    warmup_times = []
    processed_times = []
    for line in output.split("\n"):
        m = WARMUP_PATTERN.search(line)
        if m:
            warmup_times.append(float(m.group(1)))
            continue
        m = FINAL_PATTERN.search(line)
        if m:
            warmup_times.append(float(m.group(1)))
            continue
        m = PROCESSED_PATTERN.search(line)
        if m:
            processed_times.append(float(m.group(1)))
    # Prefer processed-request times when they match 1:1 with warmup iterations
    if processed_times and len(processed_times) == len(warmup_times):
        return processed_times
    return warmup_times


def _parse_compile_time(output: str) -> float:
    m = COMPILE_TIME_PATTERN.search(output)
    return float(m.group(1)) if m else -1.0


class DaCapoSuite(BenchmarkSuite):
    def __init__(self, java_path: str, jar_path: str, size: str = "small"):
        self.java_path = java_path
        self.jar_path = jar_path
        self.size = size

    @classmethod
    def detect_jar(cls) -> str:
        return _detect_dacapo_jar()

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
        cmd.extend(["-jar", self.jar_path, "-n", str(n_iters), "-s", self.size, benchmark])

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
            "-XX:+EagerCompileAfterLoad",
            "-XX:+EagerInitAfterLoad",
            "-XX:EagerInitAfterLoadAllowlist=*",
            # Deny list: skip classes with native deps that cause class-init
            # poisoning (sun/font/*, sun/management/*, com/sun/management/*)
            "-XX:EagerInitAfterLoadDenylist="
            "sun/font/*,sun/management/*,com/sun/management/*",
        ])
