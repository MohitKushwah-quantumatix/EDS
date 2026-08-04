"""The Healthcare simulation domain.

Generates a complete healthcare enterprise: master data, patients,
providers, encounters, and billing. This is the Healthcare domain,
mirroring the Retail domain's execution style.

Importing this package registers the domain with
:mod:`eds.platform.domain`, so a caller can discover Healthcare
without knowing anything about how it works (PADR-002).
"""

from eds.domains.healthcare.registry import HEALTHCARE_DOMAIN_NAME, HealthcareDomain

__all__ = ["HEALTHCARE_DOMAIN_NAME", "HealthcareDomain"]
