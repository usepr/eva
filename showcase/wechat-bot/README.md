# 微信-EVA

## 快速开始

1. 确认`eva`命令可使用（`python3 eva.py`首次运行过，并执行了`source ~/.bashrc`就会设置`eva`快捷脚本）
2. 执行`python3 bot.py`
3. 会输出一个链接，请用浏览器打开并通过微信扫码登录


## 关于wechatbot

微信官方通过 iLink 协议来对接ClawBot，也可以对接其他自定义机器人。

wechatbot是一个已封装好 iLink 协议的python库，说明文档：https://www.wechatbot.dev/en/python


## 给EVA配的hints.md

我的各种信息以及笔记都记在Obsidian里，我希望EVA能帮我检索这些内容，尤其各种杂乱的账号密码。
此外，Tavily可以让EVA具备联网检索功能。

我给EVA配的`hints.md`内容如下（`hints.md`记忆线索含义参照EVA项目的`README.md`：

```md
## 我的笔记本

存储目录：/root/Obsidian，里面记录了各种账号信息等

## 我的Tavily API key

tvly-dev-xxxxx-xxxxxxxxxxxxxxxxxxxx

可用于联网搜索
```
