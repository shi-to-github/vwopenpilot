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
  private static final String ENDPOINT = "http://127.0.0.1:8765";
  private final Handler main = new Handler(Looper.getMainLooper());
  private final ExecutorService network = Executors.newSingleThreadExecutor();
  private final AtomicBoolean busy = new AtomicBoolean(false);
  private WindowManager windows;
  private LinearLayout panel;
  private TextView stateLabel;
  private Button toggle;
  private volatile boolean enabled = false;

  @Override public void onCreate() {
    super.onCreate();
    windows = (WindowManager) getSystemService(WINDOW_SERVICE);
    panel = new LinearLayout(this);
    panel.setOrientation(LinearLayout.VERTICAL);
    panel.setPadding(dp(12), dp(9), dp(12), dp(9));
    GradientDrawable background = new GradientDrawable();
    background.setColor(Color.argb(228, 22, 26, 32));
    background.setCornerRadius(dp(12));
    background.setStroke(dp(1), Color.WHITE);
    panel.setBackground(background);

    stateLabel = new TextView(this);
    stateLabel.setTextColor(Color.WHITE);
    stateLabel.setTextSize(17);
    stateLabel.setText("测试服务未连接");
    panel.addView(stateLabel);

    toggle = new Button(this);
    toggle.setText("检查连接");
    toggle.setOnClickListener(view -> postMode(!enabled));
    panel.addView(toggle);

    int type = Build.VERSION.SDK_INT >= 26 ? WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY
        : WindowManager.LayoutParams.TYPE_SYSTEM_ALERT;
    WindowManager.LayoutParams layout = new WindowManager.LayoutParams(
        dp(210), WindowManager.LayoutParams.WRAP_CONTENT, type,
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

  private void postMode(boolean requested) {
    if (!busy.compareAndSet(false, true)) return;
    toggle.setEnabled(false);
    network.execute(() -> {
      try {
        JSONObject body = new JSONObject();
        body.put("enabled", requested);
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
    enabled = status.optBoolean("enabled", false);
    stateLabel.setText(status.optString("label", enabled ? "测试待触发" : "六分钟修复版"));
    toggle.setText(enabled ? "关闭测试模式" : "开启测试模式");
    toggle.setEnabled(true);
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
