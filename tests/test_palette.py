import colorsys
import json
from pathlib import Path
from .test_records import DatabaseFixture,ROOT
from app.db import initialize,industry_palette
from app.records import save_sector,save_stock,stock_list
from app.validation import sector_color,ValidationError
from app.analytics import build_dashboard

class PaletteTest(DatabaseFixture):
    def test_31_primary_colors_and_secondary_inheritance(self):
        parents=list(self.conn.execute('SELECT * FROM sectors WHERE level=1'))
        self.assertEqual(len({r['color'] for r in parents}),31)
        self.assertFalse(self.conn.execute('SELECT 1 FROM sectors c JOIN sectors p ON p.id=c.parent_id WHERE c.color!=p.color').fetchone())
        for row in parents:
            sector_color(row['color'])
        children=list(self.conn.execute('SELECT * FROM sectors WHERE level=2 LIMIT 2'))
        self.assertEqual(children[0]['parent_id'],children[1]['parent_id'])
        save_stock(self.conn,{'id':self.stock['id'],'sector_id':children[0]['id']})
        second=save_stock(self.conn,{'code':'600498','name':'烽火通信','market':'SH','sector_id':children[1]['id']})
        stocks=stock_list(self.conn)
        self.assertEqual(stocks[0]['color'],stocks[1]['color'])
        dashboard=build_dashboard(self.conn,'2026-01-05','2026-01-05')
        self.assertEqual(dashboard['series'][0]['color'],dashboard['series'][1]['color'])

    def test_edit_parent_propagates_same_color_and_child_cannot_override(self):
        child=dict(self.conn.execute('SELECT * FROM sectors WHERE level=2 LIMIT 1').fetchone())
        parent=dict(self.conn.execute('SELECT * FROM sectors WHERE id=?',(child['parent_id'],)).fetchone())
        preview=save_sector(self.conn,{'id':parent['id'],'color':'#A665C4'},preview=True)
        self.assertTrue(all(r['color']=='#A665C4' for r in preview['children']))
        save_sector(self.conn,{'id':parent['id'],'color':'#A665C4'})
        save_sector(self.conn,{'id':child['id'],'name':child['name'],'color':'#3A5CC2'})
        self.assertEqual(self.conn.execute('SELECT color FROM sectors WHERE id=?',(child['id'],)).fetchone()[0],'#A665C4')
        initialize(self.conn,ROOT/'resources')
        self.assertEqual(self.conn.execute('SELECT color FROM sectors WHERE id=?',(parent['id'],)).fetchone()[0],'#A665C4')

    def test_existing_scheme_migrates_once_without_losing_business_data(self):
        with self.conn:
            self.conn.execute("DELETE FROM app_settings WHERE key='industry_color_scheme'")
            self.conn.execute("UPDATE sectors SET color='#334455'")
        initialize(self.conn,ROOT/'resources')
        self.assertEqual(len({r[0] for r in self.conn.execute('SELECT color FROM sectors WHERE level=1')}),31)
        self.assertEqual(stock_list(self.conn)[0]['code'],'000988')
        self.assertEqual(json.loads(self.conn.execute("SELECT value_json FROM app_settings WHERE key='industry_color_scheme'").fetchone()[0]),industry_palette()['version'])

    def test_primary_palette_excludes_red_green_black(self):
        for bad in ['#FF0000','#00AA00','#000000','#101010']:
            with self.assertRaises(ValidationError): sector_color(bad)
        for good in ['#C67519','#D49B25','#2389B9','#9950C8']:
            self.assertEqual(sector_color(good),good)

    def test_pastel_yellow_pink_and_bright_orange_are_allowed(self):
        for color in ['#F2DD87','#E8AACB','#D974A5','#F4A340']:
            self.assertEqual(sector_color(color),color)
        colors={p['name']:p['color'] for g in industry_palette()['groups'] for p in g['industries']}
        self.assertEqual(colors['医药生物'],'#D974A5')
        self.assertEqual(colors['机械设备'],'#F2DD87')
        self.assertEqual(colors['石油石化'],'#F4A340')
