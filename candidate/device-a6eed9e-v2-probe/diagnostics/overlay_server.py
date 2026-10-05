"""Loopback-only companion for the optional Android floating probe switch.

The server starts a passive trace, arms one automatic DOWN probe, and returns
to V1 after observing the sendcan attempt. A heartbeat makes mode 3 fail closed
if this process dies. It never sends CAN itself.
"""

import json
import os
import pathlib
import signal
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from cereal import messaging


ROOT = pathlib.Path("/data/pq46")
MODE = ROOT / "stock_cruise_probe_mode"
HEARTBEAT = ROOT / "auto_probe_heartbeat"
EVENTS = ROOT / "probe_control_events.jsonl"
CAPTURE = ROOT / "capture_cruise.py"
LOGS = ROOT / "logs"
PORT = 8765


def atomic_mode(value):
  temporary = MODE.with_name(MODE.name + ".tmp")
  temporary.write_text(str(value) + "\n", encoding="utf-8")
  os.replace(str(temporary), str(MODE))


def operator_event(kind, **details):
  record = {"kind": kind, "unix_ns": time.time_ns(), **details}
  line = (json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
  fd = os.open(str(EVENTS), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
  try:
    os.write(fd, line)
  finally:
    os.close(fd)


class ProbeSession:
  def __init__(self):
    ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
    LOGS.mkdir(mode=0o700, parents=True, exist_ok=True)
    self.lock = threading.RLock()
    self.enabled = False
    self.stop = threading.Event()
    self.recorder = None
    self.log_path = None
    self.last = "六分钟修复版"
    atomic_mode(0)
    HEARTBEAT.unlink(missing_ok=True)

  def status(self):
    with self.lock:
      return {"enabled": self.enabled, "label": self.last,
              "log_path": str(self.log_path) if self.log_path else None,
              "recording": self.recorder is not None and self.recorder.poll() is None}

  def _start_recorder(self):
    if self.recorder is not None and self.recorder.poll() is None:
      self._stop_recorder()
    self.log_path = LOGS / ("probe-%s-%d.jsonl" % (time.strftime("%Y%m%d-%H%M%S"), time.time_ns() % 1000000))
    error = self.log_path.with_suffix(".stderr.txt").open("w", encoding="utf-8")
    try:
      self.recorder = subprocess.Popen(
        [sys.executable, str(CAPTURE), "--seconds", "1800", "--output", str(self.log_path)],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=error,
        start_new_session=True)
    finally:
      error.close()
    time.sleep(0.15)
    if self.recorder.poll() is not None:
      raise RuntimeError("巡航记录器未能启动；查看 .stderr.txt")

  def _stop_recorder(self, expected=None):
    with self.lock:
      process = self.recorder
      if process is None or (expected is not None and process is not expected):
        return
      if process.poll() is None:
        process.send_signal(signal.SIGINT)
      self.recorder = None

  def set_enabled(self, value):
    with self.lock:
      if value:
        if not self.enabled:
          try:
            self._start_recorder()
            HEARTBEAT.touch()
            atomic_mode(3)
            operator_event("auto_probe_armed", log_path=str(self.log_path))
            self.enabled = True
            self.last = "测试待触发：一次减速"
          except Exception:
            atomic_mode(0)
            HEARTBEAT.unlink(missing_ok=True)
            self._stop_recorder()
            raise
      else:
        atomic_mode(0)
        HEARTBEAT.unlink(missing_ok=True)
        self.enabled = False
        self.last = "六分钟修复版"
        operator_event("auto_probe_disabled")
        self._stop_recorder()
      return self.status()

  def heartbeat_loop(self):
    while not self.stop.wait(1):
      with self.lock:
        if self.enabled:
          if self.recorder is None or self.recorder.poll() is not None:
            self.enabled = False
            atomic_mode(0)
            HEARTBEAT.unlink(missing_ok=True)
            self.last = "记录失败，测试已关闭"
            operator_event("auto_probe_logger_failed")
          else:
            HEARTBEAT.touch()

  def watch_sendcan(self):
    try:
      socket = messaging.sub_sock("sendcan", conflate=False, timeout=1000)
      while not self.stop.is_set():
        event = messaging.recv_one(socket)
        if event is None:
          continue
        for frame in event.sendcan:
          data = bytes(frame.dat)
          if frame.address == 906 and len(data) >= 2 and data[1] & 4:
            with self.lock:
              if not self.enabled:
                continue
              atomic_mode(0)
              HEARTBEAT.unlink(missing_ok=True)
              self.enabled = False
              self.last = "已尝试一次减速，已回六分钟修复版"
              operator_event("auto_probe_sendcan_seen", note="Panda/车辆是否执行需核对日志与仪表")
              threading.Timer(20, self._stop_recorder, args=(self.recorder,)).start()
    except Exception:
      with self.lock:
        self.enabled = False
        atomic_mode(0)
        HEARTBEAT.unlink(missing_ok=True)
        self.last = "监测进程失败，测试已关闭"

  def close(self):
    with self.lock:
      self.stop.set()
      atomic_mode(0)
      HEARTBEAT.unlink(missing_ok=True)
      self.enabled = False
      self._stop_recorder()


class Handler(BaseHTTPRequestHandler):
  session = None

  def _json(self, status, body):
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    self.send_response(status)
    self.send_header("Content-Type", "application/json; charset=utf-8")
    self.send_header("Content-Length", str(len(data)))
    self.end_headers()
    self.wfile.write(data)

  def do_GET(self):
    if self.path != "/status":
      self._json(404, {"error": "not found"})
    else:
      self._json(200, self.session.status())

  def do_POST(self):
    if self.path == "/shutdown":
      self.session.close()
      self._json(200, {"enabled": False, "label": "六分钟修复版"})
      threading.Thread(target=self.server.shutdown, daemon=True).start()
      return
    if self.path != "/mode":
      self._json(404, {"error": "not found"})
      return
    try:
      length = int(self.headers.get("Content-Length", "0"))
      if length < 1 or length > 256:
        raise ValueError("invalid body size")
      body = json.loads(self.rfile.read(length))
      if type(body.get("enabled")) is not bool:
        raise ValueError("enabled must be boolean")
      self._json(200, self.session.set_enabled(body["enabled"]))
    except (ValueError, OSError, RuntimeError) as error:
      self._json(400, {"error": str(error), **self.session.status()})

  def log_message(self, format_string, *args):
    pass


def main():
  session = ProbeSession()
  Handler.session = session
  threading.Thread(target=session.heartbeat_loop, daemon=True).start()
  threading.Thread(target=session.watch_sendcan, daemon=True).start()
  server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
  try:
    server.serve_forever(poll_interval=0.2)
  finally:
    session.close()
    server.server_close()


if __name__ == "__main__":
  main()
