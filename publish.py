#!/usr/bin/env python3
import os
import re
import sys
import ast
import json
import pkgutil
import subprocess
import importlib.util
from shutil import rmtree, copytree

def get_standard_library_modules():
    """Return a set of stdlib module names (excluding site-packages)."""
    stdlib = set()
    for mod in pkgutil.iter_modules():
        if mod.ispkg or mod.name.startswith('_'):
            continue
        try:
            spec = importlib.util.find_spec(mod.name)
            if spec and spec.origin and 'site-packages' not in spec.origin:
                stdlib.add(mod.name)
        except Exception:
            pass
    stdlib.update({
        'builtins', 'sqlite3', 'sys', 'os', 'math', 'time', 'datetime', 'random',
        'json', 're', 'string', 'collections', 'itertools', 'functools', 'shutil',
        'subprocess', 'pathlib', 'configparser', 'io', 'types', 'warnings', 'abc'
    })
    return stdlib

def infer_dependencies(app_dir, project_name):
    """
    Parse all .py files under app_dir for imports, then remove any modules
    that are internal, part of the standard library, or the project itself.
    """
    stdlib = get_standard_library_modules()
    deps = set()
    internal_modules = set()

    for root, dirs, files in os.walk(app_dir):
        for fn in files:
            if fn.endswith('.py') and fn != '__init__.py':
                module_name = fn[:-3]
                internal_modules.add(module_name)
        for dir_name in dirs:
            if os.path.exists(os.path.join(root, dir_name, '__init__.py')):
                internal_modules.add(dir_name)

    for root, _, files in os.walk(app_dir):
        for fn in files:
            if not fn.endswith('.py'):
                continue
            path = os.path.join(root, fn)
            with open(path, 'r', encoding='utf-8') as f:
                text = f.read()
            try:
                tree = ast.parse(text)
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for n in node.names:
                            pkg = n.name.split('.')[0]
                            if pkg not in stdlib and pkg not in internal_modules and pkg != project_name:
                                deps.add(pkg)
                    elif isinstance(node, ast.ImportFrom) and node.module:
                        pkg = node.module.split('.')[0]
                        if pkg not in stdlib and pkg not in internal_modules and pkg != project_name:
                            deps.add(pkg)
            except SyntaxError:
                for m in re.findall(r'^\s*(?:import|from)\s+([A-Za-z0-9_]+)',
                                    text, re.MULTILINE):
                    if m not in stdlib and m not in internal_modules and m != project_name:
                        deps.add(m)

    print(f"Detected external dependencies: {sorted(deps)}")
    print(f"Excluded internal modules/packages: {sorted(internal_modules)}")

    return sorted(deps)

def read_local_version():
    """Read version = "X.Y.Z" from pyproject.toml, or return None."""
    fn = "pyproject.toml"
    if not os.path.exists(fn):
        return None
    with open(fn, 'r', encoding='utf-8') as f:
        txt = f.read()
    m = re.search(r'version\s*=\s*"(\d+)\.(\d+)\.(\d+)"', txt)
    return tuple(map(int, m.groups())) if m else None

def read_pypi_version(name):
    """Fetch version tuple from PyPI JSON, or None on error."""
    try:
        import urllib.request
        url = f"https://pypi.org/pypi/{name}/json"
        with urllib.request.urlopen(url, timeout=5) as resp:
            info = json.loads(resp.read().decode())
        return tuple(map(int, info['info']['version'].split('.')))
    except Exception:
        return None

def bump_patch(vt):
    """Given (X,Y,Z) return 'X.Y.(Z+1)'."""
    return f"{vt[0]}.{vt[1]}.{vt[2] + 1}"

def determine_new_version(name):
    """
    Compare local version vs PyPI version, pick the higher,
    bump its patch number, or start at 0.0.1.
    """
    local = read_local_version()
    remote = read_pypi_version(name)
    print(f"Local version: {local}, Remote version: {remote}")
    if not local and not remote:
        return "0.0.1"
    
    base = local
    if remote and (not local or remote > local):
        base = remote
        
    return bump_patch(base)

def detect_app_structure(app_dir):
    """Detect if app/ has a modules/ subdirectory or only .py files."""
    has_modules = os.path.exists(os.path.join(app_dir, "modules"))
    py_files = [f[:-3] for f in os.listdir(app_dir) if f.endswith('.py') and f != '__init__.py']
    return has_modules, py_files

