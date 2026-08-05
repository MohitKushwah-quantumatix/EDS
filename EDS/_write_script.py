import pathlib

pathlib.Path("D:/EDS/EDS/_update_reference.py").write_text("""
with open('D:/EDS/EDS/eds/domains/healthcare/generators/reference.py', 'w', encoding='utf-8') as f:
    f.write('PLACEHOLDER')
""", encoding="utf-8")
print("script written")
