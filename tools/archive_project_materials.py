"""Archive project materials as plain compressed, deduplicated files.

No encryption, network access or source deletion. Standalone private keys are
excluded; complete original device backup containers remain local.
"""
import argparse
from datetime import datetime, timezone
import gzip
import hashlib
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / 'archive/20261003'
CHUNK_BYTES = 64 * 1024 * 1024


def sha(data):
  return hashlib.sha256(data).hexdigest()


def excluded(path):
  lower = path.name.lower()
  if lower in ('id_rsa', 'id_ed25519') or lower.endswith(('.jks', '.p12', '.pfx')):
    return 'private_key_or_signing_keystore'
  if lower.endswith(('.pyc', '.class')):
    return 'rebuildable_compiler_cache'
  with path.open('rb') as stream:
    prefix = stream.read(8192)
  if any(marker in prefix for marker in (b'-----BEGIN PRIVATE KEY-----', b'-----BEGIN RSA PRIVATE KEY-----',
                                        b'-----BEGIN OPENSSH PRIVATE KEY-----', b'-----BEGIN EC PRIVATE KEY-----')):
    return 'private_key_material'
  return None


def put_chunk(data, object_index):
  plain_hash = sha(data)
  if plain_hash in object_index:
    return object_index[plain_hash]
  rel = 'objects/' + plain_hash[:2] + '/p-' + plain_hash + '.gz'
  destination = ARCHIVE/rel
  destination.parent.mkdir(parents=True, exist_ok=True)
  if destination.exists():
    packed = destination.read_bytes()
    if gzip.decompress(packed) != data:
      raise RuntimeError('Existing archive object differs: '+rel)
  else:
    packed = gzip.compress(data, compresslevel=1, mtime=0)
    destination.write_bytes(packed)
  record = {'object': rel, 'plain_sha256': plain_hash, 'stored_sha256': sha(packed),
            'plain_bytes': len(data), 'stored_bytes': len(packed), 'encoding': 'gzip'}
  object_index[plain_hash] = record
  return record


def create():
  objects, files, links, skipped = {}, [], [], []
  groups = {}
  for group in ('vendor', 'device-backups', 'artifacts'):
    print('Archiving '+group, flush=True)
    count, total = 0, 0
    for base, directories, names in os.walk(ROOT/group, followlinks=False):
      for name in list(directories):
        path = Path(base)/name
        if path.is_symlink():
          links.append({'path': path.relative_to(ROOT).as_posix(), 'target': os.readlink(path)})
          directories.remove(name)
        elif name in ('.git', '__pycache__'):
          directories.remove(name)
      for name in sorted(names):
        path = Path(base)/name
        rel = path.relative_to(ROOT).as_posix()
        if path.name == '.git':
          continue
        if path.is_symlink():
          links.append({'path': rel, 'target': os.readlink(path)})
          continue
        reason = excluded(path)
        if reason:
          skipped.append({'path': rel, 'reason': reason})
          continue
        before = path.stat()
        digest, chunks = hashlib.sha256(), []
        with path.open('rb') as stream:
          while True:
            data = stream.read(CHUNK_BYTES)
            if not data:
              break
            digest.update(data)
            chunks.append(put_chunk(data, objects))
        after = path.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
          raise RuntimeError('Source changed during snapshot: '+rel)
        files.append({'path': rel, 'bytes': before.st_size, 'sha256': digest.hexdigest(),
                      'mtime_ns': before.st_mtime_ns, 'chunks': chunks})
        count += 1
        total += before.st_size
        if count % 1000 == 0:
          print(group+': '+str(count)+' files', flush=True)
    groups[group] = {'files': count, 'source_bytes': total}
  repositories = []
  for path in sorted((ROOT/'vendor').iterdir()):
    if not (path/'.git').exists():
      continue
    item = {'path': path.relative_to(ROOT).as_posix()}
    for name, args in (('head', ['rev-parse', 'HEAD']), ('branch', ['rev-parse', '--abbrev-ref', 'HEAD'])):
      result = subprocess.run(['git', '-C', str(path), *args], capture_output=True, text=True)
      item[name] = result.stdout.strip() if result.returncode == 0 else None
    repositories.append(item)
  index = {'format': 'vwopenploot-materials-v1', 'created_utc': datetime.now(timezone.utc).isoformat(),
           'scope': ['vendor', 'device-backups', 'artifacts'], 'chunk_bytes': CHUNK_BYTES,
           'groups': groups, 'files': files, 'symlinks': links, 'excluded': skipped,
           'source_repositories': repositories,
           'unique_objects': len(objects), 'stored_bytes': sum(item['stored_bytes'] for item in objects.values()),
           'privacy': 'No encryption. Local Git only. Standalone private key files excluded; complete device backup containers retained.'}
  (ARCHIVE/'index.json').write_text(json.dumps(index, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
  return index


def verify():
  index = json.loads((ARCHIVE/'index.json').read_text(encoding='utf-8'))
  # Reconstruct every archived file and verify its full original hash.
  verified = set()
  for number, item in enumerate(index['files'], 1):
    digest, size = hashlib.sha256(), 0
    for chunk in item['chunks']:
      packed = (ARCHIVE/chunk['object']).read_bytes()
      if sha(packed) != chunk['stored_sha256']:
        raise RuntimeError('Stored hash mismatch: '+chunk['object'])
      if chunk['encoding'] != 'gzip':
        raise RuntimeError('Only plain compressed archive objects are allowed')
      data = gzip.decompress(packed)
      if sha(data) != chunk['plain_sha256'] or len(data) != chunk['plain_bytes']:
        raise RuntimeError('Decoded chunk mismatch: '+chunk['object'])
      digest.update(data)
      size += len(data)
      verified.add(chunk['object'])
    if digest.hexdigest() != item['sha256'] or size != item['bytes']:
      raise RuntimeError('Reconstructed file mismatch: '+item['path'])
    if number % 1000 == 0:
      print('Verified '+str(number)+' files', flush=True)
  report = {'verified_utc': datetime.now(timezone.utc).isoformat(), 'files': len(index['files']),
            'unique_objects': len(verified), 'source_bytes': sum(item['bytes'] for item in index['files']),
            'stored_bytes': index['stored_bytes'], 'all_reconstructed_file_hashes_match': True,
            'encryption': False, 'index_sha256': sha((ARCHIVE/'index.json').read_bytes())}
  (ARCHIVE/'verification.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
  print(json.dumps(report), flush=True)
  return report


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument('--verify-only', action='store_true')
  args = parser.parse_args()
  if not args.verify_only:
    create()
  verify()


if __name__ == '__main__':
  main()