def write_configs(name, deps, version, has_modules):
    """Rewrite pyproject.toml + setup.cfg based on app structure."""
    dep_block = ""
    if deps:
        dep_block = "\n".join(f'  "{d}",' for d in deps)

    py_proj_content = f"""[build-system]
requires = ["setuptools>=61.0", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "{name}"
version = "{version}"
description = "A decentralized terminal social network using IPFS."
readme = "README.md"
requires-python = ">=3.6"
license = {{ file = "LICENSE" }}

authors = [
  {{ name = "Ryan Gerard Wilson", email = "ryan@wilsonfamilyoffice.com" }}
]

dependencies = [
{dep_block}
]

classifiers = [
  "Programming Language :: Python :: 3",
  "License :: OSI Approved :: MIT License",
  "Operating System :: OS Independent"
]

[project.urls]
Homepage = "https://github.com/yourusername/sclik"
Issues   = "https://github.com/yourusername/sclik/issues"

[project.entry-points."console_scripts"]
{name} = "{name}.app.main:main"
"""
    with open("pyproject.toml", "w", encoding="utf-8") as f:
        f.write(py_proj_content)

    if has_modules:
        packages = f"{name}.app, {name}.app.modules"
        package_dir = f"""    {name}.app = {name}/app
    {name}.app.modules = {name}/app/modules"""
    else:
        packages = f"{name}.app"
        package_dir = f"    {name}.app = {name}/app"

    setup_cfg_content = f"""[metadata]
long_description = file: README.md
long_description_content_type = text/markdown

[options]
packages = {packages}
package_dir =
{package_dir}
python_requires = >=3.6
include_package_data = True
"""
    with open("setup.cfg", "w", encoding="utf-8") as f:
        f.write(setup_cfg_content)

    manifest_content = f"""include LICENSE
include README.md
recursive-include {name}/app *.py
"""
    if not os.path.exists("README.md"):
        manifest_content = manifest_content.replace("include README.md\n", "")
    with open("MANIFEST.in", "w", encoding="utf-8") as f:
        f.write(manifest_content)

    print(f"→ Wrote pyproject.toml, setup.cfg, and MANIFEST.in (version = {version})")

def prepare_build(name):
    """Copy app/ to <project_name>/app/ and create __init__.py files."""
    if not os.path.exists("app"):
        print("Error: app/ directory not found.", file=sys.stderr)
        sys.exit(1)

    print(f"Preparing build: Copying app/ to {name}/app/")
    project_dir = name
    project_app_dir = os.path.join(project_dir, "app")
    rmtree(project_dir, ignore_errors=True)
    copytree("app", project_app_dir)

    # Create __init__.py files
    with open(os.path.join(project_dir, "__init__.py"), "w", encoding="utf-8") as f:
        f.write("")
    with open(os.path.join(project_app_dir, "__init__.py"), "w", encoding="utf-8") as f:
        f.write("")

    return project_dir, project_app_dir

def cleanup_build(project_dir):
    """Remove temporary <project_name>/ directory after build."""
    print(f"Cleaning up: Removing temporary {project_dir}")
    rmtree(project_dir, ignore_errors=True)

def rebuild():
    """Install build/twine, clear dist/, and build sdist+wheel."""
    subprocess.run([sys.executable, "-m", "pip", "install", "--upgrade", "build", "twine"], check=True)
    rmtree("dist", ignore_errors=True)
    os.makedirs("dist", exist_ok=True)
    result = subprocess.run([sys.executable, "-m", "build"], check=False, capture_output=True, text=True)
    if result.returncode != 0:
        print("Build failed!", file=sys.stderr)
        print("--- STDOUT ---", file=sys.stderr)
        print(result.stdout, file=sys.stderr)
        print("--- STDERR ---", file=sys.stderr)
        print(result.stderr, file=sys.stderr)
        raise subprocess.CalledProcessError(result.returncode, result.args, result.stdout, result.stderr)
    print("→ Package rebuilt")

def upload():
    """Upload with twine, skipping existing files."""
    cmd = [sys.executable, "-m", "twine", "upload", "--skip-existing", "dist/*"]
    subprocess.run(cmd, check=True)
    print("→ Upload done (existing files skipped)")

def verify(name, version):
    print("\nOnce PyPI has processed your upload, run:")
    print(f"  pip install --upgrade {name}=={version}")
    print()

def main():
    entry = "app/main.py"
    if not os.path.exists(entry):
        print(f"Error: entry-point {entry} not found.", file=sys.stderr)
        sys.exit(1)

    project_name = os.path.basename(os.getcwd())

    print("1) Inferring dependencies…")
    deps = infer_dependencies("app", project_name)
    print(f"   Detected: {deps or '(none)'}")

    print("2) Determining next version…")
    new_version = determine_new_version(project_name)
    print(f"   New version: {new_version}")

    print("3) Preparing build directory…")
    project_dir, _ = prepare_build(project_name)

    print("4) Detecting app structure…")
    has_modules, _ = detect_app_structure("app")
    print(f"   Has modules/: {has_modules}")

    print("5) Writing config files…")
    write_configs(project_name, deps, new_version, has_modules)

    print("6) Rebuilding package…")
    rebuild()

    print("7) Uploading package…")
    upload()

    print("8) Cleaning up build directory…")
    cleanup_build(project_dir)

    print("9) Done.")
    verify(project_name, new_version)

if __name__ == "__main__":
    main()
