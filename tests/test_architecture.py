import ast
from collections.abc import Iterable
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC = PROJECT_ROOT / 'src'


def python_files(*paths: Path) -> list[Path]:
    files: list[Path] = []
    for path in paths:
        if path.is_file():
            files.append(path)
        else:
            files.extend(path.rglob('*.py'))
    return sorted(files)


def imports_in(path: Path) -> Iterable[tuple[str, int]]:
    tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name, node.lineno
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            yield node.module, node.lineno


def assert_no_imports(paths: Iterable[Path], forbidden: set[str]) -> None:
    violations: list[str] = []
    for path in paths:
        for module, line in imports_in(path):
            if any(module == prefix or module.startswith(f'{prefix}.') for prefix in forbidden):
                relative = path.relative_to(PROJECT_ROOT)
                violations.append(f'{relative}:{line} imports {module}')
    assert not violations, 'Forbidden architecture dependencies:\n' + '\n'.join(violations)


def test_web_does_not_depend_on_telegram_presentation() -> None:
    assert_no_imports(python_files(SRC / 'web'), {'commands', 'telegram'})


def test_commands_do_not_depend_on_database_implementation() -> None:
    assert_no_imports(
        python_files(SRC / 'commands'),
        {'database.repositories', 'database.sqlite', 'sqlite3'},
    )


def test_domain_does_not_depend_on_outer_layers() -> None:
    assert_no_imports(
        python_files(SRC / 'domain'),
        {'commands', 'database', 'services', 'telegram', 'web'},
    )


def test_repositories_do_not_depend_on_presentations() -> None:
    assert_no_imports(
        python_files(SRC / 'database' / 'repositories'),
        {'commands', 'telegram', 'web'},
    )


def test_telegram_bot_does_not_own_database() -> None:
    assert_no_imports(
        python_files(SRC / 'run.py', SRC / 'commands'),
        {'database', 'sqlite3'},
    )
