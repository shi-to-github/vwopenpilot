package nl.vwopenploot.probe;

import android.app.Service;
import android.content.Intent;
import android.graphics.Color;
import android.graphics.PixelFormat;
import android.graphics.drawable.GradientDrawable;
import android.os.Build;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.view.Gravity;
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
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicBoolean;
import org.json.JSONObject;

public final class OverlayService extends Service {
  private static final String ENDPOINT = "http://127.0.0.1:8766";
  private final Handler main = new Handler(Looper.getMainLooper());
  private final ExecutorService network = Executors.newSingleThreadExecutor();
  private final AtomicBoolean busy = new AtomicBoolean(false);
  private WindowManager windows;
  private LinearLayout panel;
  private TextView stateLabel;
  private Button toggle;
  private volatile boolean enabled = false;
  private LinearLayout tests;

  @Override public void onCreate() {
    super.onCreate();
    windows = (WindowManager) getSystemService(WINDOW_SERVICE);
    panel = new LinearLayout(this);
    panel.setOrientation(LinearLayout.VERTICAL);
    panel.setPadding(dp(6), dp(5), dp(6), dp(5));
    GradientDrawable background = new GradientDrawable();
    background.setColor(Color.argb(228, 22, 26, 32));
    background.setCornerRadius(dp(12));
    background.setStroke(dp(1), Color.WHITE);
    panel.setBackground(background);

    stateLabel = new TextView(this);
    stateLabel.setTextColor(Color.WHITE);
    stateLabel.setTextSize(12);
    stateLabel.setText("测试服务未连接");
    panel.addView(stateLabel);

    toggle = new Button(this);
    toggle.setText("检查连接");
    toggle.setTextSize(12);
    toggle.setOnClickListener(view -> postMode(enabled ? "base" : "auto"));
    panel.addView(toggle);
    tests = new LinearLayout(this);
    String[] modes = {"probe_down", "probe_up", "probe_recall"};
    String[] labels = {"试−10", "试+10", "试+1"};
    for (int i = 0; i < modes.length; i++) {
      final String mode = modes[i];
      Button button = new Button(this);
      button.setText(labels[i]);
      button.setTextSize(10);
      button.setPadding(0, 0, 0, 0);
      button.setOnClickListener(view -> postMode(mode));
      tests.addView(button, new LinearLayout.LayoutParams(0, dp(38), 1));
    }
    panel.addView(tests);

    int type = Build.VERSION.SDK_INT >= 26 ? WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY
        : WindowManager.LayoutParams.TYPE_SYSTEM_ALERT;
    WindowManager.LayoutParams layout = new WindowManager.LayoutParams(
        dp(180), WindowManager.LayoutParams.WRAP_CONTENT, type,
        WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE |
            WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL,
        PixelFormat.TRANSLUCENT);
    layout.gravity = Gravity.RIGHT | Gravity.BOTTOM;
    layout.x = dp(20);
    layout.y = dp(115);
    windows.addView(panel, layout);
    main.post(refresh);
  }

  private final Runnable refresh = new Runnable() {
    @Override public void run() {
      if (busy.compareAndSet(false, true)) {
        network.execute(() -> {
          try {
            JSONObject status = request("GET", "/status", null);
            main.post(() -> show(status));
          } catch (Exception error) {
            main.post(() -> {
              stateLabel.setText("测试服务未连接");
              toggle.setText("重试");
              toggle.setEnabled(false);
            });
          } finally {
            busy.set(false);
          }
        });
      }
      main.postDelayed(this, 2000);
    }
  };

  private void postMode(String requested) {
    if (!busy.compareAndSet(false, true)) return;
    toggle.setEnabled(false);
    network.execute(() -> {
      try {
        JSONObject body = new JSONObject();
        body.put("mode", requested);
        JSONObject result = request("POST", "/mode", body);
        main.post(() -> show(result));
      } catch (Exception error) {
        main.post(() -> stateLabel.setText("切换失败，请检查服务"));
      } finally {
        busy.set(false);
        main.post(() -> toggle.setEnabled(true));
      }
    });
  }

