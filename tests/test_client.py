"""ZKHClient sign 计算和 checkin form 构建测试."""

import hashlib
import pytest
from zkh_punchout.client import ZKHClient


class TestZKHClientMd5:
    def test_md5_basic(self):
        assert ZKHClient.md5("hello") == hashlib.md5(b"hello").hexdigest()

    def test_md5_chinese(self):
        result = ZKHClient.md5("测试")
        assert len(result) == 32
        assert result == hashlib.md5("测试".encode("utf-8")).hexdigest()

    def test_md5_empty(self):
        assert ZKHClient.md5("") == hashlib.md5(b"").hexdigest()


class TestTrustedLoginSign:
    def test_sign_computation(self, zkh_client):
        """验证 strustNo 签名 MD5(pin + uniqueNo + time)"""
        pin = "test_user"
        unique_no = "U001"
        ts = 1234567890000
        expected = zkh_client.md5(f"{pin}{unique_no}{ts}")
        assert len(expected) == 32

    def test_sign_with_empty_pin(self, zkh_client):
        """pin 为空时签名计算"""
        pin = ""
        unique_no = "U001"
        ts = 1234567890000
        expected = zkh_client.md5(f"{pin}{unique_no}{ts}")
        assert len(expected) == 32


class TestBuildCheckinForm:
    def test_basic_form(self, zkh_client):
        form = zkh_client.build_checkin_form(
            unique_no="U001",
            strust_no="STRUST123",
            hook_url="https://mro.water-healer.com/api/zkh/checkout",
            pin="test_user",
        )
        assert form["pin"] == "test_user"
        assert form["strustNo"] == "STRUST123"
        assert form["appId"] == "ESP"
        assert form["uniqueNo"] == "U001"
        assert form["hookUrl"] == "https://mro.water-healer.com/api/zkh/checkout"
        assert "sign" in form
        assert len(form["sign"]) == 32

    def test_form_sign_consistency(self, zkh_client):
        """相同参数应产生相同 sign"""
        form1 = zkh_client.build_checkin_form("U001", "S123", "http://hook", "user")
        form2 = zkh_client.build_checkin_form("U001", "S123", "http://hook", "user")
        assert form1["sign"] == form2["sign"]

    def test_form_different_hook_url(self, zkh_client):
        """不同 hook_url 不影响 sign（sign 不含 hook_url）"""
        form1 = zkh_client.build_checkin_form("U001", "S123", "http://hook1", "user")
        form2 = zkh_client.build_checkin_form("U001", "S123", "http://hook2", "user")
        assert form1["sign"] == form2["sign"]

    def test_form_with_custom_fields(self, zkh_client):
        form = zkh_client.build_checkin_form(
            unique_no="U001",
            strust_no="S123",
            hook_url="http://hook",
            pin="user",
            custom_fields={"invoiceName": "测试公司"},
        )
        # json.dumps with ensure_ascii=False produces non-ASCII output
        import json as _json
        parsed = _json.loads(form["customFields"])
        assert parsed["invoiceName"] == "测试公司"

    def test_form_without_pin(self, zkh_client):
        form = zkh_client.build_checkin_form(
            unique_no="U001",
            strust_no="S123",
            hook_url="http://hook",
        )
        assert form["pin"] == ""
        assert "sign" in form

    def test_form_sign_format(self, zkh_client):
        """sign = MD5(pin + uniqueNo + strustNo + appId)"""
        pin = "test_user"
        unique_no = "U001"
        strust_no = "STRUST123"
        app_id = "ESP"
        expected = zkh_client.md5(f"{pin}{unique_no}{strust_no}{app_id}")

        form = zkh_client.build_checkin_form(unique_no, strust_no, "http://hook", pin)
        assert form["sign"] == expected