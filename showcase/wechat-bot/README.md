# EVA-在微信中使用

作为你的个人助理，帮你维护东西、检索信息等。你可以自由修改bot.py，加入类似openclaw的heartbeat机制功能、identity人设等

https://github.com/user-attachments/assets/1ae819dc-1673-40cd-bbab-250f87e778c1

## 快速开始

1. 确认`eva`命令可使用（`python3 eva.py`首次运行过，并执行了`source ~/.bashrc`就会设置`eva`快捷脚本）
2. 执行`python3 bot.py`
3. 会输出一个链接，请用浏览器打开并通过微信扫码登录


## 关于wechatbot

微信官方通过 iLink 协议来对接ClawBot，也可以对接其他自定义机器人。不过iLink有比较多限制，比如只能作为个人Bot，无法加入群聊等。

wechatbot是一个已封装好 iLink 协议的python库，说明文档：https://www.wechatbot.dev/en/python


## 给EVA配的`.eva/hints.md`

我的各种信息以及笔记都记在Obsidian里，我希望EVA能帮我检索这些内容，尤其各种杂乱的账号密码。
此外，Tavily可以让EVA具备联网检索功能。

我给EVA配的`.eva/hints.md`内容如下（`hints.md`记忆线索是什么参照EVA项目的`README.md`）：

```md
## 我的信息

- 我叫hzq
- 我在深圳

## 我的笔记本

存储目录：/root/Obsidian，里面记录了各种账号信息等

## 我的Tavily API key

tvly-dev-xxxxx-xxxxxxxxxxxxxxxxxxxx

可用于联网搜索
```
