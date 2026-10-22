import colorsys
import json
from pathlib import Path
import sqlite3

SCHEMA_VERSION=2

def connect(db_path):
    db_path=Path(db_path)
    db_path.parent.mkdir(parents=True,exist_ok=True)
    conn=sqlite3.connect(str(db_path),timeout=15)
    conn.row_factory=sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    return conn

SCHEMA_V1='''
CREATE TABLE IF NOT EXISTS sectors (
 id INTEGER PRIMARY KEY, name TEXT NOT NULL, level INTEGER NOT NULL CHECK(level IN (1,2)),
 parent_id INTEGER REFERENCES sectors(id), color TEXT NOT NULL,
 source TEXT DEFAULT '', source_checked_at TEXT DEFAULT '',
 CHECK((level=1 AND parent_id IS NULL) OR (level=2 AND parent_id IS NOT NULL)));
CREATE UNIQUE INDEX IF NOT EXISTS sector_names ON sectors(COALESCE(parent_id,0),name);
CREATE TABLE IF NOT EXISTS stocks (
 id INTEGER PRIMARY KEY, code TEXT NOT NULL, name TEXT NOT NULL, market TEXT NOT NULL DEFAULT '',
 asset_type TEXT NOT NULL DEFAULT 'stock' CHECK(asset_type IN ('stock','etf','product')),
 sector_id INTEGER REFERENCES sectors(id), fund_category TEXT DEFAULT '', fund_theme TEXT DEFAULT '',
 classification_status TEXT DEFAULT 'unclassified', active INTEGER NOT NULL DEFAULT 1,
 UNIQUE(market,code));
CREATE TABLE IF NOT EXISTS daily_returns (
 id INTEGER PRIMARY KEY,date TEXT NOT NULL,stock_id INTEGER NOT NULL REFERENCES stocks(id),
 pnl_cents INTEGER NOT NULL,source TEXT NOT NULL DEFAULT 'manual',note TEXT DEFAULT '',
 updated_at TEXT DEFAULT CURRENT_TIMESTAMP,UNIQUE(date,stock_id));
CREATE TABLE IF NOT EXISTS daily_accounts (
 date TEXT PRIMARY KEY,total_assets_cents INTEGER,cash_cents INTEGER,
 other_pnl_cents INTEGER NOT NULL DEFAULT 0,note TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS day_status (
 date TEXT PRIMARY KEY,status TEXT NOT NULL CHECK(status IN ('draft','confirmed','skip')),
 expected_stock_ids TEXT NOT NULL DEFAULT '[]',note TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS import_batches (
 id INTEGER PRIMARY KEY,file_name TEXT NOT NULL,file_hash TEXT NOT NULL UNIQUE,
 imported_at TEXT DEFAULT CURRENT_TIMESTAMP,record_count INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS import_rows (
 id INTEGER PRIMARY KEY,batch_id INTEGER NOT NULL REFERENCES import_batches(id),row_number INTEGER NOT NULL,
 raw_json TEXT NOT NULL,normalized_json TEXT NOT NULL,UNIQUE(batch_id,row_number));
CREATE TABLE IF NOT EXISTS ledger_entries (
 id INTEGER PRIMARY KEY,date TEXT NOT NULL,sequence INTEGER NOT NULL DEFAULT 0,
 stock_id INTEGER REFERENCES stocks(id),kind TEXT NOT NULL CHECK(kind IN ('buy','sell','deposit','withdraw','other')),
 quantity INTEGER NOT NULL DEFAULT 0,price_decimal TEXT NOT NULL DEFAULT '0',amount_cents INTEGER NOT NULL DEFAULT 0,
 cash_change_cents INTEGER NOT NULL DEFAULT 0,fees_cents INTEGER NOT NULL DEFAULT 0,fees_json TEXT DEFAULT '{}',
 summary TEXT DEFAULT '',note TEXT DEFAULT '',import_row_id INTEGER UNIQUE REFERENCES import_rows(id));
CREATE TABLE IF NOT EXISTS app_settings (key TEXT PRIMARY KEY,value_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS change_log (
 id INTEGER PRIMARY KEY,entity TEXT,entity_id TEXT,action TEXT,before_json TEXT,after_json TEXT,
 created_at TEXT DEFAULT CURRENT_TIMESTAMP);
'''

