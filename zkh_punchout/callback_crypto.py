"""
钉钉回调加解密工具

严格遵循钉钉官方 Java 实现：
https://github.com/open-dingtalk/dingtalk-callback-Crypto

签名算法: SHA1(sort([token, timestamp, nonce, encrypt]).join(""))
加密算法: AES-256-CBC, PKCS7 padding (block_size=32)
解密后结构: 16字节随机串 + 4字节网络字节序长度 + 明文 + corpId

OWNER_KEY 说明:
  - 事件订阅: 使用 appKey（开发者后台应用的 Client ID）
  - 注册回调地址: 使用 corpId
"""

import base64
import hashlib
import json
import logging
import os
import time
from typing import Optional, Dict, Any

from Crypto.Cipher import AES

logger = logging.getLogger(__name__)

# PKCS7 block size (钉钉使用 32 字节，而非标准的 16)
BLOCK_SIZE = 32


class DingCallbackCrypto:
    """钉钉回调加解密"""

    def __init__(self, token: str, encoding_aes_key: str, owner_key: str):
        """
        :param token: 钉钉开放平台开发者设置的 Token
        :param encoding_aes_key: 钉钉开放平台开发者设置的 EncodingAESKey（43 位）
        :param owner_key: 企业自建应用-事件订阅用 appKey，注册回调地址用 corpId
        """
        if not encoding_aes_key or len(encoding_aes_key) != 43:
            raise ValueError(f"EncodingAESKey 必须为 43 位，当前长度: {len(encoding_aes_key)}")
        self.token = token
        self.owner_key = owner_key
        # AES Key = Base64.decode(EncodingAESKey + "=")
        self.aes_key = base64.b64decode(encoding_aes_key + "=")

    # ==================== 签名 ====================

    def get_signature(self, timestamp: str, nonce: str, encrypt: str) -> str:
        """
        计算签名: SHA1(sort([token, timestamp, nonce, encrypt]).join(""))
        """
        array = sorted([self.token, str(timestamp), str(nonce), encrypt])
        raw = "".join(array)
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()

    # ==================== 加密 ====================

    def get_encrypted_map(self, plaintext: str,
                          timestamp: Optional[int] = None,
                          nonce: Optional[str] = None) -> Dict[str, str]:
        """
        加密明文，返回钉钉需要的响应 Map
        :return: {"msg_signature": ..., "timeStamp": ..., "nonce": ..., "encrypt": ...}
        """
        if timestamp is None:
            timestamp = int(time.time() * 1000)
        if nonce is None:
            nonce = self._random_str(16)

        encrypt = self._encrypt(plaintext)
        signature = self.get_signature(str(timestamp), nonce, encrypt)

        return {
            "msg_signature": signature,
            "timeStamp": str(timestamp),
            "nonce": nonce,
            "encrypt": encrypt,
        }

    def _encrypt(self, plaintext: str) -> str:
        """加密明文"""
        random_bytes = self._random_str(16).encode("utf-8")
        plain_bytes = plaintext.encode("utf-8")
        length_bytes = self._int2bytes(len(plain_bytes))
        owner_bytes = self.owner_key.encode("utf-8")

        raw = random_bytes + length_bytes + plain_bytes + owner_bytes

        # PKCS7 padding (block_size = 32)
        pad_amount = BLOCK_SIZE - (len(raw) % BLOCK_SIZE)
        if pad_amount == 0:
            pad_amount = BLOCK_SIZE
        raw += bytes([pad_amount] * pad_amount)

        cipher = AES.new(self.aes_key, AES.MODE_CBC, self.aes_key[:16])
        encrypted = cipher.encrypt(raw)
        return base64.b64encode(encrypted).decode("utf-8")

    # ==================== 解密 ====================

    def get_decrypt_msg(self, msg_signature: str, timestamp: str,
                        nonce: str, encrypt_msg: str) -> str:
        """
        验证签名并解密
        :param msg_signature: 请求中的签名
        :param timestamp: 请求中的时间戳
        :param nonce: 请求中的随机串
        :param encrypt_msg: 请求中的密文
        :return: 解密后的明文 JSON 字符串
        :raises ValueError: 签名不匹配或解密失败
        """
        # 1. 验证签名
        expected_sig = self.get_signature(timestamp, nonce, encrypt_msg)
        if expected_sig != msg_signature:
            logger.error(f"Signature mismatch: expected={expected_sig}, got={msg_signature}")
            logger.error(f"  token={self.token[:8]}..., timestamp={timestamp}, nonce={nonce}")
            logger.error(f"  encrypt={encrypt_msg[:50]}...")
            raise ValueError("签名验证失败")

        # 2. 解密
        return self._decrypt(encrypt_msg)

    def _decrypt(self, text: str) -> str:
        """解密密文"""
        cipher = AES.new(self.aes_key, AES.MODE_CBC, self.aes_key[:16])
        encrypted = base64.b64decode(text)
        decrypted = cipher.decrypt(encrypted)

        # 去除 PKCS7 padding
        pad = decrypted[-1]
        if pad < 1 or pad > BLOCK_SIZE:
            pad = 0
        decrypted = decrypted[:len(decrypted) - pad]

        # 解析：16 字节随机串 + 4 字节网络字节序长度 + 明文 + owner_key
        random_bytes = decrypted[:16]
        length_bytes = decrypted[16:20]
        content_len = self._bytes2int(length_bytes)
        plaintext = decrypted[20:20 + content_len].decode("utf-8")
        from_owner = decrypted[20 + content_len:].decode("utf-8")

        if from_owner != self.owner_key:
            raise ValueError(f"OWNER_KEY 不匹配: expected={self.owner_key}, got={from_owner}")

        return plaintext

    # ==================== 工具方法 ====================

    @staticmethod
    def _random_str(length: int) -> str:
        """生成随机字符串"""
        chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
        return "".join(chars[ord(os.urandom(1)) % len(chars)] for _ in range(length))

    @staticmethod
    def _int2bytes(count: int) -> bytes:
        """int 转 4 字节网络字节序（大端）"""
        return count.to_bytes(4, "big")

    @staticmethod
    def _bytes2int(byte_arr: bytes) -> int:
        """4 字节网络字节序转 int"""
        return int.from_bytes(byte_arr, "big")