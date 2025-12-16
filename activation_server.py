"""
PDF Fusion Pro - 激活服务器 (PostgreSQL)
主服务器文件
"""

import os
import json
import base64
import hashlib
import logging
from datetime import datetime, timedelta
from functools import wraps

from flask import Flask, request, jsonify
from flask_cors import CORS
from cryptography.fernet import Fernet
import psycopg2
from psycopg2.extras import RealDictCursor

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 初始化Flask应用
app = Flask(__name__)
CORS(app)

# 配置类
class Config:
    # 从环境变量读取
    ENCRYPTION_KEY = os.getenv('ENCRYPTION_KEY', '')
    ADMIN_API_KEY = os.getenv('ADMIN_API_KEY', '')
    DATABASE_URL = os.getenv('DATABASE_URL', '')
    
    # 邮件配置
    SMTP_HOST = os.getenv('SMTP_HOST', 'smtp.gmail.com')
    SMTP_PORT = int(os.getenv('SMTP_PORT', 587))
    SMTP_USER = os.getenv('SMTP_USER', '')
    SMTP_PASSWORD = os.getenv('SMTP_PASSWORD', '')
    
    # Gumroad配置
    GUMROAD_WEBHOOK_SECRET = os.getenv('GUMROAD_WEBHOOK_SECRET', '')
    
    @classmethod
    def validate(cls):
        """验证配置"""
        required = ['ENCRYPTION_KEY', 'ADMIN_API_KEY', 'DATABASE_URL']
        missing = [var for var in required if not getattr(cls, var)]
        
        if missing:
            raise ValueError(f"缺少环境变量: {', '.join(missing)}")
        
        logger.info("✅ 配置验证通过")

# 初始化配置
config = Config()

# 初始化加密
def init_encryption():
    """初始化加密工具"""
    try:
        key = base64.urlsafe_b64encode(
            config.ENCRYPTION_KEY.ljust(32)[:32].encode()
        )
        return Fernet(key)
    except Exception as e:
        logger.error(f"加密初始化失败: {e}")
        raise

# 初始化数据库连接
def get_db_connection():
    """获取数据库连接"""
    try:
        conn = psycopg2.connect(config.DATABASE_URL)
        return conn
    except Exception as e:
        logger.error(f"数据库连接失败: {e}")
        raise

# 初始化
try:
    config.validate()
    cipher = init_encryption()
    logger.info("✅ 系统初始化完成")
except Exception as e:
    logger.error(f"❌ 初始化失败: {e}")
    raise

# ==================== 工具函数 ====================

