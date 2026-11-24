package site.fabrich.relais;

import android.app.Activity;
import android.content.Intent;
import android.graphics.Color;
import android.graphics.Typeface;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.view.WindowInsets;
import android.webkit.CookieManager;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebStorage;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.TextView;

import org.json.JSONObject;

import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;

/**
 * Connexion d'un compte Messenger depuis le téléphone : la VRAIE page officielle s'ouvre ici, l'utilisateur saisit
 * lui-même ses identifiants (jamais lus par l'application). Quand la session est établie, ses cookies sont envoyés
 * au hub (sous la session de l'utilisateur), puis effacés du téléphone : le compte ne vit plus que sur le serveur.
 */
public class MessengerLoginActivity extends Activity {
    private static final String LOGIN_URL = BuildConfig.LOGIN_URL;
    private static final String[] ERROR_MARKERS = {"n’est pas disponible", "n'est pas disponible", "isn’t available", "isn't available", "Return to messenger.com"};
    private final Handler ui = new Handler(Looper.getMainLooper());
    private WebView web;
    private TextView status;
    private View cover;
    private boolean sending = false, finished = false;
    private int retries = 0;
    private long lastNudge = 0;
    private int cleanPolls = 0;        // nombre de vérifications consécutives où la page est « normale » (pas une étape de Messenger)
    private boolean failed = false;    // le hub a refusé la session : on attend que la personne termine l'étape demandée
    private TextView retry;
    private TextView hint;             // consigne affichée sous l'en-tête

    @Override
    protected void onCreate(Bundle b) {
        super.onCreate(b);
        final int bg = Look.bg(this);
        final int accent = Look.accent(this);
        final boolean dark = Look.dark(this);
        Look.bars(this, bg, dark);
        final int ink = dark ? Color.parseColor("#F3EBE4") : Color.parseColor("#1F1814");
        float d = getResources().getDisplayMetrics().density;

        LinearLayout col = new LinearLayout(this);
        col.setOrientation(LinearLayout.VERTICAL);
        col.setBackgroundColor(bg);

        LinearLayout head = new LinearLayout(this);
        head.setOrientation(LinearLayout.HORIZONTAL);
        head.setGravity(Gravity.CENTER_VERTICAL);
        head.setPadding(Math.round(16 * d), Math.round(6 * d), Math.round(8 * d), Math.round(6 * d));
        TextView title = new TextView(this);
        title.setText("Connexion à Messenger");
        title.setTextColor(ink);
        title.setTextSize(17);
        title.setTypeface(Typeface.DEFAULT_BOLD);
        head.addView(title, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f));
        retry = new TextView(this);
        retry.setText("Réessayer");
        retry.setTextColor(accent);
        retry.setTextSize(15);
        retry.setTypeface(Typeface.DEFAULT_BOLD);
        retry.setPadding(Math.round(12 * d), Math.round(12 * d), Math.round(12 * d), Math.round(12 * d));
        retry.setVisibility(View.GONE);
        retry.setOnClickListener(v -> {
            if (sending) return;
            String c = CookieManager.getInstance().getCookie(BuildConfig.LOGIN_COOKIE_URL);
            if (c != null && hasCookie(c, "c_user") && hasCookie(c, "xs") && hasCookie(c, "datr") && !isStep(web.getUrl())) {
                failed = false; hint.setVisibility(View.GONE); retry.setVisibility(View.GONE); send(c);
            } else {
                hint.setText("Messenger n'est pas encore prêt : termine l'étape affichée.");
            }
        });
        head.addView(retry);
        TextView refresh = new TextView(this);
        refresh.setText("Actualiser");
        refresh.setTextColor(ink);
        refresh.setTextSize(15);
        refresh.setPadding(Math.round(12 * d), Math.round(12 * d), Math.round(12 * d), Math.round(12 * d));
        refresh.setOnClickListener(v -> { if (!sending) web.loadUrl(LOGIN_URL); });
        head.addView(refresh);
        TextView close = new TextView(this);
        close.setText("Annuler");
        close.setTextColor(accent);
        close.setTextSize(15);
        close.setTypeface(Typeface.DEFAULT_BOLD);
        close.setPadding(Math.round(14 * d), Math.round(12 * d), Math.round(14 * d), Math.round(12 * d));
        close.setOnClickListener(v -> end(RESULT_CANCELED, ""));
        head.addView(close);
        col.addView(head);
        hint = new TextView(this);
        hint.setTextColor(accent);
        hint.setTextSize(13);
        hint.setPadding(Math.round(16 * d), 0, Math.round(16 * d), Math.round(8 * d));
        hint.setVisibility(View.GONE);
        col.addView(hint);

        FrameLayout box = new FrameLayout(this);
        web = new WebView(this);
        web.setBackgroundColor(bg);
        box.addView(web, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        cover = new FrameLayout(this);
        cover.setBackgroundColor(bg);
        cover.setVisibility(View.GONE);
        status = new TextView(this);
        status.setTextColor(ink);
        status.setTextSize(16);
        status.setGravity(Gravity.CENTER);
        status.setPadding(Math.round(32 * d), 0, Math.round(32 * d), 0);
        ((FrameLayout) cover).addView(status, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        box.addView(cover, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        col.addView(box, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f));
        setContentView(col);
        col.setOnApplyWindowInsetsListener((v, insets) -> {
            if (Build.VERSION.SDK_INT >= 30) {
                android.graphics.Insets bars = insets.getInsets(WindowInsets.Type.systemBars());
                android.graphics.Insets ime = insets.getInsets(WindowInsets.Type.ime());
                v.setPadding(bars.left, bars.top, bars.right, Math.max(bars.bottom, ime.bottom));
            } else {
                v.setPadding(insets.getSystemWindowInsetLeft(), insets.getSystemWindowInsetTop(), insets.getSystemWindowInsetRight(), insets.getSystemWindowInsetBottom());
            }
            return insets;
        });

        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setAllowFileAccess(false);
        s.setAllowContentAccess(false);
        s.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        s.setSafeBrowsingEnabled(true);
        s.setSupportMultipleWindows(false);
        // « Version bureau » (comme l'option du navigateur) avec la VRAIE version du moteur de ce téléphone : messenger.com sur mobile ne propose plus que l'installation de l'appli
        java.util.regex.Matcher m = java.util.regex.Pattern.compile("Chrome/([0-9.]+)").matcher(WebSettings.getDefaultUserAgent(this));
        s.setUserAgentString("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/" + (m.find() ? m.group(1) : "126.0.0.0") + " Safari/537.36");
        s.setUseWideViewPort(false);          // mise en page à la largeur du téléphone (sinon la page de bureau est réduite et illisible)
        s.setLoadWithOverviewMode(false);
        s.setSupportZoom(true);
        s.setBuiltInZoomControls(true);
        s.setDisplayZoomControls(false);

        CookieManager cm = CookieManager.getInstance();
        cm.setAcceptCookie(true);
        cm.setAcceptThirdPartyCookies(web, true);   // la page de connexion de Facebook en a besoin
        wipeMeta();                                  // départ propre : on ne reprend jamais une ancienne session du téléphone

        web.setWebChromeClient(new WebChromeClient());
        web.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView v, WebResourceRequest r) {
                Uri u = r.getUrl();
