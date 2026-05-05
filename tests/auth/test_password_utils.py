"""
密码工具函数的单元测试。

测试 app/utils/passwords.py 中的所有公共函数：
- hash_password
- verify_password
- is_bcrypt_hash
- legacy_sha256_hash
- needs_password_rehash
"""

import hashlib

import pytest

from app.utils.passwords import (
    hash_password,
    is_bcrypt_hash,
    legacy_sha256_hash,
    needs_password_rehash,
    verify_password,
)


# ---------------------------------------------------------------------------
# hash_password
# ---------------------------------------------------------------------------


class TestHashPassword:
    """hash_password 函数测试组。"""

    def test_returns_bcrypt_hash(self):
        """hash_password 应返回 bcrypt 格式的哈希字符串。"""
        result = hash_password("secureP@ss123")
        assert isinstance(result, str)
        # bcrypt 哈希以 $2a$, $2b$ 或 $2y$ 开头
        assert result.startswith(("$2a$", "$2b$", "$2y$"))

    def test_different_calls_produce_different_hashes(self):
        """由于 bcrypt 自带随机盐，相同密码每次调用应产生不同哈希。"""
        password = "same_password"
        hash1 = hash_password(password)
        hash2 = hash_password(password)
        assert hash1 != hash2

    def test_hash_length_is_60(self):
        """标准 bcrypt 哈希长度固定为 60 个字符。"""
        result = hash_password("test")
        assert len(result) == 60

    def test_accepts_unicode_password(self):
        """hash_password 应正确处理包含 Unicode 字符的密码。"""
        result = hash_password("密码测试🔐")
        assert is_bcrypt_hash(result)

    def test_accepts_empty_string(self):
        """hash_password 对空字符串也不应崩溃（业务层应做校验）。"""
        result = hash_password("")
        assert is_bcrypt_hash(result)


# ---------------------------------------------------------------------------
# verify_password
# ---------------------------------------------------------------------------


class TestVerifyPassword:
    """verify_password 函数测试组。"""

    def test_correct_password_returns_true(self):
        """正确密码应验证通过。"""
        password = "correct_password"
        hashed = hash_password(password)
        assert verify_password(password, hashed) is True

    def test_wrong_password_returns_false(self):
        """错误密码应验证失败。"""
        hashed = hash_password("real_password")
        assert verify_password("wrong_password", hashed) is False

    def test_sha256_legacy_hash_matches(self):
        """对历史 SHA256 哈希应能正确验证。"""
        password = "legacy_pass"
        sha_hash = legacy_sha256_hash(password)
        assert verify_password(password, sha_hash) is True

    def test_sha256_legacy_hash_wrong_password_fails(self):
        """对历史 SHA256 哈希，错误密码应验证失败。"""
        sha_hash = legacy_sha256_hash("correct")
        assert verify_password("incorrect", sha_hash) is False

    def test_empty_plain_password_returns_false(self):
        """空明文密码应返回 False。"""
        hashed = hash_password("something")
        assert verify_password("", hashed) is False

    def test_empty_hash_returns_false(self):
        """空哈希应返回 False。"""
        assert verify_password("password", "") is False

    def test_both_empty_returns_false(self):
        """明文和哈希都为空时应返回 False。"""
        assert verify_password("", "") is False

    def test_none_plain_password_returns_false(self):
        """None 明文密码应返回 False（空值保护）。"""
        hashed = hash_password("something")
        # 函数签名要求 str，但做防御性测试
        assert verify_password(None, hashed) is False  # type: ignore[arg-type]

    def test_malformed_bcrypt_hash_returns_false(self):
        """格式错误的 bcrypt 哈希应返回 False 而不抛异常。"""
        assert verify_password("password", "$2b$12$invalidhashvalue") is False

    def test_unicode_password_verify(self):
        """Unicode 密码的完整哈希+验证流程。"""
        password = "中文密码🔐"
        hashed = hash_password(password)
        assert verify_password(password, hashed) is True


# ---------------------------------------------------------------------------
# is_bcrypt_hash
# ---------------------------------------------------------------------------


