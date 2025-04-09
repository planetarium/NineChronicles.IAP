import base64
from io import StringIO
import os
import paramiko
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from sshtunnel import SSHTunnelForwarder
DB_USER = os.getenv("DB_USER", "iap")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", 5432)
DB_NAME = os.getenv("DB_NAME", "iap")

pk = os.environ["SSH_PRIVATE_KEY"]
decoded = base64.b64decode(pk).decode('utf-8')
private_key = paramiko.RSAKey.from_private_key(StringIO(decoded))
local_port = os.getenv('LOCAL_PORT', 6543)
tunnel = SSHTunnelForwarder(
    (os.environ["SSH_HOST"], 22),
    ssh_username=os.environ["SSH_USERNAME"],
    ssh_pkey=private_key,
    remote_bind_address=(os.environ['REMOTE_HOST'], 5432),
    local_bind_address=('0.0.0.0', int(local_port)),
)
tunnel.start()
DATABASE_URL = f"postgresql://{DB_USER}:{DB_PASSWORD}@0.0.0.0:{local_port}/{DB_NAME}"
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()
