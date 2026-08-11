from pathlib import Path
from eds.adapters.parquet.reader import read_dataset
from eds.adapters.postgres.adapter import PostgresAdapter

# 1. Adapter banao — apna connection string yahan do
adapter = PostgresAdapter(
    "postgresql+psycopg://postgres:root1234@localhost:5432/eds_db",
    schema="public",
)

# 2. Jo bhi Parquet files chahiye unhe padho
names = ["customers", "journey", "commerce"]
frames = {n: read_dataset(n, Path("output")) for n in names}

# 3. Postgres mein likho
results = adapter.write(frames)
for r in results:
    print(r)   # WriteResult(dataset='customers', location='public.customers', rows=1000)

adapter.dispose()