"""
PDF Fusion Pro - 激活码服务器
部署到 Render.com 的完整版本
"""
import os
import json
import base64
import hashlib
import sqlite3
from datetime import datetime, timedelta
from functools import wraps

from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
from cryptography.fernet import Fernet
import requests

# 初始化Flask应用
app = Flask(__name__)
CORS(app)  # 允许跨域

# 配置
class Config:
    # 从环境变量读取（在Render.com面板设置）
    SECRET_KEY = os.getenv('ENCRYPTION_KEY', 'default_secret_key_change_in_production')
    DATABASE_URL = os.getenv('DATABASE_URL', 'sqlite:///activations.db')
    SMTP_HOST = os.getenv('SMTP_HOST', 'smtp.gmail.com')
    SMTP_PORT = int(os.getenv('SMTP_PORT', 587))
    SMTP_USER = os.getenv('SMTP_USER', '')
    SMTP_PASSWORD = os.getenv('SMTP_PASSWORD', '')
    ADMIN_API_KEY = os.getenv('ADMIN_API_KEY', 'change_this_in_production')
    GUMROAD_WEBHOOK_SECRET = os.getenv('GUMROAD_WEBHOOK_SECRET', '')
    
    # 初始化加密
    @classmethod
    def get_cipher(cls):
        key = base64.urlsafe_b64encode(cls.SECRET_KEY.ljust(32)[:32].encode())
        return Fernet(key)

config = Config()
cipher = config.get_cipher()

# 数据库连接
def get_db_connection():
    if config.DATABASE_URL.startswith('sqlite'):
        conn = sqlite3.connect('activations.db')
        conn.row_factory = sqlite3.Row
    else:
        # PostgreSQL连接（Render.com默认）
        import psycopg2
        import urllib.parse as urlparse
        url = urlparse.urlparse(config.DATABASE_URL)
        conn = psycopg2.connect(
            database=url.path[1:],
            user=url.username,
            password=url.password,
            host=url.hostname,
            port=url.port
        )
    return conn

