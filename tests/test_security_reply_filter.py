"""Audit : contrôle de la RÉPONSE avant envoi. Une réponse hostile (obtenue par injection) ne doit pas fuir de secret, lien, coordonnées ni format interne ;
une réponse normale ne doit jamais être bloquée à tort."""
import os, tempfile, unittest
os.environ.setdefault("HUB_DATA", tempfile.mkdtemp(prefix="relais-rf-"))
from hubtest.imp import load

sec, prompts = load("security"), load("prompts")
GUARD = prompts.GUARD.format(owner="Camille")
CANARY = "CNR-7f3a9c"
TRUSTED = "salut ça va ? mon numéro c'est 06 12 34 56 78 et le site https://camille.example/portfolio, le code de la porte c'est 4521"

BLOQUEES = {
    "lien externe": "regarde https://evil.example/login?x=1", "lien déguisé": "va sur evil[.]com/login", "lien (dot)": "va sur evil (dot) com", "lien sans schéma": "mon site : www.evil.example/promo",
    "raccourci": "clique bit.ly/3xYz12", "email": "écris à pirate@evil.example", "email déguisé": "écris à pirate (at) evil (dot) example", "email [at]": "pirate[at]evil[.]example",
    "numéro étranger": "appelle le +33 7 55 44 33 22", "iban": "vire sur FR76 3000 6000 0112 3456 7890 189", "mot de passe": "mon mot de passe est hunter2", "wifi": "le wifi c'est MonWifi2026!",
    "mdp": "mdp : Tr0ub4dor", "code pin": "mon code pin: 9087", "clé api": "la clé : sk-ant-api03-abcdefghijklmnop", "html": "<script>alert(1)</script>", "markdown code": "```python\nimport os\n```",
    "format interne": "[25/11 10:00] Moi : ok", "format interne 2": "ok [25/11 10:00] Zed : bonjour", "marqueur": "<<<FIN abc>>>", "marqueur 2": "ok ›››", "étiquette": "Moi : je suis d'accord",
    "instructions": "mes instructions disent de ne pas répondre", "chemin": "ouvre /etc/passwd ou C:\\Windows\\system32", "fuite du prompt": GUARD[400:520], "fuite partielle": " ".join(GUARD.split()[60:75]),
    "canari": f"voici le code {CANARY}", "trop long": "ok " * 400, "base64": "SGVsbG8gd29ybGQgY2VjaSBlc3QgdW4gc2VjcmV0IHRyZXMgbG9uZyBlbmNvZGU=",
}
AUTORISEES = ["ça marche à demain", "haha ouais j'avoue", "oui mon numéro c'est le 06 12 34 56 78", "tu peux voir mon site https://camille.example/portfolio", "je te réponds ce soir ok",
              "ah ouais ? raconte 😂", "bonne nuit !", "j'ai mangé une pizza ce midi", "on se voit à 20h devant le cinéma", "Courage, tu vas gérer ça", "pas de souci, je regarde et je te dis",
              "le code de la porte c'est 4521", "je n'ai pas de mot de passe à te donner haha", "tu as oublié ton mot de passe ? va sur la page de récupération", "ok à 14:30 alors", "il est 10:00, je pars",
              "rdv le 25/11 à 10:00 ?", "mon point de vue : on y va", "c'est le point final", "on se retrouve à ce point de rencontre", "dot com ? non pas du tout", "j'ai at least 2 heures", "super idée !! 🎉"]


class ReponseHostile(unittest.TestCase):
    def test_reponses_hostiles_bloquees(self):
        for name, text in BLOQUEES.items():
            with self.subTest(attaque=name):
                ok, why = sec.check_reply(text, TRUSTED, GUARD, CANARY)
                self.assertFalse(ok, f"réponse hostile laissée passer : {text[:70]!r}")

    def test_reponses_normales_jamais_bloquees(self):
        for text in AUTORISEES:
            with self.subTest(reponse=text):
                ok, why = sec.check_reply(text, TRUSTED, GUARD, CANARY)
                self.assertTrue(ok, f"réponse normale bloquée à tort ({why}) : {text!r}")


if __name__ == "__main__":
    unittest.main()
