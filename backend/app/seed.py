from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Document


SAMPLES = [
    ("演示：校园一卡通补办", "演示流程：如校园一卡通遗失，请先在学校官方服务平台挂失，再携带有效身份证件到一卡通服务窗口核验并申请补办。具体窗口地点、费用和办理时间以所在学校最新公告为准。"),
    ("演示：图书借阅与续借", "演示流程：读者可登录图书馆官方系统查看借阅记录并申请续借。存在预约、逾期或达到续借次数上限时可能无法续借。借期和罚则以所在学校图书馆公告为准。"),
    ("演示：宿舍报修", "演示流程：描述故障、具体地点和联系方式后提交报修申请。紧急用电或漏水问题应立即联系学校后勤值班电话。当前系统只保存演示工单，不会派送给学校后勤。"),
]


def seed_demo_documents(db: Session):
    from .config import get_settings

    if not get_settings().database_url.startswith("sqlite"):
        return
    if db.scalar(select(Document.id).limit(1)) is not None:
        return
    for i, (title, content) in enumerate(SAMPLES, 1):
        db.add(Document(id=f"demo-{i}", title=title, content=content))
    db.commit()
