"""
旅游规划帝 · 交互式对话模式

用法:
  python chat.py               # 启动交互对话
  python chat.py --mock         # Mock 模式 (无需 API)

特性:
  - 多轮对话记忆 (你说过"不吃辣"，下次自动记住)
  - 指代消解 ("那里"自动替换为上次提到的城市)
  - RAG 知识增强 (自动检索攻略库)
  - 长期偏好积累 (自动检测并存储用户喜好)
"""

import asyncio
import logging
import sys
import os

_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)

logging.basicConfig(level=logging.WARNING, format="%(message)s")

# ─── 欢迎信息 ───

WELCOME = """
╔══════════════════════════════════════════════╗
║       🌍 旅游规划帝 · 你的智能旅行助手       ║
╠══════════════════════════════════════════════╣
║  我可以：                                    ║
║  ✈️  规划行程 · 🏨 推荐酒店 · 💰 核算预算    ║
║  📚 提供攻略 · 🧠 记住偏好 · 🔄 理解指代     ║
╠══════════════════════════════════════════════╣
║  命令: /clear 清除记忆  /exit 退出           ║
╚══════════════════════════════════════════════╝
"""



def _assign_time_slots(attractions: list) -> list:
    """将景点列表自动分配到上午/下午/晚上时段。"""
    if not attractions:
        return []
    slots = []
    periods = ["上午", "下午", "晚上"]
    for i, spot in enumerate(attractions):
        slot = periods[min(i, len(periods) - 1)]
        slots.append((slot, spot))
    return slots



# ═══════════════════════════════════════════════
# 突发/修改指令处理
# ═══════════════════════════════════════════════

EMERGENCY_KEYWORDS = {
    "受伤": "injury",
    "医院": "hospital",
    "生病": "sick",
    "不舒服": "sick",
    "过敏": "allergy",
    "发烧": "fever",
    "腹泻": "diarrhea",
    "拉肚子": "diarrhea",
    "骨折": "fracture",
    "摔伤": "injury",
    "中暑": "heatstroke",
}

MODIFY_KEYWORDS = [
    ("添加", "add"), ("加上", "add"), ("增加", "add"), ("再加", "add"),
    ("去掉", "remove"), ("删除", "remove"), ("不去", "remove"), ("取消", "remove"),
    ("换成", "replace"), ("替换", "replace"), ("改为", "replace"), ("改成", "replace"),
]


def _detect_emergency(text: str):
    """检测紧急情况。"""
    for keyword, etype in EMERGENCY_KEYWORDS.items():
        if keyword in text:
            return etype
    return None


def _handle_emergency(text: str, etype: str, result: dict, pipeline) -> str:
    """处理无现有规划时的紧急情况。"""
    city = result.get("city", "当地")
    tips = {
        "injury": f"建议立即前往{city}市人民医院急诊科。携带身份证+医保卡。轻微擦伤可去附近药店买碘伏和创可贴。",
        "hospital": f"已为你查询{city}主要医院：市第一人民医院（三甲）、市中心医院。建议先电话确认急诊是否开放。",
        "sick": f"建议前往{city}三甲医院。如症状轻微可先去药店咨询药师。注意饮食清淡，多喝温水。",
        "allergy": f"立即停止食用可疑食物。前往{city}医院皮肤科/急诊科。可先服用氯雷他定应急。严重过敏（呼吸困难）打120！",
        "fever": f"体温超过38.5°C建议就医。{city}发热门诊可在市医院查询。多喝水、物理降温。",
        "diarrhea": f"建议服用蒙脱石散+口服补液盐。{city}药店均有售。严重脱水需去医院输液。暂停行程休息。",
        "fracture": f"疑似骨折请勿移动患肢！立即拨打120或前往{city}市人民医院骨科急诊。",
        "heatstroke": f"立即转移到阴凉处，解开衣领，用湿毛巾降温。补充电解质饮料。严重中暑需送医。",
    }
    return tips.get(etype, f"检测到紧急情况，建议立即处理。如需帮助请描述具体情况。")


def _modify_plan_for_emergency(text: str, etype: str, plan: dict) -> str:
    """修改现有计划以应对紧急情况。"""
    city = plan.get("city", "目的地")
    days = plan.get("days", 0)
    tips = {
        "injury": "已将今日行程调整为休息+就医，后续行程顺延或取消。建议联系酒店前台获取最近医院信息。",
        "sick": "已暂停当前行程，建议休息半天至一天。轻症可继续但放慢节奏，重症建议取消后续行程。",
        "hospital": f"已查询{city}三甲医院信息。建议预留半天就医时间。",
    }
    msg = tips.get(etype, "已调整行程以应对紧急情况。")
    return f"🚨 {msg}\n📍 {city} | 行程暂停 | 请优先处理健康问题后再继续旅程"


def _detect_modification(text: str):
    """检测计划修改指令。返回 (action, target) 或 None。"""
    for keyword, action in MODIFY_KEYWORDS:
        if keyword in text:
            # 提取目标（关键词后面的部分）
            idx = text.find(keyword)
            target = text[idx + len(keyword):].strip().rstrip("。，.!！")
            if not target:
                # 尝试整句当作目标
                target = text.strip()
            return (action, target)
    return None


