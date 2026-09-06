#!/usr/bin/env python3
"""Early 1.1/schema-2 -> 1.2.1 bridge; never restore an old database over live data."""
from datetime import datetime, timezone
from pathlib import Path
import argparse
import hashlib
import json
import os
import secrets
import shutil
import sqlite3
import sys
import tempfile
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts import update as u

VERSION='1.2.1'
IMAGE='dopamine-local:'+VERSION
MAX_DATABASE=128*1024*1024


def verify_bundle(bundle,target=None):
    m=json.loads((bundle/'manifest.json').read_text())
    if m.get('version')!=VERSION or m.get('bridge')!='early11-schema2-v1':
        raise u.UpgradeError('This is not the early-1.1/schema-2 bridge package')
    for name,entry in m['files'].items():
        p=u.safe_path(bundle/'release',name)
        if not p.is_file() or u.digest(p)!=entry['sha256']:
            raise u.UpgradeError('Bundle checksum mismatch: '+name)
    if target is not None:
        conflicts=[]
        for name,entry in m['sources'].items():
            p=u.safe_path(target,name)
            if not p.exists():
                if entry['required']:conflicts.append(name+' (missing)')
            elif not p.is_file() or u.digest(p) not in entry['sha256']:
                conflicts.append(name)
        if conflicts:
            raise u.UpgradeError('Unsupported source changes; nothing overwritten:\n'+'\n'.join(conflicts))
    return m


RUNTIME_CODE=r'''
from pathlib import Path
import hashlib,json,sqlite3,sys
from contextlib import closing
names=json.loads(sys.argv[1]);root=Path('/app'); hashes={}
for name in names:
 p=root/name
 if any(a.is_symlink() for a in (p,*p.parents)) or not p.is_file():
  raise SystemExit('Unsafe/missing image file: '+name)
 hashes[name]=hashlib.sha256(p.read_bytes()).hexdigest()
p=Path('/data/dopamine.sqlite3')
if p.is_symlink() or not p.is_file():raise SystemExit('Unsafe/missing active database')
with closing(sqlite3.connect(p.as_uri()+'?mode=ro',uri=True)) as c:
 c.execute('PRAGMA query_only=ON')
 version=c.execute('PRAGMA user_version').fetchone()[0]
 objs={n:[t,s] for n,t,s in c.execute("SELECT name,type,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' AND sql IS NOT NULL")}
 size=c.execute('PRAGMA page_count').fetchone()[0]*c.execute('PRAGMA page_size').fetchone()[0]
 features=dict(c.execute('SELECT name,revision FROM schema_features')) if 'schema_features' in objs else {}
print(json.dumps({'hashes':hashes,'user_version':version,'objects':objs,'features':features,'bytes':size,'maintenance':(p.parent/'.dopamine-upgrading').exists()}))
'''


def runtime_info(app,m,new=False,allow_gate=False):
    wanted=m['runtime_new' if new else 'runtime_early']
    text=u.run(['docker','exec',app['Id'],'python','-I','-B','-c',RUNTIME_CODE,json.dumps(list(wanted))],capture=True,timeout=60)
    value=json.loads(text)
    mismatched=[name for name,h in wanted.items() if value['hashes'].get(name)!=h]
    if mismatched:raise u.UpgradeError('Running image differs from the expected branch: '+','.join(mismatched))
    if value['user_version']!=2:raise u.UpgradeError('This bridge requires core user_version=2; no version number was changed')
    from app.schema_bridge import canonical
    actual={n:(v[0],canonical(v[1])) for n,v in value['objects'].items()}
    core={n:tuple(v) for n,v in m['core_objects'].items()}
    allowed={n:tuple(v) for n,v in m['bridge_objects'].items()}
    if any(actual.get(n)!=v for n,v in core.items()) or any(n not in allowed or v!=allowed[n] for n,v in actual.items()):
        raise u.UpgradeError('Active schema 2 is not the known early-1.1 layout')
    expected={'expanded_games':1,'interactive_tables':1,'early11_bridge':1}
    if any(expected.get(k)!=v for k,v in value['features'].items()):raise u.UpgradeError('Unknown schema feature')
    if new and not value['maintenance']:raise u.UpgradeError('Maintenance marker vanished before validation completed')
    if new and (value['features']!=expected or actual!=allowed):raise u.UpgradeError('Bridge incomplete in active database')
    if value['maintenance'] and not allow_gate:raise u.UpgradeError('Existing maintenance marker found; do not clear an unknown update lock')
    if value['bytes']>MAX_DATABASE:raise u.UpgradeError('Database exceeds this bridge snapshot limit of 128 MiB; not modified')
    return value


