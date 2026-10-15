"""Upgrade an existing database without losing users or reseeding edited replies."""
import os,subprocess,sys
from pathlib import Path
from sqlalchemy import create_engine,text

def test_upgrade_preserves_data_and_seeds_only_once(tmp_path):
    url='sqlite:///'+str(tmp_path/'migration.db');env={**os.environ,'DATABASE_URL':url};root=Path(__file__).resolve().parents[1]
    def upgrade(revision):
        subprocess.run([sys.executable,'-m','alembic','upgrade',revision],cwd=root,env=env,capture_output=True,check=True,timeout=30)
    upgrade('005');engine=create_engine(url)
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO users (username,password,role) VALUES ('existing-user','fake-test-hash','operator')"))
        connection.execute(text("INSERT INTO system_values (key,value) VALUES ('existing-setting','preserve-me')"))
    upgrade('head')
    with engine.begin() as connection:
        assert connection.execute(text('SELECT display_name FROM users')).scalar()=='existing-user'
        assert connection.execute(text("SELECT value FROM system_values WHERE key='existing-setting'")).scalar()=='preserve-me'
        assert connection.execute(text('SELECT COUNT(*) FROM quick_replies')).scalar()==6
        assert connection.execute(text("SELECT body FROM quick_replies WHERE title='Karşılama'")).scalar().startswith('Merhaba, ben HYS')
        connection.execute(text("UPDATE quick_replies SET body='Edited reply' WHERE title='Karşılama'"))
        connection.execute(text("DELETE FROM quick_replies WHERE title='Teşekkür'"))
    upgrade('head')
    with engine.connect() as connection:
        assert connection.execute(text('SELECT COUNT(*) FROM quick_replies')).scalar()==5
        assert connection.execute(text("SELECT body FROM quick_replies WHERE title='Karşılama'")).scalar()=='Edited reply'
        assert connection.execute(text('SELECT COUNT(*) FROM users')).scalar()==1
    engine.dispose()