class TestIsBcryptHash:
    """is_bcrypt_hash 函数测试组。"""

    @pytest.mark.parametrize(
        "prefix",
        ["$2a$", "$2b$", "$2y$"],
    )
    def test_recognizes_bcrypt_prefixes(self, prefix):
        """应识别所有三种 bcrypt 前缀。"""
        fake_hash = prefix + "12$abcdefghijklmnopqrstuvwxyz"
        assert is_bcrypt_hash(fake_hash) is True

    def test_real_bcrypt_hash(self):
        """应识别真实 bcrypt 哈希。"""
        hashed = hash_password("test")
        assert is_bcrypt_hash(hashed) is True

    def test_sha256_hash_returns_false(self):
        """SHA256 哈希不应被识别为 bcrypt。"""
        sha = legacy_sha256_hash("test")
        assert is_bcrypt_hash(sha) is False

    def test_empty_string_returns_false(self):
        """空字符串应返回 False。"""
        assert is_bcrypt_hash("") is False

    def test_random_string_returns_false(self):
        """随机字符串应返回 False。"""
        assert is_bcrypt_hash("not_a_hash_at_all") is False

    def test_md5_like_hash_returns_false(self):
        """MD5 格式的哈希应返回 False。"""
        assert is_bcrypt_hash("d41d8cd98f00b204e9800998ecf8427e") is False


# ---------------------------------------------------------------------------
# legacy_sha256_hash
# ---------------------------------------------------------------------------


class TestLegacySha256Hash:
    """legacy_sha256_hash 函数测试组。"""

    def test_produces_correct_sha256(self):
        """应产生与 hashlib 一致的 SHA256 哈希。"""
        password = "test_password"
        expected = hashlib.sha256(password.encode("utf-8")).hexdigest()
        assert legacy_sha256_hash(password) == expected

    def test_output_is_hex_string(self):
        """输出应为十六进制字符串。"""
        result = legacy_sha256_hash("abc")
        assert all(c in "0123456789abcdef" for c in result)

    def test_output_length_is_64(self):
        """SHA256 哈希长度固定为 64。"""
        assert len(legacy_sha256_hash("test")) == 64

    def test_deterministic(self):
        """相同输入应产生相同输出。"""
        assert legacy_sha256_hash("same") == legacy_sha256_hash("same")

    def test_different_inputs_differ(self):
        """不同输入应产生不同输出。"""
        assert legacy_sha256_hash("a") != legacy_sha256_hash("b")

    def test_unicode_password(self):
        """应正确处理 Unicode 密码。"""
        result = legacy_sha256_hash("中文密码")
        expected = hashlib.sha256("中文密码".encode("utf-8")).hexdigest()
        assert result == expected


# ---------------------------------------------------------------------------
# needs_password_rehash
# ---------------------------------------------------------------------------


class TestNeedsPasswordRehash:
    """needs_password_rehash 函数测试组。"""

    def test_bcrypt_hash_does_not_need_rehash(self):
        """bcrypt 哈希不需要重哈希。"""
        hashed = hash_password("test")
        assert needs_password_rehash(hashed) is False

    @pytest.mark.parametrize("prefix", ["$2a$", "$2b$", "$2y$"])
    def test_all_bcrypt_prefixes_no_rehash(self, prefix):
        """所有 bcrypt 前缀都不需要重哈希。"""
        fake_bcrypt = prefix + "12$abcdefghijklmnopqrstuvwxyz"
        assert needs_password_rehash(fake_bcrypt) is False

    def test_sha256_hash_needs_rehash(self):
        """SHA256 哈希需要重哈希。"""
        sha = legacy_sha256_hash("test")
        assert needs_password_rehash(sha) is True

    def test_plain_string_needs_rehash(self):
        """普通字符串需要重哈希。"""
        assert needs_password_rehash("not_a_hash") is True

    def test_empty_string_needs_rehash(self):
        """空字符串需要重哈希。"""
        assert needs_password_rehash("") is True
