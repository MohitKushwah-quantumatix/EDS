"""The PostgreSQL output adapter.

Wraps a SQLAlchemy engine behind the adapter protocols. Each dataset becomes
one table in the target schema; a write replaces the table in full.
"""
