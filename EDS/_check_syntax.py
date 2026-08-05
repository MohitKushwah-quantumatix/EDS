with open('D:/EDS/EDS/eds/domains/healthcare/generators/reference.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()
for i, line in enumerate(lines, 1):
    if '"),)' in line:
        print(f'Line {i}: {line.rstrip()}')
