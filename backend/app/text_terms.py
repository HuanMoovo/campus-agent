"""中文二元组 + 英文单词的文本分词，供知识库检索与联网搜索共用。"""
import re


def terms(text: str) -> set[str]:
    lowered = (text or "").lower()
    cjk = re.findall(r"[\u4e00-\u9fff]", lowered)
    words = re.findall(r"[a-z0-9]+", lowered)
    return set(words + ["".join(cjk[i:i + 2]) for i in range(len(cjk) - 1)])
