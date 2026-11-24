package site.fabrich.relais;

import android.app.Activity;
import android.content.Context;
import android.content.SharedPreferences;
import android.graphics.Color;
import android.os.Build;
import android.view.View;
import android.view.Window;
import android.view.WindowInsetsController;

/** Apparence choisie dans le hub (thème sombre/clair + couleur) : mémorisée pour que l'appli démarre déjà à la bonne couleur (pas d'éclair blanc) et pour accorder les barres système. */
final class Look {
    private Look() { }

    static final int DEFAULT_BG = Color.parseColor("#08080A");
    static final int DEFAULT_ACCENT = Color.parseColor("#F26A1B");

    private static SharedPreferences p(Context c) { return c.getSharedPreferences("look", Context.MODE_PRIVATE); }

    static int bg(Context c) { return p(c).getInt("bg", DEFAULT_BG); }
    static int accent(Context c) { return p(c).getInt("accent", DEFAULT_ACCENT); }
    static boolean dark(Context c) { return p(c).getBoolean("dark", true); }

    static int parse(String s, int fallback) {
        try { return Color.parseColor(s == null ? "" : s.trim()); } catch (Exception e) { return fallback; }
    }

    static void save(Context c, int bg, boolean dark, int accent) {
        p(c).edit().putInt("bg", bg).putBoolean("dark", dark).putInt("accent", accent).apply();
    }

    /** Barres d'état et de navigation à la couleur du fond, icônes claires sur fond sombre et inversement.
     *  Purement cosmétique : toute erreur est ignorée (l'appli ne doit jamais planter pour une couleur). */
    @SuppressWarnings("deprecation")
    static void bars(Activity a, int bg, boolean dark) {
        try {
            Window w = a.getWindow();
            View d = w.getDecorView();   // installe la fenêtre : sans cela getInsetsController() est nul avant setContentView (plantage Android 11+)
            w.setStatusBarColor(bg);
            w.setNavigationBarColor(bg);
            if (Build.VERSION.SDK_INT >= 30) {
                WindowInsetsController c = d.getWindowInsetsController();
                if (c != null) {
                    int m = WindowInsetsController.APPEARANCE_LIGHT_STATUS_BARS | WindowInsetsController.APPEARANCE_LIGHT_NAVIGATION_BARS;
                    c.setSystemBarsAppearance(dark ? 0 : m, m);
                }
            } else {
                int f = d.getSystemUiVisibility();
                int m = View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR | (Build.VERSION.SDK_INT >= 26 ? View.SYSTEM_UI_FLAG_LIGHT_NAVIGATION_BAR : 0);
                d.setSystemUiVisibility(dark ? (f & ~m) : (f | m));
            }
        } catch (Throwable ignored) { }
    }
}
