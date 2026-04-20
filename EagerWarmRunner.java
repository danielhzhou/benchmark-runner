import java.lang.reflect.Method;
import java.lang.management.ManagementFactory;
import java.lang.management.CompilationMXBean;

/**
 * Wrapper that runs DaCapo in two phases within the same JVM:
 * 1. Priming phase: runs N warmup iterations (loads classes, triggers MDO import + eager compilation)
 * 2. Drain phase: waits for all background compilations to finish
 * 3. Measurement phase: runs the measured iterations (should be flat/hot from iteration 1)
 *
 * Usage: java EagerWarmRunner <warmup_iters> <measure_iters> <dacapo_jar> <benchmark> [dacapo_args...]
 */
public class EagerWarmRunner {
    public static void main(String[] args) throws Exception {
        if (args.length < 4) {
            System.err.println("Usage: EagerWarmRunner <warmup_iters> <measure_iters> <dacapo_jar> <benchmark> [extra_args...]");
            System.exit(1);
        }

        int warmupIters = Integer.parseInt(args[0]);
        int measureIters = Integer.parseInt(args[1]);
        String jarPath = args[2];
        String benchmark = args[3];

        // Collect extra DaCapo args
        String[] extraArgs = new String[args.length - 4];
        System.arraycopy(args, 4, extraArgs, 0, extraArgs.length);

        // Load DaCapo's main class from the jar
        java.net.URL jarUrl = new java.io.File(jarPath).toURI().toURL();
        java.net.URLClassLoader loader = new java.net.URLClassLoader(
            new java.net.URL[]{jarUrl}, EagerWarmRunner.class.getClassLoader());
        Class<?> dacapoClass = loader.loadClass("org.dacapo.harness.TestHarness");
        Method mainMethod = dacapoClass.getMethod("main", String[].class);

        // Phase 1: Priming — run warmup iterations to load all classes
        System.out.println("=== PRIMING PHASE: " + warmupIters + " warmup iterations ===");
        String[] primingArgs = buildArgs(benchmark, warmupIters, extraArgs);
        mainMethod.invoke(null, (Object) primingArgs);

        // Phase 2: Drain — wait for background compilations to finish
        System.out.println("=== DRAIN PHASE: waiting for compilations ===");
        waitForCompilations();
        System.out.println("=== DRAIN COMPLETE ===");

        // Phase 3: Measurement — run the measured iterations
        System.out.println("=== MEASUREMENT PHASE: " + measureIters + " measured iterations ===");
        String[] measureArgs = buildArgs(benchmark, measureIters, extraArgs);
        mainMethod.invoke(null, (Object) measureArgs);
    }

    private static String[] buildArgs(String benchmark, int iters, String[] extra) {
        // Build: -n <iters> -s small <benchmark> [extra...]
        String[] base = new String[]{"-n", String.valueOf(iters), "-s", "small", benchmark};
        String[] result = new String[base.length + extra.length];
        System.arraycopy(base, 0, result, 0, base.length);
        System.arraycopy(extra, 0, result, base.length, extra.length);
        return result;
    }

    private static void waitForCompilations() throws InterruptedException {
        CompilationMXBean compilationBean = ManagementFactory.getCompilationMXBean();
        if (compilationBean == null || !compilationBean.isCompilationTimeMonitoringSupported()) {
            // Fallback: just sleep
            Thread.sleep(3000);
            return;
        }

        // Poll until compilation time stops increasing
        long lastCompTime = compilationBean.getTotalCompilationTime();
        int stableCount = 0;
        while (stableCount < 10) {
            Thread.sleep(100);
            long currentCompTime = compilationBean.getTotalCompilationTime();
            if (currentCompTime == lastCompTime) {
                stableCount++;
            } else {
                stableCount = 0;
                lastCompTime = currentCompTime;
            }
        }
    }
}
