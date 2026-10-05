package nl.vwopenploot.probe;

import android.app.Activity;
import android.content.Intent;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.provider.Settings;
import android.widget.Toast;

public final class OverlayActivity extends Activity {
  private static final int OVERLAY_PERMISSION_REQUEST = 1001;

  @Override public void onCreate(Bundle state) {
    super.onCreate(state);
    if (Build.VERSION.SDK_INT >= 23 && !Settings.canDrawOverlays(this)) {
      Intent request = new Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION,
          Uri.parse("package:" + getPackageName()));
      startActivityForResult(request, OVERLAY_PERMISSION_REQUEST);
    } else {
      launchOverlay();
    }
  }

  @Override protected void onActivityResult(int requestCode, int resultCode, Intent data) {
    super.onActivityResult(requestCode, resultCode, data);
    if (requestCode == OVERLAY_PERMISSION_REQUEST && Settings.canDrawOverlays(this)) {
      launchOverlay();
    } else {
      Toast.makeText(this, "请允许悬浮窗权限", Toast.LENGTH_LONG).show();
      finish();
    }
  }

  private void launchOverlay() {
    startService(new Intent(this, OverlayService.class));
    finish();
  }
}
