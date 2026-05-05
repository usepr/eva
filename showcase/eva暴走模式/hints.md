## 暴走模式：用 run_cli 生成分身

当遇到多个独立、不互相依赖的子任务时（如分析多个文件、检查多个服务、搜索多个关键词），可以考虑用分身并行加速。若子任务间存在依赖关系则不适合。

### ⚠️ 关键坑点：锁冲突

EVA 基于 `os.getcwd()`（当前工作目录）生成锁文件，防止同一目录启动多个EVA实例，因此：
- **分身启动时必须先 `cd` 到自己的 workspace 目录**，否则会与主 EVA（或其他分身）的锁冲突
- 正确做法：`cd $WS && EVA_HOME=$WS eva ...`
- 错误做法：直接在原目录 `EVA_HOME=$WS eva ...`（锁文件仍用原目录的cwd）

### 生成分身（同步等待）
分身任务简单时，直接用 -asu 同步执行，`run_cli` 会等它跑完返回结果：

```bash
WS=/tmp/eva-spawn-任务名
mkdir -p "$WS"
cat > "$WS/hints.md" << SPWN_HINTS
## 我是分身

- 我是由主 EVA 生成的子分身
- 我的任务是：<具体任务>
- 完成后将结果写入：<结果文件路径>

## 任务背景
<主 EVA 提供的上下文、前置信息、注意事项等>

## 相关技能与知识
<主 EVA 整理的对完成任务有帮助的技能、命令、参考信息>

## 分身能力（递归）
我需要子分身时，也可以用同样的方式通过 run_cli 生成：
\`\`\`bash
WS=/tmp/eva-spawn-子任务
mkdir -p "\$WS"
cd "\$WS" && EVA_HOME=\$WS eva -asu "子任务描述"
\`\`\`
SPWN_HINTS
cd $WS && EVA_HOME=$WS eva -asu "子任务描述"
```

`run_cli` 执行这段 bash 后会阻塞等待分身完成，分身的 stdout 输出会作为 `run_cli` 的返回结果。同时分身也会把结果写入约定的结果文件，双重保障。

### 生成分身（异步后台运行）
分身任务耗时较长时，用 nohup 放后台，主 EVA 继续做其他事：

```bash
WS=/tmp/eva-spawn-任务名
mkdir -p "$WS"
cat > "$WS/hints.md" << SPWN_HINTS
...（同上模板）...
SPWN_HINTS
WS="$WS" nohup bash -c 'cd "$WS" && EVA_HOME="$WS" eva -asu "子任务描述"' > "$WS/stdout.log" 2>&1 &
echo "PID=$! WS=$WS"
```

`run_cli` 会立即返回，输出分身 PID 和 workspace 路径，主 EVA 记录下来后续追踪。

### 获取异步分身的结果
分身放后台后，主 EVA 需要通过以下方式检查和收取结果：

```bash
# 1. 检查分身进程是否存活
ps -p <PID> > /dev/null 2>&1 && echo "running" || echo "done"

# 2. 检查结果文件是否已生成
cat <结果文件路径> 2>/dev/null || echo "not_ready"

# 3. 查看分身 stdout 日志，了解进度
cat <workspace>/stdout.log 2>/dev/null | tail -20

# 4. 查看分身 workspace，了解进度（分身自己的 result.json）
cat <workspace>/result.json 2>/dev/null || echo "not_ready"

# 5. 强制终止分身
kill <PID>
```

主 EVA 可以用一个文件来记录所有后台分身的信息，方便后续轮询：

```bash
# 注册分身信息（spawn 时写入）
cd 【EVA对应的私人空间】
echo '{"spawns":[
  {"id":"模块A","pid":12345,"ws":"/tmp/eva-spawn-A","result":"/tmp/result-A.json","status":"running"},
  {"id":"模块B","pid":12346,"ws":"/tmp/eva-spawn-B","result":"/tmp/result-B.json","status":"running"}
]}' > ./spawn-registry.json

# 检查所有分身状态（后续回合调用）
cd 【EVA对应的私人空间】
python3 -c "
import json, os
reg = json.load(open(os.path.expanduser('./spawn-registry.json')))
for s in reg['spawns']:
    alive = os.system(f'ps -p {s[\"pid\"]} > /dev/null 2>&1') == 0
    done = os.path.exists(s['result'])
    s['status'] = 'done' if done else ('running' if alive else 'crashed')
json.dump(reg, open(os.path.expanduser('./spawn-registry.json'),'w'), indent=2)
for s in reg['spawns']:
    print(f\"{s['id']}: {s['status']}\")
"
```

### 同步 vs 异步的选择

| 场景 | 方式 | 结果获取 |
|------|------|---------|
| 任务简单（几秒完成） | 同步（不加 nohup） | `run_cli` 直接返回结果 |
| 任务耗时（分钟级） | 异步（nohup 后台） | 后续回合用注册文件轮询 |
| 多个并行分身 | 异步 | 各自写结果文件，主 EVA 逐个 merge |

### 分身 hints 设计原则

- 分身 hints 应**轻量但完整**——任务背景和相关技能/知识能让分身更快进入状态
- 不要 cp 主 EVA 的 hints.md，里面可能索引了大量本地文件，分身不需要
- API key、BASE_URL 等通过环境变量 `EVA_API_KEY`、`EVA_BASE_URL` 自动继承，不需要写入 hints
- **始终在 spawn 前写好 hints.md**，不要让分身带着空 hints 启动

### 分身可以再生分身（递归）
分身也是完整的 EVA，只要分身自己的 hints.md 里写了 spawn 技巧，分身内部同样可以再生子分身，形成分身树。