def init_database():
    """初始化数据库表"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 激活码表
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS activations (
        id SERIAL PRIMARY KEY,
        email VARCHAR(255) NOT NULL,
        activation_code TEXT NOT NULL UNIQUE,
        product_type VARCHAR(50) DEFAULT 'personal',
        days_valid INTEGER DEFAULT 365,
        max_devices INTEGER DEFAULT 3,
        generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        valid_until TIMESTAMP,
        is_used BOOLEAN DEFAULT FALSE,
        used_at TIMESTAMP,
        used_by_device TEXT,
        purchase_id TEXT,
        order_id TEXT,
        metadata JSONB
    )
    ''')
    
    # 设备激活记录表
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS device_activations (
        id SERIAL PRIMARY KEY,
        activation_id INTEGER REFERENCES activations(id),
        device_id TEXT NOT NULL,
        device_name TEXT,
        activated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        last_used TIMESTAMP,
        is_active BOOLEAN DEFAULT TRUE
    )
    ''')
    
    # Gumroad购买记录表
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS purchases (
        id SERIAL PRIMARY KEY,
        purchase_id TEXT UNIQUE NOT NULL,
        email VARCHAR(255) NOT NULL,
        product_name TEXT,
        price DECIMAL(10,2),
        currency VARCHAR(10),
        purchased_at TIMESTAMP,
        gumroad_data JSONB,
        processed BOOLEAN DEFAULT FALSE,
        processed_at TIMESTAMP
    )
    ''')
    
    conn.commit()
    conn.close()

# API密钥验证装饰器
def require_api_key(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        api_key = request.headers.get('X-API-Key')
        if not api_key or api_key != config.ADMIN_API_KEY:
            return jsonify({"error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated_function

# Gumroad Webhook验证
def verify_gumroad_signature(request):
    """验证Gumroad Webhook签名"""
    if not config.GUMROAD_WEBHOOK_SECRET:
        return True  # 如果没有设置密钥，跳过验证
    
    signature = request.headers.get('X-Gumroad-Signature')
    if not signature:
        return False
    
    # 验证签名逻辑（根据Gumroad文档）
    import hmac
    import hashlib
    
    payload = request.get_data()
    expected_signature = hmac.new(
        config.GUMROAD_WEBHOOK_SECRET.encode(),
        payload,
        hashlib.sha256
    ).hexdigest()
    
    return hmac.compare_digest(signature, expected_signature)

# 激活码生成
class ActivationGenerator:
    @staticmethod
    def generate_code(email, product_type="personal", days=365, purchase_data=None):
        """生成加密的激活码"""
        
        # 激活数据
        activation_data = {
            "email": email,
            "product_type": product_type,
            "days_valid": days,
            "generated_at": datetime.now().isoformat(),
            "valid_until": (datetime.now() + timedelta(days=days)).isoformat(),
            "max_devices": 3 if product_type == "personal" else 10,
            "purchase_id": purchase_data.get('id') if purchase_data else '',
            "seller_id": purchase_data.get('seller_id') if purchase_data else ''
        }
        
        # 加密
        data_str = json.dumps(activation_data, separators=(',', ':'))
        encrypted = cipher.encrypt(data_str.encode())
        activation_code = base64.urlsafe_b64encode(encrypted).decode()
        
        # 格式化为易读格式
        formatted_code = '-'.join([
            activation_code[i:i+8] 
            for i in range(0, len(activation_code), 8)
        ])[:59]  # 限制长度
        
        return formatted_code, activation_data
    
    @staticmethod
    def save_to_database(email, activation_code, activation_data):
        """保存到数据库"""
        conn = get_db_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
            INSERT INTO activations 
            (email, activation_code, product_type, days_valid, valid_until, max_devices, purchase_id, metadata)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ''', (
                email,
                activation_code,
                activation_data['product_type'],
                activation_data['days_valid'],
                activation_data['valid_until'],
                activation_data['max_devices'],
                activation_data.get('purchase_id'),
                json.dumps(activation_data)
            ))
            
            conn.commit()
            activation_id = cursor.lastrowid
            return activation_id
            
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()

# 邮件发送
class EmailSender:
    @staticmethod
    def send_activation_email(email, activation_code, activation_data):
        """发送激活邮件"""
        
        # 如果未配置SMTP，记录到日志
        if not config.SMTP_USER or not config.SMTP_PASSWORD:
            print(f"[模拟发送] 激活邮件到 {email}: {activation_code}")
            return True
        
        # 邮件内容
        subject = f"🎉 您的 PDF Fusion Pro 激活码 - {activation_data['product_type'].capitalize()} 版"
        
        # 读取HTML模板
        try:
            with open('templates/activation_email.html', 'r', encoding='utf-8') as f:
                html_template = f.read()
        except:
            html_template = '''
            <html>
            <body>
                <h1>您的 PDF Fusion Pro 激活码</h1>
                <p>激活码: <strong>{activation_code}</strong></p>
                <p>有效期至: {valid_until}</p>
                <p>感谢您的购买！</p>
            </body>
            </html>
            '''
        
        # 填充模板
        html_content = html_template.format(
            activation_code=activation_code,
            email=email,
            product_type=activation_data['product_type'].capitalize(),
            valid_until=activation_data['valid_until'][:10],
            max_devices=activation_data['max_devices'],
            current_year=datetime.now().year
        )
        
        # 发送邮件
        try:
            import smtplib
            from email.mime.text import MIMEText
            from email.mime.multipart import MIMEMultipart
            
            msg = MIMEMultipart('alternative')
            msg['Subject'] = subject
            msg['From'] = config.SMTP_USER
            msg['To'] = email
            
            msg.attach(MIMEText(html_content, 'html'))
            
            with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT) as server:
                server.starttls()
                server.login(config.SMTP_USER, config.SMTP_PASSWORD)
                server.send_message(msg)
            
            print(f"✅ 激活邮件已发送到 {email}")
            return True
            
        except Exception as e:
            print(f"❌ 发送邮件失败: {e}")
            return False

# ==================== API 路由 ====================

@app.route('/')
def home():
    """主页"""
    return jsonify({
        "service": "PDF Fusion Pro Activation Server",
        "version": "1.0.0",
        "status": "running",
        "endpoints": {
            "health": "/health",
            "generate": "/api/generate (POST)",
            "verify": "/api/verify (POST)",
            "webhook": "/api/webhook/gumroad (POST)",
            "admin": "/api/admin/*"
        }
    })

@app.route('/health')
def health_check():
    """健康检查"""
    return jsonify({"status": "healthy", "timestamp": datetime.now().isoformat()})

@app.route('/api/generate', methods=['POST'])
@require_api_key
def generate_activation():
    """手动生成激活码（管理员用）"""
    try:
        data = request.json
        email = data.get('email')
        product_type = data.get('product_type', 'personal')
        days = data.get('days', 365)
        
        if not email:
            return jsonify({"error": "Email is required"}), 400
        
        # 生成激活码
        code, activation_data = ActivationGenerator.generate_code(
            email, product_type, days
        )
        
        # 保存到数据库
        activation_id = ActivationGenerator.save_to_database(
            email, code, activation_data
        )
        
        # 发送邮件
        EmailSender.send_activation_email(email, code, activation_data)
        
        return jsonify({
            "success": True,
            "activation_id": activation_id,
            "activation_code": code,
            "data": activation_data
        })
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/verify', methods=['POST'])
def verify_activation():
    """验证激活码（客户端调用）"""
    try:
        data = request.json
        activation_code = data.get('activation_code')
        device_id = data.get('device_id')
        device_name = data.get('device_name', 'Unknown Device')
        
        if not activation_code:
            return jsonify({"error": "Activation code is required"}), 400
        
        # 清理激活码
        code_clean = activation_code.replace('-', '').replace(' ', '')
        
        try:
            # 解码和解密
            encrypted = base64.urlsafe_b64decode(code_clean + '=' * (4 - len(code_clean) % 4))
            decrypted = cipher.decrypt(encrypted).decode()
            activation_data = json.loads(decrypted)
            
            # 检查有效期
            valid_until = datetime.fromisoformat(activation_data['valid_until'])
            if datetime.now() > valid_until:
                return jsonify({
                    "valid": False,
                    "message": "激活码已过期"
                })
            
            # 查询数据库
            conn = get_db_connection()
            cursor = conn.cursor()
            
            cursor.execute(
                'SELECT * FROM activations WHERE activation_code = %s',
                (activation_code,)
            )
            db_record = cursor.fetchone()
            
            if not db_record:
                # 如果数据库中没有记录，可能是旧版本生成的，仍然允许
                print(f"⚠️ 激活码不在数据库中: {activation_code}")
            else:
                if db_record['is_used']:
                    # 检查是否当前设备
                    cursor.execute('''
                    SELECT * FROM device_activations 
                    WHERE activation_id = %s AND device_id = %s AND is_active = TRUE
                    ''', (db_record['id'], device_id))
                    
                    device_record = cursor.fetchone()
                    
                    if not device_record:
                        # 不是当前设备，检查设备数量
                        cursor.execute('''
                        SELECT COUNT(*) as device_count FROM device_activations 
                        WHERE activation_id = %s AND is_active = TRUE
                        ''', (db_record['id'],))
                        
                        device_count = cursor.fetchone()['device_count']
                        
                        if device_count >= db_record['max_devices']:
                            return jsonify({
                                "valid": False,
                                "message": f"已达到最大设备数 ({db_record['max_devices']}台)"
                            })
            
            # 记录设备激活
            if device_id and db_record:
                cursor.execute('''
                INSERT INTO device_activations (activation_id, device_id, device_name)
                VALUES (%s, %s, %s)
                ON CONFLICT (activation_id, device_id) 
                DO UPDATE SET last_used = CURRENT_TIMESTAMP, is_active = TRUE
                ''', (db_record['id'], device_id, device_name))
                
                # 更新激活码为已使用
                cursor.execute('''
                UPDATE activations 
                SET is_used = TRUE, used_at = CURRENT_TIMESTAMP
                WHERE id = %s
                ''', (db_record['id'],))
                
                conn.commit()
            
            conn.close()
            
            return jsonify({
                "valid": True,
                "message": "激活码有效",
                "data": {
                    "email": activation_data['email'],
                    "product_type": activation_data['product_type'],
                    "valid_until": activation_data['valid_until'],
                    "max_devices": activation_data['max_devices'],
                    "days_remaining": (valid_until - datetime.now()).days
                }
            })
            
        except Exception as e:
            return jsonify({
                "valid": False,
                "message": f"激活码无效: {str(e)}"
            })
            
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/webhook/gumroad', methods=['POST'])
def gumroad_webhook():
    """Gumroad Webhook 接收器"""
    try:
        # 验证签名
        if not verify_gumroad_signature(request):
            return jsonify({"error": "Invalid signature"}), 401
        
        data = request.json
        
        # 记录购买
        conn = get_db_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
            INSERT INTO purchases (purchase_id, email, product_name, price, currency, purchased_at, gumroad_data)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (purchase_id) DO NOTHING
            ''', (
                data.get('id'),
                data.get('email'),
                data.get('product_name'),
                data.get('price') / 100 if data.get('price') else 0,
                data.get('currency'),
                data.get('created_at'),
                json.dumps(data)
            ))
            
            conn.commit()
            purchase_id = cursor.lastrowid
            
        except Exception as e:
            conn.rollback()
            print(f"❌ 保存购买记录失败: {e}")
            return jsonify({"error": str(e)}), 500
        finally:
            conn.close()
        
        # 根据产品名称判断产品类型
        product_name = data.get('product_name', '').lower()
        product_type = 'personal'
        days_valid = 365
        
        if 'business' in product_name:
            product_type = 'business'
            max_devices = 10
        elif 'enterprise' in product_name:
            product_type = 'enterprise'
            max_devices = 999
            days_valid = 365 * 3  # 企业版3年
        else:
            max_devices = 3
        
        # 生成激活码
        email = data.get('email')
        activation_code, activation_data = ActivationGenerator.generate_code(
            email=email,
            product_type=product_type,
            days=days_valid,
            purchase_data=data
        )
        
        # 保存到数据库
        activation_id = ActivationGenerator.save_to_database(
            email, activation_code, activation_data
        )
        
        # 发送激活邮件
        EmailSender.send_activation_email(email, activation_code, activation_data)
        
        # 标记购买为已处理
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('''
        UPDATE purchases 
        SET processed = TRUE, processed_at = CURRENT_TIMESTAMP
        WHERE purchase_id = %s
        ''', (data.get('id'),))
        conn.commit()
        conn.close()
        
        print(f"✅ 已处理购买: {email} - {activation_code}")
        
        return jsonify({
            "success": True,
            "message": "Activation code generated and sent",
            "activation_code": activation_code,
            "activation_id": activation_id
        })
        
    except Exception as e:
        print(f"❌ Webhook处理失败: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/admin/stats', methods=['GET'])
@require_api_key
def admin_stats():
    """管理员统计信息"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 获取统计信息
    cursor.execute('SELECT COUNT(*) as total FROM activations')
    total_activations = cursor.fetchone()['total']
    
    cursor.execute('SELECT COUNT(*) as used FROM activations WHERE is_used = TRUE')
    used_activations = cursor.fetchone()['used']
    
    cursor.execute('SELECT COUNT(*) as purchases FROM purchases')
    total_purchases = cursor.fetchone()['purchases']
    
    cursor.execute('SELECT COUNT(*) as processed FROM purchases WHERE processed = TRUE')
    processed_purchases = cursor.fetchone()['processed']
    
    # 最近激活
    cursor.execute('''
    SELECT email, product_type, generated_at 
    FROM activations 
    ORDER BY generated_at DESC 
    LIMIT 10
    ''')
    recent_activations = cursor.fetchall()
    
    conn.close()
    
    return jsonify({
        "total_activations": total_activations,
        "used_activations": used_activations,
        "unused_activations": total_activations - used_activations,
        "total_purchases": total_purchases,
        "processed_purchases": processed_purchases,
        "recent_activations": [
            dict(row) for row in recent_activations
        ]
    })

@app.route('/api/admin/activations', methods=['GET'])
@require_api_key
def admin_list_activations():
    """列出所有激活码"""
    page = int(request.args.get('page', 1))
    limit = int(request.args.get('limit', 50))
    offset = (page - 1) * limit
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
    SELECT a.*, COUNT(d.id) as device_count
    FROM activations a
    LEFT JOIN device_activations d ON a.id = d.activation_id AND d.is_active = TRUE
    GROUP BY a.id
    ORDER BY a.generated_at DESC
    LIMIT %s OFFSET %s
    ''', (limit, offset))
    
    activations = [dict(row) for row in cursor.fetchall()]
    
    cursor.execute('SELECT COUNT(*) as total FROM activations')
    total = cursor.fetchone()['total']
    
    conn.close()
    
    return jsonify({
        "page": page,
        "limit": limit,
        "total": total,
        "total_pages": (total + limit - 1) // limit,
        "activations": activations
    })

# 初始化数据库
init_database()

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=os.getenv('DEBUG', 'False') == 'True')