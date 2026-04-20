"""DaCapo benchmark suite adapter using Portable MDO export/import.

Instead of the .mdox profile checkpoint system, this uses:
  - Profiling run: -XX:ExportMDOFile=<path> to export profiling data at shutdown
  - Warm run: -XX:ImportMDOFile=<path> to import profiling data at startup

Warm runs use a DaCapo callback (PortableMDODrainCallback) installed via
`-c PortableMDODrainCallback`. The architecture:

  Iteration 1 (priming): the benchmark runs as normal. As classes link
  — including custom-loader-loaded benchmark code — HotSpot's
  on_class_linked hook installs imported MDOs and records each
  installed method on a side install-list. No compilation happens yet.
  This iteration is a true cold start enriched with profile data.

  After iter 1's stop(): the callback calls VM.waitForEagerCompilation(),
  which drains the install-list. Every recorded method is queued into
  CompileBroker at the recorded tier and we block until both compile
  queues are empty.

  Iterations 2..N: run with all profile-driven compilations already in
  place. These are the measured "warm" iterations.

The runner therefore slices iteration 1 off the warm timings — it is the
priming iteration, equivalent to a cold-start request in serverless.

Because DaCapo is normally launched with `-jar` (which forbids `-cp`),
the warm path switches to a `-cp` + `Harness` invocation and explicitly
replays the dacapo jar's manifest Add-Exports/Add-Opens directives.
"""

import re
import subprocess
from pathlib import Path

from .base import BenchmarkSuite, RunResult
from config import detect_jar as _detect_dacapo_jar

# Callback class injected after the first warm iteration to drain the
# Portable MDO eager-compilation queue.
DRAIN_CALLBACK_CLASS = "PortableMDODrainCallback"
RUNNER_DIR = Path(__file__).resolve().parent.parent

# Manifest Add-Exports from dacapo-evaluation-git-89a9cf79.jar.
# Required because launching with `-cp` (instead of `-jar`) skips the
# manifest, so we have to replay these on the command line.
DACAPO_ADD_EXPORTS = [
    "java.base/jdk.internal.ref",
    "java.base/jdk.internal.misc",
    "java.base/sun.nio.ch",
    "java.management.rmi/com.sun.jmx.remote.internal.rmi",
    "java.rmi/sun.rmi.registry",
    "java.rmi/sun.rmi.server",
    "java.sql/java.sql",
    "java.base/jdk.internal.math",
    "java.base/jdk.internal.module",
    "java.base/jdk.internal.util.jar",
    "jdk.management/com.sun.management.internal",
]

DACAPO_ADD_OPENS = [
    "java.base/java.lang",
    "java.base/java.lang.module",
    "java.base/java.net",
    "java.base/jdk.internal.loader",
    "java.base/jdk.internal.ref",
    "java.base/jdk.internal.reflect",
    "java.base/java.io",
    "java.base/sun.nio.ch",
    "java.base/java.util",
    "java.base/java.util.concurrent",
    "java.base/java.util.concurrent.atomic",
    "java.base/java.nio",
]

KNOWN_BENCHMARKS = [
    "avrora", "batik", "biojava", "eclipse", "fop",
    "graphchi", "h2", "jme", "kafka", "luindex",
    "lusearch", "pmd", "sunflow", "tomcat", "xalan",
]

WARMUP_PATTERN = re.compile(r"completed warmup \d+ in (\d+) msec")
FINAL_PATTERN = re.compile(r"PASSED in (\d+) msec")
PROCESSED_PATTERN = re.compile(r"processed \d+ requests in (\d+) msec")
MDO_EXPORT_PATTERN = re.compile(r"PortableMDO: exported (\d+) mature MDO profiles")
MDO_IMPORT_PATTERN = re.compile(r"PortableMDO import: loaded (\d+) MDO profiles")
MDO_RECONSTRUCT_PATTERN = re.compile(r"PortableMDO import: reconstructed MDO")
DRAIN_TIME_PATTERN = re.compile(r"PortableMDODrainCallback: drain complete in (\d+) ms")
DRAIN_QUEUED_PATTERN = re.compile(
    r"PortableMDO: drain queued (\d+) compilations \(skipped (\d+) dead, (\d+) no-mdo\)"
)

