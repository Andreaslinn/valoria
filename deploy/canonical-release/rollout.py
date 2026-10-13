"""Host-side API-only rollout/rollback. Default is a plan; --approved is mandatory to apply."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from pathlib import Path

API = "valoria_oracle_beta-api-1"


def run(args, **kwargs):
    result = subprocess.run(args,capture_output=True,text=True,timeout=120,**kwargs)
    if result.returncode:
        raise RuntimeError("Controlled release command failed; sensitive diagnostics withheld")
    return result.stdout


def inspect(name):
    return json.loads(run(["docker","inspect",name]))[0]


def healthy(image):
    for _ in range(30):
        state = inspect(API)
        if state["Image"] == image and state["State"].get("Health",{}).get("Status") == "healthy":
            return
        time.sleep(2)
    raise RuntimeError("API health deadline exceeded")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release",type=Path,required=True)
    parser.add_argument("--backup",type=Path,required=True)
    parser.add_argument("--approved",action="store_true")
    parser.add_argument("--rollback",action="store_true")
    args = parser.parse_args()
    release = json.loads(args.release.read_text())
    before = json.loads((args.backup/"api-before-private.json").read_text())
    root = Path("/home/ubuntu/apps/valoria")
    env = dict(os.environ,PORTAL_GEO_RELEASE_IMAGE=before["Config"]["Image"])
    base = ["docker","compose","--project-name","valoria_oracle_beta","--env-file",str(root/"deploy/oracle.env")]
    for filename in before["Config"]["Labels"]["com.docker.compose.project.config_files"].split(","):
        base += ["-f",filename]
    if not args.approved:
        print(json.dumps({"status":"approval_required","candidate_image":release["image_id"],
                          "rollback_image":before["Image"],"changes":"api.image only","migrations":False}))
        return
    if args.rollback:
        run([*base,"up","-d","--no-deps","--no-build","api"],env=env)
        healthy(before["Image"])
        print(json.dumps({"status":"rolled_back","image_id":before["Image"]}))
        return
    if inspect(API)["Image"] != before["Image"]:
        raise RuntimeError("Production changed since preparation; re-audit before deployment")
    candidate = json.loads(run(["docker","image","inspect",release["image"]]))[0]
    if candidate["Id"] != release["image_id"] or candidate["Config"]["Labels"].get("org.opencontainers.image.revision") != release["commit"]:
        raise RuntimeError("Candidate identity differs from reviewed release")
    proof = run(["docker","run","--rm","--network=none",release["image"],"python","-c",
                 "import json;from pathlib import Path;from services.release_guard import verify_release_tree;print(json.dumps(verify_release_tree(Path('/app'))))"])
    if json.loads(proof)["commit"] != release["commit"]:
        raise RuntimeError("Candidate source differs from reviewed commit")
    override = args.backup/"canonical-image.override.yml"
    override.write_text("services:\n  api:\n    image: "+release["image"]+"\n")
    override.chmod(0o600)
    new = [*base,"-f",str(override)]
    original = json.loads(run([*base,"config","--format","json"],env=env))
    updated = json.loads(run([*new,"config","--format","json"],env=env))
    expected = json.loads(json.dumps(original))
    expected["services"]["api"]["image"] = release["image"]
    if expected != updated:
        raise RuntimeError("Deployment would change configuration beyond api.image")
    try:
        run([*new,"up","-d","--no-deps","--no-build","api"],env=env)
        healthy(release["image_id"])
        gate = json.loads(run(["docker","exec",API,"python","-B","-m","scripts.verify_canonical_live"]))
        if gate["status"] != "passed":
            raise RuntimeError("Canonical production exit gate failed")
        preserved = json.loads((args.backup/"preservation-state-private.json").read_text())
        for name, identity in preserved["other_container_ids"].items():
            state = inspect(name)
            if state["Id"] != identity or state["State"]["StartedAt"] != preserved["other_started_at"][name]:
                raise RuntimeError("An unrelated production container changed")
        if not any(item.get("Destination") == "/portal-session" and item.get("RW") is False
                   for item in inspect(API)["Mounts"]):
            raise RuntimeError("Portal session mount is no longer read-only")
        print(json.dumps({"status":"deployed_and_verified","gate":gate}))
    except Exception:
        run([*base,"up","-d","--no-deps","--no-build","api"],env=env)
        healthy(before["Image"])
        raise RuntimeError("Candidate failed acceptance; previous API restored") from None


if __name__ == "__main__":
    main()
