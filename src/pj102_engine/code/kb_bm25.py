"""
kb_bm25.py - W2 T2.3: jieba 分词 + BM25 倒排索引 (Karpathy L2 导航层)

设计 (对齐腾讯云 2658818 实现参考):
  - 纯内存, 启动构建 <3s (504 页 × 平均 3KB)
  - 标题(文件名) token 权重 3.0, 正文 1.0
  - BM25 参数 k1=1.5, b=0.75
  - 索引范围: 全 wiki 内容页 (Meetings/Entities/Knowledge/Summaries),
    排除 index.md / log* / .obsidian 等结构文件
  - 无外部依赖服务, 断电即重建 (写时计算, 不持久化索引)
"""
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import List, Tuple

try:
    import jieba
    _HAS_JIEBA = True
except ImportError:  # 降级: 字符 bigram
    _HAS_JIEBA = False

_STOPWORDS = set(
    "的 了 是 在 我 与 和 及 或 上下 中 有 无 为 对 到 从 被 把 给 向 于 以 由 此 其 之 者 也"
    " 都 还 又 再 就 只 才 便 然 但 各 什么 怎么 如何 这个 那个 以及 我们 你们 他们".split())


def tokenize(text: str) -> List[str]:
    """中文 jieba 分词 + 英文/数字保留, 去停用词"""
    text = re.sub(r"[\[\]#*`|-]", " ", text)  # 剥离 markdown 语法噪音
    if _HAS_JIEBA:
        toks = [t.strip() for t in jieba.cut(text)]
    else:
        toks = text.split()
    out = []
    for t in toks:
        if not t or t in _STOPWORDS:
            continue
        if re.fullmatch(r"[\u4e00-\u9fff]", t):
            continue  # 单字中文信息量低
        out.append(t.lower())
    return out


class KB_BM25:
    """BM25 倒排索引 (内存常驻)"""

    K1 = 1.5
    B = 0.75
    TITLE_WEIGHT = 3.0

    def __init__(self, wiki_root: Path):
        self.wiki_root = Path(wiki_root)
        self.docs: List[Path] = []
        self.doc_len: List[int] = []
        self.doc_tfs: List[Counter] = []
        self.df: Counter = Counter()          # term -> 出现文档数
        self.inverted: defaultdict = defaultdict(list)  # term -> [doc_idx]
        self._avg_len = 0.0
        self._build()

    # ---- 构建 ----
    def _build(self):
        if not self.wiki_root.exists():
            return
        skip_names = {"index.md", "log.md"}
        for md in sorted(self.wiki_root.rglob("*.md")):
            if md.name in skip_names or md.name.startswith("log.legacy"):
                continue
            if any(p.startswith(".") for p in md.relative_to(self.wiki_root).parts):
                continue  # .obsidian / .claude 等隐藏目录
            try:
                content = md.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            body_toks = tokenize(content)
            title_toks = tokenize(md.stem) * int(self.TITLE_WEIGHT)
            tf = Counter(body_toks + title_toks)
            if not tf:
                continue
            idx = len(self.docs)
            self.docs.append(md)
            self.doc_tfs.append(tf)
            self.doc_len.append(len(body_toks) + len(title_toks))
            for term in tf:
                self.df[term] += 1
                self.inverted[term].append(idx)
        self._avg_len = (sum(self.doc_len) / len(self.doc_len)) if self.doc_len else 1.0

    # ---- 查询 ----
    def search(self, query: str, top_k: int = 10) -> List[Tuple[float, Path]]:
        """返回 [(score, path)] 降序"""
        q_toks = tokenize(query)
        if not q_toks or not self.docs:
            return []
        N = len(self.docs)
        scores = defaultdict(float)
        for term in q_toks:
            postings = self.inverted.get(term)
            if not postings:
                continue
            idf = math.log(1 + (N - len(postings) + 0.5) / (len(postings) + 0.5))
            for idx in postings:
                tf = self.doc_tfs[idx][term]
                dl = self.doc_len[idx] or 1
                denom = tf + self.K1 * (1 - self.B + self.B * dl / self._avg_len)
                scores[idx] += idf * tf * (self.K1 + 1) / denom
        ranked = sorted(scores.items(), key=lambda x: -x[1])[:top_k]
        return [(s, self.docs[i]) for i, s in ranked]

    @property
    def size(self) -> int:
        return len(self.docs)


# ---- CLI 自测 ----
if __name__ == "__main__":
    import sys
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("wiki")
    import time
    t0 = time.time()
    bm = KB_BM25(root)
    print(f"构建: {bm.size} 页 / {time.time()-t0:.1f}s / jieba={'on' if _HAS_JIEBA else 'off(bigram降级)'}")
    for q in (sys.argv[2:] or ["供应链金融 票据"]):
        print(f"\n查询: {q}")
        for s, p in bm.search(q, top_k=5):
            print(f"  {s:6.2f}  {p.relative_to(root)}")
