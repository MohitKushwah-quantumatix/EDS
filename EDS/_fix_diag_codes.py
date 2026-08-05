with open('D:/EDS/EDS/eds/domains/healthcare/generators/reference.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Find the line with J99 and add closing ) after it
for i, line in enumerate(lines):
    if '"J99"' in line:
        lines.insert(i + 1, ')\n')
        print(f'Added closing ) after line {i+1}')
        break

with open('D:/EDS/EDS/eds/domains/healthcare/generators/reference.py', 'w', encoding='utf-8') as f:
    f.writelines(lines)

print('Fixed DIAGNOSIS_CODES closing parenthesis')
