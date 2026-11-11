"""Build a relocatable, host-native Python backend for Electron packaging.

Requires uv. The interpreter is uv-managed; dependencies are exported from
uv.lock without development extras.
Build each OS/architecture on that target, then pass the directory to after-pack.
"""

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def source_hash():
    digest = hashlib.sha256()
    source = ROOT / "src" / "deepseek_tui"
    for path in sorted(source.rglob("*"), key=lambda p: p.relative_to(source).as_posix()):
        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
            digest.update(path.relative_to(source).as_posix().encode() + b"\0")
            digest.update(path.read_bytes())
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Replace an existing validated build after the new build passes",
    )
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists() and not (args.replace and (output / "manifest.json").is_file()):
        raise SystemExit(
            "Output already exists; use a new directory to avoid replacing a validated runtime"
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="python-runtime-build-", dir=output.parent
    ) as temporary:
        stage = Path(temporary)
        env = dict(os.environ)
        env.setdefault("UV_CACHE_DIR", str(output.parent / "uv-cache"))
        interpreter = subprocess.check_output(
            ["uv", "python", "find", "--managed-python", "--system", "--no-project", "3.12"],
            env=env,
            text=True,
        ).strip()
        info = json.loads(
            subprocess.check_output(
                [
                    interpreter,
                    "-c",
                    "import json,sys,os;print(json.dumps({"
                    "'prefix':os.path.realpath(sys.base_prefix),"
                    "'executable':os.path.relpath(os.path.realpath(sys.executable),os.path.realpath(sys.base_prefix)),'version':sys.version}))",
                ],
                text=True,
            )
        )
        relative = Path(info["executable"])
        if relative.is_absolute() or ".." in relative.parts:
            raise RuntimeError("Interpreter is outside its managed prefix")
        shutil.copytree(info["prefix"], stage / "python", symlinks=False)
        python = stage / "python" / relative
        packages = stage / "site-packages"
        locked = stage / "requirements.txt"
        export_env = dict(env)
        export_env.pop("UV_DEFAULT_INDEX", None)
        export_env.pop("UV_INDEX_URL", None)
        with locked.open("w") as stream:
            subprocess.run(
                [
                    "uv",
                    "export",
                    "--locked",
                    "--offline",
                    "--no-dev",
                    "--no-emit-project",
                    "--no-header",
                    "--no-annotate",
                ],
                cwd=ROOT,
                env=export_env,
                check=True,
                stdout=stream,
            )
        subprocess.run(
            [
                "uv",
                "pip",
                "install",
                "--python",
                str(python),
                "--target",
                str(packages),
                "--require-hashes",
                "-r",
                str(locked),
            ],
            env=env,
            check=True,
        )
        wheels = stage / "wheels"
        subprocess.run(
            ["uv", "build", "--wheel", "--out-dir", str(wheels)], cwd=ROOT, env=env, check=True
        )
        wheel = next(wheels.glob("*.whl"))
        subprocess.run(
            [
                "uv",
                "pip",
                "install",
                "--python",
                str(python),
                "--target",
                str(packages),
                "--no-deps",
                str(wheel),
            ],
            env=env,
            check=True,
        )
        manifest = {
            "platform": {"Darwin": "darwin", "Windows": "win32", "Linux": "linux"}[
                platform.system()
            ],
            "arch": {"aarch64": "arm64", "arm64": "arm64", "AMD64": "x64", "x86_64": "x64"}[
                platform.machine()
            ],
            "python": str(Path("python") / relative),
            "version": info["version"],
            "source_sha256": source_hash(),
            "requirements_sha256": hashlib.sha256(locked.read_bytes()).hexdigest(),
            "lock_sha256": hashlib.sha256((ROOT / "uv.lock").read_bytes()).hexdigest(),
            "wheel_sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
        }
        shutil.rmtree(wheels)
        (stage / "manifest.json").write_text(json.dumps(manifest, indent=2))
        # Smoke from outside the repository, with no developer/user site packages.
        smoke_env = {**env, "PYTHONPATH": str(packages), "PYTHONNOUSERSITE": "1"}
        smoke_env.pop("PYTHONHOME", None)
        subprocess.run(
            [str(python), "-m", "deepseek_tui", "--help"],
            cwd=stage,
            env=smoke_env,
            check=True,
            stdout=subprocess.DEVNULL,
        )
        previous = (
            output.with_name(output.name + ".previous-" + uuid.uuid4().hex)
            if output.exists()
            else None
        )
        if previous is not None:
            output.rename(previous)
        try:
            # Installable bundles must be readable by users other than the builder.
            stage.chmod(0o755)
            stage.rename(output)
        except BaseException:
            if previous is not None:
                previous.rename(output)
            raise
        if previous is not None:
            shutil.rmtree(previous)
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