  private void show(JSONObject status) {
    String mode = status.optString("mode", "base");
    enabled = !"base".equals(mode);
    JSONObject runtime = status.optJSONObject("runtime");
    String label = status.optString("label", "横向＋日志");
    if (runtime != null) {
      JSONObject hca = runtime.optJSONObject("hca");
      JSONObject cruise = runtime.optJSONObject("cruise");
      if (hca != null) {
        String phase = hca.optString("phase");
        if ("standby".equals(phase)) label += "\n横向暂停，剩余 " + hca.optDouble("standby_left_s") + "s";
        else if ("takeover_required".equals(phase)) label += "\n横向需要接管";
        else if ("seeking".equals(phase)) label += "\n横向寻找直行窗口";
        else label += "\n寻找窗口倒计时 " + hca.optInt("seek_in_s") + "s";
      }
      if (cruise != null) {
        label += "\n定速 " + runtime.optInt("motor_target_kph") + " / 上限 " + cruise.optInt("ceiling_kph");
        label += "\n" + describe(cruise.optString("reason"));
        if (cruise.optBoolean("manual_control_required")) label += "\n请人工控速";
      }
    }
    label += "\n" + status.optString("note");
    label += status.optBoolean("recording") ? " · 录制中" : " · 待记录";
    stateLabel.setText(label);
    toggle.setText(enabled ? "关闭调速／测试" : "开启前车调速");
    toggle.setEnabled(true);
    tests.setVisibility(enabled ? android.view.View.GONE : android.view.View.VISIBLE);
  }

  private String describe(String reason) {
    if (reason.startsWith("sending_")) return "发送一次定速短拨";
    if ("waiting_for_ecu_target".equals(reason)) return "等待定速目标确认";
    if ("target_changed_releasing".equals(reason)) return "目标变化，松开按键";
    if ("ecu_target_acknowledged".equals(reason) || "test_acknowledged".equals(reason)) return "车辆已确认目标变化";
    if ("ecu_ack_timeout".equals(reason)) return "目标未变化，调速停止";
    if ("waiting_for_stable_engagement".equals(reason)) return "等待稳定定速 5 秒";
    if ("confirming_lead".equals(reason)) return "确认前车";
    if ("confirming_clear_road".equals(reason)) return "确认前车离开";
    if (reason.startsWith("lead_data_") || "lead_uncertain".equals(reason)) return "前车信息不足，保持目标";
    if (reason.startsWith("driver_")) return "驾驶员操作或等待条件";
    if ("feedback_unavailable".equals(reason)) return "定速回读不可用";
    if ("observing".equals(reason)) return "观察前车与定速目标";
    if ("inactive".equals(reason)) return "等待定速与 C2 接合";
    if ("lateral_and_logging".equals(reason)) return "调速关闭";
    if ("test_target_guard".equals(reason)) return "目标速度不满足测试条件";
    return "调速停止，请查看日志";
  }

  private JSONObject request(String method, String path, JSONObject body) throws Exception {
    HttpURLConnection connection = (HttpURLConnection) new URL(ENDPOINT + path).openConnection();
    connection.setRequestMethod(method);
    connection.setConnectTimeout(1000);
    connection.setReadTimeout(1000);
    if (body != null) {
      connection.setDoOutput(true);
      connection.setRequestProperty("Content-Type", "application/json");
      byte[] bytes = body.toString().getBytes(StandardCharsets.UTF_8);
      try (OutputStream stream = connection.getOutputStream()) { stream.write(bytes); }
    }
    try (InputStream stream = connection.getInputStream();
         ByteArrayOutputStream buffer = new ByteArrayOutputStream()) {
      byte[] bytes = new byte[1024];
      int count;
      while ((count = stream.read(bytes)) != -1) buffer.write(bytes, 0, count);
      return new JSONObject(new String(buffer.toByteArray(), StandardCharsets.UTF_8));
    } finally {
      connection.disconnect();
    }
  }

  private int dp(int value) {
    return Math.round(value * getResources().getDisplayMetrics().density);
  }

  @Override public void onDestroy() {
    main.removeCallbacks(refresh);
    if (panel != null) windows.removeView(panel);
    network.shutdownNow();
    super.onDestroy();
  }

  @Override public IBinder onBind(Intent intent) { return null; }
}
