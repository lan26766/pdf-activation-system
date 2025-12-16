"""
激活码生成器
"""

import base64
import json
import hashlib
from datetime import datetime, timedelta
from typing import Dict, Any, Tuple
from cryptography.fernet import Fernet

class ActivationGenerator:
    """激活码生成器"""
    
    def __init__(self, cipher: Fernet):
        self.cipher = cipher
    
    def generate(self, email: str, product_type: str = "personal", 
                days_valid: int = 365, max_devices: int = 3,
                purchase_id: str = "", note: str = "") -> Tuple[str, Dict[str, Any]]:
        """生成激活码"""
        
        # 激活数据
        activation_data = {
            "email": email,
            "product_type": product_type,
            "days_valid": days_valid,
            "generated_at": datetime.now().isoformat(),
            "valid_until": (datetime.now() + timedelta(days=days_valid)).isoformat(),
            "max_devices": max_devices,
            "purchase_id": purchase_id,
            "note": note,
            "version": "2.0"
        }
        
        # 生成校验码
        checksum = hashlib.md5(
            f"{email}:{product_type}:{days_valid}".encode()
        ).hexdigest()[:8]
        activation_data['checksum'] = checksum
        
        # 加密
        data_str = json.dumps(activation_data, separators=(',', ':'))
        encrypted = self.cipher.encrypt(data_str.encode())
        
        # Base64编码
        activation_code = base64.urlsafe_b64encode(encrypted).decode()
        
        # 格式化为易读格式
        formatted_code = '-'.join([
            activation_code[i:i+8] 
            for i in range(0, len(activation_code), 8)
        ])[:59]  # 限制长度
        
        return formatted_code, activation_data
    
    def verify(self, activation_code: str) -> Tuple[bool, str, Dict[str, Any]]:
        """验证激活码"""
        try:
            # 清理格式
            code_clean = activation_code.replace('-', '').replace(' ', '')
            
            # Base64解码
            encrypted = base64.urlsafe_b64decode(code_clean + '=' * (4 - len(code_clean) % 4))
            
            # 解密
            decrypted = self.cipher.decrypt(encrypted).decode()
            activation_data = json.loads(decrypted)
            
            # 验证校验码
            expected_checksum = hashlib.md5(
                f"{activation_data['email']}:{activation_data['product_type']}:{activation_data['days_valid']}".encode()
            ).hexdigest()[:8]
            
            if activation_data.get('checksum') != expected_checksum:
                return False, "激活码校验失败", {}
            
            # 检查有效期
            valid_until = datetime.fromisoformat(activation_data['valid_until'])
            if datetime.now() > valid_until:
                return False, "激活码已过期", {}
            
            # 计算剩余天数
            days_remaining = (valid_until - datetime.now()).days
            activation_data['days_remaining'] = days_remaining
            
            return True, "激活码有效", activation_data
            
        except Exception as e:
            return False, f"激活码无效: {str(e)}", {}
    
    def decode(self, activation_code: str) -> Dict[str, Any]:
        """解码激活码（不验证）"""
        try:
            code_clean = activation_code.replace('-', '').replace(' ', '')
            encrypted = base64.urlsafe_b64decode(code_clean + '=' * (4 - len(code_clean) % 4))
            decrypted = self.cipher.decrypt(encrypted).decode()
            return json.loads(decrypted)
        except:
            return {}.
