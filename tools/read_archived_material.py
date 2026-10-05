"""Show archived file metadata or recover one file to a new local destination."""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import tempfile

ARCHIVE = Path(__file__).resolve().parents[1]/'archive/20261003'


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument('--path', required=True, help='Exact relative path listed in archive index.json')
  parser.add_argument('--output', type=Path, help='New file to recover; existing files are never overwritten')
  args = parser.parse_args()
  index = json.loads((ARCHIVE/'index.json').read_text(encoding='utf-8'))
  matches = [item for item in index['files'] if item['path'] == args.path]
  if len(matches) != 1:
    parser.error('Archive path is missing or ambiguous')
  item = matches[0]
  if args.output is None:
    print(json.dumps({name:item[name] for name in ('path','bytes','sha256')},ensure_ascii=False,indent=2))
    return
  output = args.output.resolve()
  if output.exists():
    parser.error('Output already exists; not overwritten')
  output.parent.mkdir(parents=True,exist_ok=True)
  digest, size = hashlib.sha256(), 0
  with tempfile.NamedTemporaryFile(prefix='.vw-archive-', dir=str(output.parent), delete=False) as stream:
    temporary = Path(stream.name)
    try:
      for chunk in item['chunks']:
        path = (ARCHIVE/chunk['object']).resolve()
        if ARCHIVE.resolve() not in path.parents or chunk['encoding'] != 'gzip':
          raise RuntimeError('Invalid archive object location or format')
        packed = path.read_bytes()
        if hashlib.sha256(packed).hexdigest() != chunk['stored_sha256']:
          raise RuntimeError('Stored object hash mismatch')
        data = gzip.decompress(packed)
        if hashlib.sha256(data).hexdigest() != chunk['plain_sha256']:
          raise RuntimeError('Decoded object hash mismatch')
        digest.update(data)
        size += len(data)
        stream.write(data)
      stream.flush()
      os.fsync(stream.fileno())
    except Exception:
      stream.close()
      temporary.unlink(missing_ok=True)
      raise
  try:
    if size != item['bytes'] or digest.hexdigest() != item['sha256']:
      raise RuntimeError('Reconstructed file hash mismatch')
    # Both files resolve into the explicitly requested destination directory.
    # Link creation fails atomically if the destination already exists.
    if temporary.resolve().parent != output.parent:
      raise RuntimeError('Unexpected temporary output location')
    os.link(temporary,output)
  finally:
    temporary.unlink(missing_ok=True)
  print(json.dumps({'output':str(output),'bytes':size,'sha256':digest.hexdigest(),'verified':True},ensure_ascii=False))


if __name__ == '__main__':
  main()
