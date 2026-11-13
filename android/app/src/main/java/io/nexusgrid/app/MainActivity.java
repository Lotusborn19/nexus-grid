package io.nexusgrid.app;

import android.app.Activity;
import android.content.ActivityNotFoundException;
import android.content.Intent;
import android.graphics.Color;
import android.net.Uri;
import android.os.Bundle;
import android.webkit.JavascriptInterface;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;

/**
 * NEXUS // GRID for Android.
 * A full-screen WebView around assets/index.html (the same page that runs on the web).
 * Links to other sites open in the phone's browser. Nothing here collects or sends data.
 */
public class MainActivity extends Activity {

    private static final String HOME = "file:///android_asset/index.html";
    private WebView web;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        getWindow().setStatusBarColor(Color.parseColor("#020804"));
        getWindow().setNavigationBarColor(Color.parseColor("#020804"));

        web = new WebView(this);
        web.setBackgroundColor(Color.parseColor("#020804"));
        setContentView(web);

        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);          // localStorage: profile, XP, notes
        s.setDatabaseEnabled(true);
        s.setAllowFileAccess(true);            // needed to load the bundled page
        s.setMediaPlaybackRequiresUserGesture(false);
        s.setMixedContentMode(WebSettings.MIXED_CONTENT_ALWAYS_ALLOW);   // http bridge / Ollama / robot on your own device or LAN
        s.setSupportMultipleWindows(false);

        web.addJavascriptInterface(new NativeBridge(), "NexusNative");
        web.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                Uri uri = request.getUrl();
                if ("file".equals(uri.getScheme())) return false;      // stay inside the app
                try {
                    startActivity(new Intent(Intent.ACTION_VIEW, uri)); // everything else: the real browser
                } catch (ActivityNotFoundException ignored) { }
                return true;
            }
        });

        if (savedInstanceState != null) web.restoreState(savedInstanceState);
        else web.loadUrl(HOME);
    }

    @Override
    protected void onSaveInstanceState(Bundle outState) {
        super.onSaveInstanceState(outState);
        web.saveState(outState);
    }

    @Override
    public void onBackPressed() {
        // The page is a single screen with its own windows, so Back sends the app to the background
        // instead of closing it and losing what is open.
        moveTaskToBack(true);
    }

    @Override
    protected void onDestroy() {
        if (web != null) web.destroy();
        super.onDestroy();
    }

    /** Lets the page know it is running inside the Android app (see isInstalled() in the page). */
    private static class NativeBridge {
        @JavascriptInterface
        public String version() { return "7.0"; }
    }
}
