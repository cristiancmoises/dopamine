#!/usr/bin/env python3
"""Conservative, manifest-checked 1.0 / supported 1.1 -> 1.2 updater, invoked by apply.fish.

Only the Dopamine service is recreated. Existing .env and the live database are
never overwritten. Rollback restores source + an exact retained image, not an
older database snapshot. Interactive v1.2 history remains stored during a v1 rollback.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import argparse
import fcntl
import hashlib
import ipaddress
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile

VERSION='1.2.1'
IMAGE='dopamine-local:'+VERSION
PROJECT='dopamine'
ALIAS='dopamine-web'

class UpgradeError(RuntimeError): pass

def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):h.update(block)
    return h.hexdigest()

def safe_path(root, relative):
    p=PurePosixPath(relative)
    if not relative or p.is_absolute() or any(x in {'.','..',''} for x in p.parts):
        raise UpgradeError('Unsafe manifest path: '+relative)
    current=root
    for part in p.parts:
        current=current/part
        if current.is_symlink():raise UpgradeError('Symlink refused: '+str(current))
    if root.resolve() not in current.resolve().parents:
        raise UpgradeError('Path escapes target: '+relative)
    return current

def read_env(path):
    if path.is_symlink() or not path.is_file():raise UpgradeError('Regular .env file required.')
    values={}
    for line in path.read_text().splitlines():
        if not line.strip() or line.lstrip().startswith('#'):continue
        if '=' not in line:raise UpgradeError('Unsupported .env syntax; nothing changed.')
        key,value=line.split('=',1)
        if not re.fullmatch(r'[A-Z][A-Z0-9_]*',key) or key in values:
            raise UpgradeError('Duplicate or invalid .env key; nothing changed.')
        values[key]=value
    return values

def atomic_copy(source, destination, mode=None):
    destination.parent.mkdir(parents=True,exist_ok=True)
    if destination.is_symlink():raise UpgradeError('Refusing symlink destination.')
    fd,name=tempfile.mkstemp(prefix='.dopamine-copy-',dir=destination.parent)
    temporary=Path(name)
    try:
        with os.fdopen(fd,'wb') as out,source.open('rb') as src:
            shutil.copyfileobj(src,out);out.flush();os.fsync(out.fileno())
        os.chmod(temporary,mode if mode is not None else source.stat().st_mode&0o777)
        os.replace(temporary,destination)
    finally:temporary.unlink(missing_ok=True)

def private_json(path, value):
    with path.open('x',encoding='utf-8') as stream:
        json.dump(value,stream,ensure_ascii=False,indent=2);stream.write('\n')
    path.chmod(0o600)

def verify_manifest(bundle, target=None):
    manifest=json.loads((bundle/'manifest.json').read_text())
    if manifest.get('version')!=VERSION:raise UpgradeError('Unexpected bundle version.')
    entries=manifest.get('files',{})
    if not entries or 'compose.yaml' not in entries:raise UpgradeError('Incomplete manifest.')
    for name,entry in entries.items():
        source=safe_path(bundle/'release',name)
        if not source.is_file() or digest(source)!=entry['sha256']:
            raise UpgradeError('Bundle checksum mismatch: '+name)
        if target is not None:
            dest=safe_path(target,name)
            accepted=entry.get('old_sha256',[])
            if dest.exists():
                if not dest.is_file() or digest(dest) not in accepted+[entry['sha256']]:
                    raise UpgradeError('Local modifications detected; not overwritten: '+name)
            elif accepted and not entry.get('may_be_absent',False):
                raise UpgradeError('Baseline source file missing: '+name)
    if target is not None and manifest.get('baselines'):
        matched=[]
        for label,anchors in manifest['baselines'].items():
            if all(safe_path(target,name).is_file() and digest(safe_path(target,name)) in hashes for name,hashes in anchors.items()):matched.append(label)
        if not matched:raise UpgradeError('Source baseline is not a supported release. The conflicting early 1.1 archive is not overwritten.')
    return manifest

def run(args, *, cwd=None, capture=False, timeout=None, stdout=None):
    # Never log environment values, .env content or authentication form bodies.
    try:
        r=subprocess.run([str(a) for a in args],cwd=cwd,text=stdout is None,
                         stdout=stdout if stdout is not None else (subprocess.PIPE if capture else None),
                         stderr=subprocess.PIPE if capture else None,timeout=timeout,check=False)
    except (OSError,subprocess.TimeoutExpired) as exc:
        raise UpgradeError('Command unavailable or timed out: '+str(args[0])) from exc
    if r.returncode:
        if capture and r.stderr:print(r.stderr[:4000],file=sys.stderr)
        raise UpgradeError('Command failed ('+str(r.returncode)+'): '+' '.join(map(str,args[:6])))
    return r.stdout if capture else None

def inspect(kind,name):
    result=json.loads(run(['docker',kind,'inspect',name],capture=True,timeout=30))
    if len(result)!=1:raise UpgradeError('Ambiguous Docker object: '+name)
    return result[0]

def compose(target, override=None):
    result=['docker','compose','-p',PROJECT,'--project-directory',str(target),'-f',str(target/'compose.yaml')]
    if override:result+=['-f',str(override)]
    return result+['--env-file',str(target/'.env')]

@contextmanager
def lock_target(target):
    lock=target/'.dopamine-update.lock'
    if lock.is_symlink():raise UpgradeError('Unsafe update lock.')
    fd=os.open(lock,os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    try:
        try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise UpgradeError('Another Dopamine update is active.')
        yield
    finally:os.close(fd)

def resolve_live(target,npm_name):
    values=read_env(target/'.env')
    network=values.get('PROXY_NETWORK','')
    if network!='npm-bridge':raise UpgradeError('Keep the working npm-bridge network; no network migration is performed.')
    if not network or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,62}',network):
        raise UpgradeError('Keep the existing explicit PROXY_NETWORK in .env.')
    if values.get('SITE_URL')!='https://dopamine.securityops.co' or values.get('ALLOWED_HOSTS')!='dopamine.securityops.co':
        raise UpgradeError('This patch targets https://dopamine.securityops.co only.')
    if len(values.get('SECRET_KEY',''))<48:raise UpgradeError('Existing SECRET_KEY is missing/invalid; not regenerated.')
    app_id=run(compose(target)+['ps','-q','web'],capture=True,timeout=30).strip()
    if not app_id or '\n' in app_id:raise UpgradeError('Exactly one running Dopamine web container is required.')
    app=inspect('container',app_id);npm=inspect('container',npm_name)
    active_env=dict(item.split('=',1) for item in app.get('Config',{}).get('Env',[]) if '=' in item)
    for key in ('SECRET_KEY','SITE_URL','ALLOWED_HOSTS','TRUSTED_PROXY_CIDRS','PROXY_NETWORK'):
        if not values.get(key) or active_env.get(key)!=values[key]:
            raise UpgradeError(key+' differs between .env and the running container; no values were printed or changed.')
    if active_env.get('DATABASE_PATH')!='/data/dopamine.sqlite3':
        raise UpgradeError('Unexpected active DATABASE_PATH; refusing to point a new image at a different database.')
    labels=app.get('Config',{}).get('Labels') or {}
    if labels.get('com.docker.compose.project')!=PROJECT or labels.get('com.docker.compose.service')!='web':
        raise UpgradeError('Container is not the expected Compose service.')
    if not app['State']['Running'] or not npm['State']['Running']:
        raise UpgradeError('Both existing containers must be running.')
    if any(x in npm['Name'].lower() for x in ('rollback','backup','old-')):
        raise UpgradeError('A rollback NPM container cannot be selected.')
    if network not in app['NetworkSettings']['Networks'] or network not in npm['NetworkSettings']['Networks']:
        raise UpgradeError('Existing .env network is not shared by app and NPM; not changed automatically.')
    peer=npm['NetworkSettings']['Networks'][network]
    addresses=[peer.get('IPAddress'),peer.get('GlobalIPv6Address')]
    trusted=[]
    for item in values.get('TRUSTED_PROXY_CIDRS','').split(','):
        if not item:continue
        net=ipaddress.ip_network(item.strip(),strict=True)
        if net.prefixlen!=net.max_prefixlen:raise UpgradeError('Proxy trust must remain exact /32 or /128 addresses.')
        trusted.append(net)
    if not any(ipaddress.ip_address(ip) in net for ip in addresses if ip for net in trusted):
        raise UpgradeError('TRUSTED_PROXY_CIDRS does not include the actual NPM peer; nothing changed.')
    data=[m for m in app.get('Mounts',[]) if m['Destination']=='/data']
    if len(data)!=1 or data[0]['Type']!='volume':raise UpgradeError('Expected one named data volume at /data.')
    ports=app.get('HostConfig',{}).get('PortBindings') or {}
    if any(v for v in ports.values()):raise UpgradeError('Unexpected published app ports; refusing to replace custom topology.')
    return app,npm,network,data[0]['Name']

def backup_source(target, directory, entries):
    records={}
    for name,entry in entries.items():
        current=safe_path(target,name)
        rec={'new_sha256':entry['sha256'],'old_sha256':None,'old_mode':None}
        if current.exists():
            rec.update(old_sha256=digest(current),old_mode=current.stat().st_mode&0o777)
            atomic_copy(current,safe_path(directory/'source',name),mode=0o600)
        records[name]=rec
    return records

def validate_restore(target,directory,records):
    for name,rec in records.items():
        current=safe_path(target,name)
        if current.exists() and digest(current) not in {rec['new_sha256'],rec['old_sha256']}:
            raise UpgradeError('Modified since update; not overwritten by rollback: '+name)
        if rec['old_sha256']:
            saved=safe_path(directory/'source',name)
            if not saved.is_file() or digest(saved)!=rec['old_sha256']:
                raise UpgradeError('Backup integrity failed: '+name)

def restore_source(target,directory,records):
    validate_restore(target,directory,records)
    for name,rec in records.items():
        current=safe_path(target,name)
        if rec['old_sha256']:
            atomic_copy(safe_path(directory/'source',name),current,rec['old_mode'])
        elif current.exists():
            current.unlink()  # Only a manifest-owned new file with the checked hash.

def verify_sqlite(path):
    connection=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)
    try:
        if connection.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise UpgradeError('SQLite snapshot failed integrity_check.')
        if connection.execute('PRAGMA foreign_key_check').fetchall():raise UpgradeError('SQLite snapshot has broken foreign keys.')
    finally:connection.close()

def fetch_photos(app_id,stage):
    raise UpgradeError('Category-photo reuse is disabled in release 1.2.')

def rehearse_candidate(image,backup):
    rehearsal=backup/'migration-rehearsal';rehearsal.mkdir(mode=0o700)
    copy=rehearsal/'copy.sqlite3';shutil.copy2(backup/'database.sqlite3',copy)
    code="""from pathlib import Path
