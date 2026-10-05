"""Local V3 screen controls, automatic bounded logging, and mode heartbeat."""

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from cereal import messaging
from common.realtime import sec_since_boot


ROOT = Path('/data/pq46')
LOGS = ROOT / 'logs'
MODE = ROOT / 'v3_mode.json'
EVENTS = ROOT / 'v3_events.jsonl'
STATUS = ROOT / 'v3_status.json'
UI_STATE = ROOT / 'hca_ui.json'
LABELS = {'base': '横向择机＋日志', 'auto': '前车调速',
          'probe_down': '测试减十', 'probe_up': '测试加十', 'probe_recall': '测试加一'}


def event(kind, **details):
  record = {'kind': kind, 'boot_s': sec_since_boot(), 'unix_ns': time.time_ns(), **details}
  with EVENTS.open('a', encoding='utf-8') as output:
    output.write(json.dumps(record, ensure_ascii=False) + '\n')


class Session:
  def __init__(self):
    ROOT.mkdir(mode=0o700, exist_ok=True)
    LOGS.mkdir(mode=0o700, exist_ok=True)
    self.lock = threading.RLock()
    self.stop = threading.Event()
    self.mode = 'base'
    self.recorder = None
    self.log_path = None
    self.last_active = -100
    self.retry_record_after = 0
    self.last_tick = -100
    self.note = '默认横向＋日志'
    self.ui_state = {}
    UI_STATE.unlink(missing_ok=True)
    self.write_mode()

  def write_mode(self):
    temp = MODE.with_suffix('.tmp')
    temp.write_text(json.dumps({'mode': self.mode, 'boot_s': sec_since_boot()}), encoding='utf-8')
    os.replace(str(temp), str(MODE))

  def status(self):
    with self.lock:
      try:
        runtime = json.loads(STATUS.read_text(encoding='utf-8'))
        if not isinstance(runtime, dict) or not 0 <= sec_since_boot() - runtime['boot_s'] <= 1:
          runtime = {}
      except (OSError, ValueError, KeyError, TypeError):
        runtime = {}
      return {'mode': self.mode, 'label': LABELS[self.mode], 'note': self.note,
              'recording': self.recorder is not None and self.recorder.poll() is None,
              'log_path': str(self.log_path) if self.log_path else None, 'runtime': runtime}

  def retain(self):
    # Only this package's closed traces, within this exact directory, may rotate.
    files = sorted(LOGS.glob('v3-*.jsonl'), key=lambda p: p.stat().st_mtime)
    size = sum(p.stat().st_size for p in files)
    while files and (len(files) >= 20 or size > 500 * 1024 * 1024):
      oldest = files.pop(0)
      if oldest == self.log_path and self.recorder is not None and self.recorder.poll() is None:
        continue
      if oldest.resolve().parent != LOGS.resolve():
        raise RuntimeError('Unexpected log path')
      size -= oldest.stat().st_size
      oldest.unlink()
      oldest.with_suffix('.stderr.txt').unlink(missing_ok=True)

  def start_recording(self):
    if self.recorder is not None and self.recorder.poll() is None:
      return
    if sec_since_boot() < self.retry_record_after:
      raise RuntimeError('日志等待重试')
    self.retain()
    self.log_path = LOGS / ('v3-%s-%d.jsonl' % (time.strftime('%Y%m%d-%H%M%S'), time.time_ns()))
    with self.log_path.with_suffix('.stderr.txt').open('w', encoding='utf-8') as error:
      self.recorder = subprocess.Popen(
        [sys.executable, '/data/pq46/v3_capture.py', '--seconds', '1800', '--output', str(self.log_path)],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=error,
        start_new_session=True)
    time.sleep(0.15)
    if self.recorder.poll() is not None:
      self.retry_record_after = sec_since_boot() + 10
      raise RuntimeError('记录器启动失败')
    event('trace_started', path=str(self.log_path))

  def stop_recording(self):
    if self.recorder is not None and self.recorder.poll() is None:
      self.recorder.send_signal(signal.SIGINT)
    self.recorder = None

  def set_mode(self, mode):
    with self.lock:
      if not isinstance(mode, str) or mode not in LABELS:
        raise ValueError('Unknown mode')
      if mode != 'base':
        self.start_recording()
      self.mode = mode
      self.note = '已选择，等待车辆条件' if mode != 'base' else '横向择机运行'
      self.write_mode()
      event('mode_selected', mode=mode)
      return self.status()

  def ui_heartbeat(self, payload):
    with self.lock:
      now = sec_since_boot()
      state = dict(self.ui_state)
      state.update(boot_s=now, audio_ready=payload.get('audio_ready') is True)
      notice_id = payload.get('notice_id', '')
      if notice_id:
        hca = self.status()['runtime'].get('hca', {})
        # The 350 s forced-pause prompt is fire-and-forget: it is recorded so the
        # log shows whether the driver was actually warned, but it never gates the
        # fallback pause, so a missing tone cannot cancel it.
        if (not isinstance(notice_id, str) or len(notice_id) > 80 or
            hca.get('version') != 'hca-r4-forced' or
            notice_id not in (hca.get('notice_id'), hca.get('prompt_id')) or
            hca.get('phase') not in ('awaiting_notice', 'countdown', 'forced_prompt')):
          raise ValueError('Notice no longer current')
        if state.get('notice_id') != notice_id:
          state.update(notice_id=notice_id, ack_boot_s=now, audio_ok=payload.get('audio_ok') is True)
          event('hca_notice_played', notice_id=notice_id, audio_ok=state['audio_ok'])
      temp = UI_STATE.with_suffix('.tmp')
      temp.write_text(json.dumps(state), encoding='utf-8')
      os.replace(str(temp), str(UI_STATE))
      self.ui_state = state
      return {'accepted': True}

  def loop(self):
    sm = messaging.SubMaster(['carState', 'controlsState'])
    while not self.stop.is_set():
      try:
        sm.update(100)
        now = sec_since_boot()
        if now - self.last_tick < 0.1:
          continue
        self.last_tick = now
        self.tick(sm, now)
      except (OSError, RuntimeError, ValueError, TypeError):
        with self.lock:
          self.mode = 'base'
          self.note = '日志或状态不可用，调速关闭'
          self.retry_record_after = max(self.retry_record_after, sec_since_boot() + 10)
          try:
            self.write_mode()
          except OSError:
            pass

  def tick(self, sm, now):
      with self.lock:
        active = (sm.valid['carState'] and sm.alive['carState'] and
                  0 <= now - sm.logMonoTime['carState'] / 1e9 < 0.5 and
                  sm['carState'].cruiseState.enabled)
        if active or self.mode != 'base':
          self.last_active = now
        if self.recorder is not None and self.recorder.poll() is not None:
          code = self.recorder.returncode
          self.recorder = None
          event('trace_finished', exit_code=code)
          if code != 0:
            self.mode = 'base'
            self.retry_record_after = now + 10
            self.note = '日志异常，调速已关闭'
            event('logger_failed')
        if active or self.mode != 'base':
          self.start_recording()
        elif now - self.last_active > 20:
          self.stop_recording()
        runtime = self.status()['runtime']
        cruise = runtime.get('cruise', {})
        if self.mode != 'base' and cruise.get('mode') == self.mode:
          if cruise.get('fault'):
            self.note = '调速停止：目标未确认或条件中断'
            event('cruise_fault', reason=cruise['fault'])
            self.mode = 'base'
          elif self.mode.startswith('probe_') and cruise.get('phase') == 'done':
            self.note = '测试已回读：定速目标变化'
            event('probe_ecu_acknowledged', direction=cruise.get('direction'))
            self.mode = 'base'
        self.write_mode()

  def close(self):
    with self.lock:
      self.stop.set()
      self.mode = 'base'
      try:
        self.write_mode()
      finally:
        self.stop_recording()


