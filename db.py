import os
from sqlalchemy import create_engine,String,ForeignKey,Boolean,DateTime,func
from sqlalchemy.orm import mapped_column,DeclarativeBase,Mapped,relationship,Session,sessionmaker
from sqlalchemy import select
import datetime
from decimal import Decimal
from sqlalchemy import Numeric
from sqlalchemy import Index
# 连接串从环境变量读，本地开发用默认值；生产环境用 DATABASE_URL 覆盖
URL = os.environ.get(
    "DATABASE_URL",
    "mysql+pymysql://dev:dev123456@localhost/llm_gateway_db?charset=utf8mb4",
)

engine = create_engine(URL,echo=False)
SessionLocal = sessionmaker(bind=engine)

class Base(DeclarativeBase):
    pass

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(50),unique=True,index=True) 
    pwd_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime,server_default=func.now())

def init_db():
    Base.metadata.create_all(engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def get_user_by_name(session: Session,username: str) -> User | None:
    return session.scalars(select(User).where(User.username == username)).first()

def add_user(session: Session,username: str,pwd_hash: str) -> User:
    u = User(username = username,pwd_hash = pwd_hash)
    session.add(u)
    session.commit()
    session.refresh(u)
    return u 

class ApiCall(Base):
    __tablename__ = "api_calls"
    __table_args__ = (
        Index("ix_api_calls_user_created","user_id","created_at"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    model: Mapped[str] = mapped_column(String(50))
    prompt_tokens: Mapped[int] = mapped_column(server_default="0")
    completion_tokens: Mapped[int] = mapped_column(server_default="0")
    cost :Mapped[Decimal] = mapped_column(Numeric(10,6),server_default="0")
    status: Mapped[str] = mapped_column(String(20),server_default="success")
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime,server_default=func.now())
