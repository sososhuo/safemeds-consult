"""
手工流水线配置模块：集中管理输入、输出和中间产物路径。
"""

from __future__ import annotations

from pathlib import Path


# 1. 把你的 XLSX 文件夹路径填在这里。
#    支持：
#    - 一个总文件夹：脚本会递归查找下面所有 .xlsx 文件
#    - 多个文件夹
#    - 多个具体 .xlsx 文件
#
# 示例：
# XLSX_INPUT_PATHS = [
#     Path("/Users/shuo/Documents/project/药品说明书数据库_医药数据查询"),
# ]
XLSX_INPUT_PATHS = [
    Path("/Users/shuo/Documents/project/药品说明书数据库_医药数据查询"),
]


# 2. 如果所有 XLSX 都在指定 sheet，填写 sheet 名；不填则读取每个文件的第一个 sheet。
SHEET_NAME = None


# 3. 测试时可以填 1000；正式构建保持 None。
MAX_ROWS = None


# 4. 段落最小保留长度。一般不用改。
MIN_SECTION_CHARS = 4


# 5. 向量库是否只保留本次结果。
#    True 会先删除当前 Chroma 目录，再用本次 XLSX 结果重建。
RESET_VECTOR_STORE = True


# 6. 知识图谱是否只保留本次结果。
#    True 会清空当前 Neo4j database，再导入本次 XLSX 结果。
RESET_KNOWLEDGE_GRAPH = True


# 7. 图谱候选关系最低置信度。一般不用改。
MIN_KG_CONFIDENCE = 0.0
