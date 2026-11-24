package site.fabrich.relais;

import android.animation.ValueAnimator;
import android.app.Activity;
import android.app.DownloadManager;
import android.content.Intent;
import android.graphics.Bitmap;
import android.graphics.Color;
import android.net.ConnectivityManager;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Environment;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.view.WindowInsets;
import android.view.WindowInsetsAnimation;
import android.view.animation.DecelerateInterpolator;
import android.webkit.CookieManager;
import android.webkit.JavascriptInterface;
import android.webkit.URLUtil;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.window.OnBackInvokedDispatcher;
import android.widget.FrameLayout;
import android.widget.Toast;

import java.util.List;

/**
 * Coque native du hub Relais : une WebView plein écran qui n'ouvre QUE l'adresse du hub.
 * Soignée pour la fluidité : écran de lancement de la marque, apparition en fondu (aucun flash blanc), fine barre de
 * progression, clavier qui glisse avec l'interface, geste « retour » natif, barres système assorties au thème.
 */
public class MainActivity extends Activity {
    private WebView web;
    private FrameLayout root;
    private View bar;
    private String hubHost;
    private boolean shown = false;

    @Override
    protected void onCreate(Bundle b) {
        super.onCreate(b);
        hubHost = Uri.parse(BuildConfig.HUB_URL).getHost();
        final int bg = Look.bg(this);
        final int accent = Look.accent(this);
        Look.bars(this, bg, Look.dark(this));

        root = new FrameLayout(this);
        root.setBackgroundColor(bg);
        web = new WebView(this);
        web.setBackgroundColor(bg);
        web.setOverScrollMode(View.OVER_SCROLL_NEVER);
        web.setAlpha(0f);                       // apparaît en fondu quand la page est prête
        web.setLayerType(View.LAYER_TYPE_HARDWARE, null);
        root.addView(web, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));

        float d = getResources().getDisplayMetrics().density;
        bar = new View(this);                    // fine barre de progression de la couleur de la marque
        bar.setBackgroundColor(accent);
        bar.setPivotX(0f);
        bar.setScaleX(0f);
        bar.setAlpha(0f);
        root.addView(bar, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, Math.round(2.5f * d), Gravity.TOP));
        setContentView(root);

        // insets : barres système + clavier, avec animation synchronisée du clavier (pas de saut)
        root.setOnApplyWindowInsetsListener((v, insets) -> {
            applyInsets(v, insets);
            return insets;
        });
        if (Build.VERSION.SDK_INT >= 30) {
            root.setWindowInsetsAnimationCallback(new WindowInsetsAnimation.Callback(WindowInsetsAnimation.Callback.DISPATCH_MODE_CONTINUE_ON_SUBTREE) {
                @Override
                public WindowInsets onProgress(WindowInsets insets, List<WindowInsetsAnimation> running) {
                    applyInsets(root, insets);
                    return insets;
                }
            });
        }

        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setAllowFileAccess(false);
        s.setAllowContentAccess(false);
        s.setAllowFileAccessFromFileURLs(false);
        s.setAllowUniversalAccessFromFileURLs(false);
        s.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        s.setSafeBrowsingEnabled(true);
        s.setSupportMultipleWindows(false);
        s.setMediaPlaybackRequiresUserGesture(true);
        s.setUserAgentString(s.getUserAgentString() + " RelaisApp/2.0");
        s.setTextZoom(100);

        CookieManager cm = CookieManager.getInstance();
        cm.setAcceptCookie(true);
        cm.setAcceptThirdPartyCookies(web, false);
        if (BuildConfig.DEBUG) WebView.setWebContentsDebuggingEnabled(true);   // tests automatiques uniquement (jamais dans la version publiée)

        web.setWebChromeClient(new WebChromeClient() {
            @Override
            public void onProgressChanged(WebView v, int p) { progress(p); }
        });
        web.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView v, WebResourceRequest r) {
                Uri u = r.getUrl();
                if (("https".equals(u.getScheme()) || (BuildConfig.DEBUG && "http".equals(u.getScheme()))) && hubHost.equalsIgnoreCase(u.getHost())) return false;
                try {   // tout le reste (liens partagés, autres sites) : navigateur du téléphone, jamais dans la WebView
                    if ("http".equals(u.getScheme()) || "https".equals(u.getScheme())) startActivity(new Intent(Intent.ACTION_VIEW, u));
                } catch (Exception ignored) { }
                return true;
            }

            @Override
            public void onPageStarted(WebView v, String url, Bitmap f) { progress(8); }

            @Override
            public void onPageCommitVisible(WebView v, String url) { reveal(); }

            @Override
            public void onPageFinished(WebView v, String url) { progress(100); reveal(); }

            @Override
