"""Dry-run by default. Copy SQLite into an EMPTY migrated PostgreSQL, never overwrite."""
import argparse,json,os,sys
from pathlib import Path
from sqlalchemy import create_engine,select,func,text
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.core import Base,database_dsn,now

def transform(table,row):
    row=dict(row)
    if table=='sessions':return None # Do not transfer browser sessions.
    if table=='system_values' and (row['key']=='meta_verified' or row['key'].startswith(('login:','import:','bulk_preview:','bulk_draft:'))):return None
    if table=='campaigns' and row['status'] in ('running','scheduled','preparing'):row['status']='paused'
    if table=='messages' and row['status']=='sending':
        row['status']='uncertain';row['error']='Taşıma sırasında API sonucu belirsiz; otomatik tekrar yapılmaz.'
    return row

def run():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',type=Path,required=True)
    p.add_argument('--apply',action='store_true')
    p.add_argument('--confirm-empty-target',action='store_true')
    args=p.parse_args()
    if not args.source.is_file():raise RuntimeError('SQLite yedeği bulunamadı.')
    # Source is always read-only; use a consistent SQLite backup, never a live file copy.
    source=create_engine('sqlite:///file:'+args.source.resolve().as_posix()+'?mode=ro&uri=true',hide_parameters=True)
    with source.connect() as src:
        counts={t.name:src.scalar(select(func.count()).select_from(t)) for t in Base.metadata.sorted_tables}
        print(json.dumps({'mode':'apply' if args.apply else 'plan','source_counts':counts,'active_campaigns_will_pause':True,'sessions_will_not_transfer':True}))
        if not args.apply:return
        if not args.confirm_empty_target:raise RuntimeError('Uygulamak için boş hedefe açık onay gerekir.')
        url=database_dsn(os.environ.get('TRANSFER_DATABASE_URL',''))
        if not url.startswith('postgresql+psycopg://'):raise RuntimeError('TRANSFER_DATABASE_URL PostgreSQL olmalıdır.')
        target=create_engine(url,hide_parameters=True,pool_pre_ping=True)
        with target.begin() as dst:
            if dst.scalar(text('SELECT version_num FROM alembic_version'))!='003':raise RuntimeError('Önce hedefte alembic upgrade head çalıştırın; beklenen revision 003.')
            # Empty-target check and copy share a transaction/table locks. A nonempty
            # destination aborts; no DELETE/DROP/TRUNCATE or schema reset is performed.
            for t in Base.metadata.sorted_tables:
                dst.execute(text('LOCK TABLE "'+t.name+'" IN ACCESS EXCLUSIVE MODE'))
                if dst.scalar(select(func.count()).select_from(t)):raise RuntimeError('Hedef boş değil; taşıma durduruldu.')
            transferred={}
            for t in Base.metadata.sorted_tables:
                count=0;batch=[]
                for row in src.execute(select(t)).mappings():
                    value=transform(t.name,row)
                    if value is None:continue
                    batch.append(value)
                    if len(batch)>=500:dst.execute(t.insert(),batch);count+=len(batch);batch=[]
                if batch:dst.execute(t.insert(),batch);count+=len(batch)
                transferred[t.name]=count
                if len(t.primary_key.columns)==1:
                    col=next(iter(t.primary_key.columns))
                    if col.name=='id' and str(col.type)=='INTEGER':
                        dst.execute(text('SELECT setval(pg_get_serial_sequence(:t, :c), COALESCE(MAX("id"),1), COUNT(*)>0) FROM "'+t.name+'"'),{'t':t.name,'c':col.name})
                if dst.scalar(select(func.count()).select_from(t))!=count:raise RuntimeError('Kayıt sayısı doğrulanamadı; işlem geri alınır.')
        print(json.dumps({'copied_counts':transferred,'completed':True,'campaigns_not_started':True}))

if __name__=='__main__':
    try:run()
    except Exception:
        # DB exception text can contain credentials/data; never print it.
        print('Taşıma tamamlanmadı. Kaynak korunur; hedef işlemi geri alınır. Boş hedef, migration ve bağlantı ayarlarını kontrol edin.',file=sys.stderr)
        sys.exit(1)