# JVM unified logging fragments that can interleave with DaCapo output,
# e.g. "[1.596s][info][aot,training] PortableMDO import: ..."
_JVM_LOG_FRAGMENT = re.compile(r"\[\d+\.\d+s\]\[(?:info|warning|debug)\]\[[^\]]*\] [^\n]*")

# Base JVM args for Portable MDO runs
BASE_JVM_ARGS = [
    "-XX:+UnlockDiagnosticVMOptions",
    "-Xlog:compilation=info",
    "-Xlog:aot+training=info",
]


def _strip_jvm_log_fragments(output: str) -> str:
    """Remove JVM unified logging fragments that interleave with benchmark output.

    When -Xlog output is written from background threads it can land mid-line
    in the DaCapo output, splitting a single "completed warmup N in X msec"
    message across multiple lines.  Stripping these fragments and joining the
    remaining text lets the normal regex parser work correctly.
    """
    cleaned = _JVM_LOG_FRAGMENT.sub("", output)
    # After removing JVM log fragments, a single DaCapo line like
    #   "===== ... eclipse completed warmup 1 in 274 msec ====="
    # may be split across several lines.  Join everything into a single
    # string so regex patterns can match across the original line breaks.
    parts = [part.strip() for part in cleaned.split("\n")]
    return " ".join(part for part in parts if part)


def _parse_latencies(output: str) -> list[float]:
    # Strip JVM log fragments so interleaved lines don't break parsing
    cleaned = _strip_jvm_log_fragments(output)
    warmup_times = WARMUP_PATTERN.findall(cleaned)
    final_times = FINAL_PATTERN.findall(cleaned)
    processed_times = PROCESSED_PATTERN.findall(cleaned)

    all_warmup = [float(t) for t in warmup_times] + [float(t) for t in final_times]
    all_processed = [float(t) for t in processed_times]

    if all_processed and len(all_processed) == len(all_warmup):
        return all_processed
    return all_warmup


def _parse_drain_time(output: str) -> float:
    """Parse the drain compilation time from PortableMDODrainCallback output."""
    m = DRAIN_TIME_PATTERN.search(output)
    return float(m.group(1)) if m else -1.0


def _parse_drain_info(output: str) -> dict:
    """Parse drain queue stats (compilations queued, skipped)."""
    m = DRAIN_QUEUED_PATTERN.search(output)
    if m:
        return {
            "queued": int(m.group(1)),
            "skipped_dead": int(m.group(2)),
            "skipped_no_mdo": int(m.group(3)),
        }
    return {"queued": 0, "skipped_dead": 0, "skipped_no_mdo": 0}


def _parse_mdo_stats(output: str) -> dict:
    """Parse Portable MDO log lines for diagnostics."""
    stats = {"exported": 0, "imported": 0, "reconstructed": 0}
    m = MDO_EXPORT_PATTERN.search(output)
    if m:
        stats["exported"] = int(m.group(1))
    m = MDO_IMPORT_PATTERN.search(output)
    if m:
        stats["imported"] = int(m.group(1))
    stats["reconstructed"] = len(MDO_RECONSTRUCT_PATTERN.findall(output))
    return stats


