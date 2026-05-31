import bcrypt
from database import get_setting, set_setting


def check_credentials(login, password):
    stored_login = get_setting('app_login', 'admin')
    stored_hash = get_setting('app_password_hash', '')
    if login != stored_login:
        return False
    if not stored_hash:
        return False
    return bcrypt.checkpw(password.encode(), stored_hash.encode())


def set_password(new_password):
    hashed = bcrypt.hashpw(new_password.encode(), bcrypt.gensalt()).decode()
    set_setting('app_password_hash', hashed)


def set_login(new_login):
    set_setting('app_login', new_login)
