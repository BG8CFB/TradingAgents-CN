# DeepSeek API 深度指南

> 基于 DeepSeek 官方文档（2026 年 5 月）+ 实际 API 测试验证
> 
> 测试环境：Windows 11 / OpenAI Python SDK v1.109.1
> 
> 测试日期：2026-05-28

---

## 目录

1. [概述与接入配置](#1-概述与接入配置)
2. [模型与定价](#2-模型与定价)
3. [基础对话 API](#3-基础对话-api)
4. [思考模式（Thinking Mode）](#4-思考模式thinking-mode)
5. [工具调用（Tool Calls）](#5-工具调用tool-calls)
6. [多轮对话](#6-多轮对话)
7. [流式输出（Streaming）](#7-流式输出streaming)
8. [JSON Output](#8-json-output)
9. [对话前缀续写（Chat Prefix Completion）](#9-对话前缀续写chat-prefix-completion)
10. [FIM 补全（Fill In the Middle）](#10-fim-补全fill-in-the-middle)
11. [Anthropic API 兼容](#11-anthropic-api-兼容)
12. [上下文缓存](#12-上下文缓存)
13. [错误处理](#13-错误处理)
14. [请求/响应完整格式参考](#14-请求响应完整格式参考)
15. [与项目集成要点](#15-与项目集成要点)

---

## 1. 概述与接入配置

### API 兼容性

DeepSeek API 兼容 **OpenAI API 格式** 和 **Anthropic API 格式**两种：

| 格式 | base_url | SDK |
|------|----------|-----|
| OpenAI 兼容 | `https://api.deepseek.com` | `openai` Python SDK |
| Anthropic 兼容 | `https://api.deepseek.com/anthropic` | `anthropic` Python SDK |
| Beta 功能 | `https://api.deepseek.com/beta` | `openai` Python SDK |

### 基础配置

```python
from openai import OpenAI

client = OpenAI(
    api_key="<DeepSeek API Key>",
    base_url="https://api.deepseek.com",
)
```

### Beta 功能配置

前缀续写、FIM 补全、strict 模式工具调用需要使用 Beta endpoint：

```python
client_beta = OpenAI(
    api_key="<DeepSeek API Key>",
    base_url="https://api.deepseek.com/beta",
)
```

---

## 2. 模型与定价

### 当前可用模型

通过 `client.models.list()` 实际查询返回：

| 模型 ID | 说明 | 思考模式 |
|---------|------|---------|
| `deepseek-v4-flash` | 轻量快速模型 | 默认开启 |
| `deepseek-v4-pro` | 高性能模型 | 默认开启 |

### 旧模型名（兼容映射，将于 2026/07/24 弃用）

| 旧名称 | 映射到 | 思考模式 |
|--------|--------|---------|
| `deepseek-chat` | `deepseek-v4-flash` | 关闭（非思考模式） |
| `deepseek-reasoner` | `deepseek-v4-flash` | 开启（思考模式） |

**实测验证**：
- `deepseek-chat`：返回 `model: "deepseek-v4-flash"`，`reasoning_content: None`
- `deepseek-reasoner`：返回 `model: "deepseek-v4-flash"`，`reasoning_content` 有内容

### 性能对比实测

| 指标 | deepseek-v4-flash | deepseek-v4-pro |
|------|-------------------|-----------------|
| 响应时间（3句话解释量子纠缠） | ~4.6s | ~11.9s |
| completion_tokens | 214 | 401 |
| reasoning_tokens | 117 | 309 |
| total_tokens | 225 | 412 |

---

## 3. 基础对话 API

### 非流式请求

```python
response = client.chat.completions.create(
    model="deepseek-v4-flash",
    messages=[
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "用一句话介绍北京"},
    ],
    stream=False,
)
```

### 实测返回结构

```json
{
  "id": "f5530d25-1be4-4cfd-9c33-d5903b8b4a42",
  "object": "chat.completion",
  "created": 1779940138,
  "model": "deepseek-v4-flash",
  "system_fingerprint": "fp_8b330d02d0_prod0820_fp8_kvcache_20260402",
  "choices": [
    {
      "index": 0,
      "finish_reason": "stop",
      "message": {
        "role": "assistant",
        "content": "北京是中华人民共和国的首都，是一座融合了悠久历史与现代文明的国际化大都市。",
        "reasoning_content": "我们要求用一句话介绍北京。需要简洁、全面，涵盖北京的核心特点...",
        "tool_calls": null,
        "refusal": null,
        "function_call": null,
        "annotations": null
      }
    }
  ],
  "usage": {
    "prompt_tokens": 14,
    "completion_tokens": 46,
    "total_tokens": 60,
    "completion_tokens_details": {
      "reasoning_tokens": 28,
      "accepted_prediction_tokens": null,
      "audio_tokens": null,
      "rejected_prediction_tokens": null
    },
    "prompt_tokens_details": {
      "audio_tokens": null,
      "cached_tokens": 0
    },
    "prompt_cache_hit_tokens": 0,
    "prompt_cache_miss_tokens": 14
  }
}
```

### 关键发现：默认思考模式

**重要**：即使不显式设置 `thinking` 参数，`deepseek-v4-flash` 和 `deepseek-v4-pro` 默认也会：

1. 返回 `reasoning_content` 字段（思考链内容）
2. 在 `usage.completion_tokens_details.reasoning_tokens` 中记录思考消耗的 token

这意味着 **DeepSeek V4 系列模型默认开启思考模式**。如需关闭，必须显式设置：

```python
response = client.chat.completions.create(
    model="deepseek-v4-flash",
    messages=[...],
    extra_body={"thinking": {"type": "disabled"}},
)
```

关闭后 `reasoning_content` 为 `None`，`completion_tokens_details` 也为 `None`。

### Usage 字段详解

| 字段 | 说明 |
|------|------|
| `prompt_tokens` | 输入 token 总数 |
| `completion_tokens` | 输出 token 总数（含 reasoning） |
| `total_tokens` | prompt + completion |
| `completion_tokens_details.reasoning_tokens` | 思考链消耗的 token 数 |
| `prompt_cache_hit_tokens` | 命中缓存的 prompt token 数 |
| `prompt_cache_miss_tokens` | 未命中缓存的 prompt token 数 |

**token 计算公式**：
- `completion_tokens` = 思考 tokens + 最终回答 tokens
- `prompt_tokens` = `prompt_cache_hit_tokens` + `prompt_cache_miss_tokens`

---

## 4. 思考模式（Thinking Mode）

### 概述

DeepSeek V4 模型支持思考模式：在输出最终回答之前，模型先输出一段思维链（Chain of Thought），提升最终答案的准确性。

### 控制参数

| 功能 | 参数（OpenAI 格式） | 参数（Anthropic 格式） |
|------|---------------------|----------------------|
| 思考模式开关 | `extra_body={"thinking": {"type": "enabled/disabled"}}` | - |
| 思考强度控制 | `reasoning_effort="high/max"` | `output_config={"effort": "high/max"}` |

**默认值**：
- 思考开关默认为 `enabled`
- `reasoning_effort` 默认为 `high`（普通请求）或 `max`（复杂 Agent 类请求如 Claude Code）

**兼容性映射**：`low`/`medium` → `high`，`xhigh` → `max`

### 思考模式使用示例

```python
response = client.chat.completions.create(
    model="deepseek-v4-flash",
    messages=[{"role": "user", "content": "9.11和9.8哪个大？"}],
    reasoning_effort="high",
    extra_body={"thinking": {"type": "enabled"}},
)

reasoning = response.choices[0].message.reasoning_content  # 思考链
answer = response.choices[0].message.content               # 最终回答
```

### reasoning_effort 级别对比实测

使用题目「一个农夫有17只羊，除了9只以外都死了，还剩几只？」：

| effort | reasoning 长度 | 耗时 | reasoning_tokens | completion_tokens |
|--------|---------------|------|-----------------|------------------|
| `high` | 411 字符 | 4.5s | 267 | 310 |
| `max` | 167 字符 | 2.2s | 109 | 146 |

> 注：`max` 的 reasoning 更短但 prompt_tokens 更多（100 vs 21），这是因为 `max` 模式会注入更多系统级 prompt 来引导更深入的推理。对于简单问题，`max` 可能反而更简洁。

### 不支持的参数

思考模式下以下参数**不会报错但也不生效**：
- `temperature`
- `top_p`
- `presence_penalty`
- `frequency_penalty`

### 多轮对话中的 reasoning_content 处理规则

这是最关键的部分：

| 场景 | reasoning_content 是否回传 |
|------|--------------------------|
| 两个 user 消息之间，assistant **未进行工具调用** | **无需回传**（API 会忽略） |
| 两个 user 消息之间，assistant **进行了工具调用** | **必须回传**（否则 400 错误） |

**简单做法**：始终将完整的 `message` 对象 append 到 messages，它会自动携带所有字段：

```python
messages.append(response.choices[0].message)
# 等价于：
# messages.append({
#     'role': 'assistant',
#     'content': msg.content,
#     'reasoning_content': msg.reasoning_content,
#     'tool_calls': msg.tool_calls,
# })
```

---

## 5. 工具调用（Tool Calls）

### 5.1 非思考模式下的工具调用

#### 工具定义格式

```python
tools = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "获取指定城市的天气信息",
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {
                        "type": "string",
                        "description": "城市名称",
                    },
                    "unit": {
                        "type": "string",
                        "enum": ["celsius", "fahrenheit"],
                        "description": "温度单位",
                    },
                },
                "required": ["city"],
            },
        },
    },
]
```

#### 调用流程

```python
# Step 1: 发送请求，模型决定调用工具
response = client.chat.completions.create(
    model="deepseek-v4-flash",
    messages=[{"role": "user", "content": "杭州天气怎么样？"}],
    tools=tools,
)
msg = response.choices[0].message

# 此时 finish_reason = "tool_calls"
# msg.content 可能有内容（模型的引导语）或为空
# msg.tool_calls 是一个列表

# Step 2: 执行工具，回传结果
if msg.tool_calls:
    messages.append(msg)  # 注意：append 完整的 message 对象
    
    for tool_call in msg.tool_calls:
        tool_name = tool_call.function.name
        tool_args = json.loads(tool_call.function.arguments)
        tool_call_id = tool_call.id
        
        # 执行你的工具函数
        result = execute_tool(tool_name, tool_args)
        
        # 回传工具结果
        messages.append({
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": str(result),
        })
    
    # Step 3: 再次请求，模型生成最终回答
    response2 = client.chat.completions.create(
        model="deepseek-v4-flash",
        messages=messages,
        tools=tools,
    )
```

#### 并行工具调用实测

当用户请求涉及多个工具时，模型会在 **单次响应中并行返回多个 tool_call**：

```
用户：杭州今天天气怎么样？顺便看看 000001 的股价

模型返回：
  tool_calls[0]: get_weather({"city": "杭州", "unit": "celsius"})
  tool_calls[1]: get_stock_price({"symbol": "000001"})
  content: "好的，我来同时查询这两个信息！"
  finish_reason: "tool_calls"
```

### 5.2 思考模式下的工具调用

从 DeepSeek-V3.2 开始支持思考模式 + 工具调用。核心区别：

- 模型可能进行**多轮思考-调用循环**（Sub-turn）
- 进行了工具调用的轮次，`reasoning_content` **必须回传**

```
用户: "明天杭州天气怎么样？"

Sub-turn 1.1:
  reasoning: "用户想知道明天杭州天气。我需要先获取日期..."
  content: "让我查一下明天杭州的天气。"
  tool_calls: [get_weather({city: "杭州", date: "2026-04-13"})]

  -> 工具返回: "多云，18~24°C"

Sub-turn 1.2:
  reasoning: "好的，明天杭州的天气是多云，温度在18°C到24°C之间。"
  content: "明天杭州的天气：多云，18~24°C，建议带外套。"
  tool_calls: None  ← 最终轮，无工具调用
```

### 5.3 strict 模式（Beta）

strict 模式确保模型严格遵循 Function 的 JSON Schema 格式。

**使用方法**：
1. `base_url` 设为 `https://api.deepseek.com/beta`
2. 每个 function 定义中添加 `"strict": true`
3. `parameters` 中所有属性必须设为 `required`，`additionalProperties` 必须为 `false`

```python
tools = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "strict": True,  # 开启 strict 模式
            "description": "Get weather of a location.",
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {"type": "string", "description": "The city name"},
                    "unit": {"type": "string", "enum": ["celsius", "fahrenheit"]},
                },
                "required": ["location", "unit"],
                "additionalProperties": False,  # 必须
            },
        },
    },
]

response = client_beta.chat.completions.create(
    model="deepseek-v4-flash",
    messages=[{"role": "user", "content": "北京多少度？"}],
    tools=tools,
)
```

#### strict 模式支持的 JSON Schema 类型

| 类型 | 支持情况 | 额外参数 |
|------|---------|---------|
| `object` | ✅ 所有属性必须 required，`additionalProperties: false` | - |
| `string` | ✅ | `pattern`（正则）、`format`（email/hostname/ipv4/ipv6/uuid） |
| `number`/`integer` | ✅ | `const`、`default`、`minimum`、`maximum`、`exclusiveMinimum`、`exclusiveMaximum`、`multipleOf` |
| `boolean` | ✅ | - |
| `array` | ✅ | 不支持 `minItems`、`maxItems` |
| `enum` | ✅ | - |
| `anyOf` | ✅ | - |
| `$ref`/`$def` | ✅ | 支持模块化定义和递归结构 |

---

## 6. 多轮对话

### 核心原理

DeepSeek API 是**无状态**的——服务端不记录上下文。每次请求需将之前所有对话历史拼接后传入。

### 标准多轮对话

```python
messages = [
    {"role": "system", "content": "你是一个简洁的助手"},
    {"role": "user", "content": "中国最高的山是什么？"},
]

# Round 1
r1 = client.chat.completions.create(model="deepseek-v4-flash", messages=messages)
messages.append(r1.choices[0].message)  # append 完整的 message 对象

# Round 2
messages.append({"role": "user", "content": "那第二高的呢？"})
r2 = client.chat.completions.create(model="deepseek-v4-flash", messages=messages)
messages.append(r2.choices[0].message)

# Round 3
messages.append({"role": "user", "content": "它们的落差是多少米？"})
r3 = client.chat.completions.create(model="deepseek-v4-flash", messages=messages)
```

### 实测 messages 链

```
[0] system: 你是一个简洁的助手，每次只回答核心要点。
[1] user: 中国最高的山是什么？
[2] assistant: 珠穆朗玛峰（海拔8,848.86米）。
[3] user: 那第二高的呢？
[4] assistant: 乔戈里峰（K2），海拔8,611米。
[5] user: 它们的落差是多少米？
```

### 关键注意事项

1. **message 对象直接 append**：使用 `messages.append(response.choices[0].message)` 而非手动构造 dict
2. **reasoning_content 保留**：虽然非工具调用轮次的 reasoning_content 会被 API 忽略，但保留它不会有副作用
3. **Token 累积**：每次请求都会发送完整 messages，注意 token 总量限制

---

## 7. 流式输出（Streaming）

### 基础流式

```python
response = client.chat.completions.create(
    model="deepseek-v4-flash",
    messages=[{"role": "user", "content": "数到5"}],
    stream=True,
)

for chunk in response:
    if chunk.choices and chunk.choices[0].delta.content:
        print(chunk.choices[0].delta.content, end="", flush=True)
```

### 流式 Chunk 结构

#### 第一个 chunk（role 声明）

```json
{
  "id": "fc6caa6b-...",
  "object": "chat.completion.chunk",
  "model": "deepseek-v4-flash",
  "choices": [{
    "index": 0,
    "delta": {
      "content": null,
      "role": "assistant",
      "reasoning_content": ""
    },
    "finish_reason": null
  }],
  "usage": null
}
```

#### 内容 chunk（思考阶段）

思考模式的流式中，`reasoning_content` 先于 `content` 到达：

```json
{
  "choices": [{
    "delta": {
      "reasoning_content": "我们被要求...",
      "content": null
    },
    "finish_reason": null
  }],
  "usage": null
}
```

#### 内容 chunk（回答阶段）

```json
{
  "choices": [{
    "delta": {
      "reasoning_content": null,
      "content": "证明"
    },
    "finish_reason": null
  }],
  "usage": null
}
```

#### 最后一个 chunk（终止信号 + usage）

```json
{
  "choices": [{
    "delta": {
      "content": "",
      "reasoning_content": null
    },
    "finish_reason": "stop"
  }],
  "usage": {
    "prompt_tokens": 11,
    "completion_tokens": 405,
    "total_tokens": 416,
    "completion_tokens_details": {
      "reasoning_tokens": 168
    },
    "prompt_cache_hit_tokens": 0,
    "prompt_cache_miss_tokens": 11
  }
}
```

### 流式思考模式的时间线

```
|-- reasoning_content chunks (思考链) --|-- content chunks (最终回答) --|-- stop --|
```

思考链先全部输出完毕，然后才开始输出最终回答。两者通过 `delta.reasoning_content` 和 `delta.content` 区分。

---

## 8. JSON Output

通过 `response_format` 参数强制模型输出 JSON：

```python
response = client.chat.completions.create(
    model="deepseek-v4-flash",
    messages=[
        {"role": "system", "content": "You are a JSON generator."},
        {"role": "user", "content": "列出3个中国城市的名称、人口和特色"},
    ],
    response_format={"type": "json_object"},
)
```

**实测结果**：输出为标准 JSON 数组，可直接 `json.loads()` 解析：

```json
[
  {"name": "北京", "population": 21540000, "feature": "中国的首都，拥有故宫、长城等历史文化古迹"},
  {"name": "上海", "population": 24280000, "feature": "国际大都市，东方明珠塔、外滩等现代地标"},
  {"name": "广州", "population": 15300000, "feature": "南方商贸中心，以美食和岭南文化闻名"}
]
```

---

## 9. 对话前缀续写（Chat Prefix Completion）

通过在 messages 末尾添加一条 `prefix: true` 的 assistant 消息，让模型续写指定前缀的内容。

### 使用方法

```python
client_beta = OpenAI(api_key=API_KEY, base_url="https://api.deepseek.com/beta")

messages = [
    {"role": "user", "content": "请写一段快速排序代码"},
    {"role": "assistant", "content": "```python\n", "prefix": True},
]

response = client_beta.chat.completions.create(
    model="deepseek-v4-flash",
    messages=messages,
    stop=["```"],  # 在 ``` 处停止
)
```

### 关键点

1. **必须使用 Beta endpoint**：`base_url="https://api.deepseek.com/beta"`
2. **prefix 标记**：assistant 消息需要 `"prefix": True`
3. **stop 参数**：通常配合 `stop` 参数控制输出终止位置
4. **适用场景**：代码生成（强制特定语言）、格式化输出、引导特定输出格式

---

## 10. FIM 补全（Fill In the Middle）

FIM 用于代码补全场景——提供前缀和后缀，模型补全中间内容。

```python
client_beta = OpenAI(api_key=API_KEY, base_url="https://api.deepseek.com/beta")

response = client_beta.completions.create(
    model="deepseek-v4-flash",
    prompt="def fib(a):",              # 前缀
    suffix="    return fib(a-1) + fib(a-2)",  # 后缀
    max_tokens=128,
)
```

**限制**：
- 最大补全长度 4K
- 使用 `/v1/completions` 端点（非 `/chat/completions`）
- 需要 Beta endpoint

---

## 11. Anthropic API 兼容

DeepSeek 提供 Anthropic API 格式的兼容层，可直接使用 `anthropic` SDK。

### 配置

```python
import anthropic

# 环境变量方式
# export ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic
# export ANTHROPIC_API_KEY=${YOUR_API_KEY}

client = anthropic.Anthropic()
message = client.messages.create(
    model="deepseek-v4-pro",
    max_tokens=1000,
    system="You are a helpful assistant.",
    messages=[{"role": "user", "content": [{"type": "text", "text": "Hi"}]}],
)
```

### 兼容性矩阵

**简单字段**：

| 字段 | 支持状态 |
|------|---------|
| `max_tokens` | ✅ 完全支持 |
| `stop_sequences` | ✅ 完全支持 |
| `stream` | ✅ 完全支持 |
| `system` | ✅ 完全支持 |
| `temperature` | ✅ 完全支持 (0.0~2.0) |
| `top_p` | ✅ 完全支持 |
| `thinking` | ✅ 支持（`budget_tokens` 被忽略） |
| `top_k` | ❌ 忽略 |

**工具字段**：

| 字段 | 支持状态 |
|------|---------|
| `tools[].name` | ✅ |
| `tools[].input_schema` | ✅ |
| `tools[].description` | ✅ |
| `tool_choice` | ✅ (none/auto/any/tool) |

**消息字段**：

| 类型 | 支持状态 |
|------|---------|
| `text` | ✅ |
| `thinking` | ✅ |
| `tool_use` | ✅ |
| `tool_result` | ✅ |
| `image` | ❌ 不支持 |
| `document` | ❌ 不支持 |
| `redacted_thinking` | ❌ 不支持 |

---

## 12. 上下文缓存

DeepSeek 支持**硬盘缓存**：相同的 prompt 前缀会被自动缓存，后续请求命中缓存时按缓存价格计费。

### 缓存命中指标

在 `usage` 中通过以下字段体现：

```json
{
  "prompt_cache_hit_tokens": 512,
  "prompt_cache_miss_tokens": 83
}
```

**实测验证**：在工具调用的第二轮请求中，返回了 `prompt_cache_hit_tokens: 512`，说明前缀（system prompt + 前几轮 messages）被成功缓存。

### 缓存策略

- **自动触发**：无需额外配置，DeepSeek 自动检测并缓存 prompt 前缀
- **缓存粒度**：以 prompt 的前缀为 key，只要前缀相同即命中
- **保留时间**：硬盘级缓存，保留时间较长（具体策略见官方定价文档）

---

## 13. 错误处理

### 错误响应格式

```json
{
  "error": {
    "message": "错误描述",
    "type": "error_type",
    "param": null,
    "code": "error_code"
  }
}
```

### 实测错误场景

| 场景 | HTTP 状态码 | error.type | error.code | error.message |
|------|-----------|-----------|-----------|--------------|
| 无效模型名 | 400 | `invalid_request_error` | `invalid_request_error` | "The supported API model names are deepseek-v4-pro or deepseek-v4-flash, but you passed deepseek-nonexistent." |
| 空 messages | 400 | `invalid_request_error` | `invalid_request_error` | "Empty input messages" |
| 无效 API Key | 401 | `authentication_error` | `invalid_request_error` | "Authentication Fails, Your api key: ****alid is invalid" |
| 思考模式 + temperature | 200 | - | - | 不报错，但 temperature 不生效 |

### SDK 异常类型

```python
from openai import BadRequestError, AuthenticationError

try:
    response = client.chat.completions.create(...)
except BadRequestError as e:
    # 400 错误
    print(e.status_code, e.message)
except AuthenticationError as e:
    # 401 错误
    print(e.status_code, e.message)
```

---

## 14. 请求/响应完整格式参考

### Chat Completions 请求参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `model` | string | ✅ | `deepseek-v4-flash` 或 `deepseek-v4-pro` |
| `messages` | array | ✅ | 消息列表 |
| `stream` | boolean | ❌ | 默认 `false` |
| `temperature` | number | ❌ | 思考模式下不生效 |
| `top_p` | number | ❌ | 思考模式下不生效 |
| `max_tokens` | integer | ❌ | 最大生成 token 数 |
| `stop` | array | ❌ | 停止序列 |
| `tools` | array | ❌ | 工具定义列表 |
| `tool_choice` | string/object | ❌ | `none`/`auto`/`required`/`{type: "function", function: {name: "xxx"}}` |
| `response_format` | object | ❌ | `{"type": "json_object"}` |
| `reasoning_effort` | string | ❌ | `high` 或 `max` |
| `thinking` | object | ❌（extra_body） | `{"type": "enabled"}` 或 `{"type": "disabled"}` |
| `frequency_penalty` | number | ❌ | 思考模式下不生效 |
| `presence_penalty` | number | ❌ | 思考模式下不生效 |

### Message 格式

| role | 说明 | 必含字段 |
|------|------|---------|
| `system` | 系统指令 | `content` |
| `user` | 用户消息 | `content` |
| `assistant` | 模型回复 | `content`（可能为空字符串），`reasoning_content`（可选），`tool_calls`（可选） |
| `assistant` (prefix) | 前缀续写 | `content`，`prefix: true` |
| `tool` | 工具结果 | `tool_call_id`，`content` |

### finish_reason 枚举

| 值 | 说明 |
|----|------|
| `stop` | 正常结束 |
| `tool_calls` | 模型请求调用工具 |
| `length` | 达到 max_tokens |
| `content_filter` | 内容过滤 |

---

## 15. 与项目集成要点

### 对接 OpenAI Compatible Base Adapter

本项目（TradingAgents-CN）的 LLM 适配器位于 `app/engine/llm_adapters/openai_compatible_base.py`，已支持 OpenAI 兼容格式。DeepSeek 可直接通过此适配器接入。

### 关键适配注意

1. **reasoning_content 处理**：OpenAI 原生 API 不返回 `reasoning_content`，需要在适配器中处理此额外字段
2. **默认思考模式**：DeepSeek V4 默认开启思考，如果项目不期望此行为，需要显式 `thinking: disabled`
3. **prompt_cache 字段**：`prompt_cache_hit_tokens` / `prompt_cache_miss_tokens` 是 DeepSeek 特有的 usage 扩展字段
4. **旧模型名兼容**：`deepseek-chat` 和 `deepseek-reasoner` 将于 2026/07/24 弃用，建议统一使用 `deepseek-v4-flash` + `thinking` 参数控制

### 配置示例

```yaml
# config/agents/phase1_agents_config.yaml 中配置 DeepSeek 模型
llm:
  provider: "deepseek"
  model: "deepseek-v4-flash"
  base_url: "https://api.deepseek.com"
  api_key_env: "DEEPSEEK_API_KEY"
  extra_body:
    thinking:
      type: "enabled"
  reasoning_effort: "high"
```

---

## 附录：测试原始数据

### Test 1: 基础非流式

- **模型**: deepseek-v4-flash
- **finish_reason**: stop
- **usage**: prompt=14, completion=46, total=60, reasoning_tokens=28
- **reasoning_content**: 自动返回（未显式开启思考）
- **system_fingerprint**: `fp_8b330d02d0_prod0820_fp8_kvcache_20260402`

### Test 5: 思考模式关闭

- **reasoning_content**: `None`（显式 disabled）
- **completion_tokens_details**: `None`

### Test 6: 工具调用（并行）

- 模型一次性返回 2 个 tool_calls（get_weather + get_stock_price）
- **第二轮 usage**: prompt=595, completion=134, **cache_hit=512**（前缀缓存生效）

### Test 7: 思考模式 + 工具调用

- Sub-turn 1: reasoning → tool_call (get_weather)
- Sub-turn 2: reasoning → 最终回答（无 tool_call）
- 每轮都携带了 reasoning_content 给 API

### Test 9: 前缀续写

- 使用 Beta endpoint + `prefix: True` + `stop: ["```"]`
- 成功生成 Python 快速排序代码

### Test 10: JSON Output

- `response_format={"type": "json_object"}` 成功输出纯 JSON
- 可直接 `json.loads()` 解析

### Test 11: strict 模式

- Beta endpoint + `strict: True` + `additionalProperties: false`
- 工具参数严格按 Schema 返回

### Test 16: 旧模型名

- `deepseek-chat` → 返回 `model: "deepseek-v4-flash"`, `reasoning_content: None`（非思考）
- `deepseek-reasoner` → 返回 `model: "deepseek-v4-flash"`, `reasoning_content: "..."`（思考）