class DaCapoMDOSuite(BenchmarkSuite):
    """DaCapo suite using Portable MDO export/import for warm-up evaluation."""

    def __init__(self, java_path: str, jar_path: str, size: str = "small"):
        self.java_path = java_path
        self.jar_path = jar_path
        self.size = size

    @classmethod
    def detect_jar(cls) -> str:
        return _detect_dacapo_jar()

    def name(self) -> str:
        return "dacapo-mdo"

    def available_benchmarks(self) -> list[str]:
        return list(KNOWN_BENCHMARKS)

    def validate_setup(self) -> None:
        if not Path(self.java_path).exists():
            raise FileNotFoundError(f"Java binary not found: {self.java_path}")
        if not Path(self.jar_path).exists():
            raise FileNotFoundError(f"DaCapo jar not found: {self.jar_path}")
        result = subprocess.run(
            [self.java_path, "-version"],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            raise RuntimeError(f"Java binary failed: {result.stderr}")

    def _ensure_callback_compiled(self) -> Path:
        """Compile PortableMDODrainCallback against the dacapo jar if needed.

        Returns the directory containing the compiled .class file, suitable
        for prepending to the warm-run classpath.
        """
        src = RUNNER_DIR / "PortableMDODrainCallback.java"
        out_dir = RUNNER_DIR / "callback_classes"
        out_class = out_dir / "PortableMDODrainCallback.class"
        if out_class.exists() and out_class.stat().st_mtime >= src.stat().st_mtime:
            return out_dir
        out_dir.mkdir(parents=True, exist_ok=True)
        javac = str(Path(self.java_path).parent / "javac")
        cmd = [
            javac,
            "--add-exports", "java.base/jdk.internal.misc=ALL-UNNAMED",
            "-cp", self.jar_path,
            "-d", str(out_dir),
            str(src),
        ]
        print(f"  Compiling callback: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            raise RuntimeError(
                f"Failed to compile {src}:\n{result.stdout}\n{result.stderr}"
            )
        return out_dir

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
            compile_time=-1.0,
            raw_output=output,
            exit_code=result.returncode,
        )

    def _run_warm_with_callback(
        self, benchmark: str, n_iters: int, extra_jvm_args: list[str]
    ) -> RunResult:
        """Warm run that uses -cp + Harness to enable the drain callback.

        DaCapo cannot use `-jar` here because we need to add our compiled
        callback class to the system classpath. Switching to `-cp` skips
        the dacapo jar's manifest, so we replay its Add-Exports/Add-Opens
        directives explicitly.
        """
        callback_dir = self._ensure_callback_compiled()
        cp = f"{self.jar_path}:{callback_dir}"

        cmd: list[str] = [self.java_path] + list(BASE_JVM_ARGS)
        for export in DACAPO_ADD_EXPORTS:
            cmd.extend(["--add-exports", f"{export}=ALL-UNNAMED"])
        for opens in DACAPO_ADD_OPENS:
            cmd.extend(["--add-opens", f"{opens}=ALL-UNNAMED"])
        cmd.extend(extra_jvm_args)
        cmd.extend([
            "-cp", cp,
            "Harness",
            "-c", DRAIN_CALLBACK_CLASS,
            "-n", str(n_iters),
            "-s", self.size,
            benchmark,
        ])

        print(f"  Running: {' '.join(cmd)}")
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=1800,
        )
        output = result.stdout + "\n" + result.stderr
        return RunResult(
            iteration_times=_parse_latencies(output),
            compile_time=-1.0,
            raw_output=output,
            exit_code=result.returncode,
        )

    def run_cold(self, benchmark: str, n_iters: int) -> RunResult:
        return self._run(benchmark, n_iters)

    def run_profiling(self, benchmark: str, n_iters: int, profile_path: str) -> RunResult:
        # Change extension from .mdox to .mdo for Portable MDO
        mdo_path = str(Path(profile_path).with_suffix(".mdo"))
        result = self._run(benchmark, n_iters, [
            f"-XX:ExportMDOFile={mdo_path}",
            "-XX:MDOExportDeoptDecayPercent=50",
        ])
        # Report MDO export stats
        stats = _parse_mdo_stats(result.raw_output)
        print(f"  -> MDO export: {stats['exported']} profiles")
        return result

    def run_warm(self, benchmark: str, n_iters: int, profile_path: str) -> RunResult:
        mdo_path = str(Path(profile_path).with_suffix(".mdo"))
        if not Path(mdo_path).exists():
            print(f"  WARNING: MDO file not created at {mdo_path}")
            return RunResult(raw_output="MDO file missing", exit_code=-1)

        # Iter 1 is the priming iteration: it triggers class linking, which
        # installs imported MDOs onto the install-list. The callback drains
        # the list (compiling everything in it) after iter 1's stop() and
        # before iter 2's start(). Iter 1 is reported as-is — it represents
        # the cold-start request in the serverless analogy.
        result = self._run_warm_with_callback(benchmark, n_iters, [
            f"-XX:ImportMDOFile={mdo_path}",
            "-XX:+EagerCompilePortableMDO",
        ])
        stats = _parse_mdo_stats(result.raw_output)
        drain_time = _parse_drain_time(result.raw_output)
        drain_info = _parse_drain_info(result.raw_output)
        result.compile_time = drain_time
        print(f"  -> MDO import: {stats['imported']} loaded, {stats['reconstructed']} reconstructed")
        if drain_time >= 0:
            print(f"  -> Drain: {drain_info['queued']} compilations in {drain_time:.0f}ms"
                  f" (skipped {drain_info['skipped_dead']} dead, {drain_info['skipped_no_mdo']} no-mdo)")
        return result
