import pathlib

text = pathlib.Path('D:/EDS/EDS/eds/domains/healthcare/generators/reference.py').read_text(encoding='utf-8-sig')
# Remove BOM if present
if text.startswith('\ufeff'):
    text = text[1:]
with open('D:/EDS/EDS/eds/domains/healthcare/generators/reference.py', 'w', encoding='utf-8') as f:
    f.write(text)
print('Removed BOM from reference.py')
