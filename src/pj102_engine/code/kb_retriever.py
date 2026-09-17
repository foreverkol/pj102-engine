"""
v4.0 kb_retriever.py - 双层 Query 架构 (Karpathy LLM Wiki 方法论落地)

L1 entity_nav.py: 实体导航 (纯规则, 毫秒级, 直接返回实体卡片)
L2 semantic_synthesis: 语义综合 (LLM 读取已编译 wiki 文件内容综合回答)

核心改进 (对齐 Karpathy "LLM Knowledge Bases" 方法论):
  - L2 不再只把实体名告诉 LLM, 而是真实读取 wiki/*.md 已编译内容作为上下文
  - LLM 基于已编译知识综合回答, 而非凭空生成 (抗幻觉)
  - citations 真实指向 wiki 文件路径 (可点击查看来源)
  - 用 AppConfig 自动获取路径, CLI 无需手动传
  - persons_master 不存在时优雅降级 (用 entity_registry 替代)

主入口 query_wiki(query):
  1. 调用 entity_nav.nav(query) → matches
  2. 若 L1 命中 且 非综合查询 → 返回 L1 实体卡片 (毫秒级)
  3. 若 L1 fallback 或 综合查询 → 收集 wiki 文件内容 → LLM 综合答案 + 引用
  4. 返回 {level: "L1"|"L2", content, synthesis, citations}
"""

import json
import re
import sys
from pathlib import Path
from typing import List, Dict, Optional

sys.path.insert(0, str(Path(__file__).parent))
from entity_nav import EntityNav


# 综合类查询关键词 (触发 L2)
SYNTHESIS_KEYWORDS = [
    # T-P6.1: 移除 "是谁"/"是什么" —— 实体卡片区 (L1) 的本职查询, 交由复合意图启发接管;
    # 其余为真综合意图词 (对比/演进/分析类)
    "综合", "总结", "演化", "演进", "对比", "全部", "所有", "跨", "总览",
    "整体", "汇总", "梳理", "分析", "趋势", "脉络", "关系", "怎么",
    "如何", "为什么", "评价", "看法", "观点", "区别", "差异",
    "介绍", "详情", "情况", "背景", "过程", "历程",
    "决策标准", "发展",
]


