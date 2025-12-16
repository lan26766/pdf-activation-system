"""
Gumroad Webhook 处理器
"""

import json
import logging
import hmac
import hashlib
from typing import Dict, Any, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

class GumroadWebhook:
    """Gumroad Webhook处理器"""
    
    def __init__(self, webhook_secret: str = ""):
        self.webhook_secret = webhook_secret
    
    def verify_signature(self, payload: bytes, signature: str) -> bool:
        """验证Webhook签名"""
        if not self.webhook_secret:
            return True  # 如果没有设置密钥，跳过验证
        
        expected_signature = hmac.new(
            self.webhook_secret.encode(),
            payload,
            hashlib.sha256
        ).hexdigest()
        
        return hmac.compare_digest(signature, expected_signature)
    
    def parse_product_type(self, product_name: str) -> str:
        """从产品名称解析产品类型"""
        product_name_lower = product_name.lower()
        
        if 'enterprise' in product_name_lower:
            return 'enterprise'
        elif 'business' in product_name_lower:
            return 'business'
        elif 'professional' in product_name_lower:
            return 'professional'
        elif 'personal' in product_name_lower:
            return 'personal'
        else:
            # 默认判断
            price = product_name_lower
            if '99' in price or 'business' in price:
                return 'business'
            elif '299' in price or 'enterprise' in price:
                return 'enterprise'
            else:
                return 'personal'
    
    def get_days_valid(self, product_type: str) -> int:
        """根据产品类型获取有效期"""
        days_map = {
            'personal': 365,
            'professional': 365,
            'business': 365 * 2,
            'enterprise': 365 * 3
        }
        return days_map.get(product_type, 365)
    
    def get_max_devices(self, product_type: str) -> int:
        """根据产品类型获取最大设备数"""
        devices_map = {
            'personal': 3,
            'professional': 5,
            'business': 10,
            'enterprise': 99
        }
        return devices_map.get(product_type, 3)
    
    def process_webhook(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """处理Webhook数据"""
        try:
            # 基本信息
            purchase_id = payload.get('id', '')
            email = payload.get('email', '')
            product_name = payload.get('product_name', '')
            price = float(payload.get('price', 0)) / 100
            currency = payload.get('currency', 'USD')
            created_at = payload.get('created_at', '')
            
            # 解析产品信息
            product_type = self.parse_product_type(product_name)
            days_valid = self.get_days_valid(product_type)
            max_devices = self.get_max_devices(product_type)
            
            # 格式化日期
            try:
                purchase_date = datetime.fromisoformat(
                    created_at.replace('Z', '+00:00')
                ).strftime('%Y-%m-%d %H:%M:%S')
            except:
                purchase_date = created_at
            
            result = {
                'purchase_id': purchase_id,
                'email': email,
                'product_name': product_name,
                'product_type': product_type,
                'price': price,
                'currency': currency,
                'purchase_date': purchase_date,
                'days_valid': days_valid,
                'max_devices': max_devices,
                'raw_data': payload,
                'success': True
            }
            
            logger.info(f"✅ 解析Webhook: {email} -> {product_type}")
            return result
            
        except Exception as e:
            logger.error(f"❌ 解析Webhook失败: {e}")
            return {
                'success': False,
                'error': str(e),
                'raw_data': payload
            }.
