"""DingCallbackCrypto 加解密单元测试."""

import json
import pytest
from zkh_punchout.callback_crypto import DingCallbackCrypto


class TestDingCallbackCrypto:
    """测试钉钉回调加解密"""

    def test_init_with_invalid_key_length(self):
        """AES key 长度必须为 43 位"""
        with pytest.raises(ValueError, match="EncodingAESKey"):
            DingCallbackCrypto(
                token="test",
                encoding_aes_key="too_short",  # 只有 9 位
                owner_key="test_corp",
            )

    def test_init_with_valid_key(self, crypto):
        assert crypto.token == "test_token_123"
        assert crypto.owner_key == "ding4f4b796d63d5f483f5bf40eda33b7ba0"

    def test_get_signature(self, crypto):
        """签名计算应该稳定"""
        sig = crypto.get_signature("1234567890", "abc123", "test_encrypt")
        assert len(sig) == 40  # SHA1 hexdigest
        # 相同参数应该产生相同签名
        sig2 = crypto.get_signature("1234567890", "abc123", "test_encrypt")
        assert sig == sig2

    def test_get_signature_order_independent(self, crypto):
        """签名应该与参数传入顺序无关（内部排序）"""
        sig1 = crypto.get_signature("t1", "n1", "e1")
        sig2 = crypto.get_signature("n1", "e1", "t1")
        assert sig1 == sig2

    def test_encrypt_decrypt_roundtrip(self, crypto):
        """加密后解密应该得到原文"""
        plaintext = "success"
        encrypted = crypto.get_encrypted_map(plaintext)
        assert "msg_signature" in encrypted
        assert "timeStamp" in encrypted
        assert "nonce" in encrypted
        assert "encrypt" in encrypted

        decrypted = crypto.get_decrypt_msg(
            encrypted["msg_signature"],
            encrypted["timeStamp"],
            encrypted["nonce"],
            encrypted["encrypt"],
        )
        assert decrypted == plaintext

    def test_encrypt_decrypt_json(self, crypto):
        """加密/解密 JSON 数据"""
        event = json.dumps({
            "EventType": "bpms_instance_change",
            "processInstanceId": "INST-001",
        })
        encrypted = crypto.get_encrypted_map(event)
        decrypted = crypto.get_decrypt_msg(
            encrypted["msg_signature"],
            encrypted["timeStamp"],
            encrypted["nonce"],
            encrypted["encrypt"],
        )
        parsed = json.loads(decrypted)
        assert parsed["EventType"] == "bpms_instance_change"
        assert parsed["processInstanceId"] == "INST-001"

    def test_encrypt_decrypt_chinese(self, crypto):
        """加密/解密中文内容"""
        plaintext = "审批通过 - 订单2026080700001A"
        encrypted = crypto.get_encrypted_map(plaintext)
        decrypted = crypto.get_decrypt_msg(
            encrypted["msg_signature"],
            encrypted["timeStamp"],
            encrypted["nonce"],
            encrypted["encrypt"],
        )
        assert decrypted == plaintext

    def test_signature_mismatch(self, crypto):
        """签名不匹配应该抛出异常"""
        encrypted = crypto.get_encrypted_map("test")
        with pytest.raises(ValueError, match="签名验证失败"):
            crypto.get_decrypt_msg(
                "wrong_signature",
                encrypted["timeStamp"],
                encrypted["nonce"],
                encrypted["encrypt"],
            )

    def test_encrypted_map_consistency(self, crypto):
        """多次加密相同内容应该产生不同密文（随机串）"""
        map1 = crypto.get_encrypted_map("hello")
        map2 = crypto.get_encrypted_map("hello")
        # 相同的明文加密后应该不同（因为有随机字节）
        assert map1["encrypt"] != map2["encrypt"]
        # 但解密后应该相同
        dec1 = crypto.get_decrypt_msg(
            map1["msg_signature"], map1["timeStamp"], map1["nonce"], map1["encrypt"]
        )
        dec2 = crypto.get_decrypt_msg(
            map2["msg_signature"], map2["timeStamp"], map2["nonce"], map2["encrypt"]
        )
        assert dec1 == "hello"
        assert dec2 == "hello"

    def test_owner_key_mismatch(self, crypto):
        """owner_key 不匹配应该抛出异常"""
        # 创建另一个 crypto 实例，使用不同的 owner_key
        crypto2 = DingCallbackCrypto(
            token="test_token_123",
            encoding_aes_key="abcdefghijklmnopqrstuvwxyz0123456789ABCDEFG",
            owner_key="different_corp_id",
        )
        encrypted = crypto2.get_encrypted_map("test")
        with pytest.raises(ValueError, match="OWNER_KEY"):
            crypto.get_decrypt_msg(
                encrypted["msg_signature"],
                encrypted["timeStamp"],
                encrypted["nonce"],
                encrypted["encrypt"],
            )