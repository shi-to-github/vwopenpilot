"""Read-only C2 inventory and streaming backup of /data/openpilot and /data/params."""

import argparse
import hashlib
import pathlib
import subprocess
import sys
import tarfile
import time


REQUIRED_MEMBERS = {
  "openpilot/.git/HEAD",
  "openpilot/selfdrive/car/volkswagen/carcontroller.py",
  "openpilot/selfdrive/car/volkswagen/interface.py",
  "params/d",
  "params/d_tmp",
}


def verify_archive(path):
  sha256 = hashlib.sha256()
  with path.open("rb") as source:
    for chunk in iter(lambda: source.read(4 * 1024 * 1024), b""):
      sha256.update(chunk)

  found = set()
  members = 0
  files = 0
  params = 0
  with tarfile.open(path, mode="r|gz") as archive:
    for member in archive:
      members += 1
      if member.isfile():
        files += 1
        params += member.name.startswith("params/d_tmp/")
      if member.name in REQUIRED_MEMBERS:
        found.add(member.name)

  missing = REQUIRED_MEMBERS - found
  if missing or not params:
    raise RuntimeError(f"Backup is missing required entries: {sorted(missing)}; params files={params}")
  return sha256.hexdigest(), members, files, params


def ssh_command(args, remote_command):
  return [
    "ssh", "-p", str(args.port), "-i", str(args.identity),
    "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes",
    "-o", "ConnectTimeout=8", "-o", "StrictHostKeyChecking=accept-new",
    "-o", f"UserKnownHostsFile={args.known_hosts}",
    f"{args.user}@{args.ip}", remote_command,
  ]


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("--ip")
  parser.add_argument("--port", type=int, default=8022)
  parser.add_argument("--user", default="root")
  parser.add_argument("--identity", type=pathlib.Path)
  parser.add_argument("--known-hosts", type=pathlib.Path,
                      default=pathlib.Path.home() / ".ssh" / "known_hosts_vwopenploot_c2")
  parser.add_argument("--destination", type=pathlib.Path)
  parser.add_argument("--verify-only", type=pathlib.Path,
                      help="Verify an existing archive without contacting the C2")
  args = parser.parse_args()

  if args.verify_only:
    digest, members, files, params = verify_archive(args.verify_only)
    print(f"VALID sha256={digest} members={members} files={files} params_files={params}")
    return

  if not args.ip or not args.identity or not args.destination:
    parser.error("--ip, --identity and --destination are required for collection")
  if not args.identity.is_file():
    parser.error(f"SSH identity not found: {args.identity}")

  destination = args.destination.resolve()
  destination.mkdir(parents=True, exist_ok=True)
  archive = destination / "c2-data-openpilot-params.tar.gz"
  partial = destination / "c2-data-openpilot-params.tar.gz.partial"
  if archive.exists() or partial.exists():
    raise RuntimeError("Destination already contains an archive; choose a new directory")

  inventory_command = (
    "date; uname -a; cat /VERSION 2>/dev/null || true; "
    "getprop ro.build.display.id 2>/dev/null || true; "
    "df -h /data; du -sh /data/openpilot /data/params/d_tmp 2>/dev/null; "
    "cd /data/openpilot || exit 1; "
    "git rev-parse --abbrev-ref HEAD; git rev-parse HEAD; git status --short"
  )
  inventory = subprocess.run(ssh_command(args, inventory_command),
                             capture_output=True, text=True, check=True)
  (destination / "device-and-version.txt").write_text(inventory.stdout, encoding="utf-8")
  print("Device inventory saved; streaming backup started", flush=True)

  start = time.monotonic()
  last_report = start
  total = 0
  stderr_path = destination / "backup-stderr.txt"
  with partial.open("wb") as output, stderr_path.open("wb") as stderr:
    process = subprocess.Popen(ssh_command(args, "tar -C /data -czf - openpilot params"),
                               stdout=subprocess.PIPE, stderr=stderr)
    while True:
      chunk = process.stdout.read(1024 * 1024)
      if not chunk:
        break
      output.write(chunk)
      total += len(chunk)
      now = time.monotonic()
      if now - last_report >= 20:
        print(f"received_mib={total / 1048576:.1f}", flush=True)
        last_report = now
    status = process.wait()

  warnings = stderr_path.read_text(encoding="utf-8", errors="replace").splitlines()
  benign_changes = all(line.startswith("tar: ") and
                       line.endswith(": file changed as we read it") for line in warnings)
  if status not in (0, 1) or (status == 1 and (not warnings or not benign_changes)):
    raise RuntimeError(f"Remote tar exited {status}; inspect {stderr_path} and keep the partial file")

  digest, members, files, params = verify_archive(partial)
  partial.rename(archive)
  (destination / "archive-sha256.txt").write_text(
    f"{digest}  {archive.name}\n", encoding="utf-8")
  (destination / "backup-validation.txt").write_text(
    f"tar_exit={status}\narchive_sha256={digest}\nmembers={members}\n"
    f"files={files}\nparams_files={params}\nwarnings={len(warnings)}\n",
    encoding="utf-8",
  )
  print(f"VALID archive={archive} members={members} params_files={params} "
        f"elapsed_s={time.monotonic() - start:.0f}", flush=True)


if __name__ == "__main__":
  try:
    main()
  except (OSError, RuntimeError, subprocess.CalledProcessError, tarfile.TarError) as error:
    print(f"ERROR: {error}", file=sys.stderr)
    sys.exit(1)
