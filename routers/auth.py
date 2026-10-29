from fastapi import APIRouter,HTTPException,Depends
from sqlalchemy.orm import Session
from security import hash_password,verify_password,create_token,verify_password_str,hash_password_str
from schemas import UserOut,RegisterIn,LoginIn,TokenOut
from db import get_db,get_user_by_name,add_user
from deps import get_current_user

router = APIRouter(prefix="/auth",tags=["auth"])

@router.post("/register",response_model=UserOut,status_code=201)
def register(body: RegisterIn,db: Session = Depends(get_db)):
    if get_user_by_name(db,body.username):
        raise HTTPException(409,"用户名重复")
    user = add_user(db,body.username,hash_password_str(body.password))
    return {'id':user.id,"username":user.username}

@router.post("/login",response_model=TokenOut)
def login(body: LoginIn,db :Session = Depends(get_db)):
    user = get_user_by_name(db,body.username)
    if not user:
        raise HTTPException(401,"用户名或密码错误")
    if not verify_password_str(body.password,user.pwd_hash):
        raise HTTPException(401,"用户名或密码错误")
    token = create_token(user.id,user.username)
    return {"access_token": token, "token_type":"bearer"}

@router.get("/me",response_model=UserOut)
def me(current_user: dict = Depends(get_current_user)):
    return {'id': current_user.id,"username": current_user.username}