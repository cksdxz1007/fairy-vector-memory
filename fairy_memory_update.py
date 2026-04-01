#!/usr/bin/env python3
"""
fairy-memory-update: 读取所有 session transcript JSONL，提取今日对话（用户 + Fairy），追加到 memory 文件

修复版（2026-03-30）：
- 遍历所有 session 文件，而非只读最新一个
- 聚合所有 session 的今日消息，去重后按时间排序
- 解决了 cron session 与 Telegram session 分离导致漏读的问题
"""
import hashlib
import json
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ====== 配置 ======
SESSIONS_DIR = Path("/Users/cynningli/.openclaw/agents/main/sessions")
MEMORY_DIR = Path("/Users/cynningli/.openclaw/workspace/memory")
STATE_FILE = MEMORY_DIR / ".update_state.json"
TZ = timezone(timedelta(hours=8))
TODAY = datetime.now(TZ).strftime("%Y-%m-%d")
MEMORY_FILE = MEMORY_DIR / f"{TODAY}.md"

# ====== 通用密码脱敏 ======
SECRET_PATTERNS = [
    (r'\b(sk[-_][a-zA-Z0-9]{20,})', '[API_KEY]'),
    (r'\b(api[-_]?(key|token|secret|password)?[-_]?[a-zA-Z0-9]{16,})', '[API_KEY]'),
    (r'\b(key[-_]?[a-zA-Z0-9]{20,})', '[API_KEY]'),
    (r'\b(secret[-_]?[a-zA-Z0-9]{16,})', '[SECRET]'),
    (r'(Bearer\s+[a-zA-Z0-9_\-\.]+)', '[BEARER_TOKEN]'),
    (r'\beyJ[a-zA-Z0-9_\-]+\.[a-zA-Z0-9_\-]+\.[a-zA-Z0-9_\-]+\b', '[JWT_TOKEN]'),
    (r'\b(AKIA[0-9A-Z]{16})\b', '[AWS_KEY]'),
    (r'\b(\d{8,10}:[a-zA-Z0-9_-]{35})\b', '[TELEGRAM_BOT_TOKEN]'),
    (r'\b([a-z]{4}\s+[a-z]{4}\s+[a-z]{4}\s+[a-z]{4})\b', '[Gmail_App_Password]'),
    (r'\b([a-zA-Z0-9]{32,})\b', '[SECRET_KEY]'),
    (r'[a-zA-Z0-9_.+-]+:[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+', '[URL_WITH_CRED]'),
]
COMPILED_PATTERNS = [(re.compile(p, re.IGNORECASE), repl) for p, repl in SECRET_PATTERNS]

def sanitize(text):
    """通用密码脱敏处理"""
    for pattern, replacement in COMPILED_PATTERNS:
        text = pattern.sub(replacement, text)
    return text

# ====== 读取 state（last_check + seen 持久化） ======
if STATE_FILE.exists():
    state = json.loads(STATE_FILE.read_text())
else:
    state = {"last_check": ""}

# 持久化的 seen 集合（跨运行去重）
persistent_seen = set(state.get("seen_hashes", []))

last_check_str = state.get("last_check", "")
if last_check_str:
    last_check_str_clean = last_check_str.replace("Z", "").replace("+00:00", "").replace("+08:00", "").rstrip()
    try:
        last_check = datetime.fromisoformat(last_check_str_clean).replace(tzinfo=TZ)
    except:
        last_check = datetime(2024, 1, 1, tzinfo=TZ)
else:
    last_check = datetime(2024, 1, 1, tzinfo=TZ)

print(f"[fairy-memory-update] 上次检查: {last_check.strftime('%Y-%m-%d %H:%M')} CST")

# ====== 如果 memory 文件不存在，跳过 ======
if not MEMORY_FILE.exists():
    print(f"[fairy-memory-update] memory 文件不存在，跳过: {MEMORY_FILE.name}")
    new_entries = []
    seen = set(persistent_seen)
