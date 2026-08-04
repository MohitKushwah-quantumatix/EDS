import polars as pl

print("Current data counts:")
print(f"Customers: {len(pl.read_parquet('output/customers.parquet'))}")
print(f"Products: {len(pl.read_parquet('output/products.parquet'))}")
print(f"Orders: {len(pl.read_parquet('output/orders.parquet'))}")
print(f"Sessions: {len(pl.read_parquet('output/sessions.parquet'))}")
print(f"Carts: {len(pl.read_parquet('output/shopping_carts.parquet'))}")
print(f"Last modified:")
import os
from datetime import datetime
print(f"Products file: {datetime.fromtimestamp(os.path.getmtime('output/products.parquet'))}")