SNAPSHOT_CODE=r'''
from contextlib import closing
from pathlib import Path
import sqlite3,sys,tempfile,shutil
p=Path('/data/dopamine.sqlite3')
if p.is_symlink() or not p.is_file():raise SystemExit('Regular source database required')
with tempfile.TemporaryDirectory() as d:
 out=Path(d)/'snapshot.sqlite3'
 with closing(sqlite3.connect(p.as_uri()+'?mode=ro',uri=True,timeout=30)) as src, closing(sqlite3.connect(out)) as dst:
  src.execute('PRAGMA query_only=ON')
  size=src.execute('PRAGMA page_count').fetchone()[0]*src.execute('PRAGMA page_size').fetchone()[0]
  if size>128*1024*1024:raise SystemExit('Snapshot exceeds 128 MiB limit')
  src.backup(dst)
  if dst.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise SystemExit('Snapshot integrity failure')
  if dst.execute('PRAGMA foreign_key_check').fetchone():raise SystemExit('Snapshot foreign-key failure')
 with out.open('rb') as f:shutil.copyfileobj(f,sys.stdout.buffer)
'''


def snapshot(image,volume,destination):
    # Dedicated read-only mount + SQLite backup includes committed WAL content.
    with destination.open('xb') as out:
        u.run(['docker','run','--rm','--network','none','--read-only','--user','10001:10001',
               '--cap-drop','ALL','--security-opt','no-new-privileges:true','--pids-limit','64',
               '--memory','512m','--cpus','1','--tmpfs','/tmp:rw,noexec,nosuid,nodev,size=268435456,mode=1777',
               '--mount','type=volume,src='+volume+',dst=/data,readonly',
               '--entrypoint','python',image,'-I','-B','-c',SNAPSHOT_CODE],stdout=out,timeout=240)
        out.flush();os.fsync(out.fileno())
    destination.chmod(0o600);u.verify_sqlite(destination)


def rehearse(image,snapshot_path,directory):
    directory.mkdir(mode=0o700)
    copy=directory/'copy.sqlite3';shutil.copy2(snapshot_path,copy)
    # Only a snapshot copy is writable here. The live volume is never attached.
    u.run(['docker','run','--rm','--network','none','--read-only','--user','0:0',
           '--cap-drop','ALL','--security-opt','no-new-privileges:true',
           '--mount','type=bind,src='+str(directory)+',dst=/rehearsal',
           '--entrypoint','python',image,'/app/scripts/bridge_rehearsal.py','/rehearsal/copy.sqlite3'],timeout=240)
    u.verify_sqlite(copy)


GATE_CODE=r'''
from pathlib import Path
import os,sys
p=Path('/data/.dopamine-upgrading');action,token=sys.argv[1:]
if action=='set':
 fd=os.open(p,os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600)
 with os.fdopen(fd,'w') as f:f.write(token);f.flush();os.fsync(f.fileno())
elif action=='clear':
 if not p.exists() and not p.is_symlink():raise SystemExit(0)
 if p.is_symlink() or p.read_text()!=token:raise SystemExit('Maintenance marker not owned by this update')
 p.unlink()
else:raise SystemExit('Invalid gate action')
'''


def gate(app_id,action,token):
    u.run(['docker','exec',app_id,'python','-I','-B','-c',GATE_CODE,action,token],timeout=30)


def immutable_target(bundle,target,env_hash,records):
    verify_bundle(bundle,target)
    if u.digest(target/'.env')!=env_hash:raise u.UpgradeError('.env changed during build; no switch performed')
    for name,rec in records.items():
        p=u.safe_path(target,name)
        if (u.digest(p) if p.exists() else None)!=rec['old_sha256']:
            raise u.UpgradeError('Source changed during build: '+name)


def wait_for_upstream(npm):
    for attempt in range(12):
        try:
            u.probe(npm);return
        except u.UpgradeError:
            if attempt==11:raise
            time.sleep(2)


def rollback(directory):
    meta=json.loads((directory/'bridge-state.json').read_text())
    target=Path(meta['target'])
    # Generic helper verifies retained image ID, source hashes, env and volume.
    u.rollback(directory)
    active_id=u.run(u.compose(target,directory/'rollback-compose.json')+['ps','-q','web'],capture=True,timeout=30).strip()
    gate(active_id,'clear',meta['token'])
    print('BRIDGE ROLLBACK: same live database; original early-1.1 runtime restored; own maintenance marker cleared.')


