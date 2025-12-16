"""
初始化数据库
"""

import psycopg2
import logging

logger = logging.getLogger(__name__)

def init_database(database_url):
    """初始化数据库表"""
    
    # 读取SQL文件
    try:
        with open('database/schema.sql', 'r', encoding='utf-8') as f:
            sql_commands = f.read()
    except FileNotFoundError:
        logger.error("找不到 schema.sql 文件")
        return False
    
    conn = None
    try:
        # 连接数据库
        conn = psycopg2.connect(database_url)
        conn.autocommit = False
        
        with conn.cursor() as cursor:
            # 分割SQL命令并执行
            commands = sql_commands.split(';')
            
            for command in commands:
                command = command.strip()
                if command:
                    cursor.execute(command)
            
            conn.commit()
        
        logger.info("✅ 数据库初始化完成")
        return True
        
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"❌ 数据库初始化失败: {e}")
        return False
    finally:
        if conn:
            conn.close()

if __name__ == "__main__":
    import sys
    import os
    
    if len(sys.argv) != 2:
        print("用法: python init_db.py <database_url>")
        sys.exit(1)
    
    database_url = sys.argv[1]
    success = init_database(database_url)
    
    if success:
        print("✅ 数据库初始化成功")
        sys.exit(0)
    else:
        print("❌ 数据库初始化失败")
        sys.exit(1).
