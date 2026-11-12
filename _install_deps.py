"""Install S2 vector-rendering dependencies. Run once, then delete."""
import subprocess, sys

deps = [
    "fiona>=1.10,<2",
    "shapely>=2.0,<3",
    "rasterio>=1.4,<2",
    "numpy>=1.26,<3",
    "matplotlib>=3.8,<4",
    "fonttools>=4.40,<5",
]

python = r"C:\Users\DELL\miniconda3\python.exe"
for dep in deps:
    print(f"Installing {dep}...")
    subprocess.run([python, "-m", "pip", "install", dep], check=True)
    print(f"  OK: {dep}")

print("\nAll dependencies installed.")