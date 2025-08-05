import telebot
import requests
import os
import random
import zipfile
import shutil
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from PIL import Image
from dotenv import load_dotenv
import time
import logging

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
    """清理3天前的hub文件"""
    while True:
        time.sleep(12 * 60 * 60)
        try:
            hub_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hub")
            if not os.path.exists(hub_dir):
                continue
                
            cutoff_time = time.time() - (3 * 24 * 60 * 60)  # 3天前的时间戳
            
            for item in os.listdir(hub_dir):
                item_path = os.path.join(hub_dir, item)
                try:
                    # 检查文件/文件夹的修改时间
                    if os.path.getmtime(item_path) < cutoff_time:
                        if os.path.isfile(item_path):
                            os.remove(item_path)
                            logger.info(f"Deleted old file: {item_path}")
                        elif os.path.isdir(item_path):
                            shutil.rmtree(item_path)
                            logger.info(f"Deleted old directory: {item_path}")
                except Exception as e:
                    logger.error(f"Error deleting {item_path}: {e}")
                    
        except Exception as e:
            logger.error(f"Error in cleanup thread: {e}")
        

def start_cleanup_thread():
    cleanup_thread = threading.Thread(target=cleanup_old_files, daemon=True)
    cleanup_thread.start()
    logger.info("Cleanup thread started")

start_cleanup_thread()

### bot ###

load_dotenv()
BOT_TOKEN = os.getenv('BOT_TOKEN')
bot = telebot.TeleBot(BOT_TOKEN)

def get_filename_without_extension(filepath):
    return os.path.splitext(os.path.basename(filepath))[0]

def to_gif(png_images, output_path, duration=0.1):
    # 加载第一张图片来创建动画
    first_image = Image.open(png_images[0])
    # 设置动画的帧数和时间间隔
    frames = [first_image.copy()]
    for image in png_images[1:]:
        frames.append(Image.open(image))
 
    # 保存为GIF
    frames[0].save(output_path, format='GIF', append_images=frames[1:],
                  save_all=True, duration=duration, loop=0)

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

def phototrans(hub, srcphoto): # miku.png miku.jpg
    srcphoto_ne = get_filename_without_extension(srcphoto) # miku
    srcphoto = os.path.join(hub, srcphoto) # hub/mikugif
    dstphoto = os.path.join(hub, srcphoto_ne+".gif") # hub/mikugif
    to_gif([srcphoto], dstphoto)
    return dstphoto

def videotrans(hub, srcvideo):
    srcvideo_ne = get_filename_without_extension(srcvideo) # miku
    srcvideo = os.path.join(hub, srcvideo) # hub/mikugif
    dstvideo = os.path.join(hub, srcvideo_ne+".gif") # hub/mikugif
    os.system(f"ffmpeg -i {srcvideo} {dstvideo}")

def split_compress(hub, srcstickerset, part): # hub = hub/xxxgif
    dstzip = f"{hub}{part}.zip" # hub/xxxgif0.zip
    if os.path.exists(dstzip):
        os.remove(dstzip)
    compress_to_zip(hub, dstzip, srcstickerset)
    return dstzip

def stickersettrans(hub, srcstickerset): # hub = hub/xxx
    dstdir = hub+"gif" # hub/xxxgif
    # 创建dst目录
    if os.path.exists(dstdir):
        shutil.rmtree(dstdir)
    os.makedirs(dstdir)
    if srcstickerset and srcstickerset[0].endswith('tgs'):
        os.system(f"docker run --rm -v {hub}:/source edasriyan/lottie-to-gif")
        os.system(f"mv {hub}/*.gif {dstdir}")
    else:
        for srcsticker in srcstickerset:
            srcsticker_ne = get_filename_without_extension(srcsticker) # miku.tgs
            srcsticker_ext = srcsticker.split('.')[-1] # tgs
            src = os.path.join(hub, srcsticker) # hub/xxx/miku.tgs
            dst = os.path.join(dstdir, srcsticker_ne+".gif") # hub/xxxgif/miku.gif
            if srcsticker_ext in ['webm', 'mp4']:
                videotrans(dstdir, src)
            else :
                phototrans(dstdir, src)

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
            return file_name, file_name_ne + ".gif"
        
        with open(file_path, "wb") as f:
            f.write(r.content)
        
        if progress_callback:
            progress_callback()
            
        return file_name, file_name_ne + ".gif"
    except Exception as e:
        logger.error(f"Error downloading sticker {sticker_info.get('file_unique_id', 'unknown')}: {e}")
        return None, None

