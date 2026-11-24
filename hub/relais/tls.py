"""Contexte TLS pour les requêtes sortantes (vérification des certificats)."""

import os
import ssl


def make_ssl_context():
    """Vérification TLS stricte ; si Python n'a pas de certificats racine, on prend ceux du système."""
    ctx = ssl.create_default_context()
    if ctx.cert_store_stats().get("x509_ca", 0) == 0:
        for cafile in ("/etc/ssl/cert.pem", "/etc/ssl/certs/ca-certificates.crt", "/etc/pki/tls/certs/ca-bundle.crt"):
            if os.path.exists(cafile):
                ctx.load_verify_locations(cafile)
                break
    return ctx


SSL_CTX = make_ssl_context()
