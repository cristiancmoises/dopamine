"""Bridge deployment state machine, real files/SQLite, simulated Docker adapter."""
from contextlib import ExitStack,closing
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import unittest
from unittest.mock import patch
from app.config import ROOT
from app import db
from app.schema_bridge import expected_objects
from scripts import update as u, update_early11 as bridge
from scripts.bridge_rehearsal import rehearse,fingerprint
from tests import test_updater as fixtures


class BridgeUpdaterTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.UpdaterTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        f=self.f
        entries=json.loads((f.bundle/'manifest.json').read_text())['files']
        sources={n:{'sha256':e['old_sha256'],'required':bool(e['old_sha256'])} for n,e in entries.items()}
        retired=f.target/'app/retired.py';retired.write_text('known retired helper')
        sources['app/retired.py']={'sha256':[u.digest(retired)],'required':True}
        m={'version':bridge.VERSION,'bridge':'early11-schema2-v1','files':entries,'sources':sources,'removed':{'app/retired.py':u.digest(retired)}}
        (f.bundle/'manifest.json').write_text(json.dumps(m));self.m=m
        f.snapshot.unlink()
        with closing(sqlite3.connect(f.snapshot)) as c:
            c.executescript((ROOT/'data/migrations/early11-core.sql').read_text())
            c.execute("INSERT INTO users(id,nickname,nickname_key,password_hash,recovery_hash,adult_confirmed,created_at) VALUES(1,'dummy','dummy','hash','recovery',1,1)")
            c.execute("INSERT INTO rounds VALUES('old-round',1,'roulette','old-key',100,100,'{}',1)");c.commit()
        self.failure='';self.marker=f.root/'marker';self.gate_events=[]
        self.expected_env=(f.target/'.env').read_bytes()

    def run(self,result=None):
        return super().run(result)

    def adapter(self,args,**kw):
        args=list(map(str,args));f=self.f
        if args[:2]==['docker','info']:return str(f.root)
        if args[:2]==['docker','compose'] and 'stop' in args:
            f.events.append(args);f.running='stopped';return
        if args[:2]==['docker','start']:
            f.events.append(args);f.running='old';return
        r=f.adapter(args,**kw)
        if args[:2]==['docker','compose'] and 'up' in args and f.running=='new':
            db.initialize(f.snapshot)
            if self.failure=='new-start':raise u.UpgradeError('Simulated new start failure')
        return r

    def gate(self,app_id,action,token):
        self.gate_events.append((action,app_id))
        if action=='set':self.marker.write_text(token)
        elif self.marker.exists():
            if self.marker.read_text()!=token:raise u.UpgradeError('Foreign gate')
            self.marker.unlink()

    def snapshot(self,image,volume,path):
        if self.failure=='final-snapshot' and 'cutover' in path.name:
            raise u.UpgradeError('Simulated final snapshot failure')
        shutil.copy2(self.f.snapshot,path);path.chmod(0o600);u.verify_sqlite(path)

    def rehearse(self,image,source,directory):
        directory.mkdir();copy=directory/'copy.sqlite3';shutil.copy2(source,copy);rehearse(copy)
        if self.failure=='final-rehearsal' and 'cutover' in directory.name:
            raise u.UpgradeError('Simulated final rehearsal failure')

    def invoke(self,check=False,rollback=None):
        f=self.f
        with ExitStack() as stack:
            stack.enter_context(patch.object(u,'run',side_effect=self.adapter))
            stack.enter_context(patch.object(u,'inspect',side_effect=f.inspector))
            stack.enter_context(patch.object(u,'probe',side_effect=f.probe))
            stack.enter_context(patch.object(bridge,'runtime_info',return_value={'user_version':2}))
            stack.enter_context(patch.object(bridge,'snapshot',side_effect=self.snapshot))
            stack.enter_context(patch.object(bridge,'rehearse',side_effect=self.rehearse))
            stack.enter_context(patch.object(bridge,'gate',side_effect=self.gate))
            stack.enter_context(patch.object(u.shutil,'disk_usage',return_value=u.shutil._ntuple_diskusage(20*1024**3,1024**3,19*1024**3)))
            if rollback:return bridge.rollback(rollback)
            return bridge.apply(f.bundle,f.target,'npm-attachment',check_only=check)

    def backup(self):return next((self.f.root/'dopamine-backups').iterdir())

    def assert_old(self):
        f=self.f
        self.assertEqual(f.running,'old');self.assertEqual((f.target/'.env').read_bytes(),self.expected_env)
        self.assertEqual((f.target/'compose.yaml').read_text(),'old compose');self.assertTrue((f.target/'app/retired.py').is_file())
        self.assertFalse(self.marker.exists())

    def test_preflight_no_switch_stop_snapshot_or_flag(self):
        self.invoke(check=True);self.assert_old()
        self.assertFalse((self.f.root/'dopamine-backups').exists());self.assertEqual(self.gate_events,[])

    def test_all_source_conflicts_reported_without_docker(self):
        (self.f.target/'app/example.py').write_text('private edit')
        (self.f.target/'compose.yaml').write_text('private network')
        with self.assertRaises(u.UpgradeError) as ctx:self.invoke()
        self.assertIn('app/example.py',str(ctx.exception));self.assertIn('compose.yaml',str(ctx.exception))
        self.assertEqual(self.f.events,[])

    def test_payload_corruption_rejected_before_docker(self):
        (self.f.release/'app/new.py').write_text('corruption')
        with self.assertRaisesRegex(u.UpgradeError,'Bundle checksum'):self.invoke()
        self.assertEqual(self.f.events,[])

    def test_build_failure_does_not_stop_or_gate_old_app(self):
        self.f.fail_build=True
        with self.assertRaises(u.UpgradeError):self.invoke()
        self.assert_old();self.assertEqual(self.gate_events,[])
        self.assertFalse(any('stop' in x or 'up' in x for x in self.f.events))

    def test_operator_env_edit_during_build_is_not_overwritten(self):
        self.f.change_env=True
        with self.assertRaisesRegex(u.UpgradeError,'.env changed'):self.invoke()
        self.assertIn('operator changed',(self.f.target/'.env').read_text())
        self.assertEqual(self.f.running,'old');self.assertEqual(self.gate_events,[])

    def test_failed_final_snapshot_restarts_original_and_clears_own_gate(self):
        self.failure='final-snapshot'
        with self.assertRaises(u.UpgradeError):self.invoke()
        self.assert_old();self.assertEqual([a for a,_ in self.gate_events],['set','clear'])

    def test_failed_final_rehearsal_keeps_live_schema_and_source(self):
        self.failure='final-rehearsal'
        with self.assertRaises(u.UpgradeError):self.invoke()
        self.assert_old()
        with closing(sqlite3.connect(self.f.snapshot)) as c:
            self.assertIsNone(c.execute("SELECT name FROM sqlite_master WHERE name='extra_rounds'").fetchone())

    def test_new_start_failure_rolls_back_without_replacing_database(self):
        self.failure='new-start'
        with self.assertRaises(u.UpgradeError):self.invoke()
        self.assert_old()
        with closing(sqlite3.connect(self.f.snapshot)) as c:
            self.assertEqual(c.execute('PRAGMA user_version').fetchone()[0],2)
            self.assertEqual(c.execute('SELECT id FROM rounds').fetchone()[0],'old-round')

    def test_new_probe_failure_rolls_back_retained_image_and_source(self):
        self.f.fail_probe=True
        with self.assertRaises(u.UpgradeError):self.invoke()
        self.assert_old();self.assertFalse((self.f.target/'app/new.py').exists())

    def test_success_preserves_volume_env_snapshots_and_opens_writes_last(self):
        self.invoke();f=self.f
        self.assertEqual(f.running,'new');self.assertFalse(self.marker.exists())
        self.assertEqual((f.target/'.env').read_bytes(),self.expected_env)
        self.assertFalse((f.target/'app/retired.py').exists())
        for name in ('database-before-build.sqlite3','database-at-cutover.sqlite3'):
            u.verify_sqlite(self.backup()/name)
        self.assertEqual([a for a,_ in self.gate_events],['set','clear'])
        self.assertEqual(self.gate_events[-1],('clear','new'))
        for event in f.events:
            self.assertNotIn('prune',event);self.assertNotIn('down',event);self.assertNotIn('restart',event)
            if 'up' in event:self.assertEqual(event[-1],'web');self.assertIn('--no-deps',event)
        with closing(db.connect(f.snapshot)) as c:self.assertEqual(c.execute('PRAGMA user_version').fetchone()[0],2)

    def test_manual_rollback_retains_activity_written_after_upgrade(self):
        self.invoke()
        with closing(db.connect(self.f.snapshot)) as c:
            c.execute("INSERT INTO extra_rounds VALUES('after-update',1,'bingo','after-key',500,100,100,'{}')")
        self.invoke(rollback=self.backup());self.assert_old()
        with closing(db.connect(self.f.snapshot)) as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM extra_rounds WHERE id='after-update'").fetchone()[0],1)

    def test_removed_baseline_file_is_backed_up_and_restored(self):
        self.invoke()
        self.assertEqual((self.backup()/'source/app/retired.py').read_text(),'known retired helper')
        self.invoke(rollback=self.backup())
        self.assertEqual((self.f.target/'app/retired.py').read_text(),'known retired helper')

    def test_runtime_mismatch_is_not_waived_by_source_match(self):
        core,after=expected_objects()
        m={'runtime_early':{'app/__init__.py':'required-sha'},'core_objects':core,'bridge_objects':after}
        value={'hashes':{'app/__init__.py':'other-sha'},'user_version':2,'objects':{},'features':{},'bytes':4096,'maintenance':False}
        with patch.object(u,'run',return_value=json.dumps(value)):
            with self.assertRaisesRegex(u.UpgradeError,'Running image differs'):bridge.runtime_info({'Id':'old'},m)

    def test_runtime_schema_integer_alone_is_not_accepted(self):
        core,after=expected_objects()
        m={'runtime_early':{},'core_objects':core,'bridge_objects':after}
        value={'hashes':{},'user_version':2,'objects':{},'features':{},'bytes':4096,'maintenance':False}
        with patch.object(u,'run',return_value=json.dumps(value)):
            with self.assertRaisesRegex(u.UpgradeError,'known early'):bridge.runtime_info({'Id':'old'},m)

    def test_snapshot_helper_includes_committed_uncheckpointed_wal(self):
        source=self.f.root/'wal.sqlite3'
        with closing(sqlite3.connect(source)) as writer:
            writer.execute('PRAGMA journal_mode=WAL')
            writer.execute('PRAGMA wal_autocheckpoint=0')
            writer.execute('CREATE TABLE sample(value TEXT)')
            writer.execute("INSERT INTO sample VALUES('committed-in-WAL')");writer.commit()
            self.assertTrue(Path(str(source)+'-wal').stat().st_size>0)
            code=bridge.SNAPSHOT_CODE.replace("Path('/data/dopamine.sqlite3')",'Path('+repr(str(source))+')')
            snapshot=self.f.root/'snapshot-from-helper.sqlite3'
            with snapshot.open('wb') as out:
                result=subprocess.run([sys.executable,'-I','-B','-c',code],stdout=out,stderr=subprocess.PIPE,timeout=20)
            self.assertEqual(result.returncode,0,result.stderr)
        with closing(sqlite3.connect(snapshot)) as c:
            self.assertEqual(c.execute('SELECT value FROM sample').fetchone()[0],'committed-in-WAL')

    def test_gate_helper_refuses_foreign_nonce_and_symlinks(self):
        marker=self.f.root/'test-maintenance-marker'
        code=bridge.GATE_CODE.replace("Path('/data/.dopamine-upgrading')",'Path('+repr(str(marker))+')')
        def run(action,token):
            return subprocess.run([sys.executable,'-I','-B','-c',code,action,token],capture_output=True,timeout=10)
        self.assertEqual(run('set','owner').returncode,0)
        self.assertNotEqual(run('set','other').returncode,0)
        self.assertNotEqual(run('clear','other').returncode,0)
        self.assertEqual(marker.read_text(),'owner')
        self.assertEqual(run('clear','owner').returncode,0);self.assertFalse(marker.exists())
        private=self.f.root/'private';private.write_text('do not change')
        marker.symlink_to(private)
        self.assertNotEqual(run('clear','do not change').returncode,0)
        self.assertEqual(private.read_text(),'do not change')
