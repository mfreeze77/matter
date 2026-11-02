"""MAT-074 real history survives fixture upgrades and declared backup rollback."""
from contextlib import closing
from copy import copy, deepcopy
from hashlib import sha256
from pathlib import Path
import sqlite3
from unittest.mock import patch

from integration.delivery_helpers import DeliveryFixture
from integration.helpers import create_command, fixture, _in_scope
from matter.storage import SQLiteStore, StorageError, pin
from matter.contracts import ContractError
from matter.storage import migrations
from matter.controls import ControlService
from matter.budgets import BudgetService
from matter.versioning import migration_manifest, require_migration_manifest


class VersionMigration(DeliveryFixture):
    def rows(self,db):
        result={}
        for table in ('versions','heads','commands','watches'):
            count=len(db.execute('PRAGMA table_info('+table+')').fetchall())
            result[table]=db.execute('SELECT * FROM '+table+' ORDER BY '+','.join(str(i) for i in range(1,count+1))).fetchall()
        return result

    def test_episode_upgrade_interruption_and_backup_boundary_preserve_native_history(self):
        self.f.graph_monotonic=lambda:0.0
        _,_,authorization=self.authorize(identity='migration-unknown')
        def crash(_authorization):raise SystemExit('synthetic worker stopped before I/O')
        with self.assertRaises(SystemExit):self.service.send(authorization,before_io=crash)
        auth=self.f.storage.command_receipt('auth-migration-unknown')['result']['body']['authorization']
        unknown=self.service.history(auth)
        self.assertEqual(unknown['status'],'delivery_unknown')
        self.assertEqual(self.transport.calls,[])
        original_claim=pin(self.claim)
        corrected,claim,_,_=self.a.assess('migration-correction',signal='recovered',supersedes=[original_claim])
        self.assertIn(original_claim,claim['supersedes'])
        proposal=_in_scope(fixture('records/association_proposal__evaluation_failed.json'),self.f.storage.scope_id)
        proposal['id']='migration-unresolved'
        proposal.pop('creation_receipt',None)
        proposal.pop('revision',None)
        proposal['body']['subject']=pin(self.source)
        proposal['provenance']['recorded_at']=deepcopy(self.f.now)
        command=create_command('migration-association','migration-extra',scope_id=self.f.storage.scope_id)
        def insert(tx):
            tx.insert(proposal)
            return tx.success('created',{'matter':pin(tx.insert(tx.command['body']['matter']))})
        inserted=self.f.storage.execute(command,insert)
        self.assertEqual(inserted['status'],'success',inserted)
        reference={k:proposal[k] for k in ('scope_id','namespace','record_type','id')}
        original_proposal=self.f.storage.get(reference)
        self.assertEqual(original_proposal['body']['outcome'],'evaluation_failed')
        backup=Path(self.f.database).with_name('before-upgrade.sqlite')
        self.f.storage.backup_to(backup)
        database=Path(self.f.database)
        with closing(sqlite3.connect(database,isolation_level=None)) as db:
            before=self.rows(db)
            initial=migrations._registry()
            version=migrations.SCHEMA_VERSION+1
            sql=('CREATE TABLE fixture_future_feature (id INTEGER PRIMARY KEY, value TEXT);',)
            future=migrations._Migration(version,'fixture_future.sql',sha256(sql[0].encode()).hexdigest(),sql)
            with patch.object(migrations,'SCHEMA_VERSION',version),patch.object(migrations,'_migrations',return_value=initial+(future,)):
                manifest=migration_manifest()
                self.assertEqual(manifest['target_version'],version)
                self.assertEqual(require_migration_manifest(manifest),manifest)
                self.assertEqual(manifest['steps'][-1]['sha256'],future.checksum)
                def interrupt(stage):
                    if stage=='migration:before_commit':raise RuntimeError('synthetic pre-commit interruption')
                with self.assertRaises(RuntimeError):migrations.migrate(db,interrupt)
                self.assertEqual(self.rows(db),before)
                self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],version-1)
                migrations.migrate(db)
                migrations.check_database(db)
                self.assertEqual(self.rows(db),before)
                migrations.migrate(db) # exact installed migration is already applied
                self.assertEqual(self.rows(db),before)
            with self.assertRaises(ContractError) as incompatible:require_migration_manifest(manifest)
            self.assertEqual(incompatible.exception.code,'E_VERSION_UNSUPPORTED')
            with self.assertRaises(StorageError) as old_reader:migrations.check_database(db)
            self.assertEqual(old_reader.exception.code,'E_VERSION_UNSUPPORTED')
            with self.assertRaises(StorageError):migrations.migrate(db)
            self.assertEqual(self.rows(db),before)
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],version)
        # No down-migration or ledger editing. A new destination restores the
        # actual prior snapshot; the upgraded database remains unchanged.
        restored_path=database.with_name('restored-before-new-writes.sqlite')
        with SQLiteStore.restore_from(backup,restored_path,scope_id=self.f.storage.scope_id) as restored:
            self.assertEqual(restored.get(pin(claim)),claim)
            self.assertEqual(restored.get(pin(corrected)),corrected)
            self.assertEqual(restored.get(pin(original_proposal)),original_proposal)
            self.assertEqual(restored.command_receipt('auth-migration-unknown')['result']['body']['authorization'],auth)
            controls=ControlService(restored,policy=self.f.controls.policy,clock=lambda:deepcopy(self.f.now))
            assessments=copy(self.a.service.assessments)
            assessments.storage,assessments.controls=restored,controls
            attention=copy(self.a.service)
            attention.storage,attention.controls,attention.assessments=restored,controls,assessments
            budgets=BudgetService(restored,definitions=[self.definition],controls=controls,clock=lambda:deepcopy(self.f.now))
            restored_service=self.make_service(storage=restored,attention=attention,budgets=budgets,controls=controls)
            self.assertEqual(restored_service.history(auth),unknown)
        self.assertEqual(self.transport.calls,[])
