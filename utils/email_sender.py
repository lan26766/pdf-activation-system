"""
邮件发送工具 - 支持多种邮件服务商
"""
import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

class EmailService:
    """邮件服务"""
    
    SERVICES = {
        'gmail': {
            'host': 'smtp.gmail.com',
            'port': 587
        },
        'outlook': {
            'host': 'smtp.office365.com',
            'port': 587
        },
        'yahoo': {
            'host': 'smtp.mail.yahoo.com',
            'port': 587
        },
        'sendgrid': {
            'host': 'smtp.sendgrid.net',
            'port': 587
        }
    }
    
    @classmethod
    def send_email(cls, 
                  to_email: str,
                  subject: str,
                  html_content: str,
                  from_email: Optional[str] = None,
                  service_type: str = 'gmail',
                  username: Optional[str] = None,
                  password: Optional[str] = None) -> bool:
        """
        发送邮件
        
        Args:
            to_email: 收件人邮箱
            subject: 邮件主题
            html_content: HTML内容
            from_email: 发件人邮箱（默认使用username）
            service_type: 邮件服务类型
            username: SMTP用户名
            password: SMTP密码
            
        Returns:
            bool: 是否发送成功
        """
        
        if not username or not password:
            logger.warning("SMTP credentials not provided, skipping email send")
            return False
        
        if service_type not in cls.SERVICES:
            logger.error(f"Unsupported email service: {service_type}")
            return False
        
        service_config = cls.SERVICES[service_type]
        from_email = from_email or username
        
        try:
            # 创建邮件
            msg = MIMEMultipart('alternative')
            msg['Subject'] = subject
            msg['From'] = from_email
            msg['To'] = to_email
            
            # 添加HTML内容
            msg.attach(MIMEText(html_content, 'html'))
            
            # 发送邮件
            with smtplib.SMTP(service_config['host'], service_config['port']) as server:
                server.starttls()
                server.login(username, password)
                server.send_message(msg)
            
            logger.info(f"Email sent successfully to {to_email}")
            return True
            
        except smtplib.SMTPAuthenticationError as e:
            logger.error(f"SMTP authentication failed: {e}")
        except smtplib.SMTPException as e:
            logger.error(f"SMTP error: {e}")
        except Exception as e:
            logger.error(f"Failed to send email: {e}")
        
        return False