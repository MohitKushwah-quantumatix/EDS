with open('D:/EDS/EDS/eds/domains/healthcare/generators/reference.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Fix line 480 (index 479)
lines[479] = '    {"code": "J99", "description": "Respiratory disorders in diseases classified elsewhere", "category": "RESPIRATORY"},\n'

with open('D:/EDS/EDS/eds/domains/healthcare/generators/reference.py', 'w', encoding='utf-8') as f:
    f.writelines(lines)

print('Fixed line 480')
