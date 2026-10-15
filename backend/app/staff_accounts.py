"""Admin-only support account lifecycle. Historical ownership is preserved."""
from fastapi import Depends,HTTPException
from pydantic import BaseModel,Field,field_validator
from sqlalchemy import select,delete
from sqlalchemy.exc import IntegrityError
from app.core import User,LoginSession,audit,MIN_PASSWORD_LENGTH
from app.main import app,admin,db_session,ph
from app.quick_replies import profile,ProfileInput

def support(db,id):
    row=db.get(User,id)
    if not row or not row.active:raise HTTPException(404,'Destek hesabı bulunamadı.')
    if row.role!='operator':raise HTTPException(403,'Bu bölümden yalnızca destek personeli hesapları yönetilebilir.')
    return row
class StaffEdit(ProfileInput):
    username:str=Field(min_length=3,max_length=100)
    @field_validator('username')
    @classmethod
    def login_name(cls,value):
        value=value.strip()
        if len(value)<3 or any(c.isspace() for c in value):raise ValueError('Kullanıcı adı boşluk içeremez ve en az 3 karakter olmalıdır.')
        return value
@app.put('/api/users/{id}')
def update_staff(id:int,data:StaffEdit,user=Depends(admin),db=Depends(db_session)):
    row=support(db,id)
    if db.scalar(select(User.id).where(User.username==data.username,User.id!=id)):raise HTTPException(409,'Bu kullanıcı adı zaten kullanılıyor.')
    row.username=data.username;row.display_name=data.display_name
    audit(db,user.username,'staff_account_update',str(id))
    try:db.commit()
    except IntegrityError:db.rollback();raise HTTPException(409,'Bu kullanıcı adı zaten kullanılıyor.')
    return profile(row)
class StaffPassword(BaseModel):password:str=Field(min_length=MIN_PASSWORD_LENGTH,max_length=128)
@app.post('/api/users/{id}/password')
def reset_staff_password(id:int,data:StaffPassword,user=Depends(admin),db=Depends(db_session)):
    row=support(db,id);row.password=ph.hash(data.password)
    db.execute(delete(LoginSession).where(LoginSession.user_id==id));audit(db,user.username,'staff_password_reset',str(id));db.commit()
    return {'ok':True,'notice':'Parola sıfırlandı. Personelin açık oturumları kapatıldı.'}
@app.delete('/api/users/{id}')
def delete_staff(id:int,user=Depends(admin),db=Depends(db_session)):
    row=support(db,id);row.active=False
    db.execute(delete(LoginSession).where(LoginSession.user_id==id));audit(db,user.username,'staff_account_delete',str(id));db.commit()
    return {'ok':True,'notice':'Destek hesabı silindi. Geçmiş kayıtlar korundu, açık oturumlar kapatıldı.'}
