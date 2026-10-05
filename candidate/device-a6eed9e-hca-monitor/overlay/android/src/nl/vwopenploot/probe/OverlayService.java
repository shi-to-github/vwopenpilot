package nl.vwopenploot.probe;

import android.app.Service;
import android.content.Intent;
import android.graphics.Color;
import android.graphics.PixelFormat;
import android.graphics.drawable.GradientDrawable;
import android.media.AudioManager;
import android.media.ToneGenerator;
import android.os.Build;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.os.SystemClock;
import android.view.Gravity;
import android.view.MotionEvent;
import android.view.WindowManager;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.TextView;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.Locale;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicBoolean;
import org.json.JSONObject;

/** Read-only HTTP monitor. Acknowledging a reminder has no control effect. */
public final class OverlayService extends Service {
  private final Handler main = new Handler(Looper.getMainLooper());
  private final ExecutorService network = Executors.newSingleThreadExecutor();
  private final AtomicBoolean busy = new AtomicBoolean(false);
  private WindowManager windows;
  private WindowManager.LayoutParams layout;
  private LinearLayout panel;
  private TextView clock, stage, detail;
  private Button acknowledge;
  private AudioManager audio;
  private ToneGenerator tone;
  private boolean warned, acknowledged;
  private volatile boolean destroyed;
  private int currentWarning;
  private String previousPhase = "";
  private double currentElapsed, previousElapsed;
  private float dragX, dragY;
  private int originalX, originalY;

  @Override public void onCreate() {
    super.onCreate();
    windows = (WindowManager)getSystemService(WINDOW_SERVICE);
    audio = (AudioManager)getSystemService(AUDIO_SERVICE);
    try { tone = new ToneGenerator(AudioManager.STREAM_MUSIC, 35); } catch (RuntimeException ignored) {}
    panel = new LinearLayout(this); panel.setOrientation(LinearLayout.VERTICAL);
    panel.setPadding(dp(12), dp(10), dp(12), dp(10));
    GradientDrawable bg = new GradientDrawable(); bg.setColor(Color.argb(235, 20, 26, 34));
    bg.setCornerRadius(dp(12)); bg.setStroke(dp(1), Color.rgb(80, 150, 180)); panel.setBackground(bg);
    clock = text(26, 2); stage = text(18, 2); detail = text(12, 4);
    clock.setText("计时等待连接"); stage.setText("只读提醒 · 不控制车辆");
    panel.addView(clock); panel.addView(stage); panel.addView(detail);
    acknowledge = new Button(this); acknowledge.setText("确认提醒（不改变控制）"); acknowledge.setTextSize(11);
    acknowledge.setEnabled(false);
    acknowledge.setOnClickListener(v -> {
      acknowledged = true;
      record("driver_acknowledged_reminder", previousPhase, currentElapsed, currentWarning);
      acknowledge.setText("已确认提醒 · 请接管"); acknowledge.setEnabled(false);
    });
    panel.addView(acknowledge, new LinearLayout.LayoutParams(-1, dp(40)));
    int type = Build.VERSION.SDK_INT >= 26 ? WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY : WindowManager.LayoutParams.TYPE_SYSTEM_ALERT;
    layout = new WindowManager.LayoutParams(dp(260), dp(230), type,
        WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE | WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL,
        PixelFormat.TRANSLUCENT);
    layout.gravity = Gravity.RIGHT | Gravity.TOP; layout.x = dp(16); layout.y = dp(60);
    clock.setOnTouchListener((v, ev) -> {
      if (ev.getAction() == MotionEvent.ACTION_DOWN) {
        dragX = ev.getRawX(); dragY = ev.getRawY(); originalX = layout.x; originalY = layout.y; return true;
      }
      if (ev.getAction() == MotionEvent.ACTION_MOVE) {
        layout.x = Math.max(0, Math.min(getResources().getDisplayMetrics().widthPixels - layout.width,
                                     originalX - Math.round(ev.getRawX() - dragX)));
        layout.y = Math.max(0, Math.min(getResources().getDisplayMetrics().heightPixels - layout.height,
                                     originalY + Math.round(ev.getRawY() - dragY)));
        windows.updateViewLayout(panel, layout); return true;
      }
      return true;
    });
    windows.addView(panel, layout);
    record("monitor_started", "", 0, 0); main.post(refresh);
  }

