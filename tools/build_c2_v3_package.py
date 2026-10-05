"""Build a hashed V3 add-on and its V2 rollback locally; never contacts C2."""
import hashlib
import json
from pathlib import Path
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / 'candidate/device-a6eed9e-v3'
V2 = ROOT / 'candidate/device-a6eed9e-v2-probe'


def digest(path):
  return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
  previous = json.loads((V2 / 'manifest.json').read_text(encoding='utf-8'))
  deploy = {path.name: digest(path) for path in sorted((PACKAGE / 'deploy').glob('*.py'))}
  expected = {name: digest(PACKAGE / 'rollback' / name) if (PACKAGE / 'rollback' / name).is_file() else None
              for name in deploy}
  for name in ('carcontroller.py', 'pqcan.py', 'hca_timer_reset.py'):
    if expected[name] != previous['deploy_sha256'][name]:
      raise RuntimeError('V2 rollback differs from installed baseline: ' + name)
  for name in ('carstate.py', 'interface.py'):
    original = subprocess.run(['git', '-C', str(ROOT / 'vendor/dragonpilot-device-a6eed9e'), 'show',
                               previous['base_commit'] + ':selfdrive/car/volkswagen/' + name],
                              capture_output=True, check=True).stdout
    if hashlib.sha256(original).hexdigest() != expected[name]:
      raise RuntimeError('Pinned original differs: ' + name)
  for path in list((PACKAGE / 'deploy').glob('*.py')) + list((PACKAGE / 'diagnostics').glob('*.py')):
    compile(path.read_bytes(), str(path), 'exec')
  apk = PACKAGE / 'overlay/build/pq46-probe-overlay.apk'
  old_apk = V2 / 'overlay/build/pq46-probe-overlay.apk'
  if not apk.is_file() or not old_apk.is_file():
    raise RuntimeError('Build both Android overlays first; V2 APK is required for rollback')
  diagnostics = {'v3_server.py': digest(PACKAGE / 'diagnostics/v3_server.py'),
                 'v3_capture.py': digest(PACKAGE / 'diagnostics/v3_capture.py')}
  manifest = {'base_commit': previous['base_commit'], 'device_branch': previous['device_branch'],
              'package_type': 'Local V3 candidate; vehicle execution not verified',
              'default_mode': 'base; lateral opportunity reset and passive logging, no cruise injection',
              'hca': {'seek_after_s': 180, 'standby_s': 2, 'takeover_s': 240},
              'cruise': {'max_press_frames': 9, 'max_press_s': .18, 'ack_timeout_s': 2,
                         'minimum_actual_kph': 70, 'minimum_target_kph': 60},
              'preconditions_sha256': expected, 'deploy_sha256': deploy,
              'preserved_sha256': {'pq_stock_cruise_probe.py': previous['deploy_sha256']['pq_stock_cruise_probe.py']},
              'diagnostics_sha256': diagnostics,
              'startup_sha256': {'ui': previous['startup_sha256']['probe_ui'],
                                  'v2_boot': digest(PACKAGE / 'rollback/boot_overlay.py'),
                                  'v3_boot': digest(PACKAGE / 'diagnostics/boot_overlay.py')},
              'apk_sha256': {'v3': digest(apk), 'v2': digest(old_apk)}}
  if manifest['startup_sha256']['v2_boot'] != previous['startup_sha256']['boot_overlay.py']:
    raise RuntimeError('V2 startup rollback mismatch')
  (PACKAGE / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
  artifacts = ROOT / 'artifacts'
  artifacts.mkdir(exist_ok=True)
  archive = artifacts / 'pq46-c2-v3-candidate.zip'
  with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as output:
    for path in sorted(PACKAGE.rglob('*')):
      if path.is_file() and '__pycache__' not in path.parts and 'build' not in path.parts:
        output.write(path, path.relative_to(ROOT).as_posix())
    output.write(apk, apk.relative_to(ROOT).as_posix())
    output.write(old_apk, old_apk.relative_to(ROOT).as_posix())
    for name in ('manage_c2_v3_package.py', 'c2_parked_guard.py', 'check_c2_v3_package.py'):
      path = ROOT / 'tools' / name
      output.write(path, path.relative_to(ROOT).as_posix())
  sha = digest(archive)
  archive.with_suffix('.zip.sha256').write_text(sha + '  ' + archive.name + '\n', encoding='utf-8')
  print(json.dumps({'package': str(archive), 'sha256': sha, 'device_contacted': False}, ensure_ascii=False))


if __name__ == '__main__':
  main()
