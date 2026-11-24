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
                boolean test = !BuildConfig.LOGIN_EXTRA_HOST.isEmpty() && BuildConfig.LOGIN_EXTRA_HOST.equalsIgnoreCase(u.getHost());   // vide en production
                return !(("https".equals(u.getScheme()) && isMeta(u.getHost())) || (test && BuildConfig.DEBUG));   // jamais en dehors de Meta, et jamais en clair
            }

            @Override
            public void onPageFinished(WebView v, String url) {
                check();
                if (sending || finished || retries >= 2) return;
                v.evaluateJavascript("(document.body&&document.body.innerText||'').slice(0,600)", txt -> {   // page d'erreur de Messenger : on retente une fois l'adresse d'entrée
                    if (txt == null || sending || finished || retries >= 2) return;
                    for (String mk : ERROR_MARKERS) if (txt.contains(mk)) { retries++; web.loadUrl(LOGIN_URL); return; }
                });
            }
        });
        web.loadUrl(LOGIN_URL);
        ui.postDelayed(poll, 1200);
    }

    private static boolean isMeta(String h) {
        if (h == null) return false;
        h = h.toLowerCase();
        return h.equals("messenger.com") || h.endsWith(".messenger.com") || h.equals("facebook.com") || h.endsWith(".facebook.com")
                || h.endsWith(".fbcdn.net") || h.endsWith(".facebook.net") || h.equals("fb.com") || h.endsWith(".fb.com");
    }

    private final Runnable poll = new Runnable() {
        @Override
        public void run() {
            if (finished || sending) return;
            check();
            ui.postDelayed(this, 1200);
        }
    };

    /** Pages où Messenger demande encore quelque chose à la personne (connexion, consentement, vérification) : on ne capte pas la session avant leur fin. */
    private static boolean isStep(String url) {
        if (url == null) return true;
        String u = url.toLowerCase();
        for (String k : new String[]{"/login", "/privacy/consent", "/consent", "/checkpoint", "/two_step", "two_factor", "/recover", "/confirm", "/device-based", "/auth_platform", "/captcha", "/cookie/consent"})
            if (u.contains(k)) return true;
        return false;
    }

    private void check() {
        if (sending || finished) return;
        String c = CookieManager.getInstance().getCookie(BuildConfig.LOGIN_COOKIE_URL);
        if (c == null) c = "";
        boolean ok = hasCookie(c, "c_user") && hasCookie(c, "xs") && hasCookie(c, "datr");
        if (ok) {
            String url = web.getUrl();
            if (isStep(url) || web.getProgress() < 100) {   // session présente mais Messenger demande encore une étape (ex. consentement)
                cleanPolls = 0;
                hint.setText(isStep(url) && url != null && !url.toLowerCase().contains("/login") ? "Termine l'étape demandée par Messenger, puis patiente quelques secondes." : "Connexion en cours…");
                hint.setVisibility(View.VISIBLE);
                return;
            }
            if (++cleanPolls < 3) return;                    // page normale et stable (~4 s) : la session est vraiment utilisable
            if (failed) return;                              // refus du hub : on attend « Réessayer » ou une nouvelle étape
            hint.setVisibility(View.GONE);
            send(c);
            return;
        }
        // connecté côté facebook.com seulement : on ouvre messenger.com pour y établir la session (au plus toutes les 15 s)
        String fb = CookieManager.getInstance().getCookie("https://www.facebook.com");
        if (fb != null && hasCookie(fb, "c_user") && hasCookie(fb, "xs") && System.currentTimeMillis() - lastNudge > 15000) {
            lastNudge = System.currentTimeMillis();
            web.loadUrl(LOGIN_URL);
        }
    }

    private static boolean hasCookie(String all, String name) {
        for (String p : all.split(";")) {
            String t = p.trim();
            if (t.startsWith(name + "=") && t.length() > name.length() + 1) return true;
        }
        return false;
    }

    private void send(final String cookies) {
        sending = true;
        web.setVisibility(View.INVISIBLE);
        cover.setVisibility(View.VISIBLE);
        status.setText("Connexion du compte au hub…\n\nQuelques secondes.");
        new Thread(() -> {
            String err = "";
            try {
                URL u = new URL(BuildConfig.HUB_URL + "/api/accounts/import_curl");
                HttpURLConnection c = (HttpURLConnection) u.openConnection();
                c.setRequestMethod("POST");
                c.setConnectTimeout(15000);
                c.setReadTimeout(100000);
                c.setDoOutput(true);
                c.setRequestProperty("Content-Type", "application/json");
                c.setRequestProperty("X-Hub", "1");
                String hubCookie = CookieManager.getInstance().getCookie(BuildConfig.HUB_URL);
                if (hubCookie != null) c.setRequestProperty("Cookie", hubCookie);
                byte[] body = new JSONObject().put("curl", cookies).toString().getBytes(StandardCharsets.UTF_8);
                try (OutputStream o = c.getOutputStream()) { o.write(body); }
                int code = c.getResponseCode();
                java.io.InputStream in = code >= 400 ? c.getErrorStream() : c.getInputStream();
                java.io.ByteArrayOutputStream bo = new java.io.ByteArrayOutputStream();
                if (in != null) { byte[] buf = new byte[4096]; int n; while ((n = in.read(buf)) > 0 && bo.size() < 20000) bo.write(buf, 0, n); }
                JSONObject r;
                try { r = new JSONObject(bo.toString("UTF-8")); } catch (Exception e) { r = new JSONObject(); }
                if (code == 401) err = "Session du hub expirée : rouvre l'application.";
                else if (!r.optBoolean("ok", false)) err = r.optString("error", "Le hub a refusé la connexion (code " + code + ").");
            } catch (Exception e) {
                err = "Hub injoignable. Vérifie ta connexion.";
            }
            final String e2 = err;
            ui.post(() -> {
                if (e2.isEmpty()) { end(RESULT_OK, ""); return; }
                // refus : on NE ferme PAS. Messenger a sans doute une étape à valider (consentement) : on rouvre la page pour la terminer
                sending = false; failed = true; cleanPolls = 0;
                cover.setVisibility(View.GONE);
                web.setVisibility(View.VISIBLE);
                hint.setText(e2 + " Termine les étapes affichées par Messenger, puis touche « Réessayer ».");
                hint.setVisibility(View.VISIBLE);
                retry.setVisibility(View.VISIBLE);
                web.loadUrl(LOGIN_URL);
                ui.postDelayed(poll, 1200);
            });
        }).start();
    }

    /** Efface toute trace Meta du téléphone (cookies + stockage) : le compte reste uniquement sur le serveur. */
    private void wipeMeta() {
        CookieManager cm = CookieManager.getInstance();
        for (String site : new String[]{BuildConfig.LOGIN_COOKIE_URL, "https://www.messenger.com", "https://messenger.com", "https://www.facebook.com", "https://facebook.com", "https://m.facebook.com"}) {
            String c = cm.getCookie(site);
            if (c == null) continue;
            String host = Uri.parse(site).getHost();
            String dom = host.startsWith("www.") ? host.substring(3) : (host.startsWith("m.") ? host.substring(1) : "." + host);
            for (String p : c.split(";")) {
                String name = p.trim().split("=", 2)[0];
                if (name.isEmpty()) continue;
                for (String d : new String[]{dom, host})
                    cm.setCookie(site, name + "=; Max-Age=0; Domain=" + d + "; Path=/");
                cm.setCookie(site, name + "=; Max-Age=0; Path=/");
            }
        }
        cm.flush();
        try {
            for (String o : new String[]{"https://www.messenger.com", "https://www.facebook.com", "https://m.facebook.com"}) WebStorage.getInstance().deleteOrigin(o);
        } catch (Exception ignored) { }
    }

    private void end(int code, String msg) {
        if (finished) return;
        finished = true;
        ui.removeCallbacks(poll);
        wipeMeta();
        try { web.loadUrl("about:blank"); web.clearHistory(); web.clearCache(true); } catch (Exception ignored) { }
        setResult(code, new Intent().putExtra("msg", msg));
        finish();
    }

    @Override
    public void onBackPressed() {
        if (!sending && web.canGoBack()) web.goBack(); else end(RESULT_CANCELED, "");
    }

    @Override
    protected void onDestroy() {
        ui.removeCallbacks(poll);
        if (!finished) wipeMeta();
        web.destroy();
        super.onDestroy();
    }
}
