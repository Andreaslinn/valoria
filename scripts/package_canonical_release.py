"""Package only committed backend blobs, with an exact SHA256 source manifest."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import subprocess
import tarfile
from pathlib import Path

BACKEND_DIRS = {"api","audits","config","core","domain","infrastructure","scripts","services","workers","ui","alembic","deploy"}
ROOT_FILES = {"pyproject.toml","alembic.ini","README.md"}
RUNTIME_IMAGE = "sha256:22081087e836574f11091c45a164f6dbe6891f095cf55e6c6945c38c49f90f69"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    commit = subprocess.check_output(["git","rev-parse",args.commit+"^{commit}"],cwd=root,text=True).strip()
    archive = subprocess.check_output(["git","archive","--format=tar",commit],cwd=root)
    files = {}
    with tarfile.open(fileobj=io.BytesIO(archive)) as source:
        for entry in source:
            if entry.isfile() and (entry.name.split("/")[0] in BACKEND_DIRS or entry.name in ROOT_FILES):
                if any(part.startswith(".env") or part == "__pycache__" for part in Path(entry.name).parts):
                    continue
                files[entry.name] = source.extractfile(entry).read()
    manifest = {"commit":commit,"files":{name:hashlib.sha256(data).hexdigest() for name,data in sorted(files.items())},
                "runtime_dependencies_image_id":RUNTIME_IMAGE,"final_price_policy":"canonical_only"}
    files["release-manifest.json"] = json.dumps(manifest,indent=2).encode()
    dockerfile = files["deploy/canonical-release/Dockerfile"]
    with tarfile.open(args.output,"w:gz") as target:
        for name,data in {"Dockerfile":dockerfile,**{"app/"+k:v for k,v in files.items()}}.items():
            entry=tarfile.TarInfo(name)
            entry.size=len(data)
            entry.mode=0o644
            target.addfile(entry,io.BytesIO(data))
    print(json.dumps({"commit":commit,"backend_files":len(manifest["files"]),"package":str(args.output),
                      "package_sha256":hashlib.sha256(args.output.read_bytes()).hexdigest(),
                      "runtime_dependencies_image_id":RUNTIME_IMAGE}))


if __name__ == "__main__":
    main()
