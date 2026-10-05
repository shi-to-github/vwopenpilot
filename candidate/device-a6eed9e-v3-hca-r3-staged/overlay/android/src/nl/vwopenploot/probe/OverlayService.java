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
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.Locale;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicBoolean;
import org.json.JSONObject;

public final class OverlayService extends Service {
  private final Handler main = new Handler(Looper.getMainLooper());
  private final ExecutorService network = Executors.newSingleThreadExecutor();
  private final AtomicBoolean busy = new AtomicBoolean(false);
  private WindowManager windows;
  private WindowManager.LayoutParams layout;
  private LinearLayout panel;
  private TextView clock, stage, detail;
  private ToneGenerator tone;
  private AudioManager audio;
  private String playedNotice = "";
  private float dragX, dragY;
  private int originalX, originalY;

  @Override public void onCreate() {
    super.onCreate();
    windows = (WindowManager)getSystemService(WINDOW_SERVICE);
    audio = (AudioManager)getSystemService(AUDIO_SERVICE);
    try { tone = new ToneGenerator(AudioManager.STREAM_MUSIC, 25); } catch (RuntimeException ignored) {}
    panel = new LinearLayout(this);
    panel.setOrientation(LinearLayout.VERTICAL);
    panel.setPadding(dp(12), dp(10), dp(12), dp(10));
    GradientDrawable bg = new GradientDrawable();
    bg.setColor(Color.argb(235, 20, 26, 34)); bg.setCornerRadius(dp(12));
    bg.setStroke(dp(1), Color.rgb(80, 150, 180)); panel.setBackground(bg);
    clock = text(28); stage = text(20); detail = text(13);
    clock.setText("计时等待连接"); stage.setText("横向状态未确认");
    detail.setText("拖动时间区域可移动悬浮窗");
    panel.addView(clock); panel.addView(stage); panel.addView(detail);
    Button base = new Button(this); base.setText("仅横向＋日志"); base.setTextSize(12);
    base.setOnClickListener(v -> network.execute(() -> {
      try { JSONObject p = new JSONObject(); p.put("mode", "base"); request("POST", "/mode", p); }
      catch (Exception ignored) { main.post(() -> detail.setText("切换未完成，请查看连接")); }
    }));
    panel.addView(base, new LinearLayout.LayoutParams(-1, dp(38)));
    int type = Build.VERSION.SDK_INT >= 26 ? WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY : WindowManager.LayoutParams.TYPE_SYSTEM_ALERT;
    layout = new WindowManager.LayoutParams(dp(260), dp(215), type,
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
    windows.addView(panel, layout); main.post(refresh);
  }

  private TextView text(int size) {
    TextView v = new TextView(this); v.setTextColor(Color.WHITE); v.setTextSize(size);
    v.setMaxLines(size == 13 ? 4 : 2); return v;
  }

  private boolean audioReady() {
    return tone != null && audio != null && audio.getStreamVolume(AudioManager.STREAM_MUSIC) > 0;
  }

  private final Runnable refresh = new Runnable() {
    @Override public void run() {
      if (busy.compareAndSet(false, true)) network.execute(() -> {
        try {
          JSONObject p = new JSONObject(); p.put("audio_ready", audioReady());
          request("POST", "/hca_ui", p);
          JSONObject status = request("GET", "/status", null);
          main.post(() -> show(status));
        } catch (Exception e) {
          main.post(() -> { clock.setText("计时未确认"); stage.setText("连接中断");
                           stage.setTextColor(Color.YELLOW); detail.setText("当前状态不可用，请查看 C2 主界面"); });
        } finally { busy.set(false); }
      });
      main.postDelayed(this, 250);
    }
  };

  private void show(JSONObject status) {
    JSONObject r = status.optJSONObject("runtime");
    JSONObject h = r == null ? null : r.optJSONObject("hca");
    double now = SystemClock.elapsedRealtime() / 1000.0;
    if (r == null || h == null || now - r.optDouble("boot_s", 0) > 1 ||
        now < r.optDouble("boot_s", 0) || !"hca-r3-staged".equals(h.optString("version"))) {
      clock.setText("计时未确认"); stage.setText("等待当前版本状态"); detail.setText("请查看 C2 主界面"); return;
    }
    clock.setText(String.format(Locale.US, "%05.1f / 360 秒", h.optDouble("elapsed_s")));
    String phase = h.optString("phase");
    String label = "正常控制";
    if ("inactive".equals(phase)) label = "等待横向接合";
    else if ("seeking".equals(phase)) label = "择机重置";
    else if ("late_seeking".equals(phase)) label = "临近时限 · 寻找窗口";
    else if ("awaiting_notice".equals(phase)) label = "准备提示 · 仍在控制";
    else if ("countdown".equals(phase)) label = String.format(Locale.US, "%.1f 秒后暂停纠偏", h.optDouble("countdown_s"));
    else if ("standby".equals(phase)) label = String.format(Locale.US, "纠偏暂停 · 剩余 %.2f 秒", h.optDouble("standby_left_s"));
    else if ("reset_complete".equals(phase) || "natural_reset".equals(phase)) label = "复位命令完成";
    else if ("takeover_required".equals(phase)) label = "请接管方向";
    stage.setText(label);
    stage.setTextColor("takeover_required".equals(phase) ? Color.RED :
        ("standby".equals(phase) || "countdown".equals(phase)) ? Color.YELLOW : Color.WHITE);
    String body = "循环 " + h.optInt("cycle") + " · 完成 " + h.optInt("completed") + " · 中止 " + h.optInt("aborted");
    if ("takeover_required".equals(phase)) body += "\n未找到复位窗口，请接管方向";
    else if ("countdown".equals(phase) || "awaiting_notice".equals(phase)) body += "\n请保持方向，随后暂停纠偏 1.1 秒";
    else if ("standby".equals(phase)) body += "\n当前没有主动纠偏，请保持方向";
    else body += "\n180 秒择机 · 300 秒预告阶段";
    body += status.optBoolean("recording") ? "\n日志录制中" : "\n日志待记录";
    detail.setText(body);
    String notice = h.optString("notice_id");
    if ("awaiting_notice".equals(phase) && !notice.isEmpty() && !notice.equals(playedNotice)) {
      playedNotice = notice;
      boolean played = audioReady() && tone.startTone(ToneGenerator.TONE_PROP_BEEP, 180);
      network.execute(() -> {
        try {
          JSONObject p = new JSONObject(); p.put("audio_ready", audioReady());
          p.put("notice_id", notice); p.put("audio_ok", played); request("POST", "/hca_ui", p);
        } catch (Exception ignored) {}
      });
    }
  }

  private JSONObject request(String method, String path, JSONObject body) throws Exception {
    HttpURLConnection c = (HttpURLConnection)new URL("http://127.0.0.1:8766" + path).openConnection();
    c.setRequestMethod(method); c.setConnectTimeout(400); c.setReadTimeout(400);
    if (body != null) {
      c.setDoOutput(true); c.setRequestProperty("Content-Type", "application/json");
      try (OutputStream s = c.getOutputStream()) { s.write(body.toString().getBytes(StandardCharsets.UTF_8)); }
    }
    try (InputStream s = c.getInputStream(); ByteArrayOutputStream b = new ByteArrayOutputStream()) {
      byte[] buf = new byte[1024]; int n; while ((n = s.read(buf)) != -1) b.write(buf, 0, n);
      return new JSONObject(new String(b.toByteArray(), StandardCharsets.UTF_8));
    } finally { c.disconnect(); }
  }

  private int dp(int n) { return Math.round(n * getResources().getDisplayMetrics().density); }
  @Override public void onDestroy() {
    main.removeCallbacks(refresh); if (panel != null) windows.removeView(panel);
    if (tone != null) tone.release(); network.shutdownNow(); super.onDestroy();
  }
  @Override public IBinder onBind(Intent i) { return null; }
}
