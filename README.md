# EVA

如果一个智能体的执行层小到只是一个脚本，那它具有病毒传播一样的潜力。

EVA是个麻雀虽小、五脏俱全的Agent智能体，相当于低配版Claude Code，能帮你写脚本、写测试案例、执行shell、分析数据等。


## 特性

- 本地化：可以接入本地部署的OpenAI接口模型，如vLLM，或者是外网模型
- 极致轻量化：单文件，仅一个`eva.py`，有python就能运行
- 目录级Session：下次同样目录启动会延续之前对话
- 安全审查：默认只执行读命令，其他命令需要安全确认
- 移植性：很容易将EVA接入你现有的自动化流程，例如：`eva -a -u '计算100w以内所有素数和并写到/tmp/result.txt'`


## 快速开始


0. 直接创建一个eva.py并复制本仓库的eva.py文本内容粘贴进去（docker环境、运维环境等也很容易粘贴代码，无需复杂安装，Just **Paste and Go**）。当然，你也可以git clone本仓库

1. 在终端执行`export EVA_API_KEY=你的deepseek API key`（Windows系统则是`set`命令）

EVA支持OpenAI接口形式的LLM，可以是Ollma、vLLM拉起的本地模型，也可以是DeepSeek、OpenAI等官网API。切换方法是设置`EVA_BASE_URL`, `EVA_MODEL_NAME`, `EVA_API_KEY`这三个环境变量。

Linux设置方法：

```bash
export EVA_BASE_URL=http://xxxxxxxxx/v1
export EVA_MODEL_NAME=xxxxx
export EVA_API_KEY=sk-xxxxx
```

Windows 命令行设置方法：

```cmd
set EVA_BASE_URL=http://xxxxxxxxx/v1
set EVA_MODEL_NAME=xxxxx
set EVA_API_KEY=sk-xxxxx
```

Windows PowerShell设置方法：

```powershell
$env:EVA_BASE_URL=http://xxxxxxxxx/v1
$env:EVA_MODEL_NAME=xxxxx
$env:EVA_API_KEY=sk-xxxxx
```

2. 运行`python3 eva.py`。首次运行会生成`eva`脚本，你需要执行下`source ~/.bashrc`让脚本生效。后续直接输入命令`eva`即可

```python
eva支持的选项：
  -h, --help            show this help message and exit
  -a, --allow-all       允许所有命令无需用户确认即可执行
  -l, --list-session    列出所有session
  -c, --clear-session   清除当前目录session
  -u USER_ASK, --user-ask USER_ASK
                        独立地针对一条用户提问执行EVA
```

## EVA退出说明

Ctrl + C直接中断，程序会自动保存session。下次启动时将自动加载


## 关于 Skill & Command

EVA通过.eva/hints.md获取记忆线索，该线索会被拼接到system prompt，因此你可以在hints.md里放置技能、命令的相关提示。EVA会在自己认为需要的时候进入这些目录查看对应的技能内容。

hints.md文件内容示例：

```markdown
.eva/commands、.eva/skills/目录里存储了存储了大量的命令和技能，可以帮助你完成任务。其中，
1. xxxx/，可用于xxxx
    触发条件：当涉及xxxx时，可以查阅xxxx/底下的技能文件
2. yyyy/, 可用于yyyy
    触发条件：当涉及yyyy时，可以查阅yyyy/底下的技能文件
```

通过 Skill & Command，可以扩展EVA的各种能力。


## 关于Contributing

💗💗💗

欢迎大家为EVA项目贡献，如提高EVA的自主水平、增加其他语言的单文件版本、甚至英文版等等。

当前EVA的设计，有下面几点考虑：

1. 尽量发挥EVA的自主性，让EVA自我驱动去解决问题，而非加各种流程约束
2. 保持极简。我想就是因为简单，所以EVA才不简单。“完美不是在没有东西可以增加的时候，而是在没有东西可以删除的时候”
3. 长程任务连续性。当前的记忆压缩比较粗暴，无法很好保证压缩后的任务延续性，希望有更优雅的方法进行记忆压缩（工程上我们可以类似Claude Code那样做各种层次化压缩，但还记得前面第1点吗，需要尽量发挥EVA的自主性，因此希望记忆压缩可以更简单、更优雅、更AI自我驱动）
4. 自进化。机器人三大定律本来只是插在EVA中的一个meme，但它好像跟智能体发展挺契合的。当前自进化实现方式很简单，完全靠EVA记录知识、技能和线索，期望有更优雅的方式

<a href="https://www.star-history.com/?repos=usepr%2Feva&type=date&legend=top-left">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/chart?repos=usepr/eva&type=date&theme=dark&legend=top-left" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/chart?repos=usepr/eva&type=date&legend=top-left" />
   <img alt="Star History Chart" src="https://api.star-history.com/chart?repos=usepr/eva&type=date&legend=top-left" />
 </picture>
</a>

[![linux.do](https://shorturl.at/ggSqS)](https://linux.do)