class KBRetriever:
    """双层 Query 检索器"""

    def __init__(self,
                 registry_path: Path,
                 persons_master_path: Path,
                 llm_client=None,
                 wiki_root: Path = None,
                 cfg=None):
        """
        Args:
            registry_path: entity_registry.json 路径
            persons_master_path: persons_master.json 路径 (不存在则优雅降级)
            llm_client: LLMClient 实例 (L2 需要); None 时用 stub
            wiki_root: wiki/ 根目录 (L2 收集引用)
            cfg: AppConfig 实例 (用于 wiki_dir_for 映射)
        """
        self.entity_nav = EntityNav(registry_path, persons_master_path)
        self.llm = llm_client
        self.wiki_root = Path(wiki_root) if wiki_root else None
        self.cfg = cfg
        self._bm25 = None  # W2-T2.3: BM25 索引懒加载

    def query_wiki(self, query: str, max_l1: int = 8) -> Dict:
        """主入口: 返回查询结果

        Returns:
            {
                "level": "L1" | "L2",
                "query": str,
                "matches": [L1 命中实体],
                "synthesis": str | None,      # L2 综合答案
                "citations": [wiki paths],     # 引用的 wiki 文件
                "context_chunks": int,        # L2 读取的 wiki 段落数
                "fallback_reason": str | None
            }
        """
        # L1 实体导航
        l1_result = self.entity_nav.nav(query)
        is_synthesis = self._is_synthesis_query(query)

        # T-P6.1 复合意图启发: 词表之外, 命中实体名之外仍有实质修饰语 (>6 字) 视为综合查询。
        # 例: "本人对AI工具生态选型的决策标准" 命中实体"本人", 但查询远长于实体名
        # → 用户要的是综合分析而非实体卡片, 应进 L2 (query_rewrite 扩召回)。
        # 短查询 ("万联网是什么"/"本人是谁") 差值 <=6, 仍走 L1 毫秒级。
        if not is_synthesis and l1_result.get("matches") and not l1_result["fallback_to_llm"]:
            hit_names = [m.get("canonical_name", "") or "" for m in l1_result["matches"]]
            core = max((len(n) for n in hit_names), default=0)
            if len(query) - core > 6:
                is_synthesis = True

        # L1 命中 且 非综合查询 → 直接返回实体卡片 (毫秒级)
        if l1_result["matches"] and not l1_result["fallback_to_llm"] and not is_synthesis:
            matches = l1_result["matches"][:max_l1]
            return {
                "level": "L1",
                "query": query,
                "matches": matches,
                "synthesis": None,
                "citations": [],
                "context_chunks": 0,
                "fallback_reason": None,
            }

        # L2 fallback: 读 wiki 内容综合
        return self._query_l2(query, l1_result, is_synthesis)

    # ============ L2 语义综合 ============

    def _query_l2(self, query: str, l1_result: dict, is_synthesis: bool) -> Dict:
        """L2 语义综合: 读取已编译 wiki 文件内容, LLM 基于内容综合回答"""
        if not self.llm:
            return self._query_l2_stub(query, l1_result)

        # T-P6.1 query_rewrite: 综合查询多角度改写扩召回 (失败兜底=原句, 零破坏)
        queries = self._rewrite_query(query) if is_synthesis else [query]

        # 核心改进: 收集 wiki 文件实际内容作为 LLM 上下文 (多变体检索合并)
        context_text, citations = self._collect_wiki_context(l1_result, queries)

        if not context_text.strip():
            # 无可用上下文
            return {
                "level": "L2",
                "query": query,
                "matches": l1_result.get("matches", []),
                "synthesis": f"知识库中未找到与「{query}」相关的内容。请检查查询关键词或先运行 pipeline 编译相关资料。",
                "citations": [],
                "context_chunks": 0,
                "fallback_reason": "no wiki context found",
            }

        # 构造 prompt: 把已编译 wiki 内容作为"已知知识"喂给 LLM
        system_prompt = (
            "你是主理人的个人知识库助手。你将收到从知识库 wiki 中检索到的已编译结构化内容"
            "（会议纪要、人物档案、概念卡片、判断记录），每段带【资料n|路径】编号标记。"
            "请基于这些已编译内容回答主理人的问题，遵守:\n"
            "1. 只基于提供的内容回答, 不编造未提及的信息\n"
            "2. 行内引用: 每个关键论断后标注资料编号, 如 [1] 或 [2][3] (编号对应【资料n】)\n"
            "3. 引用具体来源 (会议日期 / 人物名 / 机构名)\n"
            "4. 如信息不足或不确定, 明确说明 \"知识库中暂无该信息\"\n"
            "5. 简洁专业, 中文回答"
        )
        user_prompt = self._build_l2_prompt(query, l1_result, context_text)

        try:
            synthesis = self.llm.call(
                user_prompt,
                system=system_prompt,
                max_tokens=4096,  # 综合回答不需要 524288, 节省成本
            )
        except Exception as e:
            synthesis = f"[L2 错误: {e}]"

        # T-P6.1 行内引用后处理: 越界编号剔除 + 尾部追加编号->路径映射 (可定位)
        if not synthesis.startswith("[L2 错误"):
            synthesis = self._postprocess_citations(synthesis, citations)

        result = {
            "level": "L2",
            "query": query,
            "matches": l1_result.get("matches", []),
            "synthesis": synthesis,
            "citations": citations,
            "context_chunks": len(citations),
            "rewrites": queries[1:] if len(queries) > 1 else [],  # T-P6.1 改写变体
            "fallback_reason": "L1 无精确匹配 或 综合类查询" if is_synthesis
                              else "L1 无精确匹配",
        }
        # W2-T2.3 问答回流钩子 (Karpathy Enhance 阶段):
        # 引用 >= 2 时建议归档为 Query 页 (agent 询问制防膨胀, 不自动写盘)
        if len(citations) >= 2 and not synthesis.startswith("[L2 错误"):
            result["suggest_archive"] = {
                "reason": f"citations={len(citations)} >= 2, 该问答有沉淀价值",
                "action": "调用 write_query_page(result, wiki_root) 归档到 wiki/Queries/",
            }
        return result

    def _postprocess_citations(self, synthesis: str, citations: List[str]) -> str:
        """T-P6.1 行内引用后处理 (FR-13 验收: 编号引用可定位)

        1. 剔除越界编号 (LLM 幻觉 [99] 之类), 合法编号保留
        2. 尾部追加「引用出处」映射区: [n] → wiki 相对路径
        3. 若答案完全无行内编号 (LLM 未遵守), 至少保留尾部出处区 (citations 仍可定位)
        """
        n_max = len(citations)

        def _clamp(m):
            n = int(m.group(1))
            return f"[{n}]" if 1 <= n <= n_max else ""

        cleaned = re.sub(r"\[(\d{1,2})\]", _clamp, synthesis)
        if not citations:
            return cleaned

        used = sorted({int(x) for x in re.findall(r"\[(\d{1,2})\]", cleaned)})
        lines = ["", "---", "**引用出处** (编号 → wiki 页, 可点击定位):"]

        def _rel(n):
            p = citations[n - 1]
            return p[:-3] if p.endswith(".md") else p  # 库内 wikilink 无 .md 后缀约定

        if used:
            for n in used:
                lines.append(f"- [[{_rel(n)}|[{n}]]]")
        else:
            for i, c in enumerate(citations, 1):
                lines.append(f"- [[{_rel(i)}|[{i}]]]")
        return cleaned + "\n" + "\n".join(lines)

    def _rewrite_query(self, query: str) -> List[str]:
        """T-P6.1 query_rewrite: 复杂综合问题的多角度改写 (FR-13)

        LLM 生成 3 个改写 (同义重述 / 拆解子问题 / 扩展相关术语), 用于扩大检索召回面。
        确定性兜底: LLM 失败/超时/输出解析失败 → 仅返回 [原句], 检索行为退化为 P5 现状 (零破坏)。
        仅综合查询触发 (调用方保证), L1 命中路径不经过本函数。
        """
        if not self.llm:
            return [query]
        try:
            prompt = (
                "把下面的知识库查询改写为 3 个不同角度的检索变体, 用于扩大语义召回:\n"
                "1. 同义重述 (换措辞, 保留意图)\n"
                "2. 拆解 (拆成更具体的子问题表述)\n"
                "3. 扩展 (补充领域术语/同义词)\n"
                f"原查询: {query}\n"
                '只输出 JSON 数组, 如 ["改写1", "改写2", "改写3"], 不要其他文字。'
            )
            raw = self.llm.call(prompt, max_tokens=300)
            # 关键词级解析兜底 (MiniMax 不保证纯 JSON 输出)
            m = re.search(r"\[.*?\]", raw, re.S)
            if not m:
                return [query]
            import json as _json
            variants = [v.strip() for v in _json.loads(m.group(0)) if isinstance(v.strip(), str) and v.strip()]
            variants = variants[:3]
            # 去重 + 保原句
            out = [query]
            for v in variants:
                if v and v not in out:
                    out.append(v)
            return out
        except Exception:
            return [query]

    def _collect_wiki_context(self, l1_result: dict, queries: List[str]) -> tuple:
        """收集 wiki 文件内容作为 LLM 上下文 (Karpathy 核心: 读已编译知识)

        策略:
          1. L1 命中实体 → 找对应 person/org wiki 文件
          2. 每个 query 变体 (T-P6.1 query_rewrite) → BM25 检索, 合并去重
          3. 读取每个文件的关键段落 (frontmatter + body 前 1500 字符)
          4. 拼接成上下文文本, 每段落带【资料 n|路径】编号标记 (行内引用锚点)
        """
        if not self.wiki_root or not self.wiki_root.exists():
            return "", []

        context_parts = []
        cited_files = []
        seen_files = set()

        def _add_file(wiki_file: Path) -> None:
            if wiki_file.exists() and str(wiki_file) not in seen_files:
                seen_files.add(str(wiki_file))
                chunk = self._read_wiki_chunk(wiki_file, max_chars=1500)
                if chunk:
                    n = len(cited_files) + 1
                    rel = wiki_file.relative_to(self.wiki_root).as_posix()
                    context_parts.append(f"【资料{n}|{rel}】\n{chunk}")
                    cited_files.append(rel)

        # 策略 1: L1 命中实体 → 找 person/org wiki 文件 (同实体多文件全部读取, 取前 3 个)
        for m in l1_result.get("matches", []):
            entity_type = m.get("type")
            canonical = m.get("canonical_name", "")
            if not canonical:
                continue
            wiki_files = self._find_wiki_files_for_entity(entity_type, canonical, max_n=3)
            for wiki_file in wiki_files:
                _add_file(wiki_file)

        # 策略 2: BM25 倒排索引检索 — 逐 query 变体检索合并 (T-P6.1 改写扩召回)
        # 降级链: BM25 构建/查询异常 → 旧 n-gram 关键词计数
        for q in queries:
            bm25_files = self._search_wiki_by_bm25(q, max_files=5)
            if bm25_files:
                for wf in bm25_files:
                    _add_file(wf)
            else:
                keywords = self._extract_keywords(q)
                if keywords:
                    kw_files = self._search_wiki_by_keywords(keywords, max_files=5)
                    for wf in kw_files:
                        _add_file(wf)

        return "\n\n".join(context_parts), cited_files

    def _find_wiki_files_for_entity(self, entity_type: str, canonical: str, max_n: int = 3) -> List[Path]:
        """根据实体类型和名称找对应 wiki 文件 (同实体多文件全部返回, 取前 max_n 个)"""
        if not self.wiki_root:
            return []
        results = []
        if entity_type == "person":
            person_dir = self.wiki_root / "Entities" / "Persons"
            if person_dir.exists():
                # 文件名格式: person_{name}_{hash}.md
                matches = sorted(person_dir.glob(f"person_{canonical}_*.md"))
                if matches:
                    results.extend(matches[:max_n])
                if len(results) < max_n:
                    # 模糊: 含 name 的文件
                    fuzzy = sorted(person_dir.glob(f"*{canonical}*.md"))
                    for f in fuzzy:
                        if f not in results:
                            results.append(f)
                        if len(results) >= max_n:
                            break
        elif entity_type == "organization":
            org_dir = self.wiki_root / "Entities" / "Organizations"
            if org_dir.exists():
                matches = sorted(org_dir.glob(f"*{canonical}*.md"))
                results.extend(matches[:max_n])
        return results

    def _find_wiki_file_for_entity(self, entity_type: str, canonical: str) -> Optional[Path]:
        """根据实体类型和名称找对应 wiki 文件 (单数, 兼容旧调用)"""
        files = self._find_wiki_files_for_entity(entity_type, canonical, max_n=1)
        return files[0] if files else None

    def _extract_keywords(self, query: str) -> List[str]:
        """从 query 提取搜索关键词 (N-gram 滑动窗口, 去停用词)

        用 2-4 字滑动窗口提取所有子串, 避免连续中文被匹配为无意义长串。
        """
        stopwords = {"的", "了", "是", "在", "我", "与", "和", "及", "或", "上",
                     "下", "中", "有", "无", "为", "对", "到", "从", "被", "把",
                     "给", "向", "于", "以", "由", "此", "其", "之", "者", "也",
                     "都", "还", "又", "再", "就", "只", "才", "便", "然", "但",
                     "各", "在", "现", "现各", "在各", "中的", "的差"}
        # 提取连续中文字符段
        cn_segments = re.findall(r"[\u4e00-\u9fff]+", query)
        keywords = set()
        for seg in cn_segments:
            # 2-4 字滑动窗口
            for n in (2, 3, 4):
                for i in range(len(seg) - n + 1):
                    word = seg[i:i + n]
                    if word not in stopwords and len(word) >= 2:
                        keywords.add(word)
        # 保序去重
        seen = set()
        result = []
        for seg in cn_segments:
            for n in (4, 3, 2):  # 优先长词
                for i in range(len(seg) - n + 1):
                    word = seg[i:i + n]
                    if word in keywords and word not in seen:
                        seen.add(word)
                        result.append(word)
        return result

    def _search_wiki_by_bm25(self, query: str, max_files: int = 5) -> List[Path]:
        """W2-T2.3: BM25 倒排索引检索 (jieba + 标题加权), 异常降级返回空"""
        if not self.wiki_root or not query.strip():
            return []
        try:
            bm = self._get_bm25()
            hits = bm.search(query, top_k=max_files)
            return [p for _, p in hits]
        except Exception:
            return []

    def _get_bm25(self):
        """BM25 索引懒加载 (进程内单例, 构建 ~3.7s)"""
        if self._bm25 is None:
            from kb_bm25 import KB_BM25
            self._bm25 = KB_BM25(self.wiki_root)
        return self._bm25

    def _search_wiki_by_keywords(self, keywords: List[str], max_files: int = 5) -> List[Path]:
        """用关键词搜索 wiki 文件 (meeting/judgment/concept)"""
        if not self.wiki_root or not keywords:
            return []
        results = []
        # 搜索 meeting / judgment / concept / scenario 文件
        search_dirs = [
            self.wiki_root / "Meetings",
            self.wiki_root / "Knowledge" / "Judgments",
            self.wiki_root / "Knowledge" / "Concepts",
            self.wiki_root / "Knowledge" / "Scenarios",
        ]
        scored = []  # (score, path)
        for d in search_dirs:
            if not d.exists():
                continue
            for md_file in d.glob("*.md"):
                try:
                    content = md_file.read_text(encoding="utf-8")
                except Exception:
                    continue
                score = sum(content.count(kw) for kw in keywords)
                if score > 0:
                    scored.append((score, md_file))
        # 按命中次数排序, 取前 N
        scored.sort(key=lambda x: x[0], reverse=True)
        return [p for _, p in scored[:max_files]]

    def _read_wiki_chunk(self, file_path: Path, max_chars: int = 1500) -> str:
        """读取 wiki 文件的关键段落 (frontmatter + body 摘要)"""
        try:
            content = file_path.read_text(encoding="utf-8")
        except Exception:
            return ""
        # 提取文件名作为标题
        title = file_path.stem
        # 截取 frontmatter + body 前 max_chars 字符
        if len(content) > max_chars:
            content = content[:max_chars] + "\n...(内容已截断)"
        return f"=== {title} ===\n{content}"

    def _build_l2_prompt(self, query: str, l1_result: dict, context_text: str) -> str:
        """构造 L2 prompt: 已编译 wiki 内容 + 主理人问题 (T-P6.1 行内编号引用)"""
        parts = [f"# 主理人的问题\n{query}\n"]
        parts.append(f"# 知识库已编译内容 (共 {context_text.count('【资料')} 个编号条目, "
                     "每段开头【资料n|路径】即其编号)\n")
        parts.append(context_text)
        parts.append(
            "\n# 回答要求\n"
            "基于上述已编译知识库内容回答主理人的问题。"
            "每个关键论断后用方括号标注资料编号 (如 [1] 或 [2][3]), 编号取自【资料n】。"
            "引用具体来源 (会议日期 / 人物 / 机构)。"
            "若知识库内容不足以回答, 明确说明。"
        )
        return "\n".join(parts)

    def _is_synthesis_query(self, query: str) -> bool:
        """判断是否为综合类查询 (触发 L2)"""
        return any(kw in query for kw in SYNTHESIS_KEYWORDS)

    def _query_l2_stub(self, query: str, l1_result: dict) -> Dict:
        """无 LLM 时的占位返回 (供 L1 测试用)"""
        matches = l1_result.get("matches", [])
        if matches:
            content = (
                f"[L2 Stub] 查询「{query}」命中 {len(matches)} 个实体:\n"
                + "\n".join(f"  - {m['canonical_name']} ({m['occurrences']} 次出现)"
                            for m in matches)
            )
        else:
            content = f"[L2 Stub] 查询「{query}」未找到匹配。检查 entity_nav L1 提取。"

        return {
            "level": "L2",
            "query": query,
            "matches": matches,
            "synthesis": content,
            "citations": [],
            "context_chunks": 0,
            "fallback_reason": "no LLM injected (stub mode)",
        }


