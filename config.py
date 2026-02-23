"""Default configuration and environment auto-detection."""

import glob
import os
import shutil
from pathlib import Path

# Base directory: parent of benchmark-runner/
BASE_DIR = Path(__file__).resolve().parent.parent

# Default paths (auto-detected relative to BASE_DIR)
DEFAULT_JAVA_PATTERNS = [
    "jdk25u/build/macosx-aarch64-server-release/jdk/bin/java",
    "jdk25u/build/linux-x86_64-server-release/jdk/bin/java",
    "jdk25u/build/linux-aarch64-server-release/jdk/bin/java",
]

DEFAULT_JAR_PATTERN = "dacapobench/benchmarks/dacapo-evaluation-git-*.jar"

# Benchmark defaults
DEFAULT_PROFILE_ITERS = 1
DEFAULT_BENCH_ITERS = 10
DEFAULT_TRIALS = 3

# JVM flags always passed
BASE_JVM_ARGS = [
    "--add-exports=java.base/jdk.internal.profilecheckpoint=ALL-UNNAMED",
    "-XX:+UnlockDiagnosticVMOptions",
    "-Xlog:compilation=info",
]


def detect_java() -> str:
    """Auto-detect the java binary from known build paths."""
    for pattern in DEFAULT_JAVA_PATTERNS:
        path = BASE_DIR / pattern
        if path.exists():
            return str(path)
    # Fall back to system java
    java = shutil.which("java")
    if java:
        return java
    raise FileNotFoundError(
        "Could not find java binary. Use --java to specify the path."
    )


def detect_jar() -> str:
    """Auto-detect the DaCapo jar from known paths."""
    matches = sorted(glob.glob(str(BASE_DIR / DEFAULT_JAR_PATTERN)))
    if matches:
        return matches[-1]  # newest
    raise FileNotFoundError(
        "Could not find DaCapo jar. Use --jar to specify the path."
    )