from app.db import initialize,connect
from app.real_photos import verify_photos
from contextlib import closing
p=Path('/rehearsal/copy.sqlite3')
initialize(p);initialize(p)
with closing(connect(p)) as c:
 assert c.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
 assert not c.execute('PRAGMA foreign_key_check').fetchall()
 assert c.execute("SELECT COUNT(*) FROM schema_features WHERE name='interactive_tables'").fetchone()[0]==1
print('Candidate migration copy and real catalog verified:',verify_photos())
"""
    run(['docker','run','--rm','--network','none','--user','0:0','--read-only',
         '--cap-drop','ALL','--security-opt','no-new-privileges:true',
         '--mount','type=bind,src='+str(rehearsal)+',dst=/rehearsal',
         '--entrypoint','python',image,'-c',code],timeout=180)
    verify_sqlite(copy)

def probe(npm_name,expected_version=None):
    code=r'''
const http=require("http");
async function get(path){return new Promise((resolve,reject)=>{
 const req=http.get({hostname:"dopamine-web",port:8000,path,headers:{Host:"dopamine.securityops.co","X-Forwarded-Proto":"https"}},res=>{
  let b="";res.on("data",c=>{b+=c;if(b.length>1000000)req.destroy(new Error("Response too large"));});
  res.on("end",()=>{
   if(res.statusCode!==200)return reject(new Error(path+" HTTP "+res.statusCode));
   if(process.argv[1] && res.headers["x-dopamine-version"]!==process.argv[1])return reject(new Error("Unexpected app version"));
   if(path==="/healthz" && (JSON.parse(b).service!=="dopamine" || JSON.parse(b).status!=="ok"))return reject(new Error("Wrong health response"));
   if(path==="/signup" && process.argv[1] && res.headers["referrer-policy"]!=="same-origin")return reject(new Error("Registration policy not applied"));
   console.log(path+": HTTP 200"+(res.headers["x-dopamine-version"]?" v"+res.headers["x-dopamine-version"]:""));resolve();
  });res.on("error",reject);
 });const deadline=setTimeout(()=>req.destroy(new Error("Request timeout")),12000);req.on("close",()=>clearTimeout(deadline));req.on("error",reject);
});}
(async()=>{for(const path of (process.argv[1]?["/healthz","/shop","/signup"]:["/healthz"]))await get(path);})().catch(e=>{console.error(e.message);process.exit(1);});
'''
    run(['docker','exec',npm_name,'node','-e',code,expected_version or ''],timeout=45)

def rollback(directory,automatic=False):
    directory=directory.resolve();meta=json.loads((directory/'rollback.json').read_text())
    target=Path(meta['target'])
    if not target.is_dir() or target.is_symlink():raise UpgradeError('Rollback target unavailable.')
    if digest(target/'.env')!=meta['env_sha256']:
        raise UpgradeError('.env changed since backup; not overwritten. Review before rollback.')
    # Verify retained exact image before touching any source.
    image=inspect('image',meta['rollback_image'])
    if image['Id']!=meta['image_id']:raise UpgradeError('Retained rollback image does not match snapshot.')
    restore_source(target,directory,meta['files'])
    override=directory/'rollback-compose.json'
    if not override.exists():private_json(override,{'services':{'web':{'image':meta['rollback_image']}}})
    run(compose(target,override)+['config','--quiet'],timeout=30)
    run(compose(target,override)+['up','-d','--no-deps','--no-build','--force-recreate','--wait','--wait-timeout','180','web'],timeout=240)
    live=run(compose(target,override)+['ps','-q','web'],capture=True,timeout=30).strip()
    active=inspect('container',live)
    volumes=[m['Name'] for m in active['Mounts'] if m['Destination']=='/data' and m['Type']=='volume']
    if volumes!=[meta['volume']]:raise UpgradeError('Rollback data volume verification failed.')
    probe(meta['npm'])
    print('ROLLBACK COMPLETE: original image/source, same .env and live data volume.')
    print('Interactive game history is preserved but hidden while an older release is running.')
    print('The SQLite snapshot was NOT restored. No newer activity was overwritten.')

def apply(bundle,target,npm_name,check_only=False):
    if not target.is_dir() or target.is_symlink():raise UpgradeError('Existing real deployment directory required.')
    manifest=verify_manifest(bundle,target)
    app,npm,network,volume=resolve_live(target,npm_name)
    env_hash=digest(target/'.env')
    print('Target:',target,'| app:',app['Name'].lstrip('/'),'| network:',network,'| volume:',volume,flush=True)
    probe(npm_name)
    if check_only:
        print('PREFLIGHT PASSED. No source, image, database, .env or containers changed.');return
    active_version=run(['docker','exec',app['Id'],'python','-c','from app import __version__; print(__version__)'],capture=True,timeout=30).strip()
    if active_version==VERSION:
        raise UpgradeError('Version '+VERSION+' is already running. No reapplication needed.')
    if active_version not in ('1.0.0','1.1.0'):
        raise UpgradeError('Only the original 1.0.0 or supported 1.1.0 source/runtime can be upgraded.')
    if shutil.disk_usage(target).free<2*1024**3:
        raise UpgradeError('At least 2 GiB free disk space required before build/snapshot.')
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    parent=target.parent/'dopamine-backups'
    if parent.is_symlink():raise UpgradeError('Unsafe backup directory.')
    parent.mkdir(mode=0o700,exist_ok=True);parent.chmod(0o700)
    backup=parent/stamp;backup.mkdir(mode=0o700)
    retained='dopamine-rollback:'+stamp.lower()
    run(['docker','image','tag',app['Image'],retained],timeout=30)
    records=backup_source(target,backup,manifest['files'])
    atomic_copy(target/'.env',backup/'.env.saved',0o600)
    atomic_copy(Path(__file__),backup/'updater.py',0o700)
    metadata={'version':VERSION,'target':str(target),'npm':npm_name,'network':network,'volume':volume,
              'image_id':app['Image'],'rollback_image':retained,'env_sha256':env_hash,'files':records}
    private_json(backup/'rollback.json',metadata)
    rollback_script='#!/usr/bin/env fish\nset -l here (dirname (status filename))\npython3 "$here/updater.py" --rollback "$here"\n'
    (backup/'rollback.fish').write_text(rollback_script);(backup/'rollback.fish').chmod(0o700)
    print('Backup directory:',backup,flush=True)
    print('Rollback command: fish '+str(backup/'rollback.fish'),flush=True)
    with (backup/'database.sqlite3').open('xb') as out:
        run(['docker','exec',app['Id'],'python','manage.py','backup','--stdout'],stdout=out,timeout=180)
        out.flush();os.fsync(out.fileno())
    (backup/'database.sqlite3').chmod(0o600);verify_sqlite(backup/'database.sqlite3')
    changed=False
    try:
        with tempfile.TemporaryDirectory(prefix='.dopamine-stage-',dir=target.parent) as temp:
            stage=Path(temp)/'release'
            shutil.copytree(bundle/'release',stage,ignore=shutil.ignore_patterns('__pycache__','*.pyc','.env','.env.*','.git'))
            # No .env or mutable user data enters the Docker build context.
            # Never carry the old 32 category illustrations into the real catalog.
            # BuildKit caches accepted public photos across failed/retried builds.
            print('Building '+IMAGE+'; current app remains running during build.',flush=True)
            run(['docker','build','--progress=plain','--tag',IMAGE,str(stage)])
            inspect('image',IMAGE)
            rehearse_candidate(IMAGE,backup)
            # Refuse a concurrent operator edit while the image was being built.
            verify_manifest(bundle,target)
            if digest(target/'.env')!=env_hash:raise UpgradeError('.env changed during build; deployment cancelled.')
            still=inspect('container',app['Id'])
            if not still['State']['Running']:raise UpgradeError('Original container changed during build; deployment cancelled.')
            changed=True
            for name,entry in manifest['files'].items():
                atomic_copy(safe_path(bundle/'release',name),safe_path(target,name),entry.get('mode',0o644))
            run(compose(target)+['config','--quiet'],timeout=30)
            print('Recreating only the Dopamine web service; brief interruption expected.',flush=True)
            run(compose(target)+['up','-d','--no-deps','--no-build','--force-recreate','--wait','--wait-timeout','180','web'],timeout=240)
            new_id=run(compose(target)+['ps','-q','web'],capture=True,timeout=30).strip()
            new=inspect('container',new_id)
            mounts=[m['Name'] for m in new['Mounts'] if m['Destination']=='/data' and m['Type']=='volume']
            if mounts!=[volume] or network not in new['NetworkSettings']['Networks']:
                raise UpgradeError('New container does not preserve expected volume/network.')
            if new['Image']!=inspect('image',IMAGE)['Id']:raise UpgradeError('Unexpected running image.')
            run(['docker','exec',new_id,'python','/app/scripts/healthcheck.py'],timeout=30)
            run(['docker','exec',new_id,'python','manage.py','verify-photos'],timeout=60)
            probe(npm_name,VERSION)
            # Export only public provenance/reports. The runtime image serves its
            # own verified immutable photographs; no old photos enter that image.
            for filename in ('catalog-import-report.json','catalog-live.json','photos-resolved.json'):
                run(['docker','cp',new_id+':/app/data/'+filename,str(backup/filename)],timeout=60)
                (backup/filename).chmod(0o600)
    except BaseException:
        if changed:
            print('UPDATE FAILED after source switch; attempting source/image rollback.',file=sys.stderr)
            try:rollback(backup,automatic=True)
            except BaseException as failure:
                print('AUTOMATIC ROLLBACK DID NOT COMPLETE: '+str(failure),file=sys.stderr)
                print('Preserved backup: '+str(backup),file=sys.stderr)
        else:print('Update stopped before source/container switch. Existing app left running.',file=sys.stderr)
        raise
    print('\nUPDATE COMPLETE: Dopamine '+VERSION)
    print('Same .env, network and data volume. NPM was not changed or restarted.')
    print('Internal upstream verified. Public DNS/TLS still need an external check:')
    print('curl --fail --silent --show-error -D - https://dopamine.securityops.co/healthz')
    print('Open a fresh /signup page; do not resubmit a form loaded before the update.')
    print('Rollback: fish '+str(backup/'rollback.fish'))

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle',type=Path,default=Path(__file__).resolve().parents[2])
    parser.add_argument('--target',type=Path,default=Path('/opt/dopamine'))
    parser.add_argument('--npm',default='npm-attachment')
    parser.add_argument('--check',action='store_true',help='read-only preflight; no deployment')
    parser.add_argument('--rollback',type=Path)
    args=parser.parse_args();os.umask(0o077)
    if not shutil.which('docker'):raise UpgradeError('Docker executable not found.')
    if args.rollback:
        meta=json.loads((args.rollback/'rollback.json').read_text())
        target=Path(meta['target'])
    else:target=args.target
    if target.is_symlink() or not target.is_dir():raise UpgradeError('Deployment directory missing or is a symlink.')
    target=target.resolve()
    with lock_target(target):
        if args.rollback:rollback(args.rollback)
        else:apply(args.bundle.resolve(),target,args.npm,args.check)
    return 0

if __name__=='__main__':
    print('This module is a shared updater helper. Use apply.fish or scripts/update_early11.py for this bridge.',file=sys.stderr)
    sys.exit(2)
    try:sys.exit(main())
    except (UpgradeError,OSError,ValueError,KeyError,sqlite3.Error) as exc:
        print('ERROR: '+str(exc),file=sys.stderr);sys.exit(1)
    except KeyboardInterrupt:
        print('Interrupted. Inspect the printed backup/rollback status.',file=sys.stderr);sys.exit(130)
