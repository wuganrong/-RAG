# 全文检索字段（仅使用已索引字段，content_with_weight 不可用于检索）
TEXT_SEARCH_FIELDS = [
    "title_tks^10",
    "title_sm_tks^5",
    "important_kwd^30",
    "important_tks^20",
    "question_tks^20",
    "content_ltks^2",
    "content_sm_ltks",
]

# 切片返回字段
CHUNK_SELECT_FIELDS = [
    "id",
    "doc_id",
    "docnm_kwd",
    "content_with_weight",
    "important_kwd",
    "question_kwd",
    "img_id",
    "available_int",
    "position_int",
    "parent_group_id",
    "chunk_order",
    "chunk_title_kwd",
    "create_user_name",
    "create_time",
    "create_timestamp_flt",
    "tag_kwd",
]

# 切片返回字段（含 kb_id，检索场景使用）
CHUNK_SELECT_FIELDS_WITH_KB = [
    "id", "doc_id", "docnm_kwd", "content_with_weight",
    "important_kwd", "question_kwd", "img_id", "available_int",
    "position_int", "parent_group_id", "chunk_order", "kb_id",
    "chunk_title_kwd", "create_time", "create_timestamp_flt", "tag_kwd",
]