else:
    current_memory = MEMORY_FILE.read_text()

    # ====== 预加载已有 memory 文件内容哈希 + 持久化 seen（跨运行去重） ======
    seen = set(persistent_seen)  # 先加载跨运行的持久化哈希
    for line in current_memory.split('\n'):
        # 匹配 "- [HH:MM] 主人：" 格式，提取正文
        m = re.match(r'^-\s+\[\d{2}:\d{2}\]\s+主人[：:]\s*(.*)$', line)
        if m:
            text = m.group(1).strip()
            if text:
                h = hashlib.md5(text.encode()).hexdigest()
                seen.add(f"user:{h}")
        # 也匹配没有 "- [HH:MM]" 前缀的 Fairy 回复块（『』包裹）
        if line.startswith('  『'):
            inner = line[3:].rstrip('』')
            if inner:
                h = hashlib.md5(inner.encode()).hexdigest()
                seen.add(f"assistant:{h}")

    # ====== 遍历所有 session 文件，聚合今日消息 ======
    raw_entries = []  # (msg_time, time_str, role, actual_text)
    session_files = list(SESSIONS_DIR.glob("*.jsonl"))
    print(f"[fairy-memory-update] 发现 {len(session_files)} 个 session 文件")

    for session_file in session_files:
        try:
            with open(session_file, 'r') as f:
                for line in f:
                    try:
                        msg = json.loads(line.strip())
                    except:
                        continue

                    if msg.get('type') != 'message':
                        continue

                    inner = msg.get('message', {})
                    role = inner.get('role', '')

                    if role not in ('user', 'assistant'):
                        continue

                    ts = msg.get('timestamp', '')
                    if not ts or not ts.startswith(TODAY):
                        continue

                    # 解析消息时间（UTC），处理 Z 和 +00:00 后缀
                    try:
                        ts_clean = ts.replace('Z', '+00:00')
                        # 找到 T 分割符，正确提取日期时间部分
                        t_pos = ts_clean.find('T')
                        if t_pos < 0:
                            continue
                        dt_str = ts_clean[t_pos+1:]  # 获取 time 部分
                        # 处理 timezone: +00:00, +08:00, -05:00 等
                        tz_match = re.search(r'[+-]\d{2}:?\d{2}', dt_str)
                        if tz_match:
                            tz_str = tz_match.group()
                            dt_part = dt_str[:tz_match.start()].rstrip()
                        else:
                            dt_part = dt_str.rstrip()
                            tz_str = '+00:00'
                        msg_time = datetime.fromisoformat(f"{ts_clean[:t_pos]} {dt_part}{tz_str}")
                        msg_time = msg_time.astimezone(TZ)
                    except Exception as e:
                        print(f"[警告] 时间解析失败 '{ts}': {e}")
                        continue

                    if msg_time <= last_check:
                        continue

                    # 提取实际文字
                    content = inner.get('content', [])
                    if isinstance(content, str):
                        content = [{"type": "text", "text": content}]
                    if not isinstance(content, list):
                        print(f"[警告] content 类型异常: {type(content)}")
                        continue

                    for c in content:
                        if c.get('type') != 'text':
                            continue
                        raw = c.get('text', '').strip()
                        if not raw:
                            continue

                        # 最后一个 ``` 之后就是实际文字
                        last_backtick = raw.rfind('```')
                        if last_backtick >= 0:
                            actual_text = raw[last_backtick+3:].strip()
                        else:
                            actual_text = raw

                        # 清理噪音
                        if not actual_text or len(actual_text) < 4:
                            continue
                        if actual_text.upper() in ('CONVERSATION INFO', 'SENDER (UNTRUSTED METADATA)', 'SENDER (UNTRUSTED METADATA):'):
                            continue
                        if 'HEARTBEAT' in actual_text.upper() and len(actual_text) < 20:
                            continue
                        if actual_text.startswith('[Queued messages'):
                            continue
                        if re.match(r'^---+$', actual_text.strip()):
                            continue
                        # 过滤 cron job 自身的输出（不应进入 memory）
                        if actual_text.startswith('/approve '):
                            continue
                        if 'Exec finished (gateway id=' in actual_text and ', code ' in actual_text:
                            continue
                        if actual_text.startswith('[fairy-memory-update]'):
                            continue
                        actual_text = re.sub(r'^MEDIA:.*?(?=\s|$)', '', actual_text, flags=re.DOTALL).strip()

                        # 脱敏
                        actual_text = sanitize(actual_text)

                        if not actual_text or len(actual_text) < 4:
                            continue

                        # 去重（按角色+内容md5）
                        content_hash = hashlib.md5(actual_text.encode()).hexdigest()
                        dedup_key = f"{role}:{content_hash}"
                        if dedup_key in seen:
                            continue
                        seen.add(dedup_key)

                        time_str = msg_time.strftime("%H:%M")
                        raw_entries.append((msg_time, time_str, role, actual_text))

        except Exception as e:
            print(f"[警告] 读取 session 文件失败 {session_file.name}: {e}")
            continue

    # ====== 按时间排序并配对嵌套 ======
    new_entries = []
    if raw_entries:
        raw_entries.sort(key=lambda x: x[0])
        i = 0
        while i < len(raw_entries):
            _, time_str, role, text = raw_entries[i]
            if role == 'user':
                # 主导消息
                entry = f"- [{time_str}] 主人：{text}"

                # 收集后续的连续 Fairy 回复
                fairy_paragraphs = []
                j = i + 1
                while j < len(raw_entries) and raw_entries[j][2] == 'assistant':
                    fairy_paragraphs.append(fairy_paragraphs[-1] + '\n' + raw_entries[j][3] if fairy_paragraphs else raw_entries[j][3])
                    j += 1

                if fairy_paragraphs:
                    # 首行不缩进，后续行缩进 4 字符
                    def indent_para(para):
                        lines = para.split('\n')
                        if len(lines) <= 1:
                            return para
                        return lines[0] + '\n' + '\n'.join('    ' + line for line in lines[1:])
                    indented = indent_para(fairy_paragraphs[0])
                    entry += f"\n  『{indented}』"

                new_entries.append(entry)
                i = j
            else:
                i += 1

    # ====== 追加到 memory 文件 ======
    if new_entries:
        entries_text = "\n".join(new_entries)

        marker = "\n## 主人状态"
        if marker in current_memory:
            parts = current_memory.split(marker)
            updated = parts[0].rstrip() + "\n" + entries_text + "\n" + marker + parts[1]
        else:
            updated = current_memory.rstrip() + "\n" + entries_text + "\n"
            print(f"[警告] 未找到 '{marker.strip()}' 标记，对话已追加到文件末尾")

        MEMORY_FILE.write_text(updated)
        print(f"[fairy-memory-update] ✅ 追加 {len(new_entries)} 条对话到 {MEMORY_FILE.name}")
    else:
        print(f"[fairy-memory-update] 没有新内容，跳过")

# ====== 更新 last_check 和 seen_hashes ======
# 合并本次运行新出现的哈希到 persistent_seen 并持久化
all_seen = persistent_seen | seen
final_state = {
    "last_check": datetime.now(TZ).isoformat().replace("+08:00", "").replace("Z", ""),
    "seen_hashes": list(all_seen),
    "note": "由 fairy-memory-update 自动更新（多session聚合版 + 通用脱敏 + seen持久化）",
}
STATE_FILE.write_text(json.dumps(final_state, indent=2, ensure_ascii=False))
print(f"[fairy-memory-update] last_check 已更新: {state['last_check']}")