"""
密码工具函数。

统一提供安全哈希、校验以及历史 SHA256 哈希兼容能力。
"""

import hashlib

import bcrypt


_BCRYPT_PREFIXES = ("$2a$", "$2b$", "$2y$")


def legacy_sha256_hash(password: str) -> str:
    """兼容历史存量账号的 SHA256 哈希。"""
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def is_bcrypt_hash(password_hash: str) -> bool:
    """判断是否为 bcrypt 哈希。"""
    return bool(password_hash) and password_hash.startswith(_BCRYPT_PREFIXES)


def hash_password(password: str) -> str:
    """生成带盐 bcrypt 哈希。"""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, password_hash: str) -> bool:
    """验证密码，兼容 bcrypt 和历史 SHA256。"""
    if not plain_password or not password_hash:
        return False

    if is_bcrypt_hash(password_hash):
        try:
            return bcrypt.checkpw(
                plain_password.encode("utf-8"),
                password_hash.encode("utf-8"),
            )
        except ValueError:
            return False

    return legacy_sha256_hash(plain_password) == password_hash


def needs_password_rehash(password_hash: str) -> bool:
    """历史 SHA256 哈希在下次成功认证后需要升级。"""
    return not is_bcrypt_hash(password_hash)