  private TextView text(int size, int lines) {
    TextView v = new TextView(this); v.setTextColor(Color.WHITE); v.setTextSize(size); v.setMaxLines(lines); return v;
  }
  private final Runnable refresh = new Runnable() {
    @Override public void run() {
      if (destroyed) return;
      if (busy.compareAndSet(false, true)) network.execute(() -> {
        try { JSONObject status = readStatus(); main.post(() -> show(status)); }
        catch (Exception e) { main.post(() -> unavailable("连接中断")); }
        finally { busy.set(false); }
      });
      main.postDelayed(this, 250);
    }
  };
  private void unavailable(String message) {
    if (destroyed) return;
    clock.setText("计时未确认"); stage.setText(message); stage.setTextColor(Color.YELLOW);
    detail.setText("数据不可用，请查看 C2 主界面\n本窗口不控制车辆"); acknowledge.setEnabled(false);
  }
  private void show(JSONObject status) {
    if (destroyed) return;
    JSONObject r = status.optJSONObject("runtime");
    JSONObject h = r == null ? null : r.optJSONObject("hca");
    double now = SystemClock.elapsedRealtime() / 1000.0;
    if (r == null || h == null || !MonitorTiming.fresh(now, r.optDouble("boot_s", Double.NaN))) {
      unavailable("状态已过期"); return;
    }
    double elapsed = h.optDouble("elapsed_s", Double.NaN);
    int warning = MonitorTiming.warning(h.optString("version"), elapsed,
        h.optBoolean("lat_active"), h.optBoolean("takeover_required"));
    if (warning < 0) { unavailable("计时版本未确认"); return; }
    String phase = h.optString("phase");
    if (warning == 0 || elapsed + 1 < previousElapsed) {
      warned = acknowledged = false; acknowledge.setText("确认提醒（不改变控制）");
    }
    currentElapsed = elapsed; currentWarning = warning;
    clock.setText(String.format(Locale.US, "%05.1f / 240 秒", elapsed));
    String label = h.optBoolean("lat_active") ? "横向已接合" : "横向未接合";
    if ("seeking".equals(phase)) label = "原控制程序正在择机";
    else if ("standby".equals(phase)) label = "原控制程序暂停纠偏";
    else if ("aborted".equals(phase)) label = "原控制程序中止暂停";
    if (warning == 1) label = String.format(Locale.US, "请接管 · 距软件门限 %.1f 秒", Math.max(0, 240-elapsed));
    else if (warning == 2) label = "请接管 · 软件门限已到";
    stage.setText(label); stage.setTextColor(warning == 2 ? Color.RED : warning == 1 || "standby".equals(phase) ? Color.YELLOW : Color.WHITE);
    boolean audible = tone != null && audio != null && audio.getStreamVolume(AudioManager.STREAM_MUSIC) > 0;
    detail.setText("软件计时 ≠ EPS 内部计数\n" +
        (status.optBoolean("recording") ? "车辆日志录制中" : "车辆日志未录制") +
        "\n" + (audible ? "提示音可用" : "声音不可用，请看文字") + " · 拖动时间移动");
    acknowledge.setEnabled(warning > 0 && !acknowledged);
    if (!phase.equals(previousPhase)) record("phase_changed", phase, elapsed, warning);
    if (warning > 0 && !warned) {
      warned = true;
      boolean played = false;
      try { played = audible && tone.startTone(ToneGenerator.TONE_PROP_BEEP2, 250); } catch (RuntimeException ignored) {}
      record(played ? "warning_tone_requested" : "warning_text_only", phase, elapsed, warning);
    }
    previousPhase = phase; previousElapsed = elapsed;
  }
  private void record(String event, String phase, double elapsed, int warning) {
    if (destroyed) return;
    final double boot = SystemClock.elapsedRealtime()/1000.0;
    network.execute(() -> {
      try {
        JSONObject item = new JSONObject(); item.put("version", "hca-monitor-0.5");
        item.put("event", event); item.put("boot_s", boot); item.put("phase", phase);
        item.put("software_elapsed_s", elapsed); item.put("warning", warning);
        File file = new File(getFilesDir(), "hca_monitor_events.jsonl");
        try (FileOutputStream out = new FileOutputStream(file, true)) {
          out.write((item.toString()+"\n").getBytes(StandardCharsets.UTF_8));
        }
      } catch (Exception ignored) {}
    });
  }
  private JSONObject readStatus() throws Exception {
    HttpURLConnection c = (HttpURLConnection)new URL("http://127.0.0.1:8766/status").openConnection();
    c.setRequestMethod("GET"); c.setConnectTimeout(400); c.setReadTimeout(400);
    try (InputStream s = c.getInputStream(); ByteArrayOutputStream b = new ByteArrayOutputStream()) {
      byte[] buf = new byte[1024]; int n; while ((n=s.read(buf))!=-1) b.write(buf,0,n);
      return new JSONObject(new String(b.toByteArray(), StandardCharsets.UTF_8));
    } finally { c.disconnect(); }
  }
  private int dp(int n) { return Math.round(n*getResources().getDisplayMetrics().density); }
  @Override public void onDestroy() {
    destroyed = true;
    main.removeCallbacks(refresh); if(panel != null) windows.removeView(panel);
    if(tone != null) tone.release(); network.shutdownNow(); super.onDestroy();
  }
  @Override public IBinder onBind(Intent i) { return null; }
}
