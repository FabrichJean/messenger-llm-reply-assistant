"""Audit : scripts de déploiement (syntaxe, validation des valeurs injectées dans une commande SSH, chiffrement des sauvegardes)."""
import subprocess, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(script, *args):
    return subprocess.run(["bash", str(ROOT / "deploy" / script), *args], capture_output=True, text=True, timeout=20, input="n\n", cwd=ROOT)


class Scripts(unittest.TestCase):
    def test_syntaxe_de_tous_les_scripts(self):
        for sh in list((ROOT / "deploy").glob("*.sh")) + [ROOT / "tests" / "run.sh"]:
            r = subprocess.run(["bash", "-n", str(sh)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, f"{sh.name}: {r.stderr}")

    def test_push_account_refuse_les_valeurs_dangereuses(self):
        for args in (("a;rm -rf ~", "u@h"), ("$(id)", "u@h"), ("`id`", "u@h"), ("ok_name", "u@h; id"), ("ok_name", "u@h", "~/x; id"), ("ok_name", "u@h", "$(id)"),
                     ("../x", "u@h"), ("A", "u@h"), ("a" * 40, "u@h"), ("ok name", "u@h"), ("ok_name", "-oProxyCommand=id", "~/x"), ("ok_name", "-vv", "~/x"), ("ok_name", "-J", "~/x"), ("ok_name", "u@h", "-rf")):
            r = run("push-account.sh", *args)
            with self.subTest(args=args):
                self.assertNotEqual(r.returncode, 0)
                self.assertIn("invalide", r.stdout + r.stderr, "refusé, mais pas par la validation")

    def test_sauvegarde_chiffree_avec_derivation_de_cle_lente(self):
        text = (ROOT / "deploy" / "backup.sh").read_text()
        self.assertIn("-pbkdf2", text); self.assertIn("-iter 600000", text); self.assertIn("umask 077", text)
        self.assertNotIn("-iter 600000", "") ; self.assertEqual(text.count("-iter 600000"), 2, "chiffrement ET déchiffrement doivent utiliser le même nombre d'itérations")


if __name__ == "__main__":
    unittest.main()