# ============ W2-T2.3 问答回流: Query 页归档 ============

def write_query_page(result: Dict, wiki_root) -> Optional[Path]:
    """把一次 L2 问答结果归档为 wiki/Queries/ 下的 Query 页 (Karpathy Enhance 阶段)

    双闸门防膨胀: 仅当 result 含 suggest_archive (即 citations>=2) 才允许写盘。
    幂等: 同 query 同日重复归档加 (2) 后缀。
    """
    if "suggest_archive" not in result:
        return None  # 闸门未开, 拒绝归档
    wiki_root = Path(wiki_root)
    out_dir = wiki_root / "Queries"
    out_dir.mkdir(parents=True, exist_ok=True)

    from datetime import date as _d
    q = (result.get("query") or "未命名问题").strip()
    topic = re.sub(r'[/\\:*?"<>|\[\]#^？]', "", q)[:20].rstrip("，。？? ") or "未命名"
    today = str(_d.today())

    cite_lines = []
    for c in result.get("citations", []):
        # T-P5.3 修复: 链接目标剥 .md 后缀 (库内 wikilink 约定, 与 lint stems 比对一致)
        target = c[:-3] if c.endswith(".md") else c
        stem = Path(target).stem
        cite_lines.append(f"- [[{target}|{stem}]]")

    lines = [
        "---",
        f"type: query",
        f'question: {json.dumps(q, ensure_ascii=False)}',
        f"query_date: {today}",
        f"citations_count: {len(cite_lines)}",
        f"level: {result.get('level', 'L2')}",
        f"status_stage: compiled",
        f"generator: pj102-llm-meetingkb-v4.0-refactor",
        "---",
        "",
        f"# Q: {q}",
        "",
        f"> [!quote] 提问时间 {today} · 引用 {len(cite_lines)} 条",
        "",
        "## 回答",
        "",
        result.get("synthesis") or "(无回答)",
        "",
        "## 引用来源",
        "",
        *cite_lines,
        "",
    ]
    target = out_dir / f"Query_{today}_{topic}.md"
    n = 2
    while target.exists():
        target = out_dir / f"Query_{today}_{topic}（{n}）.md"
        n += 1
    target.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    return target