def require_api_key(f):
    """API密钥验证装饰器"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        api_key = request.headers.get('X-API-Key')
        if not api_key or api_key != config.ADMIN_API_KEY:
            return jsonify({"error": "未授权"}), 401
        return f(*args, **kwargs)
    return decorated_function

def generate_activation_code(email, product_type="personal", days=365, purchase_data=None):
    """生成激活码"""
    activation_data = {
        "email": email,
        "product_type": product_type,
        "days_valid": days,
        "generated_at": datetime.now().isoformat(),
        "valid_until": (datetime.now() + timedelta(days=days)).isoformat(),
        "max_devices": 3 if product_type == "personal" else 10,
        "purchase_id": purchase_data.get('id') if purchase_data else ''
    }
    
    # 加密
    data_str = json.dumps(activation_data, separators=(',', ':'))
    encrypted = cipher.encrypt(data_str.encode())
    activation_code = base64.urlsafe_b64encode(encrypted).decode()
    
    # 格式化
    formatted_code = '-'.join([
        activation_code[i:i+8] 
        for i in range(0, len(activation_code), 8)
    ])[:59]
    
    return formatted_code, activation_data

def save_activation_to_db(email, activation_code, activation_data):
    """保存激活码到数据库"""
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute('''
            INSERT INTO activations 
            (email, activation_code, product_type, days_valid, max_devices, valid_until, metadata, purchase_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            ''', (
                email,
                activation_code,
                activation_data['product_type'],
                activation_data['days_valid'],
                activation_data['max_devices'],
                activation_data['valid_until'],
                json.dumps(activation_data),
                activation_data.get('purchase_id')
            ))
            
            activation_id = cursor.fetchone()[0]
            conn.commit()
            return activation_id
            
    except psycopg2.IntegrityError:
        conn.rollback()
        # 如果已存在，返回现有ID
        with conn.cursor() as cursor:
            cursor.execute(
                'SELECT id FROM activations WHERE activation_code = %s',
                (activation_code,)
            )
            result = cursor.fetchone()
            return result[0] if result else None
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()

def verify_activation_code(activation_code):
    """验证激活码"""
    try:
        # 清理格式
        code_clean = activation_code.replace('-', '').replace(' ', '')
        
        # 解码
        encrypted = base64.urlsafe_b64decode(code_clean + '=' * (4 - len(code_clean) % 4))
        decrypted = cipher.decrypt(encrypted).decode()
        activation_data = json.loads(decrypted)
        
        # 检查有效期
        valid_until = datetime.fromisoformat(activation_data['valid_until'])
        if datetime.now() > valid_until:
            return False, "激活码已过期", None
        
        # 计算剩余天数
        days_remaining = (valid_until - datetime.now()).days
        activation_data['days_remaining'] = days_remaining
        
        return True, "激活码有效", activation_data
        
    except Exception as e:
        return False, f"激活码无效: {str(e)}", None

def register_device(activation_code, device_id, device_name):
    """注册设备激活"""
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            # 获取激活信息
            cursor.execute('''
            SELECT id, max_devices, is_used 
            FROM activations 
            WHERE activation_code = %s
            FOR UPDATE
            ''', (activation_code,))
            
            activation = cursor.fetchone()
            if not activation:
                return False, "激活码不存在"
            
            activation_id, max_devices, is_used = activation
            
            # 检查是否已激活此设备
            cursor.execute('''
            SELECT id FROM device_activations 
            WHERE activation_id = %s AND device_id = %s AND is_active = TRUE
            ''', (activation_id, device_id))
            
            existing_device = cursor.fetchone()
            if existing_device:
                # 更新最后使用时间
                cursor.execute('''
                UPDATE device_activations 
                SET last_used = CURRENT_TIMESTAMP 
                WHERE id = %s
                ''', (existing_device[0],))
                conn.commit()
                return True, "设备已激活"
            
            # 检查设备数量
            cursor.execute('''
            SELECT COUNT(*) FROM device_activations 
            WHERE activation_id = %s AND is_active = TRUE
            ''', (activation_id,))
            
            device_count = cursor.fetchone()[0]
            if device_count >= max_devices:
                return False, f"已达到最大设备数 ({max_devices}台)"
            
            # 注册新设备
            cursor.execute('''
            INSERT INTO device_activations 
            (activation_id, device_id, device_name)
            VALUES (%s, %s, %s)
            ''', (activation_id, device_id, device_name))
            
            # 更新激活码状态
            if not is_used:
                cursor.execute('''
                UPDATE activations 
                SET is_used = TRUE, used_at = CURRENT_TIMESTAMP, used_by_device = %s
                WHERE id = %s
                ''', (device_id, activation_id))
            
            conn.commit()
            return True, "设备注册成功"
            
    except Exception as e:
        conn.rollback()
        return False, f"注册失败: {str(e)}"
    finally:
        conn.close()

# ==================== API 路由 ====================

@app.route('/')
def home():
    """主页"""
    return jsonify({
        "service": "PDF Fusion Pro 激活服务器",
        "version": "2.0.0",
        "status": "运行中",
        "database": "PostgreSQL",
        "timestamp": datetime.now().isoformat()
    })

@app.route('/health')
def health_check():
    """健康检查"""
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute('SELECT 1')
            result = cursor.fetchone()
        conn.close()
        
        return jsonify({
            "status": "healthy",
            "database": "connected",
            "timestamp": datetime.now().isoformat()
        })
    except Exception as e:
        return jsonify({
            "status": "unhealthy",
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }), 500

@app.route('/api/generate', methods=['POST'])
@require_api_key
def api_generate():
    """生成激活码"""
    try:
        data = request.json
        email = data.get('email')
        product_type = data.get('product_type', 'personal')
        days = data.get('days', 365)
        
        if not email:
            return jsonify({"error": "邮箱地址是必需的"}), 400
        
        # 生成激活码
        activation_code, activation_data = generate_activation_code(
            email, product_type, days
        )
        
        # 保存到数据库
        activation_id = save_activation_to_db(email, activation_code, activation_data)
        
        logger.info(f"✅ 激活码生成: {email} -> {activation_code[:20]}...")
        
        return jsonify({
            "success": True,
            "activation_id": activation_id,
            "activation_code": activation_code,
            "data": activation_data
        })
        
    except Exception as e:
        logger.error(f"生成激活码失败: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/verify', methods=['POST'])
def api_verify():
    """验证激活码"""
    try:
        data = request.json
        activation_code = data.get('activation_code')
        device_id = data.get('device_id')
        device_name = data.get('device_name', 'Unknown Device')
        
        if not activation_code:
            return jsonify({"error": "激活码是必需的"}), 400
        
        if not device_id:
            return jsonify({"error": "设备ID是必需的"}), 400
        
        # 验证激活码
        is_valid, message, activation_data = verify_activation_code(activation_code)
        if not is_valid:
            return jsonify({"valid": False, "message": message})
        
        # 注册设备
        registered, reg_message = register_device(activation_code, device_id, device_name)
        if not registered:
            return jsonify({"valid": False, "message": reg_message})
        
        logger.info(f"✅ 激活码验证: {activation_code[:20]}... -> {device_id}")
        
        return jsonify({
            "valid": True,
            "message": "激活成功",
            "data": {
                "email": activation_data['email'],
                "product_type": activation_data['product_type'],
                "valid_until": activation_data['valid_until'],
                "max_devices": activation_data['max_devices'],
                "days_remaining": activation_data['days_remaining'],
                "device_id": device_id
            }
        })
        
    except Exception as e:
        logger.error(f"验证激活码失败: {e}")
        return jsonify({"error": "服务器内部错误"}), 500

@app.route('/api/webhook/gumroad', methods=['POST'])
def webhook_gumroad():
    """Gumroad Webhook"""
    try:
        data = request.json
        
        # 验证Webhook签名（可选）
        if config.GUMROAD_WEBHOOK_SECRET:
            signature = request.headers.get('X-Gumroad-Signature')
            if not signature:
                return jsonify({"error": "缺少签名"}), 401
        
        # 记录购买
        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute('''
                INSERT INTO purchases 
                (purchase_id, email, product_name, price, currency, purchased_at, gumroad_data)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (purchase_id) DO UPDATE SET
                email = EXCLUDED.email,
                product_name = EXCLUDED.product_name,
                price = EXCLUDED.price,
                gumroad_data = EXCLUDED.gumroad_data
                ''', (
                    data.get('id'),
                    data.get('email'),
                    data.get('product_name'),
                    float(data.get('price', 0)) / 100,
                    data.get('currency'),
                    data.get('created_at'),
                    json.dumps(data)
                ))
                conn.commit()
        finally:
            conn.close()
        
        # 判断产品类型
        product_name = data.get('product_name', '').lower()
        product_type = 'personal'
        days_valid = 365
        
        if 'business' in product_name:
            product_type = 'business'
            days_valid = 365 * 2
        elif 'enterprise' in product_name:
            product_type = 'enterprise'
            days_valid = 365 * 3
        
        # 生成激活码
        email = data.get('email')
        activation_code, activation_data = generate_activation_code(
            email=email,
            product_type=product_type,
            days=days_valid,
            purchase_data=data
        )
        
        # 保存到数据库
        activation_id = save_activation_to_db(email, activation_code, activation_data)
        
        # 标记购买为已处理
        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute('''
                UPDATE purchases 
                SET processed = TRUE, processed_at = CURRENT_TIMESTAMP
                WHERE purchase_id = %s
                ''', (data.get('id'),))
                conn.commit()
        finally:
            conn.close()
        
        logger.info(f"✅ Gumroad Webhook: {email} -> {activation_code[:20]}...")
        
        return jsonify({
            "success": True,
            "message": "激活码已生成",
            "activation_code": activation_code,
            "activation_id": activation_id
        })
        
    except Exception as e:
        logger.error(f"Webhook处理失败: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/admin/stats', methods=['GET'])
@require_api_key
def admin_stats():
    """管理统计"""
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute('SELECT COUNT(*) as total FROM activations')
            total = cursor.fetchone()['total']
            
            cursor.execute('SELECT COUNT(*) as used FROM activations WHERE is_used = TRUE')
            used = cursor.fetchone()['used']
            
            cursor.execute('SELECT COUNT(*) as purchases FROM purchases')
            purchases = cursor.fetchone()['purchases']
            
            # 今日激活
            today = datetime.now().strftime('%Y-%m-%d')
            cursor.execute('''
            SELECT COUNT(*) as today FROM activations 
            WHERE DATE(generated_at) = %s
            ''', (today,))
            today_count = cursor.fetchone()['today']
            
            return jsonify({
                "total_activations": total,
                "used_activations": used,
                "unused_activations": total - used,
                "total_purchases": purchases,
                "today_activations": today_count,
                "timestamp": datetime.now().isoformat()
            })
    finally:
        conn.close()

# ==================== 初始化数据库 ====================

def init_database():
    """初始化数据库表"""
    from database.init_db import init_database as db_init
    db_init(config.DATABASE_URL)

# 启动时初始化数据库
init_database()

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    debug = os.getenv('DEBUG', 'false').lower() == 'true'
    
    logger.info(f"🚀 启动PDF Fusion Pro激活服务器")
    logger.info(f"🔗 数据库: PostgreSQL")
    logger.info(f"🔐 加密: 已启用")
    
    app.run(host='0.0.0.0', port=port, debug=debug)
