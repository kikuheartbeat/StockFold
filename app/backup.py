from contextlib import closing
from datetime import datetime
import json
import os
from pathlib import Path
import sqlite3
import uuid
from .db import SCHEMA_VERSION,SCHEMA,SCHEMA_V1,connect,initialize
from .validation import ValidationError,valid_date

REQUIRED={'sectors','stocks','daily_returns','daily_accounts','day_status','ledger_entries','import_batches','import_rows','app_settings','change_log'}

def create_backup(conn,backup_dir):
    folder=Path(backup_dir).resolve();folder.mkdir(parents=True,exist_ok=True)
    path=folder/f'stockfold-{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}.sqlite3'
    with closing(sqlite3.connect(path)) as target: conn.backup(target)
    return path

def validate_backup(content):
    if not isinstance(content,bytes) or not content.startswith(b'SQLite format 3\x00') or len(content)>32*1024*1024:
        raise ValidationError('请选择有效且小于32MB的 StockFold 数据库备份')
    try:
        with closing(sqlite3.connect(':memory:')) as conn:
            conn.deserialize(content)
            conn.execute('PRAGMA trusted_schema=OFF')
            if conn.execute('PRAGMA integrity_check').fetchone()[0]!='ok': raise ValidationError('备份完整性校验未通过')
            version=conn.execute('PRAGMA user_version').fetchone()[0]
            if version not in [1,SCHEMA_VERSION]: raise ValidationError('备份版本不兼容')
            tables={r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if not REQUIRED.issubset(tables): raise ValidationError('文件不是完整的 StockFold 备份')
            if conn.execute('PRAGMA foreign_key_check').fetchone(): raise ValidationError('备份中存在不完整的关联数据')
            if conn.execute("SELECT 1 FROM sqlite_master WHERE type IN ('trigger','view') LIMIT 1").fetchone(): raise ValidationError('备份包含不支持的数据库对象')
            # A version number alone does not guarantee compatible columns, constraints or indexes.
            with closing(sqlite3.connect(':memory:')) as reference:
                reference.executescript(SCHEMA_V1 if version==1 else SCHEMA)
                signature=lambda db:{(r[0],r[1],r[2],' '.join((r[3] or '').lower().split())) for r in db.execute("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_stat%'")}
                if signature(conn)!=signature(reference): raise ValidationError('备份表结构或约束不兼容')
            setting=conn.execute("SELECT value_json FROM app_settings WHERE key='record_start'").fetchone()
            if setting: valid_date(json.loads(setting[0]))
            conn.row_factory=sqlite3.Row
            from .analytics import build_dashboard
            from .returns import dates_between,local_today
            from .records import sector_list
            from .db import settings
            config=settings(conn);sector_list(conn)
            first=config.get('record_start','2026-01-01')
            dates_between(first,local_today())
            build_dashboard(conn,first,first)
            count=conn.execute('SELECT COUNT(*) FROM daily_returns').fetchone()[0]
            ledger=conn.execute('SELECT COUNT(*) FROM ledger_entries').fetchone()[0]
            stocks=conn.execute('SELECT COUNT(*) FROM stocks').fetchone()[0]
            return {'version':version,'record_count':count,'ledger_count':ledger,'stock_count':stocks,'bytes':len(content)}
    except ValidationError: raise
    except (sqlite3.DatabaseError,ValueError,TypeError,OverflowError) as e: raise ValidationError('备份校验失败，当前数据未改变') from e

def restore_backup(db_path,content,backup_dir):
    info=validate_backup(content)
    db_path=Path(db_path).resolve();db_path.parent.mkdir(parents=True,exist_ok=True)
    safety=None
    if db_path.exists():
        with closing(connect(db_path)) as current: safety=create_backup(current,backup_dir)
    temporary=db_path.parent/f'.restore-{uuid.uuid4().hex}.sqlite3'
    assert temporary.resolve().parent==db_path.parent
    try:
        temporary.write_bytes(content)
        with closing(connect(temporary)) as restored:
            initialize(restored,Path(__file__).resolve().parent.parent/'resources')
        os.replace(temporary,db_path)
    finally:
        if temporary.exists(): temporary.unlink()
    return {**info,'restored':True,'safety_backup':safety.name if safety else None}