SCHEMA=SCHEMA_V1+'''
CREATE TABLE IF NOT EXISTS market_prices (
 stock_id INTEGER NOT NULL REFERENCES stocks(id),date TEXT NOT NULL,close_decimal TEXT NOT NULL,
 source TEXT NOT NULL,fetched_at TEXT DEFAULT CURRENT_TIMESTAMP,PRIMARY KEY(stock_id,date));
CREATE TABLE IF NOT EXISTS market_sync (
 stock_id INTEGER PRIMARY KEY REFERENCES stocks(id),start_date TEXT NOT NULL,end_date TEXT NOT NULL,
 source TEXT NOT NULL,updated_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS market_calendar (
 date TEXT PRIMARY KEY,source TEXT NOT NULL,updated_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS calendar_sync (
 id INTEGER PRIMARY KEY CHECK(id=1),start_date TEXT NOT NULL,end_date TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS opening_positions (
 stock_id INTEGER PRIMARY KEY REFERENCES stocks(id),quantity INTEGER NOT NULL CHECK(quantity>=0),note TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS calculation_days (
 date TEXT PRIMARY KEY,run_id TEXT NOT NULL,updated_at TEXT DEFAULT CURRENT_TIMESTAMP);
'''

def color_for(hue,lightness=.46,saturation=.62):
    rgb=colorsys.hls_to_rgb((hue%360)/360,lightness,saturation)
    return '#'+''.join(f'{round(c*255):02X}' for c in rgb)

def industry_palette(resources_dir=None):
    path=Path(resources_dir or Path(__file__).resolve().parent.parent/'resources')/'industry_palette.json'
    return json.loads(path.read_text(encoding='utf8'))

def initialize(conn,resources_dir):
    version=conn.execute('PRAGMA user_version').fetchone()[0]
    if version>SCHEMA_VERSION: raise ValueError('数据库版本较新，请使用对应版本程序')
    conn.executescript(SCHEMA)
    catalog=Path(resources_dir)/'industry_catalog.json'
    if catalog.exists():
        data=json.loads(catalog.read_text(encoding='utf8'))
        palette=industry_palette(resources_dir)
        colors={item['name']:item['color'] for group in palette['groups'] for item in group['industries']}
        with conn:
            for i,industry in enumerate(data['industries']):
                color=colors[industry['name']]
                conn.execute('INSERT OR IGNORE INTO sectors(name,level,parent_id,color,source,source_checked_at) VALUES (?,1,NULL,?,?,?)',
                             (industry['name'],color,'大盘云图',data['retrieved_date']))
                parent=conn.execute('SELECT id FROM sectors WHERE level=1 AND name=?',(industry['name'],)).fetchone()[0]
                for j,child in enumerate(industry['second_level']):
                    conn.execute('INSERT OR IGNORE INTO sectors(name,level,parent_id,color,source,source_checked_at) VALUES (?,2,?,?,?,?)',
                                 (child['name'],parent,color,'大盘云图',data['retrieved_date']))
            current=conn.execute("SELECT value_json FROM app_settings WHERE key='industry_color_scheme'").fetchone()
            if not current or json.loads(current[0])!=palette['version']:
                for name,color in colors.items():
                    conn.execute('UPDATE sectors SET color=? WHERE name=? AND level=1',(color,name))
                conn.execute("INSERT INTO app_settings VALUES ('industry_color_scheme',?) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",(json.dumps(palette['version']),))
            conn.execute('UPDATE sectors SET color=(SELECT p.color FROM sectors p WHERE p.id=sectors.parent_id) WHERE level=2')
    with conn:
        conn.execute('INSERT OR IGNORE INTO app_settings VALUES (?,?)',('record_start',json.dumps('2026-01-01')))
        conn.execute(f'PRAGMA user_version={SCHEMA_VERSION}')

def settings(conn):
    return {r['key']:json.loads(r['value_json']) for r in conn.execute('SELECT * FROM app_settings')}

def audit(conn,entity,entity_id,action,before=None,after=None):
    dump=lambda x:json.dumps(x,ensure_ascii=False,default=str) if x is not None else None
    conn.execute('INSERT INTO change_log(entity,entity_id,action,before_json,after_json) VALUES (?,?,?,?,?)',
                 (entity,str(entity_id),action,dump(before),dump(after)))
