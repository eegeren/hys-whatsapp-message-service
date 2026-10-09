"""Interactive hidden local/SSH password input, never CLI args or logs."""
import getpass,sys
from pathlib import Path
from sqlalchemy import select,delete
from argon2 import PasswordHasher
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.core import Session,User,LoginSession,audit

def run():
    username=input('Yetkili HYS kullanıcı adı: ').strip()
    password=getpass.getpass('Yeni güçlü parola (gizli): ')
    repeat=getpass.getpass('Yeni parola tekrar (gizli): ')
    if len(password)<12 or password!=repeat:raise ValueError()
    with Session() as db:
        user=db.scalar(select(User).where(User.username==username))
        if not user or user.role not in ('admin','operator'):raise ValueError()
        user.password=PasswordHasher().hash(password)
        db.execute(delete(LoginSession).where(LoginSession.user_id==user.id))
        audit(db,'secure-console','password_reset',str(user.id));db.commit()
    print('Parola yenilendi; eski oturumlar kapatıldı.')

if __name__=='__main__':
    try:run()
    except Exception:print('Parola yenilenmedi. Kullanıcı, güçlü parola ve bağlantı ayarlarını kontrol edin.');sys.exit(1)
