import requests
import time
import json
import os
from plyer import notification
import logging
from datetime import datetime
import webbrowser
import threading

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("douyu_monitor.log", encoding='utf-8'),
    ]
)

# 添加控制台处理器，只显示INFO及以上级别的日志
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(logging.Formatter('%(message)s'))  # 简化控制台输出格式
# 设置编码为utf-8，避免emoji表情符号导致的编码错误
console_handler.stream.reconfigure(encoding='utf-8', errors='replace')
logging.getLogger().addHandler(console_handler)

class DouyuMonitor:
    def __init__(self, room_ids, check_interval=60, auto_open=True, server_chan_key=None):
        """
        初始化斗鱼监控器
        
        参数:
            room_ids (list): 要监控的斗鱼房间ID列表
            check_interval (int): 检查间隔时间(秒)
            auto_open (bool): 是否自动打开网页
            server_chan_key (str): Server酱推送密钥
        """
        self.room_ids = room_ids
        self.check_interval = check_interval
        self.room_status = {}  # 存储房间状态
        self.auto_open = auto_open  # 是否自动打开网页
        self.new_live_rooms = []  # 新开播的房间列表
        self.server_chan_key = server_chan_key  # Server酱推送密钥
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        
        # 初始化房间状态
        for room_id in self.room_ids:
            self.room_status[room_id] = False
            
        # 创建配置目录
        os.makedirs('config', exist_ok=True)
        
        # 加载房间名称缓存
        self.room_names = self.load_room_names()
    
    def load_room_names(self):
        """加载房间名称缓存"""
        try:
            if os.path.exists('config/room_names.json'):
                with open('config/room_names.json', 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            logging.error(f"加载房间名称缓存失败: {e}")
        return {}
    
    def save_room_names(self):
        """保存房间名称缓存"""
        try:
            with open('config/room_names.json', 'w', encoding='utf-8') as f:
                json.dump(self.room_names, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logging.error(f"保存房间名称缓存失败: {e}")
    
    def get_room_info(self, room_id):
        """
        获取房间信息
        
        参数:
            room_id (str): 房间ID
            
        返回:
            dict: 房间信息
        """
        url = f"https://open.douyu.com/api/RoomApi/room/{room_id}"
        try:
            response = requests.get(url, headers=self.headers)
            data = response.json()
            if data.get('error') == 0:
                return data.get('data', {})
            else:
                # 尝试使用备用方法
                return self.get_room_info_backup(room_id)
        except Exception as e:
            logging.error(f"获取房间 {room_id} 信息失败: {e}")
            # 尝试使用备用方法
            return self.get_room_info_backup(room_id)
    
    def get_room_info_backup(self, room_id):
        """备用方法获取房间信息"""
        # 尝试方法：直接解析网页内容 (处理重定向)
        try:
            # 使用移动端API，更稳定且不容易被重定向
            url = f"https://m.douyu.com/{room_id}"
            response = requests.get(url, headers=self.headers, timeout=10, allow_redirects=True)
            
            # 记录实际URL，检查是否被重定向
            final_url = response.url
            if final_url != url:
                logging.debug(f"房间 {room_id} 被重定向到 {final_url}")
                
                # 检查是否重定向到了活动页面
                if "topic" in final_url:
                    logging.warning(f"房间 {room_id} 被重定向到活动页面，可能不是有效的直播间")
                    return {
                        'room_id': room_id,
                        'room_name': self.room_names.get(room_id, f'未知房间_{room_id}'),
                        'room_status': '2',  # 默认为未开播
                        'owner_name': self.room_names.get(room_id, f'未知主播_{room_id}')
                    }
            
            if response.status_code == 200:
                html_content = response.text
                
                # 尝试提取房间名和主播名
                import re
                
                # 初始化房间名和主播名
                room_name = "未知房间"
                owner_name = "未知主播"
                is_live = False
                
                # 检查是否包含特定的开播标识 - 移动端页面
                is_live_patterns = [
                    r'"isLive":\s*([1-9])',
                    r'"isLive":\s*true',
                    r'"show_status":\s*"?1"?',
                    r'"videoLoop":\s*0',
                ]
                
                for pattern in is_live_patterns:
                    if re.search(pattern, html_content):
                        is_live = True
                        break
                
                # 提取房间名和主播名
                nickname_pattern = r'"nickname":\s*"([^"]+)"'
                room_name_pattern = r'"roomName":\s*"([^"]+)"'
                
                nickname_match = re.search(nickname_pattern, html_content)
                room_name_match = re.search(room_name_pattern, html_content)
                
                if nickname_match:
                    owner_name = nickname_match.group(1)
                
                if room_name_match:
                    room_name = room_name_match.group(1)
                else:
                    # 尝试使用其他可能的字段名
                    alt_room_name_pattern = r'"room_name":\s*"([^"]+)"'
                    alt_match = re.search(alt_room_name_pattern, html_content)
                    if alt_match:
                        room_name = alt_match.group(1)
                
                # 如果上述方法都失败，尝试从标题提取
                if owner_name == "未知主播" or room_name == "未知房间":
                    title_match = re.search(r'<title>(.*?)</title>', html_content)
                    if title_match:
                        title_text = title_match.group(1)
                        if "-" in title_text:
                            parts = title_text.split('-')
                            if len(parts) >= 2:
                                if room_name == "未知房间":
                                    room_name = parts[0].strip()
                                if owner_name == "未知主播":
                                    owner_name = parts[1].strip().replace("斗鱼", "").strip()
                
                # 检查是否是有效的房间
                if "房间未找到" in html_content or "页面找不到" in html_content:
                    logging.warning(f"房间 {room_id} 可能不存在")
                    is_live = False
                
                # 调试信息
                logging.debug(f"房间 {room_id} 解析结果: 开播状态={is_live}, 房间名={room_name}, 主播名={owner_name}")
                
                return {
                    'room_id': room_id,
                    'room_name': room_name,
                    'room_status': '1' if is_live else '2',
                    'owner_name': owner_name
                }
            else:
                logging.error(f"网页请求失败，状态码: {response.status_code}")
                
                # 尝试PC端API
                return self._try_pc_api(room_id)
        except Exception as e:
            logging.error(f"获取房间 {room_id} 信息失败: {e}")
            
            # 尝试PC端API
            return self._try_pc_api(room_id)
    
    def _try_pc_api(self, room_id):
        """尝试使用PC端API获取房间信息"""
        try:
            # 使用PC端API
            url = f"https://www.douyu.com/betard/{room_id}"
            response = requests.get(url, headers=self.headers, timeout=10)
            if response.status_code == 200:
                try:
                    data = response.json()
                    if data.get('room') and data.get('room').get('room_id'):
                        room_data = data.get('room', {})
                        return {
                            'room_id': room_id,
                            'room_name': room_data.get('room_name', f'未知房间_{room_id}'),
                            'room_status': '1' if room_data.get('show_status') == 1 else '2',
                            'owner_name': room_data.get('owner_name', '未知主播')
                        }
                except:
                    pass
        except Exception as e:
            logging.error(f"PC端API获取房间 {room_id} 信息失败: {e}")
        
        # 如果所有方法都失败了，返回一个基本信息
        cached_name = self.room_names.get(room_id)
        return {
            'room_id': room_id,
            'room_name': cached_name if cached_name else f'未知房间_{room_id}',
            'room_status': '2',  # 默认为未开播
            'owner_name': cached_name if cached_name else f'未知主播_{room_id}'
        }
    
    def check_room_status(self, room_id):
        """
        检查房间状态
        
        参数:
            room_id (str): 房间ID
            
        返回:
            bool: 是否开播
        """
        room_info = self.get_room_info(room_id)
        is_live = room_info.get('room_status') == '1'
        
        # 更新房间名称缓存
        if room_info.get('room_name'):
            self.room_names[room_id] = room_info.get('room_name')
            self.save_room_names()
        
        return is_live, room_info
    
    def notify(self, title, message):
        """
        发送桌面通知
        
        参数:
            title (str): 通知标题
            message (str): 通知内容
        """
        try:
            notification.notify(
                title=title,
                message=message,
                app_name="斗鱼开播提醒",
                timeout=10
            )
            # 移除表情符号后再记录日志
            log_title = title.replace('🔴', '[直播]').replace('⚪', '[下播]')
            logging.info(f"发送通知: {log_title} - {message}")
            
            # 同时发送Server酱推送
            if self.server_chan_key:
                self.send_server_chan(title, message)
        except Exception as e:
            logging.error(f"发送通知失败: {e}")
    
    def send_server_chan(self, title, message):
        """
        发送Server酱推送
        
        参数:
            title (str): 通知标题
            message (str): 通知内容
        """
        try:
            # Server酱推送API
            url = f"https://sctapi.ftqq.com/{self.server_chan_key}.send"
            
            # 准备推送内容
            data = {
                "title": title,
                "desp": message.replace("\n", "\n\n")  # Server酱使用Markdown格式，需要双换行
            }
            
            # 发送请求
            response = requests.post(url, data=data, timeout=10)
            
            # 检查响应
            if response.status_code == 200:
                result = response.json()
                if result.get("code") == 0:
                    logging.info(f"Server酱推送成功: {title}")
                else:
                    logging.error(f"Server酱推送失败: {result.get('message')}")
            else:
                logging.error(f"Server酱推送失败，状态码: {response.status_code}")
        except Exception as e:
            logging.error(f"Server酱推送出错: {e}")
    
    def open_live_room(self, room_id):
        """
        打开直播间网页
        
        参数:
            room_id (str): 房间ID
        """
        try:
            url = f"https://www.douyu.com/{room_id}"
            webbrowser.open(url)
            logging.info(f"已打开直播间: {url}")
        except Exception as e:
            logging.error(f"打开直播间失败: {e}")
    
    def handle_new_live_rooms(self):
        """处理新开播的房间"""
        if not self.new_live_rooms:
            return
        
        # 如果只有一个房间开播，直接打开
        if len(self.new_live_rooms) == 1:
            room_id, room_info = self.new_live_rooms[0]
            if self.auto_open:
                self.open_live_room(room_id)
            self.new_live_rooms = []
            return
        
        # 如果有多个房间开播，提供选择
        print("\n多个主播同时开播，请选择要打开的直播间:")
        for i, (room_id, room_info) in enumerate(self.new_live_rooms, 1):
            room_name = room_info.get('room_name', f'房间{room_id}')
            owner_name = room_info.get('owner_name', f'主播{room_id}')
            print(f"{i}. {owner_name} - {room_name}")
        
        print("0. 不打开任何直播间")
        
        try:
            choice = int(input("请输入数字选择: "))
            if 1 <= choice <= len(self.new_live_rooms):
                selected_room_id = self.new_live_rooms[choice-1][0]
                self.open_live_room(selected_room_id)
            elif choice != 0:
                print("无效的选择")
        except ValueError:
            print("请输入有效的数字")
        except Exception as e:
            logging.error(f"处理选择时出错: {e}")
        
        # 清空新开播列表
        self.new_live_rooms = []
    
    def run(self):
        """运行监控器"""
        logging.info(f"开始监控房间: {', '.join(self.room_ids)}")
        
        try:
            while True:
                for room_id in self.room_ids:
                    try:
                        is_live, room_info = self.check_room_status(room_id)
                        room_name = room_info.get('room_name', f'房间{room_id}')
                        owner_name = room_info.get('owner_name', f'主播{room_id}')
                        
                        # 如果状态发生变化
                        if is_live != self.room_status[room_id]:
                            self.room_status[room_id] = is_live
                            if is_live:
                                # 开播提醒
                                title = f"🔴 {owner_name} 开播啦!"
                                message = f"房间: {room_name}\n时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                                self.notify(title, message)
                                logging.info(f"主播 {owner_name}({room_id}) 开播了!")
                                
                                # 添加到新开播列表
                                self.new_live_rooms.append((room_id, room_info))
                            else:
                                # 下播提醒
                                title = f"⚪ {owner_name} 已下播"
                                message = f"房间: {room_name}\n时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                                self.notify(title, message)
                                logging.info(f"主播 {owner_name}({room_id}) 下播了")
                        else:
                            status_text = "开播中" if is_live else "未开播"
                            logging.info(f"房间 {room_name}({room_id}) 状态: {status_text}")
                    
                    except Exception as e:
                        logging.error(f"检查房间 {room_id} 时出错: {e}")
                
                # 处理新开播的房间
                if self.new_live_rooms:
                    # 使用线程处理用户输入，避免阻塞主循环
                    threading.Thread(target=self.handle_new_live_rooms).start()
                
                # 等待下一次检查
                time.sleep(self.check_interval)
        
        except KeyboardInterrupt:
            logging.info("监控已停止")
        except Exception as e:
            logging.error(f"监控过程中出错: {e}")

if __name__ == "__main__":
    try:
        # 设置更详细的日志级别用于调试
        logging.getLogger().setLevel(logging.DEBUG)
        
        print("斗鱼主播开播提醒程序启动中...")
        
        # 从配置文件加载房间ID
        config_file = 'config/room_ids.json'
        default_room_ids = [
            "6979222",  # 斗鱼-未开播房间
            "63136",    # 斗鱼-开播房间
        ]
        
        # 加载已保存的房间ID
        room_ids = []
        if os.path.exists(config_file):
            try:
                with open(config_file, 'r', encoding='utf-8') as f:
                    room_ids = json.load(f)
                print(f"已从配置文件加载 {len(room_ids)} 个房间ID")
            except Exception as e:
                print(f"加载房间ID配置失败: {e}")
                room_ids = default_room_ids
        else:
            room_ids = default_room_ids
        
        # 显示当前房间ID列表
        print("当前监控的房间ID列表:")
        for i, room_id in enumerate(room_ids, 1):
            print(f"{i}. {room_id}")
        
        # 询问是否修改房间ID列表
        modify = input("\n是否修改房间ID列表? (y/n): ").lower() == 'y'
        
        if modify:
            while True:
                print("\n房间ID操作:")
                print("1. 添加房间ID")
                print("2. 删除房间ID")
                print("3. 清空并重新输入所有房间ID")
                print("4. 完成修改")
                
                choice = input("请选择操作 (1-4): ")
                
                if choice == '1':
                    # 添加房间ID
                    new_id = input("请输入要添加的房间ID: ").strip()
                    if new_id and new_id not in room_ids:
                        room_ids.append(new_id)
                        print(f"已添加房间ID: {new_id}")
                    else:
                        print("房间ID无效或已存在")
                
                elif choice == '2':
                    # 删除房间ID
                    if not room_ids:
                        print("房间ID列表为空")
                        continue
                    
                    print("\n当前房间ID列表:")
                    for i, room_id in enumerate(room_ids, 1):
                        print(f"{i}. {room_id}")
                    
                    try:
                        index = int(input("请输入要删除的房间ID序号: ")) - 1
                        if 0 <= index < len(room_ids):
                            removed = room_ids.pop(index)
                            print(f"已删除房间ID: {removed}")
                        else:
                            print("无效的序号")
                    except ValueError:
                        print("请输入有效的数字")
                
                elif choice == '3':
                    # 清空并重新输入
                    room_ids = []
                    print("已清空房间ID列表，请输入新的房间ID列表")
                    print("每行输入一个房间ID，输入空行完成")
                    
                    while True:
                        new_id = input("房间ID: ").strip()
                        if not new_id:
                            break
                        if new_id not in room_ids:
                            room_ids.append(new_id)
                            print(f"已添加: {new_id}")
                        else:
                            print("房间ID已存在，已跳过")
                
                elif choice == '4':
                    # 完成修改
                    break
                
                else:
                    print("无效的选择，请重新输入")
            
            # 保存修改后的房间ID列表
            try:
                with open(config_file, 'w', encoding='utf-8') as f:
                    json.dump(room_ids, f, ensure_ascii=False, indent=2)
                print(f"已保存 {len(room_ids)} 个房间ID到配置文件")
            except Exception as e:
                print(f"保存房间ID配置失败: {e}")
        
        if not room_ids:
            print("错误: 房间ID列表为空，程序无法继续")
            exit(1)
        
        print(f"\n将监控以下房间: {', '.join(room_ids)}")
        
        # 询问是否自动打开网页
        auto_open = input("是否在主播开播时自动打开网页? (y/n): ").lower() == 'y'
        
        # 询问是否启用Server酱推送
        use_server_chan = input("是否启用Server酱推送? (y/n): ").lower() == 'y'
        server_chan_key = None
        
        if use_server_chan:
            # 从配置文件加载Server酱密钥
            server_chan_config = 'config/server_chan.json'
            if os.path.exists(server_chan_config):
                try:
                    with open(server_chan_config, 'r', encoding='utf-8') as f:
                        config_data = json.load(f)
                        server_chan_key = config_data.get('key')
                except Exception:
                    pass
            
            # 如果没有保存的密钥，则询问用户
            if not server_chan_key:
                server_chan_key = input("请输入Server酱密钥: ").strip()
                
                # 保存密钥到配置文件
                if server_chan_key:
                    try:
                        with open(server_chan_config, 'w', encoding='utf-8') as f:
                            json.dump({'key': server_chan_key}, f, ensure_ascii=False, indent=2)
                        print("Server酱密钥已保存")
                    except Exception as e:
                        print(f"保存Server酱密钥失败: {e}")
            
            # 如果有密钥，测试一下连接
            if server_chan_key:
                try:
                    test_url = f"https://sctapi.ftqq.com/{server_chan_key}.send"
                    test_data = {
                        "title": "斗鱼开播提醒 - 测试消息",
                        "desp": "如果您收到此消息，说明Server酱推送配置成功！"
                    }
                    response = requests.post(test_url, data=test_data, timeout=10)
                    if response.status_code == 200:
                        result = response.json()
                        if result.get("code") == 0:
                            print("Server酱推送测试成功！")
                        else:
                            print(f"Server酱推送测试失败: {result.get('message')}")
                    else:
                        print(f"Server酱推送测试失败，状态码: {response.status_code}")
                except Exception as e:
                    print(f"Server酱推送测试出错: {e}")
        
        print("程序运行中，按Ctrl+C可停止程序")
        
        # 创建并运行监控器
        monitor = DouyuMonitor(room_ids, check_interval=60, auto_open=auto_open, server_chan_key=server_chan_key)
        
        # 初始检查，确保至少有一个房间ID是有效的
        valid_rooms = False
        print("正在检查房间有效性...")
        
        # ... 保持房间有效性检查代码不变 ...
        
        print("\n开始监控，日志将记录到douyu_monitor.log文件中...")
        monitor.run()
    except KeyboardInterrupt:
        print("\n程序已被用户终止")
    except Exception as e:
        logging.critical(f"程序发生严重错误: {e}")
        print(f"\n程序发生错误: {e}")
        print("请检查日志文件获取更多信息")