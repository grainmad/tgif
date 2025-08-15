import telebot
import requests
import os
import random
import zipfile
import shutil
import threading
import subprocess
from filelock import FileLock
from concurrent.futures import ThreadPoolExecutor, as_completed
from PIL import Image
from dotenv import load_dotenv
import time
import logging
from flask import Flask, send_from_directory, render_template_string, abort


# creat .lock hub dir
lock_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".lock")
if not os.path.exists(lock_dir):
    os.makedirs(lock_dir)

hub_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hub")
if not os.path.exists(hub_dir):
    os.makedirs(hub_dir)

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('tgif.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

### clean hub ###

def cleanup_old_files():
    while True:
        try:    
            cutoff_time = time.time() - (3 * 24 * 60 * 60)  
            
            for item in os.listdir(hub_dir):
                item_path = os.path.join(hub_dir, item)
                sticker_lock = os.path.join(lock_dir, item + ".lock") # 锁文件路径
                try:
                    with FileLock(sticker_lock):
                        # 检查文件/文件夹的修改时间
                        modified_time = os.path.getmtime(item_path)
                        if modified_time < cutoff_time:
                            if os.path.isfile(item_path):
                                os.remove(item_path)
                                logger.info(f"Deleted old file: {item_path}, modified at {time.ctime(modified_time)}")
                            elif os.path.isdir(item_path):
                                shutil.rmtree(item_path)
                                logger.info(f"Deleted old directory: {item_path}, modified at {time.ctime(modified_time)}")
                except Exception as e:
                    logger.error(f"Error deleting {item_path}: {e}")
                    
        except Exception as e:
            logger.error(f"Error in cleanup thread: {e}")
        time.sleep(10 * 60)  # 每10分钟执行一次清理

def start_cleanup_thread():
    cleanup_thread = threading.Thread(target=cleanup_old_files, daemon=True)
    cleanup_thread.start()
    logger.info("Cleanup thread started")

start_cleanup_thread()

### bot ###

load_dotenv()
BOT_TOKEN = os.getenv('BOT_TOKEN')
LOTTIE_CONVERTER = os.getenv('LOTTIE_CONVERTER')
WEB_PORT = int(os.getenv('WEB_PORT', 8080))
WEB_DOMAIN = os.getenv('WEB_DOMAIN', 'localhost')
THREAD_POOL_SIZE = int(os.getenv('THREAD_POOL_SIZE', 5))
SEND_ZIP_IN_TG = os.getenv('SEND_ZIP_IN_TG', 'false').lower() in ['true', '1', 'yes']
bot = telebot.TeleBot(BOT_TOKEN)

# Initialize Flask app
app = Flask(__name__)

def generate_html_page(sticker_name, gif_list, sticker_dir):
    logger.info(f"Generating HTML page for sticker set: {sticker_name} with {len(gif_list)} GIFs")
    """Generate HTML page for a sticker set"""
    html_template = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>{sticker_name} - Sticker GIFs</title>
        <style>
            body {{ font-family: Arial, sans-serif; margin: 20px; background-color: #f5f5f5; }}
            .container {{ max-width: 1200px; margin: 0 auto; }}
            h1 {{ text-align: center; color: #333; }}
            .gif-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 20px; }}
            .gif-item {{ background: white; padding: 15px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); text-align: center; }}
            .gif-item img {{ max-width: 100%; height: auto; border-radius: 4px; }}
            .gif-name {{ margin-top: 10px; font-size: 14px; color: #666; word-break: break-all; }}
            .stats {{ text-align: center; margin: 20px 0; color: #666; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>{sticker_name}</h1>
            <div class="stats">Total GIFs: {gif_count}</div>
            <div class="stats"> <a href="zip/{sticker_name}.zip">点击下载全部</a></div>
            <div class="gif-grid">
                {gif_items}
            </div>
        </div>
    </body>
    </html>
    """
    
    # Generate GIF items HTML
    gif_items = ""
    for gif in gif_list:
        gif_items += f'''
                <div class="gif-item">
                    <img src="sticker_gif/{gif}" alt="{gif}" loading="lazy">
                    <div class="gif-name">{gif}</div>
                </div>'''
    
    html_content = html_template.format(
        sticker_name=sticker_name,
        gif_items=gif_items,
        gif_count=len(gif_list)
    )
    
    html_path = os.path.join(sticker_dir, "index.html")
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(html_content)
    
    logger.info(f"Generated HTML page: {html_path}")
    return html_path

# Flask routes
@app.route('/')
def index():
    """List all available sticker sets"""
    sticker_sets = []
    if os.path.exists(hub_dir):
        for item in os.listdir(hub_dir):
            item_path = os.path.join(hub_dir, item)
            if os.path.isdir(item_path) and os.path.exists(os.path.join(item_path, "index.html")):
                sticker_sets.append(item)
    
    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>TGIF Sticker Sets</title>
        <style>
            body { font-family: Arial, sans-serif; margin: 20px; background-color: #f5f5f5; }
            .container { max-width: 800px; margin: 0 auto; }
            h1 { text-align: center; color: #333; }
            .sticker-list { list-style: none; padding: 0; }
            .sticker-item { background: white; margin: 10px 0; padding: 15px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
            .sticker-item a { text-decoration: none; color: #333; font-weight: bold; }
            .sticker-item a:hover { color: #007bff; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Available Sticker Sets</h1>
            <ul class="sticker-list">
    """
    
    for sticker_set in sorted(sticker_sets):
        html += f'<li class="sticker-item"><a href="/sticker/{sticker_set}/">{sticker_set}</a></li>'
    
    if not sticker_sets:
        html += '<li class="sticker-item">No sticker sets available yet.</li>'
    
    html += """
            </ul>
        </div>
    </body>
    </html>
    """
    
    return html

@app.route('/sticker/<sticker_name>/')
def sticker_page(sticker_name):
    """Serve HTML page for a specific sticker set"""
    sticker_path = os.path.join(hub_dir, sticker_name)
    html_path = os.path.join(sticker_path, "index.html")
    
    if not os.path.exists(html_path):
        abort(404)
    
    with open(html_path, 'r', encoding='utf-8') as f:
        return f.read()

@app.route('/sticker/<sticker_name>/sticker_gif/<filename>')
def serve_gif(sticker_name, filename):
    """Serve GIF files"""
    sticker_gif_path = os.path.join(hub_dir, sticker_name, "sticker_gif")
    if not os.path.exists(os.path.join(sticker_gif_path, filename)):
        abort(404)
    return send_from_directory(sticker_gif_path, filename)

@app.route('/sticker/<sticker_name>/zip/<filename>')
def serve_zip(sticker_name, filename):
    """Serve GIF zip"""
    sticker_lock = os.path.join(lock_dir, sticker_name + ".lock")
    if os.path.exists(sticker_lock):
        try:
            # 尝试获取锁，如果正在处理则返回提示信息
            with FileLock(sticker_lock, timeout=0.1):
                pass
        except:
            # 无法获取锁，说明正在处理中
            return "资源正在生成中，请稍后重试", 202
        
    sticker_zip_path = os.path.join(hub_dir, sticker_name, filename)
    logger.info(f"Serving zip file: {sticker_zip_path}")
    if not os.path.exists(sticker_zip_path):
        abort(404)
    return send_from_directory(os.path.join(hub_dir, sticker_name), filename)

def start_web_server():
    """Start Flask web server in a separate thread"""
    def run_server():
        app.run(host='0.0.0.0', port=WEB_PORT, debug=False, threaded=True)
    
    web_thread = threading.Thread(target=run_server, daemon=True)
    web_thread.start()
    logger.info(f"Web server started on port {WEB_PORT}")

# Start web server
start_web_server()

def get_filename_without_extension(filepath):
    return os.path.splitext(os.path.basename(filepath))[0]


def compress_to_zip(source_path, target_path, include_list = None):
    logger.info(f"compress_to_zip {source_path} {target_path} {include_list}")
    with zipfile.ZipFile(target_path, 'w') as zf:
        if os.path.isdir(source_path):
            for root, dirs, files in os.walk(source_path):
                for file in files:
                    if include_list is None or file in include_list:
                        zf.write(os.path.join(root, file), arcname=file)
        elif os.path.isfile(source_path):
            if include_list is None or file in include_list:
                zf.write(source_path, arcname=os.path.basename(source_path))

# gif目录 gif文件名 gif压缩包目录 压缩包名 压缩包分组号
def split_compress(sticker_gif, gif_list, sticker_zip, zip_name, part):
    dstzip = os.path.join(sticker_zip, f"{zip_name}{part}.zip") # hub/xxx/sticker_zip/xxx1.zip
    if os.path.exists(dstzip):
        os.remove(dstzip)
    compress_to_zip(sticker_gif, dstzip, gif_list)
    return dstzip

def execcmd(cmd):
    
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=600)
        # if result.stdout:
        #     logger.info(f"stdout: {result.stdout}")
        if result.stderr:
            logger.warning(f"stderr: {result.stderr}")
        if result.returncode != 0:
            logger.error(f"command failed with return code {result.returncode}")
    except subprocess.TimeoutExpired:
        logger.error(f"command timed out: {cmd}")
    except Exception as e:
        logger.error(f"Error executing command: {e}")

def stickerset2gif(sticker_ori, sticker_gif, srcstickerset): # hub = hub/xxx
   # sticker_ori 可能包含不同的文件类型
    if LOTTIE_CONVERTER: # 手动编译的lottie-to-gif
        with ThreadPoolExecutor(max_workers=THREAD_POOL_SIZE) as executor:
            futures = []

            for srcsticker in srcstickerset:
                srcsticker_ne = get_filename_without_extension(srcsticker) # miku.tgs
                srcsticker_ext = srcsticker.split('.')[-1] # tgs
                src = os.path.join(sticker_ori, srcsticker) # hub/xxx/miku.tgs
                dst = os.path.join(sticker_gif, srcsticker_ne+".gif") # hub/xxxgif/miku.gif
                if srcsticker_ext in ['webm', 'mp4']:
                    # 处理视频的gif
                    cmd = f"ffmpeg -i {src} {dst}"
                    logger.info(f"Executing command: {cmd}")
                elif srcsticker_ext == 'tgs': 
                    # 处理tgs的gif
                    cmd = f"{LOTTIE_CONVERTER} && bash lottie_to_gif.sh {src} --output {dst}"
                    logger.info(f"Executing command: {cmd}")
                else :
                    # 处理透明图片的gif
                    cmd = f"ffmpeg -i {src} -vf \"split[s0][s1];[s0]palettegen=reserve_transparent=1[p];[s1][p]paletteuse=alpha_threshold=128\" -loop 0 {dst}"
                    logger.info(f"Executing command: {cmd}")
                executor.submit(execcmd, cmd)
            # 获取结果
            for future in futures:
                future.result()
    else :  
        # user docker
        # in sticker_ori/ : xxx.tgs -> xxx.tgs.gif
        execcmd(f"docker run --rm -v {sticker_ori}:/source edasriyan/lottie-to-gif")
        # in sticker_ori/ move xxx.tgs.gif to sticker_gif/
        execcmd(f"mv {sticker_ori}/*.gif {sticker_gif}")
        # in sticker_gif/ : xxx.tgs.gif -> xxx.gif
        for file in os.listdir(sticker_gif):
            if file.endswith('.tgs.gif'):
                nfile = file.replace('.tgs.gif', '.gif')
                os.rename(os.path.join(sticker_gif, file), os.path.join(sticker_gif, nfile))

        with ThreadPoolExecutor(max_workers=THREAD_POOL_SIZE) as executor:
            futures = []

            for srcsticker in srcstickerset:
                srcsticker_ne = get_filename_without_extension(srcsticker) # miku.tgs
                srcsticker_ext = srcsticker.split('.')[-1] # tgs
                if srcsticker_ext == 'tgs': continue
                src = os.path.join(sticker_ori, srcsticker) # hub/xxx/miku.tgs
                dst = os.path.join(sticker_gif, srcsticker_ne+".gif") # hub/xxxgif/miku.gif
                if srcsticker_ext in ['webm', 'mp4']:
                    # video
                    cmd = f"ffmpeg -i {src} {dst}"
                    logger.info(f"Executing command: {cmd}")
                else :
                    # picture
                    cmd = f"ffmpeg -i {src} -vf \"split[s0][s1];[s0]palettegen=reserve_transparent=1[p];[s1][p]paletteuse=alpha_threshold=128\" -loop 0 {dst}"
                    logger.info(f"Executing command: {cmd}")
                executor.submit(execcmd, cmd)
                    
            # 获取结果
            for future in futures:
                future.result()

def download_sticker(bot, sticker_info, hub, progress_callback=None):
    """Download a single sticker file"""
    try:
        url = bot.get_file_url(sticker_info["file_id"])
        file_name_ne = sticker_info["file_unique_id"]
        ext = url.split('.')[-1]
        file_name = file_name_ne + "." + ext
        
        r = requests.get(url)
        r.raise_for_status()
        
        file_path = os.path.join(hub, file_name)
        
        if os.path.exists(file_path):
            logger.info(f"File {file_name} already exists, skipping download.")
            return True, file_name, file_name_ne + ".gif"
        
        with open(file_path, "wb") as f:
            f.write(r.content)
        
        if progress_callback:
            progress_callback()
            
        return True, file_name, file_name_ne + ".gif"
    except Exception as e:
        logger.error(f"Error downloading sticker {sticker_info.get('file_unique_id', 'unknown')}: {e}")
        return False, file_name, file_name_ne + ".gif"

def get_stickerset_info(message):
    set_name = ""
    if message.sticker:
        set_name = message.sticker.set_name
    elif message.text and "/" in message.text:
        set_name = message.text.split('/')[-1]
    else :
        set_name = message.text
    resp = requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/getStickerSet", data={"name":set_name})
    return resp.json()

def opt_stickerset(message, nocache):
    logger.info(f"Processing stickerset message: {message}")
    sticker_info = get_stickerset_info(message)
    logger.debug(f"Sticker set response: {sticker_info}")
    if not sticker_info["ok"]:
        bot.reply_to(message, "焯！发的什么垃圾，不能识别捏")
        return 
        
   
    sticker_name = sticker_info["result"]["name"]
    sticker_dir = os.path.join(hub_dir, sticker_name)
    sticker_ori = os.path.join(sticker_dir, "sticker_ori") # 存储下载的表情
    sticker_gif = os.path.join(sticker_dir, "sticker_gif") # 存储转换后的gif
    sticker_zip = os.path.join(sticker_dir, "sticker_zip") # 存储压缩包
    sticker_lock = os.path.join(lock_dir, sticker_name + ".lock") # 锁文件路径

    lock = FileLock(sticker_lock)
    with lock:
        # cache mode
        if not nocache and os.path.exists(sticker_dir):
            logger.info(f"Using cached sticker set directory: {sticker_dir}")
            ziplist = sorted(os.listdir(sticker_zip))
            web_url = f"http://{WEB_DOMAIN}:{WEB_PORT}/sticker/{sticker_name}/"
            bot.send_message(message.chat.id, f'<a href="{web_url}">点这里去网页中下载表情</a>', parse_mode="HTML")
            if SEND_ZIP_IN_TG:
                bot.send_message(message.chat.id, f"使用缓存的表情包合集: {str(ziplist)}\n发送中...")
                for file in ziplist:
                    file_path = os.path.join(sticker_zip, file)
                    bot.send_document(message.chat.id, telebot.types.InputFile(file_path), timeout=180)
                bot.send_message(message.chat.id, f"发送完毕")
            return 
        
        # nocache mode
        if os.path.exists(sticker_dir):
            shutil.rmtree(sticker_dir)
        os.makedirs(sticker_ori, exist_ok=True)
        os.makedirs(sticker_gif, exist_ok=True)
        os.makedirs(sticker_zip, exist_ok=True)

        try:
            sz = len(sticker_info["result"]["stickers"])
            logger.info(f"Starting download of {sz} stickers")
            bot.send_message(message.chat.id, f"开始下载... 共计{sz}个表情")
        
            file_list, bad_file, gif_list = [], [], []
            downloaded_count = 0
            progress_lock = threading.Lock()
        
            def update_progress():
                nonlocal downloaded_count
                with progress_lock:
                    downloaded_count += 1
                    if downloaded_count % ((sz+4)//5) == 0 or downloaded_count == sz: # 缓存的集合 过快计数而无法显示
                        bot.send_message(message.chat.id, f"下载进度{downloaded_count}/{sz}")
            
            # Use ThreadPoolExecutor for concurrent downloads
            with ThreadPoolExecutor(max_workers=THREAD_POOL_SIZE) as executor:
                future_to_sticker = {
                    executor.submit(download_sticker, bot, sticker, sticker_ori, update_progress): sticker 
                    for sticker in sticker_info["result"]["stickers"]
                }
                
                for future in as_completed(future_to_sticker):
                    ok, file_name, gif_name = future.result()
                    if ok:
                        file_list.append(file_name)
                        gif_list.append(gif_name)
                    else:
                        bad_file.append(file_name)

            if bad_file:
                bot.send_message(message.chat.id, f"以下{len(bad_file)}个表情下载失败：\n{', '.join(bad_file)}")
                logger.warning(f"Failed to download stickers: {bad_file}")

            logger.info("Download finished, starting GIF conversion")
            bot.send_message(message.chat.id, "下载完毕，开始gif转化...")

            start_time = time.time()
            stickerset2gif(sticker_ori, sticker_gif, file_list)
            spend_time = time.time() - start_time
            
            logger.info(f"GIF conversion completed in {spend_time:.2f} seconds")
            bot.send_message(message.chat.id, f"转化完毕，耗时{spend_time:.2f}秒")
            
            # Generate HTML page
            actual_gif_list = [f for f in os.listdir(sticker_gif) if f.endswith('.gif')]
            logger.info(f"Actual GIF list: {actual_gif_list}")

            html_path = generate_html_page(sticker_name, actual_gif_list, sticker_dir)
            web_url = f"http://{WEB_DOMAIN}:{WEB_PORT}/sticker/{sticker_name}/"
            logger.info(f"Generated HTML page: {html_path}")
            
            message2 = bot.send_message(message.chat.id, f'<a href="{web_url}">点这里去网页中下载表情</a>', parse_mode="HTML")    
            if SEND_ZIP_IN_TG: 
                bot.send_message(message.chat.id, "开始分组压缩...（每组压缩包不超过45MB）\nTelegramBot规定不能发送超过50MB的文件")
            logger.info(f"Starting compression for gif list: {actual_gif_list}")
            gif_size, idx, total_bit = len(actual_gif_list), 0, 0
            bad_gif, part, zips = [], [[]], []
            while idx < gif_size:
                try:
                    bit = os.stat(os.path.join(sticker_gif, gif_list[idx])).st_size
                    if total_bit + bit > 45 * 1024 * 1024:
                        logger.info(f"Creating zip for part {len(zips)+1}, list {str(part[-1])}, size {total_bit} bytes")
                        zips.append(split_compress(sticker_gif, part[-1], sticker_zip, sticker_name, len(zips)+1))
                        part.append([])
                        total_bit = 0
                    part[-1].append(actual_gif_list[idx])
                    total_bit += bit
                except FileNotFoundError:
                    logger.error(f"File not found: {actual_gif_list[idx]}")
                    bad_gif.append(actual_gif_list[idx])
            
                idx += 1
            # 最后一个单独处理
            logger.info(f"Creating zip for part {len(zips)+1}, list {str(part[-1])}, size {total_bit} bytes")
            zips.append(split_compress(sticker_gif, part[-1], sticker_zip, sticker_name, len(zips)+1))

            if bad_gif:
                if SEND_ZIP_IN_TG:
                    bot.send_message(message.chat.id, f"以下{len(bad_gif)}个gif文件转换失败：\n{', '.join(bad_gif)}")
                logger.warning(f"Failed to convert GIFs: {bad_gif}")
            if SEND_ZIP_IN_TG:
                bot.send_message(message.chat.id, f"压缩完毕，开始发送...\n将分成{len(part)}个压缩包发送")
                for i in zips:
                    bot.send_document(message.chat.id, telebot.types.InputFile(i), timeout=180)
                bot.send_message(message.chat.id, f'发送完毕')
            # 生成所有表情的压缩包，嵌入网页中
            split_compress(sticker_gif, actual_gif_list, sticker_dir, sticker_name, "")
            logger.info(f"Sticker set {sticker_name} processed successfully")
            bot.reply_to(message2, f"完整表情包合集压缩完毕！\n请去网页中下载压缩包\n", parse_mode="HTML")
            logger.info("Sticker set processing completed!")
        except Exception as e:
            logger.error(f"Error processing stickerset: {e}")
            bot.send_message(message.chat.id, f"处理表情包合集时发生错误")
            if os.path.exists(sticker_dir):
                shutil.rmtree(sticker_dir)


@bot.message_handler(commands=['stickerset2gif'])
def stickerset(message):
    logger.info(f"Stickerset command received: {message}")
    nocache = True if "nocache" in message.text else False
    sent_msg = bot.reply_to(message, "你可以发送：\n1. 一个任意表情，其所属需要下载的表情包合集。\n2. 表情包合集名称。\n处理时间较长，耐心等待。")
    bot.register_next_step_handler(sent_msg, opt_stickerset, nocache)

### game ###

def read_two_integers(s):
    try:
        # 使用正则表达式匹配两个整数
        numbers = [int(num) for num in s.split() if num.isdigit()]
        # 检查是否正好找到两个整数
        if len(numbers) == 2:
            return numbers[0], numbers[1]
        else:
            raise ValueError("未找到两个整数")
    except ValueError as e:
        logger.error(f"Error reading two integers: {e}")
        return None

def read_one_integers(s):
    try:
        # 使用正则表达式匹配两个整数
        numbers = [int(num) for num in s.split() if num.isdigit()]
        # 检查是否正好找到两个整数
        if len(numbers) == 1:
            return numbers[0]
        else:
            raise ValueError("未找到一个整数")
    except ValueError as e:
        logger.error(f"Error reading one integer: {e}")
        return None

def roundx(message, x, l, r):
    n = read_one_integers(message.text)
    if n is None:
        bot.reply_to(message, "发送一个整数。您犯规了捏！请重新开始吧")
        return 
    if n < x:
        sent_msg = bot.reply_to(message, "猜小了哦")
        bot.register_next_step_handler(sent_msg, roundx, x, l, r)
    elif n > x:
        sent_msg = bot.reply_to(message, "猜大了哦")
        bot.register_next_step_handler(sent_msg, roundx, x, l, r)
    else:
        bot.reply_to(message, "被你猜到了")

def round1(message):
    n = read_two_integers(message.text)
    if n is None: 
        bot.reply_to(message, "发送两个整数，用空格分开。您犯规了捏！请重新开始吧")
        bot.send_sticker(chat_id=message.chat.id, sticker="CAACAgQAAxkBAAICaGYZDyb3_KrxmtP2gy2zpEqRUrbNAAIHAwAC2SNkIUzkymsUveDgNAQ", reply_to_message_id=message.id)
        return 
    if n[0] > n[1]: 
        bot.reply_to(message, "两个整数范围非法。您犯规了捏！请重新开始吧")
        bot.send_sticker(chat_id=message.chat.id, sticker="CAACAgQAAxkBAAICaGYZDyb3_KrxmtP2gy2zpEqRUrbNAAIHAwAC2SNkIUzkymsUveDgNAQ", reply_to_message_id=message.id)
        return 
    x = random.randint(n[0], n[1])
    sent_msg = bot.reply_to(message, "我已经想好了数字，请开始猜吧")
    bot.register_next_step_handler(sent_msg, roundx, x, n[0], n[1])

@bot.message_handler(commands=['num'])
def num(message):
    sent_msg = bot.reply_to(message, "猜数字游戏，请发送两个整数（用空格分开）代表所猜整数的范围。\n例如`5 10`", parse_mode="Markdown")
    bot.register_next_step_handler(sent_msg, round1)

from functools import reduce

def to_bin(value, num):#十进制数据，二进制位宽
    bin_chars = ""
    temp = value
    for i in range(num):
        bin_char = bin(temp % 2)[-1]
        temp = temp // 2
        bin_chars = bin_char + bin_chars
    return bin_chars.upper()#输出指定位宽的二进制字符串

def gen():
    a = [random.randint(1,16) for i in range(3)]
    xor = reduce(lambda x, y : x^y , a)
    while not xor:
        a = [random.randint(1,16) for i in range(3)]
        xor = reduce(lambda x, y : x^y , a)
    return a

def gentip(a, simple=True):
    b = [to_bin(i, 5) for i in a]
    s = ''
    for i in b:
        s += '⊕'+i
    xor = to_bin(reduce(lambda x, y : x^y , a), 5)
    rt = s[1:]+"="+xor 
    if simple: return rt
    rt += ",当异或为0则是必胜态,你的目标是让这些数异或为0。"
    rt += "注意到 {}⊕{}=0 如果一堆石头个数是x, x>x⊕{}说明可以让x减少<b>到</b>x⊕{},从而使得异或和为0".format(s[1:], xor, xor, xor)
    return rt

def robot_opt(a):
    xor = reduce(lambda x, y : x^y , a)
    if not xor:
        for i in range(len(a)):
            if a[i]:
                d = random.randint(1, a[i])
                a[i] -= d
                return "第{}个数减少{}".format(i+1,d)

    for i,j in enumerate(a):
        if j > (j^xor):
            logger.debug(f"{i}th {j} sub {j-(j^xor)} become {j^xor}")
            sub = j-(j^xor)
            a[i] = j^xor
            return "第{}个数减少{}".format(i+1,sub)

def nim_round(message, a):
    n = read_two_integers(message.text)
    if n is None: 
        bot.reply_to(message, "发送两个整数，用空格分开。您犯规了捏！请重新开始吧")
        return 
    n0 = n[0]-1
    if n0 not in range(len(a)) or n[1] not in range(1, a[n0]+1): 
        bot.reply_to(message, "两个整数范围非法。您犯规了捏！请重新开始吧")
        bot.send_sticker(chat_id=message.chat.id, sticker="CAACAgQAAxkBAAICaGYZDyb3_KrxmtP2gy2zpEqRUrbNAAIHAwAC2SNkIUzkymsUveDgNAQ", reply_to_message_id=message.id)
        return 
    a[n0] -= n[1]
    bot.reply_to(message, "现在的石堆状态是{}".format(a))
    if not sum(a):
        bot.reply_to(message, "只能说有点东西，但不多！")
        bot.send_sticker(chat_id=message.chat.id, sticker="CAACAgQAAxkBAAICSmYZDKNa_Hp_W090-PE4EJmOAAHjqQACDAMAAtkjZCEhtSw_8gOOaTQE", reply_to_message_id=message.id)
        return 
    msg = robot_opt(a)
    sent_msg = bot.reply_to(message, "我选择{},现在的石堆状态是{}\ntips:\n<tg-spoiler>{}</tg-spoiler>".format(msg, a, gentip(a)), parse_mode="HTML")
    if not sum(a):
        bot.reply_to(message, "菜就多练，输不起就别玩！")
        bot.send_sticker(chat_id=message.chat.id, sticker="CAACAgQAAxkBAAICUGYZDa7nbIrY0R1g6AM7is5xeiejAAIPAwAC2SNkIeveH7n5wxyoNAQ", reply_to_message_id=message.id)
        return 
    bot.register_next_step_handler(sent_msg, nim_round, a)

@bot.message_handler(commands=['nim'])
def nim(message):
    a = gen()
    
    sent_msg = bot.reply_to(message, 
"""尼姆游戏
今有{}堆石头，每堆石头分别有{}个。
游戏玩法: 我们轮流先选定一堆石头，再<b>至少</b>取走一个石头，<b>至多</b>全部取完。<b>您先开始拿</b>。
获胜条件：那一个先取完所有石头，谁就赢了
每次轮到你操作时,发送<code>选择石堆 取走的数量</code>，例如<code>1 3</code>将取走第1堆的3个石头。
tips:\n<tg-spoiler>{}</tg-spoiler>"""
    .format(len(a), a, gentip(a, False)), parse_mode="HTML")
    bot.register_next_step_handler(sent_msg, nim_round, a)

@bot.message_handler(commands=['start'])
def start_command(message):
    logger.info(f"Start command received: {message}")
    bot.send_sticker(chat_id=message.chat.id, sticker="CAACAgQAAxkBAAICVGYZDg7Fg7hZ96S_Wp9t8O26xxxVAAITAwAC2SNkIbQZSopsDmMTNAQ", reply_to_message_id=message.id)

@bot.message_handler(commands=['help'])
def help_command(message):
    logger.info(f"Help command received: {message}")
    bot.send_sticker(chat_id=message.chat.id, sticker="CAACAgQAAxkBAAICWGYZDmNki3c5DiCYg9impkXVKXP9AAILAwAC2SNkIZ-71pEOj1BjNAQ", reply_to_message_id=message.id)

logger.info("Starting bot...")
bot.infinity_polling()