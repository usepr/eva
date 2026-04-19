# EVA

如果一个智能体的执行层小到只是一个脚本，那它具有病毒传播一样的潜力。

EVA是个麻雀虽小、五脏俱全的Agent智能体，相当于低配版CC，能帮你写脚本、写测试案例、执行shell、分析数据等。


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

Windows设置方法：

```bash
set EVA_BASE_URL=http://xxxxxxxxx/v1
set EVA_MODEL_NAME=xxxxx
set EVA_API_KEY=sk-xxxxx
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


**古法编程、匠心打造** [狗头]
