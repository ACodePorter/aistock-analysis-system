from app.services.stock_pool_service import _is_meaningful_field


def test_business_summary_requires_detail():
    assert _is_meaningful_field("business_summary", "万方城镇投资发展股份有限公司") is False
    assert _is_meaningful_field("business_summary", "公司主营业务为军工产业、农业产业以及生物制品等，面向下游客户提供相关产品与服务，并通过项目与产品销售形成收入。") is True


def test_history_highlights_requires_timeline_signal():
    assert _is_meaningful_field("history_highlights", "公司发展良好，持续进步") is False
    assert _is_meaningful_field("history_highlights", "1996年上市；2018年完成重大资产重组；2022年投产新生产线") is True

