"""Bounded one-shot Portal job, reusing the current application image/network."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import shutil
try:
    from scripts.ingestion_launcher import summarize_process
except ModuleNotFoundError:
    from ingestion_launcher import summarize_process

ROOT = Path('/home/ubuntu/apps/valoria')
PATCH = ROOT / 'scripts/portal_session_runtime'
SESSION = ROOT / 'private/portal-session'

def main():
    circuit = SESSION / 'reauth_required.json'
    if circuit.exists():
        print(json.dumps({'session_reverification_required': True, 'portal_requests': 0}))
        return 75
    available_kb = next(int(line.split()[1]) for line in Path('/proc/meminfo').read_text().splitlines() if line.startswith('MemAvailable:'))
    if shutil.disk_usage(ROOT).free < 8 * 1024**3 or available_kb < 768 * 1024:
        print(json.dumps({'resource_reserve_required':True,'portal_requests':0}))
        return 75
    current = json.loads(subprocess.check_output(['docker','inspect','valoria_oracle_beta-api-1']))[0]
    network = next(iter(current['NetworkSettings']['Networks']))
    env = dict(x.split('=',1) for x in current['Config']['Env'])
    env.update(PORTAL_HTTP_ENABLED='true', PORTAL_SESSION_FILE='/portal-session/session.json',
               PYTHONDONTWRITEBYTECODE='1', PORTAL_GEO_DETAIL_BUDGET='5')
    fd, name = tempfile.mkstemp(prefix='valoria-portal-',suffix='.env')
    try:
        with os.fdopen(fd,'w') as stream:
            for key,value in env.items():
                if '\n' in value: raise ValueError('Multiline runtime environment unsupported')
                stream.write(key+'='+value+'\n')
        args = ['docker','run','--rm','--name','valoria-portal-session-job','--network',network,
                '--user',str(os.getuid())+':'+str(os.getgid()),
                '--memory=384m','--memory-swap=384m','--cpus=0.25','--pids-limit=96',
                '--cap-drop=ALL','--security-opt=no-new-privileges','--read-only',
                '--tmpfs','/tmp:rw,nosuid,nodev,size=32m','--env-file',name,
                '--volume',str(SESSION)+':/portal-session:rw']
        # Candidate image contains versioned acquisition code; never mount a stale host patch over it.
        args += ['--entrypoint','python',os.environ.get('VALORIA_INGESTION_IMAGE', current['Image']),'-B','scripts/portal_card_first.py']
        args += sys.argv[1:] or ['--apply','--max-pages','1','--max-details','5','--max-geo-details','5','--pause-s','3']
        result = subprocess.run(args,timeout=900,capture_output=True,text=True)
        safe = summarize_process(result)
        safe['at'] = int(time.time())
        safe['image_id'] = os.environ.get('VALORIA_INGESTION_IMAGE', current['Image'])
        report = safe['counts']
        print(json.dumps(safe,sort_keys=True))
        target = SESSION / 'last_run.json'
        with os.fdopen(os.open(target,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600),'w') as stream:
            json.dump(safe,stream)
        if report and (report.get('blocked_or_captcha') or report.get('geo_blocked') or report.get('geo_stopped')):
            with os.fdopen(os.open(circuit,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600),'w') as stream:
                json.dump({'at':int(time.time()),'reason':'official_reverification_required'},stream)
        return result.returncode
    except subprocess.TimeoutExpired:
        print(json.dumps({'runtime_error': True, 'error': {'type': 'TimeoutExpired', 'stage': 'container'}, 'exit_code': 124}))
        subprocess.run(['docker','stop','--time','10','valoria-portal-session-job'],capture_output=True)
        return 124
    finally:
        os.unlink(name)

if __name__ == '__main__': raise SystemExit(main())
