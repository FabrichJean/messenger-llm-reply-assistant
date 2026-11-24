# Interface web

Les sources de l'interface sont séparées par type, puis **assemblées en une seule page** par le hub (`relais/web/pages.py`) avant d'être servies.

```
ui/
├── index.html        squelette de la page (HTML) avec des repères {{include …}}
├── css/              base.css (styles de base), v3.css (thème et mises en page actuels)
├── js/               l'application, en fichiers numérotés (chargés dans l'ordre des numéros)
├── login.html        page de connexion
└── join.html         page d'inscription par invitation
```

- `{{include css/base.css}}` est remplacé par le contenu du fichier ; `{{include js/*.js}}` par tous les fichiers du dossier, **triés par nom** et collés tels quels. Le préfixe numérique fixe donc l'ordre : le JavaScript est en portée globale, un fichier peut utiliser ce que les précédents définissent.
- La page servie est **un seul document** avec ses scripts en ligne, comme avant : la politique de sécurité (CSP) autorise chaque script par son empreinte, sans script externe ni `unsafe-inline`.
- Les sources sont relues automatiquement quand un fichier change (au plus une vérification par seconde) : pas besoin de redémarrer le hub pour voir une modification.

## Ajouter un fichier JavaScript

Crée `js/NN-nom.js` avec un numéro qui place le fichier au bon endroit dans l'ordre de chargement. Garde les frontières entre deux instructions de niveau supérieur (jamais au milieu d'une fonction) : `tests/test_ui_pages.py` vérifie que chaque fichier est du JavaScript valide.
