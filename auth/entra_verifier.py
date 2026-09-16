"""Verification de jetons Entra ID (Azure AD) pour le serveur MCP Charlemagne.

Utilise en production quand le transport est streamable-http (Copilot 365 / Copilot
Studio). Le stdio (Claude Desktop) ne passe jamais par ce module.

Variables d'environnement attendues :
  CHARLEMAGNE_ENTRA_TENANT_ID   - ID du tenant Entra ID de l'ecole (GUID)
  CHARLEMAGNE_ENTRA_APP_ID_URI  - Application ID URI de l'app "ressource"
                                  cote Entra ID (ex: api://<client-id-ressource>)
  CHARLEMAGNE_ENTRA_ALLOWED_GROUP_ID - optionnel, ID du groupe de securite
                                  Entra ID autorise (ex: "Personnel autorise
                                  Charlemagne"). Si absent, seule la validation
                                  du jeton (signature/audience/expiration) est
                                  appliquee, sans verification de groupe.

Le jeton doit etre emis par ce tenant, pour cette audience, avec le scope
"Charlemagne.Read" (claim "scp" pour un jeton delegue utilisateur).
"""

from __future__ import annotations

import logging
import os
import time

import httpx
import jwt

logger = logging.getLogger("charlemagne.auth_entra")

from mcp.server.auth.provider import AccessToken, TokenVerifier

REQUIRED_SCOPE = "Charlemagne.Read"
_JWKS_TTL_SECONDS = 3600


class EntraTokenVerifier(TokenVerifier):
    """Valide un jeton Bearer Entra ID (Azure AD v2.0) pour Copilot Studio.

    Verifie, dans l'ordre : signature (JWKS du tenant), issuer, audience,
    expiration, puis presence du scope requis. Verifie ensuite
    l'appartenance au groupe autorise si CHARLEMAGNE_ENTRA_ALLOWED_GROUP_ID
    est renseignee.
    """

    def __init__(
        self,
        tenant_id: str | None = None,
        app_id_uri: str | None = None,
        allowed_group_id: str | None = None,
        http_client: httpx.Client | None = None,
    ) -> None:
        self.tenant_id = tenant_id or _require_env("CHARLEMAGNE_ENTRA_TENANT_ID")
        self.app_id_uri = app_id_uri or _require_env("CHARLEMAGNE_ENTRA_APP_ID_URI")
        self.allowed_group_id = allowed_group_id or os.environ.get(
            "CHARLEMAGNE_ENTRA_ALLOWED_GROUP_ID"
        )
        self.issuer = f"https://login.microsoftonline.com/{self.tenant_id}/v2.0"
        self._http = http_client or httpx.Client(timeout=5.0)
        # Cache JWKS propre a cette instance (pas de partage global entre instances -
        # ca a cause un bug de tests ou une instance de test heritait du cache d'une
        # autre). Invalide toutes les heures : evite de re-interroger Entra ID a
        # chaque requete tout en tolerant une rotation de cles.
        self._jwks_cache: dict | None = None
        self._jwks_fetched_at: float = 0.0

    def _jwks_uri(self) -> str:
        return (
            f"https://login.microsoftonline.com/{self.tenant_id}"
            "/discovery/v2.0/keys"
        )

    def _get_jwks(self) -> dict:
        now = time.time()
        if self._jwks_cache is None or now - self._jwks_fetched_at > _JWKS_TTL_SECONDS:
            resp = self._http.get(self._jwks_uri())
            resp.raise_for_status()
            self._jwks_cache = resp.json()
            self._jwks_fetched_at = now
        return self._jwks_cache

    def _signing_key(self, token: str):
        jwks = self._get_jwks()
        header = jwt.get_unverified_header(token)
        for key in jwks["keys"]:
            if key["kid"] == header["kid"]:
                return jwt.algorithms.RSAAlgorithm.from_jwk(key)
        # Cle non trouvee : peut-etre une rotation recente, on force un refresh unique.
        self._jwks_cache = None
        jwks = self._get_jwks()
        for key in jwks["keys"]:
            if key["kid"] == header["kid"]:
                return jwt.algorithms.RSAAlgorithm.from_jwk(key)
        raise jwt.InvalidTokenError(f"Cle de signature introuvable (kid={header.get('kid')})")

    async def verify_token(self, token: str) -> AccessToken | None:
        # Toute erreur ici (jeton invalide, JWKS injoignable, reponse Entra ID
        # inattendue...) doit se traduire par un rejet propre (None -> 401),
        # jamais par une exception non rattrapee qui remonterait en 500 et
        # pourrait exposer des details internes.
        try:
            signing_key = self._signing_key(token)
            claims = jwt.decode(
                token,
                key=signing_key,
                algorithms=["RS256"],
                audience=self.app_id_uri,
                issuer=self.issuer,
                options={"require": ["exp", "iss", "aud"]},
            )
        except jwt.PyJWTError as exc:
            logger.info("Jeton rejete (invalide) : %s", exc)
            return None
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            logger.warning("Jeton rejete (JWKS/Entra ID injoignable ou reponse inattendue) : %s", exc)
            return None

        scopes = claims.get("scp", "").split()
        if REQUIRED_SCOPE not in scopes:
            return None

        if self.allowed_group_id:
            groups = claims.get("groups", [])
            if self.allowed_group_id not in groups:
                return None

        return AccessToken(
            token=token,
            client_id=claims.get("appid", claims.get("azp", "unknown")),
            scopes=scopes,
            expires_at=claims.get("exp"),
        )


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(
            f"Variable d'environnement {name} manquante - requise pour le transport "
            "streamable-http avec authentification Entra ID."
        )
    return value
