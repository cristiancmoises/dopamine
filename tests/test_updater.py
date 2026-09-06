"""Updater filesystem/rollback tests with a deterministic Docker adapter double.

These exercise the real staging/backup/restore functions but DO NOT run Docker.
The separate image build still reruns application tests on the operator's VPS.
"""
from copy import deepcopy
from contextlib import redirect_stdout, redirect_stderr
import io
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import json
import sqlite3
import unittest
from scripts import update as u

class UpdaterTests(unittest.TestCase):
    def setUp(self):
        output=io.StringIO()
        out=redirect_stdout(output);err=redirect_stderr(output)
        out.__enter__();err.__enter__()
        self.addCleanup(out.__exit__,None,None,None);self.addCleanup(err.__exit__,None,None,None)
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.target=self.root/'dopamine';self.target.mkdir()
        self.bundle=self.root/'bundle';self.release=self.bundle/'release';self.release.mkdir(parents=True)
        (self.target/'.env').write_text('SECRET_KEY='+('safe-unit-test-'*6)+'\nSITE_URL=https://dopamine.securityops.co\nALLOWED_HOSTS=dopamine.securityops.co\nPROXY_NETWORK=npm-bridge\nTRUSTED_PROXY_CIDRS=172.18.0.2/32\n')
        entries={}
        for name,before,after in [('compose.yaml','old compose','new compose'),('app/example.py','old source','new source'),('app/new.py',None,'new module')]:
            dest=self.target/name;src=self.release/name;src.parent.mkdir(exist_ok=True,parents=True);src.write_text(after)
            previous=[]
            if before is not None:
                dest.parent.mkdir(exist_ok=True,parents=True);dest.write_text(before);previous=[u.digest(dest)]
            entries[name]={'sha256':u.digest(src),'old_sha256':previous,'mode':0o644}
        (self.bundle/'manifest.json').write_text(json.dumps({'version':u.VERSION,'files':entries}))
        self.entries=entries;self.running='old';self.events=[];self.fail_build=False;self.fail_probe=False
        self.change_env=False
        self.base={'Id':'old','Name':'/dopamine-web-1','Image':'sha256:old',
            'State':{'Running':True},'Config':{'Labels':{'com.docker.compose.project':'dopamine','com.docker.compose.service':'web'}},
            'NetworkSettings':{'Networks':{'npm-bridge':{'IPAddress':'172.18.0.7'}}},
            'Mounts':[{'Destination':'/data','Type':'volume','Name':'dopamine_dopamine-data'}],
            'HostConfig':{'PortBindings':{}}}
        self.base['Config']['Env']=[line for line in (self.target/'.env').read_text().splitlines() if '=' in line]+['DATABASE_PATH=/data/dopamine.sqlite3']
        self.npm={'Id':'npm','Name':'/npm-attachment','State':{'Running':True},
            'NetworkSettings':{'Networks':{'npm-bridge':{'IPAddress':'172.18.0.2','GlobalIPv6Address':''}}}}
        self.snapshot=self.root/'snapshot.sqlite3'
        c=sqlite3.connect(self.snapshot);c.execute('CREATE TABLE sentinel(value TEXT)');c.execute("INSERT INTO sentinel VALUES('live-data')");c.commit();c.close()
    def adapter(self,args,**kw):
        args=list(map(str,args));self.events.append(args)
        if args[:2]==['docker','cp']:
            Path(args[-1]).write_text('{}')
        if args[:2]==['docker','build']:
            if self.change_env:(self.target/'.env').write_text((self.target/'.env').read_text()+'# operator changed\n')
            if self.fail_build:raise u.UpgradeError('Simulated build failure')
        if args[:2]==['docker','exec']:
            if args[-1]=='--stdout':kw['stdout'].write(self.snapshot.read_bytes())
            if args[-2]=='-c':return '1.0.0\n'
        if args[:2]==['docker','compose']:
            if args[-3:]==['ps','-q','web']:return self.running+'\n'
            if 'up' in args:
                self.running='old' if any(x.endswith('rollback-compose.json') for x in args) else 'new'
        return '' if kw.get('capture') else None
    def inspector(self,kind,name):
        if kind=='image':return {'Id':'sha256:new' if name==u.IMAGE else 'sha256:old'}
        if name=='npm-attachment':return deepcopy(self.npm)
        if name=='old':return deepcopy(self.base)
        if name=='new':
            item=deepcopy(self.base);item.update(Id='new',Image='sha256:new');return item
        raise AssertionError((kind,name))
    def photos(self,app_id,stage):
        folder=stage/'app/static/photos';folder.mkdir(parents=True,exist_ok=True)
        (folder/'fixture.webp').write_bytes(b'photo-fixture')
        (stage/'data').mkdir(exist_ok=True);(stage/'data/photos-resolved.json').write_text('{}')
    def probe(self,name,version=None):
        if version and self.fail_probe:raise u.UpgradeError('Simulated upstream failure')
    def apply(self,check=False):
        with patch.object(u,'run',side_effect=self.adapter),patch.object(u,'inspect',side_effect=self.inspector),patch.object(u,'rehearse_candidate'),patch.object(u,'probe',side_effect=self.probe),patch.object(u.shutil,'disk_usage',return_value=u.shutil._ntuple_diskusage(20*1024**3,1024**3,19*1024**3)):
            return u.apply(self.bundle,self.target,'npm-attachment',check_only=check)

    def test_manifest_rejects_local_modification_before_docker(self):
        (self.target/'app/example.py').write_text('operator custom')
        with self.assertRaises(u.UpgradeError):self.apply()
        self.assertEqual(self.events,[])
        self.assertEqual((self.target/'app/example.py').read_text(),'operator custom')

    def test_manifest_rejects_corrupt_release(self):
        (self.release/'app/new.py').write_text('tampered')
        with self.assertRaises(u.UpgradeError):u.verify_manifest(self.bundle,self.target)

    def test_manifest_rejects_unexpected_new_file_collision(self):
        (self.target/'app/new.py').write_text('unrelated private file')
        with self.assertRaises(u.UpgradeError):u.verify_manifest(self.bundle,self.target)

    def test_safe_paths_reject_traversal_and_symlinks(self):
        for name in ('../escape','/absolute','x/../../escape',''):
            with self.assertRaises(u.UpgradeError):u.safe_path(self.target,name)
        (self.target/'link').symlink_to(self.root,target_is_directory=True)
        with self.assertRaises(u.UpgradeError):u.safe_path(self.target,'link/escape')

    def test_duplicate_env_rejected(self):
        with (self.target/'.env').open('a') as s:s.write('PROXY_NETWORK=other\n')
        with self.assertRaises(u.UpgradeError):u.read_env(self.target/'.env')

    def test_preflight_does_not_switch_source_or_containers(self):
        original=(self.target/'.env').read_bytes();self.apply(check=True)
        self.assertEqual((self.target/'.env').read_bytes(),original)
        self.assertEqual((self.target/'compose.yaml').read_text(),'old compose')
        self.assertFalse((self.root/'dopamine-backups').exists())
        self.assertEqual(self.running,'old')

    def test_rejects_proxy_trust_mismatch(self):
        self.npm['NetworkSettings']['Networks']['npm-bridge']['IPAddress']='172.18.0.99'
        with self.assertRaises(u.UpgradeError):self.apply()
        self.assertEqual(self.running,'old')

    def test_rejects_bind_mount_and_public_ports(self):
        self.base['Mounts'][0]['Type']='bind'
        with self.assertRaises(u.UpgradeError):self.apply()
        self.base['Mounts'][0]['Type']='volume';self.base['HostConfig']['PortBindings']={'8000/tcp':[{'HostPort':'8000'}]}
        with self.assertRaises(u.UpgradeError):self.apply()

    def test_failed_build_leaves_live_source_and_container_unchanged(self):
        self.fail_build=True;original=(self.target/'.env').read_bytes()
        with self.assertRaises(u.UpgradeError):self.apply()
        self.assertEqual(self.running,'old')
        self.assertEqual((self.target/'compose.yaml').read_text(),'old compose')
        self.assertEqual((self.target/'.env').read_bytes(),original)
        backup=next((self.root/'dopamine-backups').iterdir())
        self.assertTrue((backup/'database.sqlite3').is_file())
        self.assertFalse(any('up' in args for args in self.events))

    def test_operator_env_edit_during_build_cancels_switch(self):
        self.change_env=True
        with self.assertRaises(u.UpgradeError):self.apply()
        self.assertEqual(self.running,'old')
        self.assertEqual((self.target/'compose.yaml').read_text(),'old compose')
        self.assertIn('operator changed',(self.target/'.env').read_text())

    def test_success_preserves_env_and_records_private_verified_backup(self):
        original=(self.target/'.env').read_bytes();self.apply()
        self.assertEqual(self.running,'new');self.assertEqual((self.target/'compose.yaml').read_text(),'new compose')
        self.assertEqual((self.target/'.env').read_bytes(),original)
        backup=next((self.root/'dopamine-backups').iterdir())
        self.assertEqual((backup/'.env.saved').read_bytes(),original)
        self.assertEqual((backup/'.env.saved').stat().st_mode&0o777,0o600)
        self.assertEqual((backup/'database.sqlite3').stat().st_mode&0o777,0o600)
        u.verify_sqlite(backup/'database.sqlite3')
        for args in self.events:
            self.assertFalse(any(x in args for x in ('prune','down','restart','network','rm')))
            if 'up' in args:
                self.assertIn('--no-deps',args);self.assertIn('--no-build',args);self.assertEqual(args[-1],'web')
        self.assertNotIn('SECRET_KEY',' '.join(' '.join(a) for a in self.events))

    def test_post_switch_failure_automatically_restores_original_image_and_source(self):
        self.fail_probe=True;original=(self.target/'.env').read_bytes();snapshot=self.snapshot.read_bytes()
        with self.assertRaises(u.UpgradeError):self.apply()
        self.assertEqual(self.running,'old');self.assertEqual((self.target/'compose.yaml').read_text(),'old compose')
        self.assertEqual((self.target/'app/example.py').read_text(),'old source')
        self.assertFalse((self.target/'app/new.py').exists())
        self.assertEqual((self.target/'.env').read_bytes(),original)
        self.assertEqual(self.snapshot.read_bytes(),snapshot)
        self.assertEqual(sum('up' in a for a in self.events),2)

    def test_rollback_refuses_subsequent_custom_source_edits(self):
        saved=self.root/'saved';saved.mkdir()
        records=u.backup_source(self.target,saved,self.entries)
        (self.target/'compose.yaml').write_text('new operator edit')
        with self.assertRaises(u.UpgradeError):u.restore_source(self.target,saved,records)
        self.assertEqual((self.target/'compose.yaml').read_text(),'new operator edit')

    def test_rollback_rejects_corrupt_snapshot_files(self):
        saved=self.root/'saved';saved.mkdir();records=u.backup_source(self.target,saved,self.entries)
        (saved/'source/compose.yaml').write_text('corrupt')
        with self.assertRaises(u.UpgradeError):u.restore_source(self.target,saved,records)

    def test_only_one_updater_can_hold_lock(self):
        with u.lock_target(self.target):
            with self.assertRaises(u.UpgradeError):
                with u.lock_target(self.target):pass

    def test_running_secret_must_match_env_file_without_printing_values(self):
        self.base['Config']['Env']=[('SECRET_KEY=other-secret-not-to-print' if v.startswith('SECRET_KEY=') else v) for v in self.base['Config']['Env']]
        with self.assertRaises(u.UpgradeError) as caught:self.apply()
        self.assertIn('SECRET_KEY differs',str(caught.exception))
        self.assertNotIn('other-secret-not-to-print',str(caught.exception))
        self.assertEqual(self.running,'old')

    def test_active_database_path_cannot_change_silently(self):
        self.base['Config']['Env']=[('DATABASE_PATH=/data/custom.sqlite3' if v.startswith('DATABASE_PATH=') else v) for v in self.base['Config']['Env']]
        with self.assertRaises(u.UpgradeError):self.apply()
        self.assertFalse((self.root/'dopamine-backups').exists())
