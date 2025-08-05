
# 功能

1. 下载telegram表情包集合，保存为gif格式
2. 小游戏

# 环境
## BOT_TOKEN
``` shell
cp .env.template .env
```
修改`.env`中telegram的BOT_TOKEN

## 科学上网
内核/虚拟网卡 模式

## docker
安装docker

## ffmpeg
安装ffmepeg

## python
``` shell
cd tg
# 下载3.12.4版本
pyenv install 3.12.4
# 设置当前目录自动切换pyhton3.12.4
pyenv local 3.12.4
# 创建虚拟环境
python -m venv .venv
# 激活虚拟环境的python
source .venv/bin/activate
# 依赖下载到当前虚拟环境 
pip -r requirements.txt
```
启动
``` shell
./control.sh start
```