def apply(bundle,target,npm,check_only=False):
    m=verify_bundle(bundle,target)
    app,proxy,network,volume=u.resolve_live(target,npm)
    env_hash=u.digest(target/'.env')
    info=runtime_info(app,m)
    u.probe(npm)
    print('CONFIRMED: early 1.1 image/source, core schema 2, npm-bridge. All source/runtime hashes checked.',flush=True)
    if check_only:
        print('PREFLIGHT PASSED: no application file, data row, .env or container changed.');return
    if shutil.disk_usage(target).free<2*1024**3:raise u.UpgradeError('At least 2 GiB free on the deployment filesystem is required')
    docker_root=u.run(['docker','info','--format','{{.DockerRootDir}}'],capture=True,timeout=30).strip()
    if not Path(docker_root).is_dir() or shutil.disk_usage(docker_root).free<2*1024**3:
        raise u.UpgradeError('At least 2 GiB free in the local Docker data filesystem is required')
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    parent=target.parent/'dopamine-backups'
    if parent.is_symlink():raise u.UpgradeError('Unsafe backup parent')
    parent.mkdir(mode=0o700,exist_ok=True);parent.chmod(0o700)
    backup=parent/('bridge121-'+stamp);backup.mkdir(mode=0o700)
    retained='dopamine-rollback:early11-'+stamp.lower()
    u.run(['docker','image','tag',app['Image'],retained],timeout=30)
    records=u.backup_source(target,backup,m['files'])
    for name,expected in m.get('removed',{}).items():
        current=u.safe_path(target,name)
        if not current.is_file() or u.digest(current)!=expected:
            raise u.UpgradeError('Removed baseline file changed: '+name)
        records[name]={'new_sha256':None,'old_sha256':expected,'old_mode':current.stat().st_mode&0o777}
        u.atomic_copy(current,u.safe_path(backup/'source',name),0o600)
    u.atomic_copy(target/'.env',backup/'.env.saved',0o600)
    # Retain the entire verified updater bundle, so rollback has its exact helper code.
    saved=backup/'bundle';shutil.copytree(bundle,saved,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    token=secrets.token_hex(24)
    meta={'version':VERSION,'target':str(target),'npm':npm,'network':network,'volume':volume,
          'image_id':app['Image'],'rollback_image':retained,'env_sha256':env_hash,'files':records}
    u.private_json(backup/'rollback.json',meta)
    u.private_json(backup/'bridge-state.json',{'target':str(target),'token':token})
    (backup/'rollback.fish').write_text('#!/usr/bin/env fish\nset -l here (dirname (status filename))\npython3 -I -B "$here/bundle/release/scripts/update_early11.py" --rollback "$here"\n')
    (backup/'rollback.fish').chmod(0o700)
    print('BACKUP: '+str(backup),flush=True)
    print('ROLLBACK: fish '+str(backup/'rollback.fish'),flush=True)
    snapshot(app['Image'],volume,backup/'database-before-build.sqlite3')
    gated=False;stopped=False;changed=False;opened=False
    try:
        with tempfile.TemporaryDirectory(prefix='.dopamine-bridge121-',dir=target.parent) as tmp:
            stage=Path(tmp)/'release'
            shutil.copytree(bundle/'release',stage,ignore=shutil.ignore_patterns('__pycache__','*.pyc','.env','.env.*','.git'))
            print('Building '+IMAGE+'; the current app stays available during build and photo import.',flush=True)
            u.run(['docker','build','--progress=plain','--tag',IMAGE,str(stage)])
            built=u.inspect('image',IMAGE)['Id']
            rehearse(built,backup/'database-before-build.sqlite3',backup/'rehearsal-before-stop')
            immutable_target(bundle,target,env_hash,records)
            current=u.inspect('container',app['Id'])
            if not current['State']['Running']:raise u.UpgradeError('Original container changed during build')
            runtime_info(current,m)
            gated=True
            gate(app['Id'],'set',token)
            print('MAINTENANCE: POST actions blocked; stopping only Dopamine for the final snapshot.',flush=True)
            # Mark intent before requesting stop so failure also restarts the old container.
            stopped=True
            u.run(u.compose(target)+['stop','-t','30','web'],timeout=90)
            snapshot(app['Image'],volume,backup/'database-at-cutover.sqlite3')
            rehearse(built,backup/'database-at-cutover.sqlite3',backup/'rehearsal-at-cutover')
            immutable_target(bundle,target,env_hash,records)
            changed=True
            for name,entry in m['files'].items():
                u.atomic_copy(u.safe_path(bundle/'release',name),u.safe_path(target,name),entry['mode'])
            for name in m.get('removed',{}):
                current=u.safe_path(target,name)
                if u.digest(current)!=records[name]['old_sha256']:
                    raise u.UpgradeError('Old owned file changed during switch: '+name)
                current.unlink()
            u.run(u.compose(target)+['config','--quiet'],timeout=30)
            u.run(u.compose(target)+['up','-d','--no-build','--no-deps','--force-recreate','--wait','--wait-timeout','180','web'],timeout=240)
            new_id=u.run(u.compose(target)+['ps','-q','web'],capture=True,timeout=30).strip()
            active=u.inspect('container',new_id)
            mounts=[x['Name'] for x in active['Mounts'] if x['Destination']=='/data' and x['Type']=='volume']
            if active['Image']!=built or mounts!=[volume] or network not in active['NetworkSettings']['Networks']:
                raise u.UpgradeError('New image/volume/network mismatch')
            runtime_info(active,m,new=True,allow_gate=True)
            if u.digest(target/'.env')!=env_hash:raise u.UpgradeError('.env changed during switch')
            u.run(['docker','exec',new_id,'python','manage.py','verify-photos'],timeout=180)
            u.probe(npm,VERSION)
            # Diagnostic reports are exported before reopening writes, not used as a release gate afterwards.
            for name in ('catalog-import-report.json','catalog-live.json','photos-resolved.json'):
                u.run(['docker','cp',new_id+':/app/data/'+name,str(backup/name)],timeout=60)
                (backup/name).chmod(0o600)
            gate(new_id,'clear',token);opened=True
    except BaseException:
        if not opened:
            try:
                if changed:
                    print('CUTOVER FAILED: restoring retained early-1.1 image/source, NOT a database snapshot.',file=sys.stderr)
                    rollback(backup)
                elif stopped or gated:
                    if stopped:u.run(['docker','start',app['Id']],timeout=90)
                    wait_for_upstream(npm)
                    gate(app['Id'],'clear',token)
                    print('Original app resumed; live database was not replaced.',file=sys.stderr)
                else:print('Stopped before cutover; current app left running.',file=sys.stderr)
            except BaseException as error:
                print('RECOVERY NEEDS ATTENTION: '+str(error),file=sys.stderr)
                print('Use the saved rollback command: fish '+str(backup/'rollback.fish'),file=sys.stderr)
        raise
    print('UPDATE COMPLETE: version 1.2.1, core user_version still 2, early11_bridge=1.')
    print('Accounts, old round JSON and purchase values were not rewritten; live volume and .env preserved.')
    print('Only internal NPM-to-app HTTP was verified here. Verify public HTTPS without -k.')
    print('Rollback: fish '+str(backup/'rollback.fish'))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--bundle',type=Path,default=Path(__file__).resolve().parents[2])
    p.add_argument('--target',type=Path,default=Path('/opt/dopamine'))
    p.add_argument('--npm',default='npm-attachment')
    p.add_argument('--check',action='store_true')
    p.add_argument('--rollback',type=Path)
    a=p.parse_args();os.umask(0o077)
    if not shutil.which('docker'):raise u.UpgradeError('Docker executable not found')
    if a.rollback:
        a.rollback=a.rollback.resolve()
        target=Path(json.loads((a.rollback/'bridge-state.json').read_text())['target'])
    else:target=a.target
    if target.is_symlink() or not target.is_dir():raise u.UpgradeError('Existing real deployment directory required')
    target=target.resolve()
    with u.lock_target(target):
        if a.rollback:rollback(a.rollback)
        else:apply(a.bundle.resolve(),target,a.npm,a.check)
    return 0


if __name__=='__main__':
    try:sys.exit(main())
    except (u.UpgradeError,OSError,ValueError,KeyError,sqlite3.Error,RuntimeError) as error:
        print('ERROR: '+str(error),file=sys.stderr);sys.exit(1)
    except KeyboardInterrupt:
        print('Interrupted. Review the printed backup/rollback status.',file=sys.stderr);sys.exit(130)
