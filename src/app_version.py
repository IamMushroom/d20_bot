from pathlib import Path
from tomllib import load


def get_version() -> str:
    pyproject = Path(__file__).resolve().parent.parent / 'pyproject.toml'
    with pyproject.open('rb') as file:
        return load(file)['project']['version']
