# XLSX 手动构建流水线

这个目录用于手动把中文药品说明书 XLSX 数据构建成项目可用的向量库和知识图谱。支持单个 XLSX、多个 XLSX，或一个包含多个 XLSX 的文件夹。

## VSCode 推荐操作方式

先打开这个文件：

```text
backend/manual_xlsx_pipeline/pipeline_settings.py
```

把你的 XLSX 总文件夹路径填到这里：

```python
XLSX_INPUT_PATHS = [
    Path("/Users/shuo/Documents/project/药品说明书数据库_医药数据查询"),
]
```

如果你的数据分散在 7 个文件夹，可以这样写：

```python
XLSX_INPUT_PATHS = [
    Path("/路径/第1个文件夹"),
    Path("/路径/第2个文件夹"),
    Path("/路径/第3个文件夹"),
    Path("/路径/第4个文件夹"),
    Path("/路径/第5个文件夹"),
    Path("/路径/第6个文件夹"),
    Path("/路径/第7个文件夹"),
]
```

脚本会递归查找这些文件夹下面所有 `.xlsx` 文件。

正式构建时保持：

```python
MAX_ROWS = None
RESET_VECTOR_STORE = True
RESET_KNOWLEDGE_GRAPH = True
```

如果只是测试前 1000 行，可以临时改成：

```python
MAX_ROWS = 1000
```

配置好以后，在项目根目录运行完整流程：

```bash
cd /Users/shuo/Documents/project/safemeds-consult
backend/.venv/bin/python backend/manual_xlsx_pipeline/04_run_all.py
```

这条命令不需要再手动输入 XLSX 路径，会自动读取 `pipeline_settings.py`。

## 数据处理逻辑

- 跨所有输入文件按 `通用名称` 合并药品记录，所以同一药品即使分散在 10 个 XLSX 中，也会合并为一个药品。
- 暂不按厂家拆分；`批准文号`、来源链接会作为来源信息保留。
- 对每个药品抽取说明书结构化段落：适应症、不良反应、用法用量、禁忌、注意事项、孕妇及哺乳期妇女用药、儿童用药、老人用药、药物相互作用、药理毒理、药代动力学。
- 同一药品同一段落下的完全重复文本会去重；不同版本说明书的不同文本会保留为多个证据版本。
- 短结构段落整体保留；较长段落按条款/句群切分，供向量检索使用。
- 知识图谱候选关系从安全相关段落中抽取，包括药物相互作用、特殊人群、疾病/风险提示等。

## 第 0 步：准备环境

在项目根目录执行：

```bash
cd /Users/shuo/Documents/project/safemeds-consult
python3 -m venv backend/.venv
backend/.venv/bin/pip install -r backend/requirements.txt
```

如果已经装好后端依赖，可以跳过这一步。

确认 `.env` 中至少包含这些配置：

```bash
SAFEMEDS_DATA_PATH=backend/data/processed/instruction_knowledge_from_xlsx.json
DRUG_RESOLUTION_INDEX_PATH=backend/data/processed/drug_resolution_index.json
DRUG_ALIAS_OVERRIDES_PATH=backend/data/raw/drug_alias_overrides.json
VECTOR_BACKEND=chroma
CHROMA_PERSIST_DIR=backend/storage/chroma
NEO4J_URI=bolt://127.0.0.1:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=你的Neo4j密码
NEO4J_DATABASE=neo4j
```

Neo4j 需要先启动，否则第 3 步会连接失败。

## 第 1 步：XLSX 去重合并并抽取

如果已经在 `pipeline_settings.py` 填好了路径，可以直接运行：

```bash
cd /Users/shuo/Documents/project/safemeds-consult
backend/.venv/bin/python backend/manual_xlsx_pipeline/01_deduplicate_extract.py
```

如果你的 10 个 XLSX 都在同一个文件夹里，推荐直接传文件夹路径：

```bash
cd /Users/shuo/Documents/project/safemeds-consult
backend/.venv/bin/python backend/manual_xlsx_pipeline/01_deduplicate_extract.py \
  "/你的/xlsx文件夹路径"
```

脚本会自动读取该文件夹下所有 `.xlsx` 文件，并跳过 Excel 临时文件 `~$xxx.xlsx`。

如果你想明确指定 10 个文件，也可以把路径逐个写在命令后面：

```bash
cd /Users/shuo/Documents/project/safemeds-consult
backend/.venv/bin/python backend/manual_xlsx_pipeline/01_deduplicate_extract.py \
  "/路径/第1个.xlsx" \
  "/路径/第2个.xlsx" \
  "/路径/第3个.xlsx" \
  "/路径/第4个.xlsx" \
  "/路径/第5个.xlsx" \
  "/路径/第6个.xlsx" \
  "/路径/第7个.xlsx" \
  "/路径/第8个.xlsx" \
  "/路径/第9个.xlsx" \
  "/路径/第10个.xlsx"
```

