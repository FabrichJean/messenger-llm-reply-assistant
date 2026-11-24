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

