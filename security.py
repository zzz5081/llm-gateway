import os,bcrypt,jwt,datetime

from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")

SECRET_KEY = os.environ.get("APP_SECRET")
if not SECRET_KEY:
    raise RuntimeError("请先设置环境变量 APP_SECRET_KEY")

def hash_password(password: str) ->bytes:
    return bcrypt.hashpw(password.encode(),bcrypt.gensalt())

def verify_password(password: str,hashed: bytes)-> bool:
    return bcrypt.checkpw(password.encode(),hashed)

def create_token(user_id: int, username: str, hours: int = 2) ->str:
    payload = {
        'user_id':user_id,
        'username':username,
        'exp': datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=hours)
    }
    return jwt.encode(payload,SECRET_KEY,algorithm='HS256')

def decode_token(token: str) -> dict:
    return jwt.decode(token,SECRET_KEY,algorithms=['HS256'])

def hash_password_str(password: str) -> str:
    return hash_password(password).decode()

def verify_password_str(password: str, hashed: str) -> bool:
    return verify_password(password,hashed.encode())