输出文件：

- `backend/data/processed/instruction_knowledge_from_xlsx.json`：给 RAG/向量库使用的药品知识记录。
- `backend/data/processed/instruction_kg_candidates.jsonl`：给 Neo4j 使用的候选关系。
- `backend/data/processed/drug_resolution_index.json`：精确药名、剂型主体名和人工别名的解析索引。
- `backend/data/processed/instruction_build_report.json`：构建统计报告。

人工审核别名维护在 `backend/data/raw/drug_alias_overrides.json`。每条别名允许映射到多个完整药名；目标药名不存在时会被记录到解析索引的 `rejected_alias_overrides`，不会进入运行时匹配。

只修改人工别名、且知识 JSON 未变化时，可以单独重建药名解析索引，无需重建向量库：

```bash
cd /Users/shuo/Documents/project/safemeds-consult
backend/.venv/bin/python backend/scripts/build_drug_resolution_index.py
```

小规模试跑可以加：

```bash
--max-rows 1000
```

## 第 2 步：重建向量库

如果 `pipeline_settings.py` 里 `RESET_VECTOR_STORE = True`，可以直接运行：

```bash
cd /Users/shuo/Documents/project/safemeds-consult
backend/.venv/bin/python backend/manual_xlsx_pipeline/02_build_vector_store.py
```

输出报告：

- `backend/data/processed/vector_build_report.json`

注意：`--reset` 会删除 `CHROMA_PERSIST_DIR` 指向的 Chroma 本地目录，然后用第 1 步生成的 JSON 重新写入。

## 第 3 步：重建知识图谱

如果 `pipeline_settings.py` 里 `RESET_KNOWLEDGE_GRAPH = True`，可以直接运行：

```bash
cd /Users/shuo/Documents/project/safemeds-consult
backend/.venv/bin/python backend/manual_xlsx_pipeline/03_build_knowledge_graph.py
```

输出报告：

- `backend/data/processed/kg_import_report.json`

注意：`--reset` 会执行 `MATCH (n) DETACH DELETE n`，删除当前 Neo4j database 里的所有节点和关系，再导入本次结果。

## 一条命令跑完整流程

如果已经在 `pipeline_settings.py` 填好了路径，直接运行：

```bash
cd /Users/shuo/Documents/project/safemeds-consult
backend/.venv/bin/python backend/manual_xlsx_pipeline/04_run_all.py
```

传文件夹路径：

```bash
cd /Users/shuo/Documents/project/safemeds-consult
backend/.venv/bin/python backend/manual_xlsx_pipeline/04_run_all.py \
  "/你的/xlsx文件夹路径" \
  --reset-vector \
  --reset-kg
```

或者逐个传 10 个文件：

```bash
cd /Users/shuo/Documents/project/safemeds-consult
backend/.venv/bin/python backend/manual_xlsx_pipeline/04_run_all.py \
  "/路径/第1个.xlsx" \
  "/路径/第2个.xlsx" \
  "/路径/第3个.xlsx" \
  "/路径/第4个.xlsx" \
  "/路径/第5个.xlsx" \
  "/路径/第6个.xlsx" \
  "/路径/第7个.xlsx" \
  "/路径/第8个.xlsx" \
  "/路径/第9个.xlsx" \
  "/路径/第10个.xlsx" \
  --reset-vector \
  --reset-kg
```

## 构建后启动后端验证

```bash
cd /Users/shuo/Documents/project/safemeds-consult/backend
./.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

再访问：

```bash
curl http://127.0.0.1:8000/api/health
```

重点看：

- `indexed_documents` 是否等于本次向量库 chunk 数。
- `kg_status` 是否为 `ok`。
- `kg_relations` 是否为本次导入的图谱关系数。

## 常见问题

- 如果同一个药因为规格不同重复：这是预期输入状态，第 1 步会按 `通用名称` 合并。
- 如果同一个药分散在多个 XLSX 文件：也是预期输入状态，第 1 步会跨文件按 `通用名称` 合并。
- 如果暂不考虑厂家：不要按厂家拆分，当前脚本正是这个策略。
- 如果相互作用为 0：表示图谱中没有抽到两个具体药品之间的直接关系，不代表没有禁忌、特殊人群或疾病风险；这些风险仍会进入向量证据和非直接图谱关系。
- 如果更换 embedding 模型：修改 `.env` 的 `EMBEDDING_MODEL_NAME` 后，重新执行第 2 步并加 `--reset`。
