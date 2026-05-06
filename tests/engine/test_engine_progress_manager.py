"""测试 ProgressManager 进度管理器"""

import pytest

from app.engine.agents.analysts.dynamic_analyst import ProgressManager


@pytest.fixture(autouse=True)
def clean_progress_manager():
    ProgressManager.clear_callback(task_id=None)
    yield
    ProgressManager.clear_callback(task_id=None)


class TestSetCallback:
    def test_set_and_retrieve(self):
        cb = lambda x: None
        ProgressManager.set_callback("task-1", cb)
        assert ProgressManager.get_callback("task-1") is cb

    def test_set_none_removes(self):
        cb = lambda x: None
        ProgressManager.set_callback("task-1", cb)
        ProgressManager.set_callback("task-1", None)
        assert ProgressManager.get_callback("task-1") is None

    def test_multiple_tasks_isolated(self):
        cb1 = lambda x: "task1"
        cb2 = lambda x: "task2"
        ProgressManager.set_callback("task-1", cb1)
        ProgressManager.set_callback("task-2", cb2)
        assert ProgressManager.get_callback("task-1") is cb1
        assert ProgressManager.get_callback("task-2") is cb2


class TestRemoveCallback:
    def test_removes_specific_task(self):
        cb = lambda x: None
        ProgressManager.set_callback("task-1", cb)
        ProgressManager.set_callback("task-2", cb)
        ProgressManager.remove_callback("task-1")
        assert ProgressManager.get_callback("task-1") is None
        assert ProgressManager.get_callback("task-2") is cb

    def test_removes_current_node(self):
        ProgressManager.set_callback("task-1", lambda x: None)
        ProgressManager.node_start("分析师A", task_id="task-1")
        ProgressManager.remove_callback("task-1")
        assert ProgressManager.get_current_node("task-1") is None


class TestClearCallback:
    def test_clear_specific_task(self):
        cb = lambda x: None
        ProgressManager.set_callback("task-1", cb)
        ProgressManager.node_start("节点A", task_id="task-1")
        ProgressManager.clear_callback(task_id="task-1")
        assert ProgressManager.get_callback("task-1") is None
        assert ProgressManager.get_current_node("task-1") is None

    def test_clear_all_when_none(self):
        ProgressManager.set_callback("task-1", lambda x: None)
        ProgressManager.set_callback("task-2", lambda x: None)
        ProgressManager.clear_callback(task_id=None)
        assert ProgressManager.get_callback("task-1") is None
        assert ProgressManager.get_callback("task-2") is None


class TestNodeStartEnd:
    def test_node_start_updates_current(self):
        ProgressManager.set_callback("task-1", lambda x: None)
        ProgressManager.node_start("市场分析师", task_id="task-1")
        assert ProgressManager.get_current_node("task-1") == "市场分析师"

    def test_callback_is_invoked(self):
        received = []
        def cb(display_name):
            received.append(display_name)

        ProgressManager.set_callback("task-1", cb)
        ProgressManager.node_start("测试节点", task_id="task-1")
        assert received == ["测试节点"]

    def test_no_error_without_callback(self):
        ProgressManager.node_start("测试节点", task_id="no-callback-task")

    def test_callback_exception_does_not_propagate(self):
        def bad_cb(x):
            raise RuntimeError("callback error")

        ProgressManager.set_callback("task-1", bad_cb)
        ProgressManager.node_start("测试节点", task_id="task-1")

    def test_concurrent_tasks_do_not_interfere(self):
        ProgressManager.set_callback("task-1", lambda x: None)
        ProgressManager.set_callback("task-2", lambda x: None)
        ProgressManager.node_start("分析师A", task_id="task-1")
        ProgressManager.node_start("分析师B", task_id="task-2")
        assert ProgressManager.get_current_node("task-1") == "分析师A"
        assert ProgressManager.get_current_node("task-2") == "分析师B"
