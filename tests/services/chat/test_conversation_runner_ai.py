"""run_chat_turn 真实 LLM 调用（-m ai；需已配置模型）。

单轮「000001 的因子怎么样」：验证工具装配（query_stock_factors 被执行）
与最终回答非空。未配置模型时 skip。
"""
import pytest

pytestmark = [pytest.mark.ai, pytest.mark.requires_db]

from app.data.storage.mongo.repositories.chat_repo import ChatRepo
from app.services.chat.conversation_runner import run_chat_turn


async def test_run_chat_turn_single_question_with_tools(real_mongo_db):
    """单轮真实调用：模型选股数据工具被执行、final_text 非空、run_meta 完整。"""
    from app.llm.providers import get_engine_clients

    if (await get_engine_clients()).get("analyst") is None:
        pytest.skip("未配置可用 LLM 模型（设置页配置后重跑）")

    repo = ChatRepo()
    session = await repo.create_session("chat_ai_user")
    settings = {"model": "", "prompt": "", "enable_mcp": False}
    # prompt 为空串时 run_chat_turn 传 None → run_conversation 用客户端默认；测试用内置默认更贴近线上
    from app.services.chat.prompts import DEFAULT_CHAT_SYSTEM_PROMPT
    settings["prompt"] = DEFAULT_CHAT_SYSTEM_PROMPT

    result = await _run_or_skip_on_bad_credentials(
        session["session_id"], "000001 的因子怎么样？", "run_ai_test", settings,
    )

    text = result["text"]
    assert isinstance(text, str)
    assert text.strip(), "模型未返回内容"
    meta = result["run_meta"]
    assert meta["run_id"] == "run_ai_test"
    assert meta["turns"] >= 1
    assert meta["tool_calls_executed"] >= 1, "期望模型至少调用一次选股数据工具"
    assert meta["total_tokens"] > 0

    # 第二轮：会话已有上轮 user/assistant 消息 → history 带上文再回答
    await repo.insert_message(session["session_id"], "chat_ai_user", "user", "000001 的因子怎么样？")
    await repo.insert_message(session["session_id"], "chat_ai_user", "assistant", text)
    follow_up = await _run_or_skip_on_bad_credentials(
        session["session_id"], "它的估值水平如何？", "run_ai_test_2", settings,
    )
    assert follow_up["text"].strip()
    assert follow_up["run_meta"]["turns"] >= 1


async def _run_or_skip_on_bad_credentials(session_id: str, content: str, run_id: str, settings: dict):
    """执行一轮；凭据失效/配额类环境错误转 skip（真实调用尝试后的环境降级）。"""
    from app.llm.core.errors import AuthError

    try:
        return await run_chat_turn(session_id, "chat_ai_user", content, run_id, None, settings)
    except AuthError as e:
        pytest.skip(f"模型凭据失效，跳过真实调用: {e}")