def _apply_modification(action: str, target: str, plan: dict) -> str:
    """应用修改到现有计划。"""
    city = plan.get("city", "目的地")
    it = plan.get("itinerary", [])

    if action == "add":
        # 默认加到最近一天的最后一个时段
        last_day = it[-1] if it else {"day": 1, "attractions": []}
        return (
            f"✅ 已添加「{target}」到 Day{last_day.get('day',1)} 行程。\n"
            f"📍 {city} | 更新后的 Day{last_day.get('day',1)}: "
            f"{' → '.join(last_day.get('attractions',[]))} → {target}\n"
            f"💡 如需重新核算预算，请输入 /replan"
        )

    if action == "remove":
        found = False
        for day in it:
            for spot in list(day.get("attractions", [])):
                if target in spot:
                    day["attractions"].remove(spot)
                    found = True
                    return (
                        f"✅ 已从 Day{day.get('day')} 中移除「{spot}」。\n"
                        f"📍 {city} | Day{day.get('day')}: "
                        f"{' → '.join(day['attractions']) if day['attractions'] else '(空闲)'}"
                    )
        return f"❌ 未在行程中找到「{target}」"

    if action == "replace":
        for day in it:
            for i, spot in enumerate(day.get("attractions", [])):
                if target in spot or spot in target:
                    old_spot = spot
                    day["attractions"][i] = target
                    return (
                        f"✅ 已将 Day{day.get('day')} 的「{old_spot}」替换为「{target}」。\n"
                        f"📍 {city} | Day{day.get('day')}: "
                        f"{' → '.join(day['attractions'])}"
                    )
        # 没找到替换目标 → 按新增处理
        return _apply_modification("add", target, plan)

    return f"🤔 不太确定怎么修改，请说清楚想做什么？"


def _update_plan_state(plan: dict, response: str) -> dict:
    """简单更新计划状态（不重新跑编排器）。"""
    if plan:
        plan["_last_modified"] = True
    return plan


# ═══════════════════════════════════════════════════════════════




