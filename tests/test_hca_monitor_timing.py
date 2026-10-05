"""Run the Android monitor's pure timing decisions on the local JVM."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'candidate/device-a6eed9e-hca-monitor/overlay/android/src/nl/vwopenploot/probe/MonitorTiming.java'


class MonitorTimingTest(unittest.TestCase):
  def test_deadline_freshness_and_unknown_versions(self):
    runner = '''
import nl.vwopenploot.probe.MonitorTiming;
public final class MonitorTest {
  static void check(boolean condition) { if (!condition) throw new AssertionError(); }
  public static void main(String[] args) {
    check(MonitorTiming.warning("hca-r2-entry", 234.99, true, false) == 0);
    check(MonitorTiming.warning("hca-r2-entry", 235, true, false) == 1);
    check(MonitorTiming.warning("hca-r2-entry", 239.99, true, false) == 1);
    check(MonitorTiming.warning("hca-r2-entry", 240, true, false) == 2);
    check(MonitorTiming.warning("hca-r2-entry", 236, false, false) == 0);
    check(MonitorTiming.warning("hca-r2-entry", 236, false, true) == 2);
    check(MonitorTiming.warning("unknown", 235, true, false) == -1);
    check(MonitorTiming.warning("hca-r2-entry", Double.NaN, true, false) == -1);
    check(MonitorTiming.warning("hca-r2-entry", Double.POSITIVE_INFINITY, true, false) == -1);
    check(MonitorTiming.warning("hca-r2-entry", -1, true, false) == -1);
    check(MonitorTiming.fresh(100, 99));
    check(!MonitorTiming.fresh(100, 98.99));
    check(!MonitorTiming.fresh(100, 100.01));
    check(!MonitorTiming.fresh(100, 0));
    check(!MonitorTiming.fresh(Double.NaN, 99));
    check(!MonitorTiming.fresh(100, Double.NaN));
    System.out.println("16 monitor timing checks passed");
  }
}
'''
    with tempfile.TemporaryDirectory(prefix='pq46-monitor-') as work:
      path = Path(work)
      (path/'MonitorTest.java').write_text(runner, encoding='utf-8')
      subprocess.run(['javac', '-d', str(path), str(SOURCE), str(path/'MonitorTest.java')], check=True, capture_output=True)
      result = subprocess.run(['java', '-cp', str(path), 'MonitorTest'], check=True, capture_output=True, text=True)
      self.assertIn('16 monitor timing checks passed', result.stdout)


if __name__ == '__main__':
  unittest.main()