# ============ CLI ============

if __name__ == "__main__":
    import argparse

    # 优先用 AppConfig 自动获取路径 (无需手动传 --registry --persons-master)
    try:
        sys.path.insert(0, str(Path(__file__).parent / "core"))
        from config import AppConfig
        cfg = AppConfig()
    except Exception:
        cfg = None

    parser = argparse.ArgumentParser(
        description="PJ-102 知识库查询 (Karpathy LLM Wiki 双层架构)")
    parser.add_argument("--query", required=True, help="查询问题")
    parser.add_argument("--registry", default=None,
                       help="entity_registry.json 路径 (默认用 AppConfig)")
    parser.add_argument("--persons-master", default=None,
                       help="persons_master.json 路径 (默认同目录, 不存在则降级)")
    parser.add_argument("--wiki-root", default=None,
                       help="wiki/ 根目录 (默认用 AppConfig)")
    parser.add_argument("--stub", action="store_true",
                       help="L2 用 stub, 不调 LLM (快速 L1 测试)")
    parser.add_argument("--verbose", "-v", action="store_true",
                       help="显示详细检索过程")
    args = parser.parse_args()

    # 路径优先级: CLI 参数 > AppConfig > 默认
    if cfg:
        registry_path = Path(args.registry) if args.registry else cfg.paths.registry_path
        wiki_root = Path(args.wiki_root) if args.wiki_root else cfg.paths.wiki_base
        # persons_master: 默认同 registry 目录, 不存在则空文件降级
        persons_master_path = (
            Path(args.persons_master) if args.persons_master
            else cfg.paths.system_dir / "registry" / "persons_master.json"
        )
        if not persons_master_path.exists():
            # 优雅降级: 创建空结构, entity_nav._enrich 会返回 occurrences=0
            persons_master_path = cfg.paths.system_dir / "registry" / "persons_master.json"
    else:
        registry_path = Path(args.registry) if args.registry else Path("entity_registry.json")
        persons_master_path = (
            Path(args.persons_master) if args.persons_master
            else Path("persons_master.json")
        )
        wiki_root = Path(args.wiki_root) if args.wiki_root else None

    # LLM 接入: 非 stub 时真实创建 LLMClient
    llm = None
    if not args.stub:
        try:
            from llm_client import LLMClient
            llm = LLMClient()
            if args.verbose:
                print(f"[init] LLM provider={llm.provider}, model={llm.model}", file=sys.stderr)
        except Exception as e:
            print(f"[warn] LLM 初始化失败, 降级 stub: {e}", file=sys.stderr)

    retriever = KBRetriever(
        registry_path=registry_path,
        persons_master_path=persons_master_path,
        llm_client=llm,
        wiki_root=wiki_root,
        cfg=cfg,
    )

    if args.verbose:
        print(f"[init] registry={registry_path}", file=sys.stderr)
        print(f"[init] wiki_root={wiki_root}", file=sys.stderr)
        print(f"[init] query={args.query}", file=sys.stderr)
        print("---", file=sys.stderr)

    result = retriever.query_wiki(args.query)

    print(json.dumps(result, ensure_ascii=False, indent=2))
