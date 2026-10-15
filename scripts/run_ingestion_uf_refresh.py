"""Host-side bounded refresh; deployed only after approval with its pinned candidate image."""
import json
import os
import subprocess
import tempfile
try:
    from scripts.ingestion_launcher import sanitize_error
except ModuleNotFoundError:
    from ingestion_launcher import sanitize_error


def main():
    current = json.loads(subprocess.check_output(["docker","inspect","valoria_oracle_beta-api-1"]))[0]
    values = dict(x.split("=",1) for x in current["Config"]["Env"])
    fd, filename = tempfile.mkstemp(prefix="valoria-uf-",suffix=".env")
    try:
        with os.fdopen(fd,"w") as f:
            for key,value in values.items():
                if "\n" in value:
                    raise ValueError("multiline_environment_unsupported")
                f.write(key+"="+value+"\n")
        image = os.environ.get("VALORIA_INGESTION_IMAGE",current["Image"])
        network = next(iter(current["NetworkSettings"]["Networks"]))
        command = ["docker","run","--rm","--name","valoria-uf-calendar-job","--network",network,"--memory=384m","--memory-swap=384m",
                   "--cpus=0.25","--pids-limit=96","--cap-drop=ALL","--security-opt=no-new-privileges",
                   "--read-only","--tmpfs","/tmp:rw,nosuid,nodev,size=32m","--env-file",filename,
                   "--entrypoint","python",image,"-B","scripts/refresh_ingestion_uf.py"]
        result = subprocess.run(command,capture_output=True,text=True,timeout=150)
        # Refresh emits structured counters/error only; summarize defensively rather than arbitrary output.
        for line in result.stdout.splitlines()[-5:]:
            try:
                report=json.loads(line)
            except ValueError:
                continue
            if isinstance(report,dict):
                safe = {"exit_code":result.returncode,"calendar_days_saved":report.get("calendar_days_saved",0),
                        "error_types":[str(x)[:60] for x in report.get("errors",[]) if str(x).isidentifier()]}
                if "error" in report:
                    safe["error"] = sanitize_error(report["error"])
                print(json.dumps(safe))
        return result.returncode
    except subprocess.TimeoutExpired:
        subprocess.run(["docker","stop","--time","10","valoria-uf-calendar-job"],capture_output=True,timeout=20)
        print(json.dumps({"exit_code":124,"error_type":"TimeoutExpired"}))
        return 124
    finally:
        os.unlink(filename)


if __name__ == "__main__":
    raise SystemExit(main())
