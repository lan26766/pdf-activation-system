"""
邮件发送工具
"""

import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional

logger = logging.getLogger(__name__)

class EmailSender:
    """邮件发送器"""
    
    def __init__(self, host: str, port: int, username: str, password: str, 
                 from_email: Optional[str] = None):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.from_email = from_email or username
    
    def send_activation_email(self, to_email: str, activation_code: str, 
                            activation_data: dict) -> bool:
        """发送激活邮件"""
        
        # 如果没有配置邮件，记录到日志
        if not self.username or not self.password:
            logger.info(f"[模拟发送] 激活邮件到 {to_email}")
            logger.info(f"   激活码: {activation_code}")
            logger.info(f"   有效期: {activation_data.get('valid_until', 'N/A')}")
            return True
        
        try:
            # 创建邮件
            msg = MIMEMultipart('alternative')
            
            # 主题
            product_type = activation_data.get('product_type', 'personal').capitalize()
            subject = f"🎉 您的 PDF Fusion Pro {product_type} 版激活码"
            msg['Subject'] = subject
            msg['From'] = self.from_email
            msg['To'] = to_email
            
            # 邮件正文
            html_content = self._create_email_content(to_email, activation_code, activation_data)
            msg.attach(MIMEText(html_content, 'html'))
            
            # 发送邮件
            with smtplib.SMTP(self.host, self.port) as server:
                server.starttls()
                server.login(self.username, self.password)
                server.send_message(msg)
            
            logger.info(f"✅ 激活邮件已发送到 {to_email}")
            return True
            
        except Exception as e:
            logger.error(f"❌ 发送邮件失败: {e}")
            return False
    
    def _create_email_content(self, email: str, activation_code: str, 
                            activation_data: dict) -> str:
        """创建邮件内容"""
        
        product_type = activation_data.get('product_type', 'personal').capitalize()
        valid_until = activation_data.get('valid_until', '')[:10]
        max_devices = activation_data.get('max_devices', 3)
        
        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>PDF Fusion Pro 激活码</title>
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px; }}
                .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 30px; color: white; text-align: center; border-radius: 10px 10px 0 0; }}
                .content {{ background: white; padding: 30px; border-radius: 0 0 10px 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }}
                .code {{ background: #f8f9fa; border: 2px dashed #667eea; padding: 20px; text-align: center; font-family: monospace; font-size: 18px; letter-spacing: 2px; margin: 20px 0; border-radius: 5px; }}
                .info {{ background: #e7f3ff; border-left: 4px solid #1890ff; padding: 15px; margin: 20px 0; }}
                .warning {{ background: #fff3cd; border: 1px solid #ffeaa7; padding: 15px; border-radius: 5px; margin: 20px 0; }}
                .footer {{ text-align: center; margin-top: 30px; padding-top: 20px; border-top: 1px solid #eee; color: #666; font-size: 12px; }}
            </style>
        </head>
        <body>
            <div class="header">
                <h1 style="margin: 0; font-size: 28px;">🎉 感谢您购买 PDF Fusion Pro！</h1>
                <p style="margin: 10px 0 0 0; opacity: 0.9;">您的 {product_type} 版激活信息</p>
            </div>
            
            <div class="content">
                <h2 style="color: #2c3e50; margin-top: 0;">📋 激活信息</h2>
                
                <table style="width: 100%; border-collapse: collapse; margin-bottom: 20px;">
                    <tr>
                        <td style="padding: 10px; border-bottom: 1px solid #eee; width: 100px;"><strong>邮箱</strong></td>
                        <td style="padding: 10px; border-bottom: 1px solid #eee;">{email}</td>
                    </tr>
                    <tr>
                        <td style="padding: 10px; border-bottom: 1px solid #eee;"><strong>版本</strong></td>
                        <td style="padding: 10px; border-bottom: 1px solid #eee;">{product_type} 版</td>
                    </tr>
                    <tr>
                        <td style="padding: 10px;"><strong>有效期</strong></td>
                        <td style="padding: 10px;">{valid_until}</td>
                    </tr>
                </table>
                
                <h3 style="color: #2c3e50;">🔑 您的激活码</h3>
                <div class="code">
                    {activation_code}
                </div>
                <p style="text-align: center; color: #666;">请复制此激活码，在软件激活窗口中粘贴</p>
                
                <div class="info">
                    <h4 style="margin-top: 0; color: #1890ff;">🚀 激活步骤</h4>
                    <ol>
                        <li>下载并安装 PDF Fusion Pro</li>
                        <li>运行软件，点击"激活"按钮</li>
                        <li>粘贴上面的激活码</li>
                        <li>点击"激活"完成注册</li>
                    </ol>
                </div>
                
                <div class="warning">
                    <h4 style="margin-top: 0; color: #856404;">⚠️ 重要提醒</h4>
                    <ul>
                        <li>每个激活码最多可在 <strong>{max_devices} 台设备</strong> 使用</li>
                        <li>请妥善保管此激活码，一旦丢失无法找回</li>
                        <li>如需更换设备，请先在原设备注销</li>
                        <li>技术支持: support@example.com</li>
                    </ul>
                </div>
                
                <div class="footer">
                    <p>© 2024 PDF Fusion Pro. 版权所有。</p>
                    <p>此邮件为系统自动发送，请勿直接回复。</p>
                </div>
            </div>
        </body>
        </html>
        """
    
    def test_connection(self) -> bool:
        """测试邮件连接"""
        try:
            with smtplib.SMTP(self.host, self.port) as server:
                server.starttls()
                server.login(self.username, self.password)
                server.quit()
            return True
        except Exception as e:
            logger.error(f"邮件连接测试失败: {e}")
            return False.
