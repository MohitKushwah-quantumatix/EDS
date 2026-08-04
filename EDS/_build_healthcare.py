import os

base = "D:/EDS/EDS/eds/domains/healthcare"

def write_file(rel_path, content):
    full = os.path.join(base, rel_path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"Wrote {rel_path}")

# domain/__init__.py
write_file("domain/__init__.py", '"""Domain model packages for EDS healthcare entities.\n\nContents are introduced by subsequent features.\n"""')

print("Done with domain/__init__.py")
