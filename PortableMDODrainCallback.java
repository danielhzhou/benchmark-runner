/*
 * DaCapo callback that drains the HotSpot Portable MDO eager-compilation
 * pipeline after the first iteration completes.
 *
 * Usage:
 *   java -XX:+UnlockDiagnosticVMOptions \
 *        -XX:ImportMDOFile=foo.mdo -XX:+EagerCompilePortableMDO \
 *        --add-exports java.base/jdk.internal.misc=ALL-UNNAMED \
 *        -cp dacapo.jar:./classes Harness \
 *        -c PortableMDODrainCallback -n N -s small <bench>
 *
 * Architecture:
 *   1. Iteration 1 (priming): the benchmark runs as normal. As classes
 *      link — including custom-loader-loaded benchmark code — HotSpot's
 *      on_class_linked hook installs imported MDOs and records each
 *      installed method on a side install-list. No compilation happens
 *      yet, but the running iteration benefits from pre-populated MDO
 *      data biasing C1's inlining/branch decisions.
 *   2. After iteration 1's stop(), we call VM.waitForEagerCompilation().
 *      That drains the install-list: every recorded (Method*, level)
 *      pair is queued into CompileBroker at the right tier and we block
 *      until both compile queues are empty.
 *   3. Iterations 2..N run with all the profile-driven compilations
 *      already in place. These are the measured iterations.
 *
 * Why the drain happens here (instead of at JVM shutdown or in a static
 * initializer): the install-list is only useful AFTER the application
 * has linked the classes we care about. For DaCapo that means after at
 * least one full iteration has executed. For production serverless, the
 * equivalent is "after the first request completes".
 */

import jdk.internal.misc.VM;
import org.dacapo.harness.Callback;
import org.dacapo.harness.CommandLineArgs;

public class PortableMDODrainCallback extends Callback {

    private int completedIterations = 0;
    private boolean drained = false;

    public PortableMDODrainCallback(CommandLineArgs args) {
        super(args);
    }

    @Override
    public void stop(long duration) {
        super.stop(duration);
        completedIterations++;
        if (drained) return;
        if (completedIterations < 1) return;

        drained = true;
        drain();
    }

    private void drain() {
        System.out.println("===== PortableMDODrainCallback: draining install-list "
                + "after iteration " + completedIterations + " =====");
        System.out.flush();

        long t0 = System.nanoTime();
        try {
            VM.waitForEagerCompilation();
        } catch (Throwable t) {
            System.err.println("PortableMDODrainCallback: drain failed: " + t);
            t.printStackTrace();
            return;
        }
        long drainMs = (System.nanoTime() - t0) / 1_000_000L;

        System.out.println("===== PortableMDODrainCallback: drain complete in "
                + drainMs + " ms =====");
        System.out.flush();
    }
}
