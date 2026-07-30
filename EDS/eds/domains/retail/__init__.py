"""The Retail simulation domain.

Generates a complete retail enterprise: master data, customers, the digital
journey, and commerce from shopping cart through to product review. This is
the reference domain, and the only one implemented today.

It runs for a *business date*, not merely once.
:mod:`eds.domains.retail.temporal` holds what a passing day does: who registers,
who comes back, what sells, what is restocked, and what each of the thirty-nine
datasets does when the day arrives. A stage founds its datasets if they are
empty and continues them if they are not, so an enterprise's history is its
state (ADR-013, ADR-014).

Importing this package registers the domain with :mod:`eds.platform.domain`,
so a caller can discover Retail without knowing anything about how it works
(PADR-002). The domain announces itself rather than the platform keeping a
list, which is what keeps the platform free of domain names.

Registration is the one side effect of this import and it is deliberately
cheap: the descriptor defers every generator import until something actually
asks about a stage.
"""

from eds.domains.retail.registry import RETAIL_DOMAIN_NAME, RetailDomain

__all__ = ["RETAIL_DOMAIN_NAME", "RetailDomain"]
