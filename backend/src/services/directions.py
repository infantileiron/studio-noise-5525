"""补正重算的方向核对与安排去向：纯逻辑，不依赖 numpy，便于独立复算与测试。"""


def sign(value):
    """偏相关的方向：正 / 负 / 零；算不出来为 None。"""
    if value is None:
        return None
    return (value > 0) - (value < 0)


def consistent(reference, full, leave_out):
    """全样本与逐个剔除时段的方向是否都和原诊断一致。无参照方向时无法判断。"""
    if reference is None:
        return None
    return all(direction == reference for direction in [full, *leave_out])


def arrangement_action(arrangement, consistent_flag):
    """重算入账后复测安排的去向：rebase 推进依据 / withdraw 撤下待复核 / keep 不动。

    只有生效中的安排才会被重算驱动；已撤下的安排保持撤下，等待人工复核，
    不会被任何重算结果自动恢复。
    """
    if arrangement != 'active':
        return 'keep'
    return 'rebase' if consistent_flag is True else 'withdraw'


def withdraw_note(directions):
    """撤下原因：区分算不出来与方向翻转。"""
    if not directions:
        return '补正后重算失败，无法核对方向，安排已撤下待复核'
    checks = [directions['full'], *[item['direction'] for item in directions['leave_out']]]
    if any(direction is None for direction in checks):
        return '补正后重算无法得到有效方向，安排已撤下待复核'
    return '补正后重算方向与原诊断不一致，安排已撤下待复核'
