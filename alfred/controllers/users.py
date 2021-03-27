from datetime import datetime, timedelta
from typing import Optional
from fastapi.security import OAuth2PasswordBearer
from fastapi import Depends, HTTPException, status
from alfred.db import get_nosql_db
from alfred.models import TokenData, User, UserInDB
from alfred.config import MONGODB_DB_NAME, SALT
from jose import jwt
from passlib.context import CryptContext
from alfred.utils import format_ids
import logging

logger = logging.getLogger(__name__)
pwd_context = CryptContext(schemes=["bcrypt"], default="bcrypt")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")
# TODO: Move to aws kms
SECRET_KEY = "09d25e094faa6ca2556c818166b7a9563b93f7099f6f0f4caa6cf63b88e8d3e7"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30


def verify_password(plain_password_w_salt, hashed_password):
    return pwd_context.verify(plain_password_w_salt, str(hashed_password), scheme="bcrypt")


def get_password_hash(password_w_salt):
    return pwd_context.hash(password_w_salt)


async def authenticate_user(username: str, password: str):
    user = await get_user(username)
    if not user:
        return False
    if not verify_password(password + SALT, user["password"]):
        return False
    return user


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


async def get_current_user(token: str = Depends(oauth2_scheme)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
        token_data = TokenData(username=username)
    except Exception:
        raise credentials_exception
    user = await get_user(token_data.username)
    if user is None:
        raise credentials_exception
    return User(**user)


async def get_current_active_user(current_user: User = Depends(get_current_user)):
    if current_user.disabled:
        raise HTTPException(status_code=400, detail="Inactive user")
    return current_user


async def create_user(request, collection):
    hashed_password = get_password_hash(request.password + SALT)

    user = {}
    user["username"] = request.username
    user["password"] = hashed_password
    dbuser = UserInDB(**user)
    try:
        response = collection.insert_one(dict(dbuser))
        return {"id_inserted": str(response.inserted_id)}
    except Exception as e:
        raise Exception(f"{e}")


async def get_user(name) -> UserInDB:
    client = await get_nosql_db()
    db = client[MONGODB_DB_NAME]
    users_collection = db.users
    row = users_collection.find_one({"username": name})
    if row is not None:
        row = format_ids(row)
        return row
    else:
        return None