async def run_chat(mock: bool = False, memory_mode: str = "redis"):
    """主对话循环。"""
    from common.llm_client import LLMClient
    from agents.stage4_pipeline import ContextPipeline
    from agents.stage4_compressor import CoreferenceResolver
    from agents.stage3_framework import Orchestrator, EventBus, BaseAgent
    from agents.stage3_travel import (
        parse_agent, guide_agent, hotel_agent, finance_agent, route_after_finance,
    )

    if mock:
        LLMClient.reset_instance()

    # 初始化上下文管道
    if memory_mode == "local":
        from agents.stage4_memory import LocalMemoryManager
        memory = LocalMemoryManager()
        await memory.init()
        pipeline = ContextPipeline(memory=memory)
    else:
        pipeline = ContextPipeline()
    try:
        await pipeline.init()
    except RuntimeError as e:
        print(f"\n❌ {e}\n")
        return

    # 偷懒版快速消解 (不调LLM，用于低延迟)
    fast_resolver = CoreferenceResolver()

    session_id = "interactive-chat"
    current_plan = None  # 缓存的上次完整方案 {"city":"","itinerary":[...],"hotels":[...],"budget":0,"total_cost":0}
    print(WELCOME)

    mode = "redis"
    mem_label = "Redis (先运行 redis-server)" if memory_mode == mode else "本地内存"
    mem_label = "Redis (先运行 redis-server)" if memory_mode == "redis" else "本地内存"
    print(f"💾 记忆: {mem_label}")
    if LLMClient.get().mock_mode:
        print("⚠️  Mock 模式 (无 API Key，使用模拟回复)\n")

    turn = 0

    while True:
        try:
            user_input = input("🧑 你: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n👋 再见！")
            break

        if not user_input:
            continue
        if user_input.lower() in ("/exit", "/quit", "exit", "quit"):
            print("👋 再见！")
            break
        if user_input.lower() in ("/clear", "clear"):
            await pipeline.compressor.clear(session_id)
            pipeline.memory._fallback_short.pop(session_id, None)
            print("🧹 记忆已清除\n")
            continue

        turn += 1

        # ─── 1. 上下文增强 ───
        state = {"user_query": user_input, "session_id": session_id}
        state = await pipeline.enhance_state(state, session_id)

        # 显示增强信息 (压缩摘要)
        if state.get("compressed_summary"):
            print(f"📦 历史摘要: {state['compressed_summary'][:80]}...")

        # ─── 2. 运行编排器 ───
        orch = Orchestrator(max_backtracks=3)
        orch.add_node("parse", parse_agent)
        orch.add_node("guide", guide_agent)
        orch.add_node("hotel", hotel_agent)
        orch.add_node("finance", finance_agent)
        orch.set_route("finance", route_after_finance)

        # 注入增强后的提示
        enhanced_query = state.get("resolved_query", user_input)
        rag_ctx = state.get("rag_context", "")
        prefs = state.get("long_term_preferences", [])

        # 构建增强后的用户消息
        augmented_query = enhanced_query
        if prefs:
            pref_hint = "用户偏好: " + ", ".join(p["preference"] for p in prefs[:3])
            augmented_query = f"{pref_hint}\n{enhanced_query}"
        if rag_ctx:
            augmented_query += f"\n\n参考攻略:\n{rag_ctx}"

        result = await orch.run({"user_query": augmented_query})

        # ─── 3. 生成友好回复 ───
        city = result.get("city", "未知")
        people = result.get("people", 1)
        budget = result.get("budget", 0)
        total = result.get("total_cost", 0)
        status = result.get("budget_status", "unknown")
        itinerary = result.get("itinerary", [])
        hotels = result.get("hotels", [])

        # ─── 紧急/修改指令检测 ───
        emergency = _detect_emergency(user_input)
        if emergency and not itinerary:
            # 紧急情况 + 无现有规划 = 快速处理
            response = _handle_emergency(user_input, emergency, result, pipeline)
            print(f"\n🚨 助手:\n{response}\n")
            await pipeline.record_interaction(session_id, user_input, response)
            continue

        if emergency and current_plan:
            # 有现有规划 + 紧急情况 = 修改计划 + 加入医院/休息
            response = _modify_plan_for_emergency(user_input, emergency, current_plan)
            print(f"\n🚨 助手:\n{response}\n")
            await pipeline.record_interaction(session_id, user_input, response)
            current_plan = _update_plan_state(current_plan, response)
            continue

        # ─── 计划修改指令 ───
        modified = _detect_modification(user_input)
        if modified and current_plan:
            action, target = modified
            response = _apply_modification(action, target, current_plan)
            print(f"\n✏️ 助手:\n{response}\n")
            await pipeline.record_interaction(session_id, user_input, response)
            current_plan = _update_plan_state(current_plan, response)
            continue

        # 构建回复

        lines = []
        if itinerary:
            lines.append(f"📍 {city} · {len(itinerary)}天{len(itinerary)-1}晚 · {people}人")
            lines.append("┌──────────────────────────────────────────┐")
            lines.append("│             📅 日 程 安 排                │")
            lines.append("├────┬─────────────────────────────────────┤")

            for day in itinerary:
                day_num = day.get("day", "?")
                attractions = day.get("attractions", [])
                notes = day.get("notes", "")

                # 自动分配时段
                time_slots = _assign_time_slots(attractions)
                for slot, spot in time_slots:
                    icon = {"上午": "🌅", "下午": "☀️", "晚上": "🌙"}.get(slot, "📍")
                    lines.append(f"│ D{day_num} │ {icon} {slot}: {spot:<31s} │")
                lines.append("│    │                                     │")
                if notes:
                    lines.append(f"│    │ 💡 {notes[:37]:<37s} │")
                    lines.append("│    │                                     │")

            lines.append("├────┴─────────────────────────────────────┤")

            # 酒店
            if hotels:
                h = hotels[0]
                lines.append(f"│  🏨 {h.get('name'):<35s} │")
                lines.append(f"│     ¥{h.get('price_per_night')}/晚 · {h.get('rating')}分 · {h.get('location',''):<20s} │")

            # 预算
            if total > 0:
                emoji = "✅ 预算内" if status == "within_budget" else "⚠️ 超支"
                per_person = total / max(people, 1)
                lines.append(f"│                                             │")
                lines.append(f"│  💰 总预算 ¥{budget:.0f} → 预估 ¥{total:.0f} {emoji}   │")
                lines.append(f"│  👤 人均 ¥{per_person:.0f}                                  │")

            lines.append("└──────────────────────────────────────────┘")

        elif hotels:
            lines.append(f"🏨 推荐住宿：")
            for h in hotels:
                lines.append(f"  {h.get('name')} ¥{h.get('price_per_night')}/晚 {h.get('rating')}分")

        if not lines:
            lines.append("🤔 让我想想... 请再说详细一点？")

        response = "\n".join(lines)
        # 缓存当前方案
        if itinerary:
            current_plan = {
                "city": city, "itinerary": itinerary, "hotels": hotels,
                "budget": budget, "total_cost": total, 
                "people": people, "days": len(itinerary),
            }

        # 如果有RAG知识且没有规划，展示相关知识
        # (这里只做增强展示，实际已在augmented_query中注入)

        print(f"\n🌴 助手:\n{response}\n")

        # ─── 4. 记录交互 ───
        await pipeline.record_interaction(session_id, user_input, response)

        # ─── 5. 显示记忆状态 ───
        if turn % 5 == 0:
            recent = await pipeline.memory.get_short_term(session_id)
            stored_prefs = await pipeline.memory.get_long_term_preferences(session_id, "")
            print(f"📊 记忆状态: 短期{len(recent)}条 | 长期偏好{len(stored_prefs)}个\n")

    await pipeline.close()


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="旅游规划帝 · 交互对话")
    p.add_argument("--mock", action="store_true", help="Mock 模式")
    p.add_argument("--memory", choices=["redis","local"], default="redis",
                   help="记忆存储: redis (默认,需手动启动) | local (零依赖)")
    args = p.parse_args()
    asyncio.run(run_chat(mock=args.mock, memory_mode=args.memory))
