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
            public void onReceivedError(WebView v, WebResourceRequest r, WebResourceError e) {
                if (r.isForMainFrame()) { showOffline(); reveal(); }
            }
        });

        web.setDownloadListener((url, ua, cd, mime, len) -> {
            Uri u = Uri.parse(url);
            if (!"https".equals(u.getScheme()) || !hubHost.equalsIgnoreCase(u.getHost())) return;   // téléchargements du hub seulement
            try {
                DownloadManager.Request req = new DownloadManager.Request(u);
                String name = URLUtil.guessFileName(url, cd, mime);
                req.addRequestHeader("Cookie", CookieManager.getInstance().getCookie(url));
                req.setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED);
                req.setDestinationInExternalPublicDir(Environment.DIRECTORY_DOWNLOADS, name);
                ((DownloadManager) getSystemService(DOWNLOAD_SERVICE)).enqueue(req);
                Toast.makeText(this, "Téléchargement : " + name, Toast.LENGTH_SHORT).show();
            } catch (Exception ex) {
                Toast.makeText(this, "Téléchargement impossible", Toast.LENGTH_SHORT).show();
            }
        });

        // pont minimal vers la page du hub : une seule action, aucun retour de données (les cookies Messenger ne passent jamais par le JavaScript)
        web.addJavascriptInterface(new Object() {
            /** Le hub indique son apparence (fond, mode sombre, couleur d'accent) : barres système et fond de l'appli s'y accordent. */
            @JavascriptInterface
            public void setBars(String bgHex, boolean dark, String accentHex) {
                final int bgc = Look.parse(bgHex, Look.DEFAULT_BG), ac = Look.parse(accentHex, Look.DEFAULT_ACCENT);
                Look.save(MainActivity.this, bgc, dark, ac);
                runOnUiThread(() -> {
                    Look.bars(MainActivity.this, bgc, dark);
                    root.setBackgroundColor(bgc);
                    web.setBackgroundColor(bgc);
                    bar.setBackgroundColor(ac);
                });
            }

            @JavascriptInterface
            public void connectMessenger() {
                runOnUiThread(() -> {
                    Uri cur = Uri.parse(String.valueOf(web.getUrl()));
                    if (!("https".equals(cur.getScheme()) || BuildConfig.DEBUG) || !hubHost.equalsIgnoreCase(cur.getHost())) return;   // seulement depuis la page du hub
                    startActivityForResult(new Intent(MainActivity.this, MessengerLoginActivity.class), 41);
                });
            }
        }, "RelaisApp");

        if (Build.VERSION.SDK_INT >= 33) {   // geste « retour » prédictif
            getOnBackInvokedDispatcher().registerOnBackInvokedCallback(OnBackInvokedDispatcher.PRIORITY_DEFAULT, this::handleBack);
        }

        if (b != null) web.restoreState(b); else web.loadUrl(BuildConfig.HUB_URL);
    }

    private void applyInsets(View v, WindowInsets insets) {
        if (Build.VERSION.SDK_INT >= 30) {
            android.graphics.Insets bars = insets.getInsets(WindowInsets.Type.systemBars());
            android.graphics.Insets ime = insets.getInsets(WindowInsets.Type.ime());
            v.setPadding(bars.left, bars.top, bars.right, Math.max(bars.bottom, ime.bottom));
        } else {
            v.setPadding(insets.getSystemWindowInsetLeft(), insets.getSystemWindowInsetTop(), insets.getSystemWindowInsetRight(), insets.getSystemWindowInsetBottom());
        }
    }

    private void progress(int p) {
        float to = Math.max(0.06f, p / 100f);
        bar.animate().cancel();
        if (p >= 100) {
            bar.animate().scaleX(1f).setDuration(160).withEndAction(() -> bar.animate().alpha(0f).setDuration(220).withEndAction(() -> bar.setScaleX(0f)).start()).start();
        } else {
            bar.setAlpha(1f);
            bar.animate().scaleX(to).setDuration(240).setInterpolator(new DecelerateInterpolator()).start();
        }
    }

    private void reveal() {
        if (shown) return;
        shown = true;
        web.animate().alpha(1f).setDuration(220).start();
    }

    private boolean online() {
        ConnectivityManager c = (ConnectivityManager) getSystemService(CONNECTIVITY_SERVICE);
        return c != null && c.getActiveNetwork() != null;
    }

    private void showOffline() {
        String html = "<html><head><meta name='viewport' content='width=device-width,initial-scale=1'><style>"
                + "body{font-family:-apple-system,Roboto,sans-serif;background:#08080A;color:#F5F5F6;display:grid;place-items:center;height:100vh;margin:0;text-align:center}"
                + ""
                + "h2{margin:0 0 6px;font-size:22px;letter-spacing:-.02em}p{margin:0;opacity:.7}"
                + "button{margin-top:22px;padding:14px 32px;border:0;border-radius:99px;background:#F26A1B;color:#fff;font-size:16px;font-weight:600}"
                + "</style></head><body><div><h2>" + (online() ? "Hub injoignable" : "Pas de connexion") + "</h2>"
                + "<p>Impossible de joindre Relais.</p><button onclick=\"location.href='" + BuildConfig.HUB_URL + "'\">Réessayer</button></div></body></html>";
        shown = false;
        web.loadDataWithBaseURL(null, html, "text/html", "utf-8", null);
    }

    private void handleBack() {
        // ferme d'abord une conversation ouverte (mode mobile du hub), puis revient en arrière, puis quitte
        web.evaluateJavascript("(function(){var b=document.querySelector('.mobback');if(document.body.classList.contains('open')&&b){b.click();return 'x'}return ''})()", v -> {
            if (v != null && v.contains("x")) return;
            if (web.canGoBack()) web.goBack(); else finish();
        });
    }

    @Override
    public void onBackPressed() { handleBack(); }

    @Override
    protected void onActivityResult(int req, int res, Intent data) {
        super.onActivityResult(req, res, data);
        if (req != 41) return;
        String msg = data != null ? data.getStringExtra("msg") : "";
        if (res == RESULT_OK) Toast.makeText(this, "Compte Messenger connecté ✓", Toast.LENGTH_LONG).show();
        else if (msg != null && !msg.isEmpty()) Toast.makeText(this, msg, Toast.LENGTH_LONG).show();
        web.reload();
    }

    @Override
    protected void onSaveInstanceState(Bundle o) { super.onSaveInstanceState(o); web.saveState(o); }

    @Override
    protected void onPause() { super.onPause(); CookieManager.getInstance().flush(); web.onPause(); }

    @Override
    protected void onResume() { super.onResume(); web.onResume(); }

    @Override
    protected void onDestroy() { web.destroy(); super.onDestroy(); }
}