class Handler(BaseHTTPRequestHandler):
  session = None

  def reply(self, code, data):
    raw = json.dumps(data, ensure_ascii=False).encode('utf-8')
    self.send_response(code)
    self.send_header('Content-Type', 'application/json; charset=utf-8')
    self.send_header('Content-Length', str(len(raw)))
    self.end_headers()
    self.wfile.write(raw)

  def do_GET(self):
    self.reply(200, self.session.status()) if self.path == '/status' else self.reply(404, {})

  def do_POST(self):
    if self.path == '/shutdown':
      self.session.close()
      self.reply(200, {'mode': 'base'})
      threading.Thread(target=self.server.shutdown, daemon=True).start()
      return
    try:
      length = int(self.headers.get('Content-Length', '0'))
      if self.path not in ('/mode', '/hca_ui') or not 0 < length <= 512:
        raise ValueError('Invalid request')
      payload = json.loads(self.rfile.read(length))
      if not isinstance(payload, dict):raise ValueError('Expected object')
      result = self.session.ui_heartbeat(payload) if self.path == '/hca_ui' else self.session.set_mode(payload['mode'])
      self.reply(200, result)
    except (ValueError, KeyError, OSError, RuntimeError) as error:
      self.reply(400, {'error': str(error)})

  def log_message(self, *_):
    pass


def main():
  session = Session()
  Handler.session = session
  server = ThreadingHTTPServer(('127.0.0.1', 8766), Handler)
  threading.Thread(target=session.loop, daemon=True).start()
  try:
    server.serve_forever(poll_interval=0.2)
  finally:
    session.close()
    server.server_close()


if __name__ == '__main__':
  main()
