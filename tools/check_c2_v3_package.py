"""Verify the final local archive, payload hashes and absence of private keys."""
import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def main():
  archive = ROOT / 'artifacts/pq46-c2-v3-candidate.zip'
  digest = hashlib.sha256(archive.read_bytes()).hexdigest()
  expected = archive.with_suffix('.zip.sha256').read_text(encoding='utf-8').split()[0]
  if digest != expected:
    raise RuntimeError('Archive hash mismatch')
  base = 'candidate/device-a6eed9e-v3/'
  with zipfile.ZipFile(archive) as package:
    if package.testzip() is not None:
      raise RuntimeError('Archive CRC error')
    names = package.namelist()
    if any('/keys/' in name or name.endswith(('.jks', '.pem')) or '/device-backups/' in '/' + name for name in names):
      raise RuntimeError('Private material must not be in package')
    manifest = json.loads(package.read(base + 'manifest.json'))
    def verify(name, expected_hash):
      if hashlib.sha256(package.read(name)).hexdigest() != expected_hash:
        raise RuntimeError('Payload mismatch: ' + name)
    for name, value in manifest['deploy_sha256'].items():
      verify(base + 'deploy/' + name, value)
    for name, value in manifest['preconditions_sha256'].items():
      if value is not None:
        verify(base + 'rollback/' + name, value)
    for name, value in manifest['diagnostics_sha256'].items():
      verify(base + 'diagnostics/' + name, value)
    verify(base + 'diagnostics/boot_overlay.py', manifest['startup_sha256']['v3_boot'])
    verify(base + 'rollback/boot_overlay.py', manifest['startup_sha256']['v2_boot'])
    verify(base + 'overlay/build/pq46-probe-overlay.apk', manifest['apk_sha256']['v3'])
    verify('candidate/device-a6eed9e-v2-probe/overlay/build/pq46-probe-overlay.apk', manifest['apk_sha256']['v2'])
    for name in ('tools/manage_c2_v3_package.py', 'tools/c2_parked_guard.py'):
      if package.read(name) != (ROOT / name).read_bytes():
        raise RuntimeError('Installer differs from local source: ' + name)
  print(json.dumps({'verified': True, 'sha256': digest, 'bytes': archive.stat().st_size,
                    'files': len(names), 'device_contacted': False}))


if __name__ == '__main__':
  main()
