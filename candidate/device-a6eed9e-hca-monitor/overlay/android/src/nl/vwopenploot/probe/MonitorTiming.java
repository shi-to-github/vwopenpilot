package nl.vwopenploot.probe;

/** Displays the installed r2 software timer; never commands vehicle control. */
public final class MonitorTiming {
  public static final double SOFTWARE_DEADLINE = 240.0;
  public static boolean fresh(double now, double sample) {
    return finite(now) && finite(sample) && sample > 0 &&
        sample <= now && now - sample <= 1.0;
  }
  public static int warning(String version, double elapsed, boolean latActive, boolean takeover) {
    if (!"hca-r2-entry".equals(version) || !finite(elapsed) || elapsed < 0) return -1;
    if (takeover) return 2;
    if (!latActive) return 0;
    return elapsed >= SOFTWARE_DEADLINE ? 2 : elapsed >= SOFTWARE_DEADLINE - 5 ? 1 : 0;
  }
  private static boolean finite(double value) { return !Double.isNaN(value) && !Double.isInfinite(value); }
  private MonitorTiming() {}
}
