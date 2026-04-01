"""
lib/chunker.py — 解析 memory 文件为结构化 chunk 列表
复用 memory_convert_to_nested.py 的解析逻辑，但输出 dict 而非 markdown。
"""
import re
from pathlib import Path
from typing import Optional  # noqa: F401

# 正则：匹配用户消息行
USER_LINE_RE = re.compile(r"^(\s*)-\s+\[(\d{2}:\d{2})\]\s+主人[：:](.*)$")
# 正则：匹配 Fairy 消息行（兼容两种格式）
# 格式1（标准）：- [HH:MM] Fairy：...
# 格式2（实际）：Fairy：...（无 dash 和时间，出现在 『』 内或独立行）
FAIRY_LINE_RE = re.compile(r"^(\s*)-\s+\[(\d{2}:\d{2})\]\s+Fairy[：:](.*)$")
FAIRY_NOMETA_RE = re.compile(r"^(\s*)(?<!『)Fairy[：:](.*?)(?:』)?$")


def _indent_para(para: str) -> str:
    """『』内缩进：首行不缩进，后续行缩进 4 字符。"""
    lines = para.split("\n")
    if len(lines) <= 1:
        return para
    return lines[0] + "\n" + "\n".join("    " + line for line in lines[1:])


def parse_memory_file(filepath: Path, date: str) -> list[dict]:
    """
    解析单个 memory 文件，返回 chunk 列表。

    对话追加区以 ``"\n## 主人状态\n"`` 分割，
    收集每条用户消息后连续 Fairy 回复合并为一个 ``『』`` 块。

    Returns:
        list[dict]: 每个元素含 {id, date, time_start, time_end,
               speakers, summary, text, chunk_index}
    """
    content = filepath.read_text()

    # 以 \n## 主人状态\n 分割：
    # - segments[0] = 对话内容（在 ## 主人状态 之前，fairy-memory-update 追加的位置）
    # - segments[1] = ## 主人状态 元数据（咖啡因、心情等）和之后的 ## 备注
    segments = content.split("\n## 主人状态\n")
    dialogue_section = segments[0] if len(segments) > 1 else content

    lines = dialogue_section.split("\n")
    chunks: list[dict] = []
    chunk_index = 0

    i = 0
    while i < len(lines):
        line = lines[i]
        user_match = USER_LINE_RE.match(line)

        if user_match:
            indent = user_match.group(1)
            time_start = user_match.group(2)
            user_text = user_match.group(3).strip()

            # 收集后续连续 Fairy 回复，合并为一个段落
            fairy_merged = ""
            j = i + 1

            while j < len(lines):
                next_line = lines[j]

                # 『Fairy： 开头的行（无 dash 格式且有『前缀）→ 提取内容后遇到 Fairy：闭合行
                if next_line.strip().startswith("『Fairy："):
                    fairy_inner_first = next_line.strip()[len("『"):]
                    fairy_merged = (fairy_merged + "\n" + fairy_inner_first) if fairy_merged else fairy_inner_first
                    j += 1
                    # 收集后续缩进内容直到遇到独立 Fairy： 闭合行
                    while j < len(lines):
                        c = lines[j].strip()
                        if c.startswith("Fairy："):
                            # Fairy： 闭合行，提取内容（去掉结尾 』）
                            fairy_end = c[len("Fairy："):].rstrip("』")
                            fairy_merged += "\n" + fairy_end
                            j += 1
                            break
                        if re.match(r"^#{1,6}\s", c) or c == "---" or c == "":
                            break
                        fairy_merged += "\n" + c
                        j += 1
                    continue

                # 尝试标准 Fairy 格式：- [HH:MM] Fairy：...
                fairy_next = FAIRY_LINE_RE.match(next_line)
                # 降级：无 dash/时间的 Fairy 格式：Fairy：...
                if not fairy_next:
                    fairy_next = FAIRY_NOMETA_RE.match(next_line)

                if fairy_next:
                    # group(3) 存在 = 标准格式；否则 = 无 dash 格式（group 2）
                    fairy_text = fairy_next.group(3).strip() if fairy_next.lastindex >= 3 else fairy_next.group(2).strip()
                    fairy_merged = (fairy_merged + "\n" + fairy_text) if fairy_merged else fairy_text
                    j += 1

                    # 如果该行以 』 结束，则 Fairy 块到此为止
                    if fairy_next.lastindex < 3 and next_line.rstrip().endswith("』"):
                        # 继续收集剩余续段落（缩进内容），但不添加 』 这行内容
                        while j < len(lines):
                            cont2 = lines[j]
                            if USER_LINE_RE.match(cont2) or FAIRY_LINE_RE.match(cont2) or FAIRY_NOMETA_RE.match(cont2):
                                break
                            if re.match(r"^#{1,6}\s", cont2.strip()) or cont2.strip() == "---":
                                break
                            if cont2.strip().startswith("『"):
                                fairy_merged += "\n" + cont2.strip()[1:]
                                j += 1
                                continue
                            if cont2.strip().endswith("』"):
                                fairy_merged += "\n" + cont2.strip()[:-1]
                                j += 1
                                break
                            if cont2.strip() == "":
                                j += 1
                                continue
                            stripped2 = cont2[len(indent):] if cont2.startswith(indent) else cont2[2:]
                            fairy_merged += "\n" + stripped2
                            j += 1
                        break

                    # 收集 Fairy 续段落（缩进行）
                    while j < len(lines):
                        cont = lines[j]
                        if USER_LINE_RE.match(cont) or FAIRY_LINE_RE.match(cont) or FAIRY_NOMETA_RE.match(cont):
                            break
                        if re.match(r"^#{1,6}\s", cont.strip()) or cont.strip() == "---":
                            break
                        # 『 开头但没有 Fairy：→ Fairy 延续内容（如 『内容）
                        if cont.strip().startswith("『"):
                            fairy_merged += "\n" + cont.strip()[1:]
                            j += 1
                            continue
                        # 』 结尾 → Fairy 块结束
                        if cont.strip().endswith("』"):
                            fairy_merged += "\n" + cont.strip()[:-1]
                            j += 1
                            break
                        if cont.strip() == "":
                            j += 1
                            continue
                        # 去除当前 user 消息的缩进前缀
                        stripped = cont[len(indent):] if cont.startswith(indent) else cont[2:]
                        fairy_merged += "\n" + stripped
                        j += 1
                    continue

                user_next = USER_LINE_RE.match(next_line)
                if user_next:
                    user_content = user_next.group(3).strip()
                    # 启发式：编号列表 / "此脚本" 开头 = Fairy 延续
                    if re.match(r"^\d+\.", user_content) or user_content.startswith("此脚本"):
                        fairy_merged = (fairy_merged + "\n" + user_content) if fairy_merged else user_content
                        j += 1
                        while j < len(lines):
                            c = lines[j].strip()
                            if re.match(r"^\d+\.", c):
                                fairy_merged += "\n" + c
                                j += 1
                                continue
                            break
                        continue
                    break

                if re.match(r"^#{1,6}\s", next_line.strip()) or next_line.strip() == "---":
                    break
                if next_line.strip() == "":
                    break
                j += 1

            # 构建 text
            speakers = ["主人"]
            entry_text = f"- [{time_start}] 主人：{user_text}"
            if fairy_merged:
                speakers.append("Fairy")
                entry_text += f"\n  『{_indent_para(fairy_merged)}』"

            chunk_index += 1
            chunk = {
                "id": f"{date}_{time_start.replace(':', '')}_{chunk_index:03d}",
                "date": date,
                "time_start": time_start,
                "time_end": None,  # 暂时留空，下一步统一填充
                "speakers": speakers,
                "summary": None,
                "text": entry_text,
                "chunk_index": chunk_index,
            }
            chunks.append(chunk)
            i = j
        else:
            i += 1

    # 统一填充 time_end：每条 chunk 的 time_end = 下一条 chunk 的 time_start
    for idx in range(len(chunks) - 1):
        chunks[idx]["time_end"] = chunks[idx + 1]["time_start"]
    if chunks:
        chunks[-1]["time_end"] = None

    return chunks
