"""Build the Android 6 floating probe switch from local SDK tools."""

import os
import argparse
import pathlib
import shutil
import subprocess
import zipfile


ROOT = pathlib.Path(__file__).resolve().parents[1]
OVERLAY = ROOT / "candidate" / "device-a6eed9e-v2-probe" / "overlay"


def run(*args):
  subprocess.run([str(arg) for arg in args], check=True)


def main():
  global OVERLAY
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument('--package', choices=('v2', 'v3', 'r3', 'r4', 'monitor'), default='v2')
  args = parser.parse_args()
  if args.package == 'v3':
    OVERLAY = ROOT / 'candidate' / 'device-a6eed9e-v3' / 'overlay'
  elif args.package == 'r3':
    OVERLAY = ROOT / 'candidate' / 'device-a6eed9e-v3-hca-r3-staged' / 'overlay'
  elif args.package == 'r4':
    OVERLAY = ROOT / 'candidate' / 'device-a6eed9e-v3-hca-r4-forced' / 'overlay'
  elif args.package == 'monitor':
    OVERLAY = ROOT / 'candidate' / 'device-a6eed9e-hca-monitor' / 'overlay'
  sdk = pathlib.Path(os.environ.get("ANDROID_SDK_ROOT") or os.environ["ANDROID_HOME"])
  versions = sorted((sdk / "build-tools").iterdir(), key=lambda path: tuple(int(p) for p in path.name.split(".")))
  build_tools = versions[-1]
  android_jar = sorted((sdk / "platforms").glob("android-*/android.jar"))[-1]
  aapt = build_tools / "aapt.exe"
  d8 = build_tools / "d8.bat"
  zipalign = build_tools / "zipalign.exe"
  apksigner = build_tools / "apksigner.bat"
  output = OVERLAY / "build"
  classes = output / "classes"
  dex = output / "dex"
  classes.mkdir(parents=True, exist_ok=True)
  dex.mkdir(parents=True, exist_ok=True)
  sources = sorted((OVERLAY / "android" / "src").rglob("*.java"))
  run("javac", "-encoding", "UTF-8", "-source", "8", "-target", "8", "-cp", android_jar,
      "-d", classes, *sources)
  run(d8, "--min-api", "23", "--lib", android_jar, "--output", dex,
      *(classes.rglob("*.class")))
  unsigned = output / "unsigned.apk"
  run(aapt, "package", "-f", "-M", OVERLAY / "android" / "AndroidManifest.xml",
      "-I", android_jar, "-F", unsigned)
  with zipfile.ZipFile(unsigned, "a") as package:
    package.write(dex / "classes.dex", "classes.dex")
  aligned = output / "aligned.apk"
  run(zipalign, "-f", "4", unsigned, aligned)
  # Both versions use the same Android package; upgrades must retain its signer.
  keys = ROOT / 'candidate' / 'device-a6eed9e-v2-probe' / 'overlay' / 'keys'
  keys.mkdir(exist_ok=True)
  keystore = keys / "probe-debug.jks"
  if not keystore.exists():
    run("keytool", "-genkeypair", "-noprompt", "-alias", "probe-debug",
        "-keyalg", "RSA", "-keysize", "2048", "-validity", "3650",
        "-keystore", keystore, "-storepass", "android", "-keypass", "android",
        "-dname", "CN=VWopenploot Probe,O=Local Test,C=CN")
  signed = output / "pq46-probe-overlay.apk"
  shutil.copyfile(aligned, signed)
  run(apksigner, "sign", "--ks", keystore, "--ks-key-alias", "probe-debug",
      "--ks-pass", "pass:android", "--key-pass", "pass:android", signed)
  run(apksigner, "verify", signed)
  print(signed)


if __name__ == "__main__":
  main()
