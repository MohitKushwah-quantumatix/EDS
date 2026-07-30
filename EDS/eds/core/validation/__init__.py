"""The domain-independent validation framework.

Schema conformance, primary keys, unique columns and foreign keys are all
checked from :class:`~eds.core.schema.Dataset` declarations, so the framework
never needs to know which domain produced the data.
"""
