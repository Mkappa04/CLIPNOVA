"""Content rights policy.

Decides whether material may be exported/published for a given purpose.
Local *processing* (analysis, editing previews) is always allowed: nothing
leaves the machine. Anything that leaves the machine is checked here.

Key rule: giving credit is NOT an authorization.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum

from backend.models.entities import AuthorizationStatus, LicenseType, RightsRecord


class Purpose(str, Enum):
    INTERNAL = "internal"              # local processing only
    NON_COMMERCIAL = "non_commercial"  # export/publish without monetisation
    COMMERCIAL = "commercial"          # monetised channels, sponsorships, ads


_NON_COMMERCIAL_ONLY_LICENSES = {LicenseType.CC_BY_NC}
_ATTRIBUTION_LICENSES = {LicenseType.CC_BY, LicenseType.CC_BY_SA, LicenseType.CC_BY_NC}


@dataclass
class RightsDecision:
    purpose: Purpose
    allowed: bool
    blockers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"purpose": self.purpose.value, "allowed": self.allowed,
                "blockers": self.blockers, "warnings": self.warnings}


def evaluate(rights: RightsRecord | None, purpose: Purpose, today: date | None = None) -> RightsDecision:
    today = today or date.today()
    if purpose is Purpose.INTERNAL:
        return RightsDecision(purpose, True)

    blockers: list[str] = []
    warnings: list[str] = []

    if rights is None:
        return RightsDecision(purpose, False, ["Nessun dato sui diritti: registra proprietario, licenza e autorizzazione."])

    license_type = LicenseType(rights.license_type)
    auth = AuthorizationStatus(rights.authorization_status)

    if license_type is LicenseType.CREDIT_ONLY:
        blockers.append("Il solo credito/attribuzione non è un'autorizzazione a riutilizzare il contenuto.")
    if license_type is LicenseType.UNKNOWN:
        blockers.append("Tipo di licenza sconosciuto.")

    if auth is not AuthorizationStatus.AUTHORIZED:
        blockers.append(f"Stato autorizzazione «{auth.value}»: deve essere «authorized».")

    if rights.expires_at is not None and rights.expires_at < today:
        blockers.append(f"Autorizzazione scaduta il {rights.expires_at.isoformat()}.")
    elif rights.expires_at is not None and (rights.expires_at - today).days <= 7:
        warnings.append(f"L'autorizzazione scade a breve ({rights.expires_at.isoformat()}).")

    if purpose is Purpose.COMMERCIAL:
        if license_type in _NON_COMMERCIAL_ONLY_LICENSES:
            blockers.append("La licenza vieta l'uso commerciale (NC).")
        if not rights.commercial_use_allowed:
            blockers.append("L'uso commerciale non è indicato come consentito.")

    needs_attribution = rights.attribution_required or license_type in _ATTRIBUTION_LICENSES
    if needs_attribution and not rights.attribution_text.strip():
        blockers.append("Attribuzione richiesta ma manca il testo di attribuzione.")

    if license_type in (LicenseType.CREATOR_PERMISSION, LicenseType.LICENSED) and not rights.evidence.strip():
        warnings.append("Nessuna prova del permesso registrata (email, contratto, link).")

    if rights.restrictions.strip():
        warnings.append(f"Ci sono restrizioni, verifica a mano: {rights.restrictions.strip()}")

    if license_type is LicenseType.OWN_CONTENT:
        warnings.append("Il gameplay proprio resta soggetto alla policy dell'editore sui contenuti (es. Rockstar).")

    return RightsDecision(purpose, not blockers, blockers, warnings)
