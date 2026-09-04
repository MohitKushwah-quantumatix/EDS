import polars as pl

df = pl.read_parquet('my-hospital/output/patients.parquet')
print(f'Total rows: {df.height}')

# effective_date distribution
print('\nEffective date distribution:')
for val in df.select(pl.col('effective_date').unique().sort()).to_series().to_list():
    count = df.filter(pl.col('effective_date') == val).height
    print(f'  {val}: {count} rows')

# end_date distribution
print('\nEnd date distribution:')
for val in df.select(pl.col('end_date').unique().sort()).to_series().to_list():
    count = df.filter(pl.col('end_date') == val).height
    print(f'  {val}: {count} rows')

# Show a few sample rows with their effective/end dates
print('\nSample rows:')
print(df.select(['patient_id', 'effective_date', 'end_date', 'status']).head(20).to_pandas().to_string())
