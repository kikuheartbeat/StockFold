from pathlib import Path
import sqlite3
import unittest
from .test_records import DatabaseFixture
from app.backup import create_backup,validate_backup,restore_backup
from app.records import save_day,get_day
from app.db import connect
from app.validation import ValidationError

class BackupTest(DatabaseFixture):
    def test_backup_restores_all_values_and_prebacks_up(self):
        save_day(self.conn,'2026-01-05',self.day(12345))
        folder=Path(self.tmp.name)/'backups'
        backup=create_backup(self.conn,folder)
        content=backup.read_bytes()
        self.assertEqual(validate_backup(content)['record_count'],1)
        save_day(self.conn,'2026-01-05',self.day(99999))
        db=Path(self.tmp.name)/'test.sqlite3'
        self.conn.close()
        result=restore_backup(db,content,folder)
        self.conn=connect(db)
        self.assertEqual(get_day(self.conn,'2026-01-05')['returns'][0]['pnl_cents'],12345)
        self.assertTrue((folder/result['safety_backup']).exists())

    def test_corruption_does_not_change_existing(self):
        with self.assertRaises(ValidationError): validate_backup(b'garbage')
        old=self.conn.execute('SELECT COUNT(*) FROM sectors').fetchone()[0]
        with self.assertRaises(ValidationError): restore_backup(Path(self.tmp.name)/'test.sqlite3',b'bad',Path(self.tmp.name)/'backups')
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM sectors').fetchone()[0],old)

    def test_incompatible_schema_and_version_cannot_replace_current(self):
        content=create_backup(self.conn,Path(self.tmp.name)/'backups').read_bytes()
        for mutation in ['ALTER TABLE stocks DROP COLUMN active','PRAGMA user_version=999',
                         'DROP INDEX sector_names']:
            with self.subTest(mutation=mutation):
                bad=sqlite3.connect(':memory:');bad.deserialize(content);bad.execute(mutation);bad.commit()
                invalid=bad.serialize();bad.close()
                with self.assertRaises(ValidationError): validate_backup(invalid)
                with self.assertRaises(ValidationError):
                    restore_backup(Path(self.tmp.name)/'test.sqlite3',invalid,Path(self.tmp.name)/'backups')
                self.assertEqual(self.conn.execute('SELECT active FROM stocks').fetchone()[0],1)

    def test_legacy_backup_upgrade_keeps_records(self):
        save_day(self.conn,'2026-01-05',self.day(123))
        old=sqlite3.connect(':memory:');old.deserialize(self.conn.serialize())
        for table in ['market_prices','market_sync','market_calendar','calendar_sync','opening_positions','calculation_days']:
            old.execute('DROP TABLE '+table)
        old.execute('PRAGMA user_version=1');old.commit();content=old.serialize();old.close()
        self.assertEqual(validate_backup(content)['version'],1)
        db=Path(self.tmp.name)/'test.sqlite3';self.conn.close()
        restore_backup(db,content,Path(self.tmp.name)/'backups');self.conn=connect(db)
        self.assertEqual(self.conn.execute('PRAGMA user_version').fetchone()[0],2)
        self.assertEqual(get_day(self.conn,'2026-01-05')['returns'][0]['pnl_cents'],123)

if __name__=='__main__': unittest.main()
