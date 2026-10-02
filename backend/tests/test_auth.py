"""登录与访问控制测试：口令散列、会话 Cookie、接口围栏、限速与桌面豁免。"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ["CAMPUS_DATA_DIR"] = tempfile.mkdtemp(prefix="mens-auth-")
os.environ["ADMIN_TOKEN"] = "test-admin-token"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from app import auth, main  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.db import Base, SessionLocal, engine  # noqa: E402
from app.models import User  # noqa: E402


class PasswordTest(unittest.TestCase):
    def test_hash_and_verify_roundtrip(self):
        stored = auth.hash_password("correct horse battery")
        self.assertTrue(stored.startswith("pbkdf2_sha256$"))
        self.assertTrue(auth.verify_password("correct horse battery", stored))
        self.assertFalse(auth.verify_password("wrong password", stored))

    def test_verify_rejects_malformed_storage(self):
        for broken in ("", "plain", "md5$1$a$b", "pbkdf2_sha256$abc$!!$!!"):
            self.assertFalse(auth.verify_password("x", broken))

    def test_hash_is_salted(self):
        self.assertNotEqual(auth.hash_password("same"), auth.hash_password("same"))

    def test_validation_rules(self):
        with self.assertRaises(ValueError):
            auth.validate("a", "longenough1")          # 用户名太短
        with self.assertRaises(ValueError):
            auth.validate("bad name", "longenough1")   # 非法字符
        with self.assertRaises(ValueError):
            auth.validate("okname", "short")           # 口令太短
        auth.validate("ok.name-1", "longenough1")


class LoginFlowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Base.metadata.create_all(engine)
        cls.client = TestClient(main.app)
        cls.settings = get_settings()

    def setUp(self):
        with SessionLocal() as db:
            for row in db.query(User).all():
                db.delete(row)
            db.commit()
            auth.create_user(db, "student", "student-pass-1", role="user")
            auth.create_user(db, "teacher", "teacher-pass-1", role="admin")
        auth._attempts.clear()
        self.settings.auth_required = True
        self.settings.cookie_secure = False

    def tearDown(self):
        self.settings.auth_required = False

    def login(self, username: str, password: str):
        return self.client.post("/api/auth/login", json={"username": username, "password": password})

    def test_login_sets_httponly_cookie_and_me_works(self):
        response = self.login("student", "student-pass-1")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["user"]["username"], "student")
        cookie_header = response.headers.get("set-cookie", "")
        self.assertIn("mens_session=", cookie_header)
        self.assertIn("HttpOnly", cookie_header)
        self.assertIn("SameSite=lax", cookie_header)
        me = self.client.get("/api/auth/me")
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.json()["user"]["role"], "user")

    def test_wrong_password_and_unknown_user_are_401(self):
        self.assertEqual(self.login("student", "nope-nope-nope").status_code, 401)
        self.assertEqual(self.login("ghost", "nope-nope-nope").status_code, 401)

    def test_api_is_gated_without_cookie(self):
        self.assertEqual(self.client.get("/api/conversations").status_code, 401)
        self.assertEqual(self.client.get("/api/mcp/servers").status_code, 401)
        self.login("student", "student-pass-1")
        self.assertEqual(self.client.get("/api/conversations").status_code, 200)

    def test_public_endpoints_stay_open(self):
        self.assertEqual(self.client.get("/api/health").status_code, 200)
        self.assertEqual(self.client.get("/api/auth/me").status_code, 401)  # 401 而不是 403/500
        self.assertTrue(self.client.get("/api/health").json()["auth_required"])

    def test_logout_invalidates_session(self):
        self.login("student", "student-pass-1")
        self.assertEqual(self.client.get("/api/auth/me").status_code, 200)
        self.assertEqual(self.client.post("/api/auth/logout").status_code, 200)
        self.assertEqual(self.client.get("/api/auth/me").status_code, 401)
        self.assertEqual(self.client.get("/api/conversations").status_code, 401)

    def test_logged_in_admin_passes_require_admin(self):
        self.login("teacher", "teacher-pass-1")
        response = self.client.post("/api/mcp/servers", json={"name": "admintool", "command": "y"})
        # 管理员角色的会话可以执行管理操作（200 而不是 401/503）
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["server"]["name"], "admintool")

    def test_normal_user_still_needs_admin_token(self):
        self.login("student", "student-pass-1")
        self.assertEqual(self.client.post("/api/mcp/servers", json={"name": "x", "command": "y"}).status_code, 401)

    def test_login_rate_limit_kicks_in(self):
        for _ in range(auth.LOGIN_MAX_ATTEMPTS):
            self.assertEqual(self.login("student", "bad-pass").status_code, 401)
        self.assertEqual(self.login("student", "student-pass-1").status_code, 429)

    def test_desktop_mode_bypasses_gate(self):
        with patch.object(main, "desktop_enabled", return_value=True):
            self.assertEqual(self.client.get("/api/conversations").status_code, 200)

    def test_disabled_user_cannot_login(self):
        with SessionLocal() as db:
            user = db.query(User).filter_by(username="student").one()
            user.disabled = True
            db.commit()
        self.assertEqual(self.login("student", "student-pass-1").status_code, 401)


class BootstrapTest(unittest.TestCase):
    def test_bootstrap_creates_admin_only_when_enabled(self):
        with SessionLocal() as db:
            for row in db.query(User).all():
                db.delete(row)
            db.commit()
            settings = get_settings()
            original = settings.auth_required
            settings.auth_required = False
            auth.ensure_bootstrap_admin(db)
            self.assertEqual(auth.count_users(db), 0)
            settings.auth_required = True
            settings.auth_admin_username = "bootstrap-admin"
            settings.auth_admin_password = "bootstrap-pass-1"
            auth.ensure_bootstrap_admin(db)
            self.assertEqual(auth.count_users(db), 1)
            self.assertTrue(auth.authenticate(db, "bootstrap-admin", "bootstrap-pass-1"))
            settings.auth_required = original


if __name__ == "__main__":
    unittest.main()
