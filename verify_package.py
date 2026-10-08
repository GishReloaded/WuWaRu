"""Integration check against real source databases and the packed round-trip."""
import json
import sqlite3
from pathlib import Path
from collections import Counter
from game import quote_sql, sha1
from translator import format_signature

home=Path(__file__).resolve().parent
original=home/'data/source'
packed=home/'data/package-check/Client/Content/Aki/ConfigDB/en'
checked=changed=0
for source in original.glob('*.db'):
    target=packed/source.name
    assert target.exists(), source.name
    with sqlite3.connect(source) as a, sqlite3.connect(target) as b:
        schemas=lambda db:db.execute("select type,name,tbl_name,sql from sqlite_master order by type,name").fetchall()
        assert schemas(a)==schemas(b),('schema changed',source.name)
        for (table,) in a.execute("select name from sqlite_master where type='table' and name not like 'sqlite_%'"):
            cols=[r[1] for r in a.execute(f'pragma table_info({quote_sql(table)})')]
            rows_a=a.execute(f'select * from {quote_sql(table)} order by Id').fetchall()
            rows_b=b.execute(f'select * from {quote_sql(table)} order by Id').fetchall()
            assert len(rows_a)==len(rows_b),(source.name,table,'count')
            content=cols.index('Content')
            for before,after in zip(rows_a,rows_b):
                assert before[:content]+before[content+1:]==after[:content]+after[content+1:],(source.name,table,'non-text modified')
                if before[content]!=after[content]:
                    assert format_signature(before[content])==format_signature(after[content]),(source.name,table,before[0],'control tokens')
                    changed+=1
                checked+=1
manifest=json.loads((home/'output/manifest.json').read_text(encoding='utf-8'))
assert changed==manifest['changed_rows'],('packed translation count does not match build',changed,manifest['changed_rows'])
print(f'Checked {len(list(original.glob("*.db")))} databases, {checked:,} rows; {changed:,} changed. Schema, IDs, redirects and formatting unchanged.')