def opt_stickerset(message):
    logger.info(f"Processing stickerset message: {message}")
    set_name = ""
    if message.sticker:
        set_name = message.sticker.set_name
    elif message.text and "/" in message.text:
        set_name = message.text.split('/')[-1]
    else :
        set_name = message.text
    resp = requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/getStickerSet", data={"name":set_name})
    ss = resp.json()
    logger.debug(f"Sticker set response: {ss}")
    if not ss["ok"]:
        bot.reply_to(message, "焯！发的什么垃圾，不能识别捏", parse_mode="Markdown")
        return 
        
    hub = os.path.join(os.path.dirname(os.path.abspath("__file__")), "hub")
    hub = os.path.join(hub, ss["result"]["name"])
    if not os.path.exists(hub):
        os.makedirs(hub)

    sz = len(ss["result"]["stickers"])
    logger.info(f"Starting download of {sz} stickers")
    bot.send_message(message.chat.id, f"开始下载，共计{sz}个表情")
    
    file_list, gif_list = [], []
    downloaded_count = 0
    progress_lock = threading.Lock()
    
    def update_progress():
        nonlocal downloaded_count
        with progress_lock:
            downloaded_count += 1
            if downloaded_count % ((sz+4)//5) == 0 or downloaded_count == sz: # 缓存的集合 过快计数而无法显示
                bot.send_message(message.chat.id, f"下载进度{downloaded_count}/{sz}")
    
    # Use ThreadPoolExecutor for concurrent downloads
    with ThreadPoolExecutor(max_workers=5) as executor:
        future_to_sticker = {
            executor.submit(download_sticker, bot, sticker, hub, update_progress): sticker 
            for sticker in ss["result"]["stickers"]
        }
        
        for future in as_completed(future_to_sticker):
            file_name, gif_name = future.result()
            if file_name and gif_name:
                file_list.append(file_name)
                gif_list.append(gif_name)

    logger.info("Download finished, starting GIF conversion")
    bot.send_message(message.chat.id, "下载完毕，开始转化gif")

    stickersettrans(hub, file_list)
    bot.send_message(message.chat.id, "转化完毕，开始分组（45MB一组）压缩")
    logger.info(f"Starting compression for gif list: {gif_list}")
    
    fl, idx = len(gif_list), 0
    part = []
    while idx < fl:
        ed = idx
        csz = 0
        while ed < fl and csz + os.stat(os.path.join(hub+"gif", gif_list[ed])).st_size <= 45*1024*1024:
            csz += os.stat(os.path.join(hub+"gif", gif_list[ed])).st_size
            logger.debug(f"Current size: {csz}, idx: {ed}")
            ed += 1
        logger.info(f"Compressing files: {gif_list[idx:ed]}")
        part.append(split_compress(hub+"gif", gif_list[idx:ed], len(part)))
        idx = ed

    bot.reply_to(message, f"压缩完毕，开始发送。\nTelegram Bot每次只能发送不超过50MB大小的文件，将分成{len(part)}个压缩包发送", parse_mode="Markdown")
    for i in part:
        bot.send_document(message.chat.id, telebot.types.InputFile(i), timeout=180)
    logger.info("Sticker set processing completed!")
    
@bot.message_handler(commands=['stickerset2gif'])
def stickerset(message):
    logger.info(f"Stickerset command received: {message}")
    sent_msg = bot.reply_to(message, "你可以发送：\n1. 一个任意表情，其所属需要下载的表情包合集。\n2. 表情包合集名称。\n处理时间较长，耐心等待。", parse_mode="Markdown")
    bot.register_next_step_handler(sent_msg, opt_stickerset)

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
        bot.reply_to(message, "发送一个整数。您犯规了捏！请重新开始吧", parse_mode="Markdown")
        return 
    if n < x:
        sent_msg = bot.reply_to(message, "猜小了哦", parse_mode="Markdown")
        bot.register_next_step_handler(sent_msg, roundx, x, l, r)
    elif n > x:
        sent_msg = bot.reply_to(message, "猜大了哦", parse_mode="Markdown")
        bot.register_next_step_handler(sent_msg, roundx, x, l, r)
    else:
        bot.reply_to(message, "被你猜到了", parse_mode="Markdown")

def round1(message):
    n = read_two_integers(message.text)
    if n is None: 
        bot.reply_to(message, "发送两个整数，用空格分开。您犯规了捏！请重新开始吧", parse_mode="Markdown")
        bot.send_sticker(chat_id=message.chat.id, sticker="CAACAgQAAxkBAAICaGYZDyb3_KrxmtP2gy2zpEqRUrbNAAIHAwAC2SNkIUzkymsUveDgNAQ", reply_to_message_id=message.id)
        return 
    if n[0] > n[1]: 
        bot.reply_to(message, "两个整数范围非法。您犯规了捏！请重新开始吧", parse_mode="Markdown")
        bot.send_sticker(chat_id=message.chat.id, sticker="CAACAgQAAxkBAAICaGYZDyb3_KrxmtP2gy2zpEqRUrbNAAIHAwAC2SNkIUzkymsUveDgNAQ", reply_to_message_id=message.id)
        return 
    x = random.randint(n[0], n[1])
    sent_msg = bot.reply_to(message, "我已经想好了数字，请开始猜吧", parse_mode="Markdown")
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
        bot.reply_to(message, "发送两个整数，用空格分开。您犯规了捏！请重新开始吧", parse_mode="Markdown")
        return 
    n0 = n[0]-1
    if n0 not in range(len(a)) or n[1] not in range(1, a[n0]+1): 
        bot.reply_to(message, "两个整数范围非法。您犯规了捏！请重新开始吧", parse_mode="Markdown")
        bot.send_sticker(chat_id=message.chat.id, sticker="CAACAgQAAxkBAAICaGYZDyb3_KrxmtP2gy2zpEqRUrbNAAIHAwAC2SNkIUzkymsUveDgNAQ", reply_to_message_id=message.id)
        return 
    a[n0] -= n[1]
    bot.reply_to(message, "现在的石堆状态是{}".format(a), parse_mode="Markdown")
    if not sum(a):
        bot.reply_to(message, "只能说有点东西，但不多！", parse_mode="Markdown")
        bot.send_sticker(chat_id=message.chat.id, sticker="CAACAgQAAxkBAAICSmYZDKNa_Hp_W090-PE4EJmOAAHjqQACDAMAAtkjZCEhtSw_8gOOaTQE", reply_to_message_id=message.id)
        return 
    msg = robot_opt(a)
    sent_msg = bot.reply_to(message, "我选择{},现在的石堆状态是{}\ntips:\n<tg-spoiler>{}</tg-spoiler>".format(msg, a, gentip(a)), parse_mode="HTML")
    if not sum(a):
        bot.reply_to(message, "菜就多练，输不起就别玩！", parse_mode="Markdown")
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