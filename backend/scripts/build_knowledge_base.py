"""
构建扩展版中文药物知识库
========================
数据来源:
  1. 内置结构化数据 —— 临床高频药物的说明书关键章节（中文）
  2. DDInter 风格的结构化交互对 —— 基于公开文献整理的药物相互作用
  3. 已有 demo 知识库 —— 合并去重

输出: backend/data/processed/drug_knowledge_zh.json

运行: python -m scripts.build_knowledge_base
"""

import json
from pathlib import Path
from typing import Any, Dict, List

OUT_PATH = Path(__file__).resolve().parents[1] / "data" / "processed" / "drug_knowledge_zh.json"
EXISTING_PATH = OUT_PATH  # 合并已有数据


# ─── 内置结构化药物数据（临床高频 Top 药物） ─────────────────────────

BUILTIN_DRUGS: List[Dict[str, Any]] = [
    # ── 心血管系统 ──────────────────────────────────────────
    {
        "drug": "aspirin",
        "aliases": ["阿司匹林", "拜阿司匹灵", "acetylsalicylic acid"],
        "source": "国家药品监督管理局公开说明书摘要",
        "sections": [
            {"title": "药物相互作用", "content": "阿司匹林与华法林、肝素等抗凝药合用可显著增加出血风险。与布洛芬等 NSAIDs 合用可能降低阿司匹林的心血管保护作用并增加胃肠道出血风险。与甲氨蝶呤合用可减少甲氨蝶呤的肾清除率，增加毒性。与 ACEI/ARB 类降压药合用可能减弱降压效果。"},
            {"title": "禁忌", "content": "活动性消化道溃疡或出血患者禁用。对阿司匹林或其他水杨酸盐过敏者禁用。严重肝肾功能不全患者禁用。妊娠晚期禁用。血友病或血小板减少症患者禁用。"},
            {"title": "警告与注意事项", "content": "长期使用应监测消化道症状和出血倾向。老年患者出血风险增高。手术前 7 天应考虑停药。哮喘患者可能诱发支气管痉挛。与酒精合用增加胃肠道出血风险。"}
        ],
        "interactions": [
            {"with": "warfarin", "risk_level": "High", "mechanism": "阿司匹林抑制血小板聚集叠加华法林抗凝作用，出血风险显著增加。", "recommendation": "避免无医嘱合用；如需合用应密切监测 INR 及出血症状。"},
            {"with": "ibuprofen", "risk_level": "High", "mechanism": "布洛芬竞争性抑制 COX-1 位点，可降低阿司匹林的抗血小板活性，同时增加胃肠道出血风险。", "recommendation": "尽量避免合用；如需镇痛建议选择对乙酰氨基酚。"},
            {"with": "clopidogrel", "risk_level": "Medium", "mechanism": "双联抗血小板治疗可增加出血风险，但在急性冠脉综合征中为标准方案。", "recommendation": "仅在有明确适应症时合用，监测出血表现。"},
            {"with": "methotrexate", "risk_level": "High", "mechanism": "阿司匹林可减少甲氨蝶呤的肾排泄，导致血药浓度升高和严重毒性。", "recommendation": "低剂量甲氨蝶呤时谨慎合用；高剂量甲氨蝶呤时禁止合用。"}
        ]
    },
    {
        "drug": "clopidogrel",
        "aliases": ["氯吡格雷", "波立维", "泰嘉", "plavix"],
        "source": "国家药品监督管理局公开说明书摘要",
        "sections": [
            {"title": "药物相互作用", "content": "氯吡格雷为前药，需经 CYP2C19 代谢活化。奥美拉唑、艾司奥美拉唑等质子泵抑制剂可抑制 CYP2C19，降低氯吡格雷的抗血小板活性。与华法林、阿司匹林等抗凝/抗血小板药合用可增加出血风险。与 NSAIDs 合用增加胃肠道出血风险。"},
            {"title": "禁忌", "content": "活动性病理性出血患者禁用。对氯吡格雷或其成分过敏者禁用。严重肝功能损害患者禁用。"},
            {"title": "警告与注意事项", "content": "CYP2C19 慢代谢者（占中国人群约 14-20%）对氯吡格雷反应降低，血栓事件风险增加。手术前 5-7 天应考虑停药。"}
        ],
        "interactions": [
            {"with": "omeprazole", "risk_level": "High", "mechanism": "奥美拉唑强效抑制 CYP2C19，显著降低氯吡格雷活性代谢物浓度，减弱抗血小板效果。", "recommendation": "避免合用奥美拉唑/艾司奥美拉唑，可选用泮托拉唑作为替代 PPI。"},
            {"with": "aspirin", "risk_level": "Medium", "mechanism": "双联抗血小板增加出血风险。", "recommendation": "ACS/PCI 后标准治疗，但需监测出血。"},
            {"with": "warfarin", "risk_level": "High", "mechanism": "三联抗栓治疗出血风险极高。", "recommendation": "尽量缩短三联治疗时间，密切监测 INR 和出血。"}
        ]
    },
    {
        "drug": "atorvastatin",
        "aliases": ["阿托伐他汀", "立普妥", "lipitor"],
        "source": "国家药品监督管理局公开说明书摘要",
        "sections": [
            {"title": "药物相互作用", "content": "阿托伐他汀主要经 CYP3A4 代谢。与强 CYP3A4 抑制剂（伊曲康唑、酮康唑、克拉霉素、HIV 蛋白酶抑制剂）合用可显著升高血药浓度，增加肌病和横纹肌溶解风险。环孢素、贝特类降脂药、烟酸（大剂量）合用也可增加肌病风险。葡萄柚汁大量摄入可升高阿托伐他汀血药浓度。"},
            {"title": "禁忌", "content": "活动性肝病或不明原因转氨酶持续升高者禁用。妊娠及哺乳期禁用。对本品过敏者禁用。"},
            {"title": "警告与注意事项", "content": "用药期间应监测肝功能。出现不明原因肌痛、肌无力或深色尿时应立即就医排查横纹肌溶解。糖尿病风险可能轻度增加。"}
        ],
        "interactions": [
            {"with": "clarithromycin", "risk_level": "High", "mechanism": "克拉霉素强效抑制 CYP3A4，可使阿托伐他汀暴露量升高数倍，显著增加肌病/横纹肌溶解风险。", "recommendation": "合用期间阿托伐他汀日剂量不应超过 20mg，或改用不经 CYP3A4 代谢的瑞舒伐他汀。"},
            {"with": "gemfibrozil", "risk_level": "High", "mechanism": "吉非贝齐抑制他汀的葡萄糖醛酸化和 OATP1B1 转运，大幅升高他汀暴露，肌病风险增加。", "recommendation": "避免合用；如需联合降脂可选非诺贝特（风险较低）。"},
            {"with": "cyclosporine", "risk_level": "High", "mechanism": "环孢素抑制 CYP3A4 和 OATP1B1，可使阿托伐他汀 AUC 升高约 8 倍。", "recommendation": "合用时阿托伐他汀日剂量不应超过 10mg。"}
        ]
    },
    {
        "drug": "amlodipine",
        "aliases": ["氨氯地平", "络活喜", "norvasc"],
        "source": "国家药品监督管理局公开说明书摘要",
        "sections": [
            {"title": "药物相互作用", "content": "氨氯地平经 CYP3A4 代谢，与强 CYP3A4 抑制剂（酮康唑、伊曲康唑、克拉霉素）合用可升高血药浓度。与辛伐他汀合用时，辛伐他汀日剂量不应超过 20mg。与环孢素合用可升高环孢素血药浓度。"},
            {"title": "警告与注意事项", "content": "严重主动脉狭窄患者慎用。肝功能不全患者起始剂量应降低。可能出现踝部水肿、头痛、面部潮红。"}
        ],
        "interactions": [
            {"with": "simvastatin", "risk_level": "Medium", "mechanism": "氨氯地平轻度抑制 CYP3A4，可升高辛伐他汀暴露约 1.8 倍，增加肌病风险。", "recommendation": "合用时辛伐他汀日剂量不超过 20mg；或换用阿托伐他汀/瑞舒伐他汀。"},
            {"with": "cyclosporine", "risk_level": "Medium", "mechanism": "氨氯地平可升高环孢素血药浓度，增加肾毒性风险。", "recommendation": "合用时监测环孢素血药浓度和肾功能。"}
        ]
    },
    # ── 降压药 ──────────────────────────────────────────────
    {
        "drug": "enalapril",
        "aliases": ["依那普利", "悦宁定", "vasotec"],
        "source": "国家药品监督管理局公开说明书摘要",
        "sections": [
            {"title": "药物相互作用", "content": "与保钾利尿剂（螺内酯、氨苯蝶啶）或钾补充剂合用可致高钾血症。与 NSAIDs 合用可减弱降压效果并增加肾功能恶化风险。与锂剂合用可升高锂血药浓度。双重 RAS 阻断（ACEI + ARB 或直接肾素抑制剂）增加低血压、高钾血症和肾功能恶化风险。"},
            {"title": "禁忌", "content": "血管性水肿病史者禁用。双侧肾动脉狭窄患者禁用。妊娠期禁用（致畸）。与阿利吉仑（直接肾素抑制剂）在糖尿病患者中禁止合用。"},
            {"title": "警告与注意事项", "content": "首剂低血压风险，尤其是容量不足、高剂量利尿剂使用者。监测血钾和肾功能。"}
        ],
        "interactions": [
            {"with": "spironolactone", "risk_level": "High", "mechanism": "ACEI 减少醛固酮分泌，叠加螺内酯的保钾作用，可致严重高钾血症。", "recommendation": "合用时必须密切监测血钾，避免同时补钾。"},
            {"with": "ibuprofen", "risk_level": "Medium", "mechanism": "NSAIDs 抑制前列腺素合成，减弱 ACEI 降压效果，并可能加重肾功能损害。", "recommendation": "尽量避免长期合用；短期使用时监测血压和肾功能。"},
            {"with": "lithium", "risk_level": "High", "mechanism": "ACEI 减少锂的肾排泄，可致锂中毒。", "recommendation": "合用时必须频繁监测锂血药浓度。"}
        ]
    },
    {
        "drug": "losartan",
        "aliases": ["氯沙坦", "科素亚", "cozaar"],
        "source": "国家药品监督管理局公开说明书摘要",
        "sections": [
            {"title": "药物相互作用", "content": "氯沙坦经 CYP2C9 代谢为活性代谢物 E-3174。氟康唑等 CYP2C9 抑制剂可降低其活性代谢物浓度。与保钾利尿剂或钾补充剂合用有高钾血症风险。与 NSAIDs 合用可减弱降压效果。与锂剂合用可升高锂浓度。"},
            {"title": "禁忌", "content": "妊娠期禁用。与阿利吉仑在糖尿病或中重度肾功能不全患者中禁止合用。"},
            {"title": "警告与注意事项", "content": "肝功能不全患者应考虑减量。双侧肾动脉狭窄患者慎用。"}
        ],
        "interactions": [
            {"with": "fluconazole", "risk_level": "Medium", "mechanism": "氟康唑抑制 CYP2C9，可降低氯沙坦向活性代谢物的转化，降低降压效果。", "recommendation": "合用时监测血压，必要时调整剂量或换用其他 ARB。"},
            {"with": "spironolactone", "risk_level": "High", "mechanism": "ARB 与保钾利尿剂合用可致严重高钾血症。", "recommendation": "合用时密切监测血钾。"},
            {"with": "lithium", "risk_level": "High", "mechanism": "ARB 可减少锂的肾排泄。", "recommendation": "合用时监测锂血药浓度。"}
        ]
    },
    {
        "drug": "metoprolol",
        "aliases": ["美托洛尔", "倍他乐克", "lopressor", "betaloc"],
        "source": "国家药品监督管理局公开说明书摘要",
        "sections": [
            {"title": "药物相互作用", "content": "美托洛尔经 CYP2D6 代谢。帕罗西汀、氟西汀、奎尼丁等 CYP2D6 抑制剂可显著升高美托洛尔血药浓度，增加心动过缓和低血压风险。与维拉帕米、地尔硫䓬等非二氢吡啶类钙通道阻滞剂合用可致严重心动过缓、房室传导阻滞和心力衰竭。与胺碘酮合用也有类似风险。可掩盖低血糖的心动过速表现。"},
            {"title": "禁忌", "content": "严重心动过缓（心率 < 45 次/分）、二度以上房室传导阻滞、失代偿心力衰竭、心源性休克患者禁用。嗜铬细胞瘤未经 α 受体阻滞剂治疗者禁用。"},
            {"title": "警告与注意事项", "content": "不应突然停药，需逐渐减量。支气管哮喘患者慎用。手术麻醉前应告知麻醉医生正在使用β受体阻滞剂。"}
        ],
        "interactions": [
            {"with": "paroxetine", "risk_level": "High", "mechanism": "帕罗西汀强效抑制 CYP2D6，可使美托洛尔 AUC 升高 4-6 倍，导致严重心动过缓和低血压。", "recommendation": "避免合用，或大幅减少美托洛尔剂量并密切监测心率和血压。"},
            {"with": "verapamil", "risk_level": "High", "mechanism": "β受体阻滞剂与非二氢吡啶类钙通道阻滞剂均抑制心脏传导和收缩力，可致严重心动过缓、房室传导阻滞。", "recommendation": "原则上避免口服合用；静脉维拉帕米绝对禁止与β受体阻滞剂同时使用。"},
            {"with": "insulin", "risk_level": "Medium", "mechanism": "β受体阻滞剂可掩盖低血糖的心悸、震颤等警示症状，延迟低血糖的发现和处理。", "recommendation": "糖尿病患者使用时应加强血糖监测，告知患者注意出汗等非被掩盖的低血糖症状。"}
        ]
    },
    # ── 消化系统 ──────────────────────────────────────────
    {
        "drug": "omeprazole",
        "aliases": ["奥美拉唑", "洛赛克", "prilosec"],
        "source": "国家药品监督管理局公开说明书摘要",
        "sections": [
            {"title": "药物相互作用", "content": "奥美拉唑抑制 CYP2C19，可降低氯吡格雷活性代谢物浓度，减弱其抗血小板作用。可影响需要胃酸环境吸收的药物（如酮康唑、伊曲康唑、阿扎那韦），降低其生物利用度。长期使用可降低镁吸收，与地高辛或利尿剂合用时低镁血症风险增加。可升高甲氨蝶呤血药浓度。"},
            {"title": "警告与注意事项", "content": "长期使用（> 1 年）可能增加骨折风险、低镁血症、维生素 B12 缺乏和艰难梭菌感染风险。应使用最低有效剂量和最短疗程。"}
        ],
        "interactions": [
            {"with": "clopidogrel", "risk_level": "High", "mechanism": "奥美拉唑抑制 CYP2C19，显著降低氯吡格雷活性代谢物的生成。", "recommendation": "避免合用，改用泮托拉唑或 H2 受体拮抗剂。"},
            {"with": "methotrexate", "risk_level": "High", "mechanism": "PPI 可抑制甲氨蝶呤的肾小管分泌，延长其消除半衰期。", "recommendation": "高剂量甲氨蝶呤期间应暂停 PPI。"},
            {"with": "ketoconazole", "risk_level": "Medium", "mechanism": "PPI 升高胃内 pH，降低酮康唑溶解和吸收。", "recommendation": "避免合用或在酸性饮料中服用酮康唑。"}
        ]
    },
    # ── 抗感染药 ──────────────────────────────────────────
    {
        "drug": "amoxicillin",
        "aliases": ["阿莫西林", "amoxil", "阿莫仙"],
        "source": "国家药品监督管理局公开说明书摘要",
        "sections": [
            {"title": "药物相互作用", "content": "阿莫西林与甲氨蝶呤合用可减少甲氨蝶呤肾排泄，增加毒性。可增强华法林的抗凝作用（机制不明确，可能与肠道菌群改变有关）。与别嘌醇合用可增加皮疹发生率。丙磺舒可延长阿莫西林的半衰期。"},
            {"title": "禁忌", "content": "对青霉素类抗生素过敏者禁用。传染性单核细胞增多症患者禁用（高皮疹风险）。"},
            {"title": "警告与注意事项", "content": "用药前应详细询问过敏史。长期使用可导致菌群失调和二重感染。肾功能不全患者应调整剂量。"}
        ],
        "interactions": [
            {"with": "methotrexate", "risk_level": "High", "mechanism": "阿莫西林可减少甲氨蝶呤的肾小管分泌，升高其血药浓度。", "recommendation": "合用时密切监测甲氨蝶呤浓度和毒性。"},
            {"with": "warfarin", "risk_level": "Medium", "mechanism": "抗生素可能通过改变肠道菌群维生素 K 合成而增强华法林抗凝作用。", "recommendation": "合用时加强 INR 监测。"}
        ]
    },
    {
        "drug": "levofloxacin",
        "aliases": ["左氧氟沙星", "可乐必妥", "levaquin", "左克"],
        "source": "国家药品监督管理局公开说明书摘要",
        "sections": [
            {"title": "药物相互作用", "content": "左氧氟沙星与含铝、镁的抗酸药或含铁、锌的补充剂同服可形成螯合物，降低吸收。与茶碱合用可升高茶碱血药浓度。与华法林合用可增强抗凝作用。与 NSAIDs 合用可增加中枢神经系统刺激和癫痫风险。与降糖药合用可能导致严重的血糖紊乱。"},
            {"title": "禁忌", "content": "对喹诺酮类药物过敏者禁用。有肌腱疾病/断裂史者禁用。重症肌无力患者禁用。18 岁以下患者原则上禁用（可能影响软骨发育）。"},
            {"title": "警告与注意事项", "content": "可能导致肌腱炎和肌腱断裂（老年人、合用糖皮质激素者风险更高）。可致 QT 间期延长。可能导致周围神经病变。日光暴晒可致光敏反应。"}
        ],
        "interactions": [
            {"with": "warfarin", "risk_level": "Medium", "mechanism": "喹诺酮类可增强华法林抗凝作用，增加出血风险。", "recommendation": "合用时密切监测 INR。"},
            {"with": "insulin", "risk_level": "High", "mechanism": "喹诺酮类可干扰胰岛素分泌和葡萄糖代谢，导致严重低血糖或高血糖。", "recommendation": "糖尿病患者使用时应加强血糖监测，必要时调整降糖药剂量。"},
            {"with": "theophylline", "risk_level": "Medium", "mechanism": "喹诺酮类可抑制茶碱代谢，升高其血药浓度。", "recommendation": "合用时监测茶碱浓度，必要时减量。"}
        ]
    },
    # ── 精神/神经系统 ──────────────────────────────────────
    {
        "drug": "paroxetine",
        "aliases": ["帕罗西汀", "赛乐特", "paxil"],
        "source": "国家药品监督管理局公开说明书摘要",
        "sections": [
            {"title": "药物相互作用", "content": "帕罗西汀是强 CYP2D6 抑制剂，可显著升高经 CYP2D6 代谢的药物浓度（如美托洛尔、氟卡尼、阿托西汀、三环类抗抑郁药）。与单胺氧化酶抑制剂（MAOIs）合用禁忌——可致 5-HT 综合征。与其他 5-HT 能药物（曲普坦类、曲马多、芬太尼、圣约翰草）合用有 5-HT 综合征风险。与华法林合用可增加出血风险。与他莫昔芬合用可降低其活性代谢物浓度。"},
            {"title": "禁忌", "content": "与 MAOIs 合用或停用 MAOIs 未满 14 天者禁用。与硫利达嗪或匹莫齐特合用禁忌。"},
            {"title": "警告与注意事项", "content": "可增加 25 岁以下人群自杀倾向风险。突然停药可致撤药综合征（头晕、感觉异常、焦虑、恶心），应逐渐减量。可致低钠血症（尤其老年人）。"}
        ],
        "interactions": [
            {"with": "metoprolol", "risk_level": "High", "mechanism": "帕罗西汀强效抑制 CYP2D6，可使美托洛尔暴露量增加 4-6 倍。", "recommendation": "避免合用，或选用不经 CYP2D6 代谢的 SSRI（如舍曲林）。"},
            {"with": "tamoxifen", "risk_level": "High", "mechanism": "帕罗西汀抑制 CYP2D6，阻止他莫昔芬转化为活性代谢物 endoxifen，降低抗癌疗效。", "recommendation": "禁止合用，应换用其他 SSRI（如文拉法辛低剂量、西酞普兰）。"},
            {"with": "tramadol", "risk_level": "High", "mechanism": "曲马多有 5-HT 再摄取抑制作用，与帕罗西汀合用可致 5-HT 综合征。同时帕罗西汀抑制 CYP2D6 降低曲马多的镇痛代谢物生成。", "recommendation": "避免合用，选择其他镇痛方案。"}
        ]
    },
    {
        "drug": "carbamazepine",
        "aliases": ["卡马西平", "得理多", "tegretol"],
        "source": "国家药品监督管理局公开说明书摘要",
        "sections": [
            {"title": "药物相互作用", "content": "卡马西平是强效 CYP3A4 诱导剂，可加速多种药物的代谢从而降低其疗效，包括口服避孕药、华法林、环孢素、伊曲康唑、他汀类、HIV 蛋白酶抑制剂等。CYP3A4 抑制剂（红霉素、克拉霉素、酮康唑、葡萄柚汁）可升高卡马西平浓度致中毒。与丙戊酸合用可相互影响代谢。"},
            {"title": "禁忌", "content": "骨髓抑制病史者禁用。对三环类抗抑郁药过敏者禁用。与 MAOIs 合用禁忌。急性间歇性卟啉症禁用。HLA-B*1502 阳性者（Han Chinese 人群中比例约 6-8%）有 Stevens-Johnson 综合征/中毒性表皮坏死松解症风险，应在用药前检测。"},
            {"title": "警告与注意事项", "content": "可致严重皮肤反应（SJS/TEN），中国人群用药前应做 HLA-B*1502 基因检测。可致再生障碍性贫血和粒细胞缺乏症，应定期监测血象。可致低钠血症。治疗窗窄，需监测血药浓度。"}
        ],
        "interactions": [
            {"with": "clarithromycin", "risk_level": "High", "mechanism": "克拉霉素抑制 CYP3A4，可使卡马西平血药浓度升高致中毒（头晕、复视、共济失调）。", "recommendation": "避免合用，选用不抑制 CYP3A4 的抗生素（如阿奇霉素）。"},
            {"with": "oral_contraceptives", "risk_level": "High", "mechanism": "卡马西平诱导 CYP3A4 加速雌孕激素代谢，可致避孕失败。", "recommendation": "应使用非激素避孕方法或含高剂量雌激素的方案。"},
            {"with": "warfarin", "risk_level": "High", "mechanism": "卡马西平诱导华法林代谢，可显著降低其抗凝效果。", "recommendation": "合用时应频繁监测 INR 并调整华法林剂量。"}
        ]
    },
    # ── 内分泌/代谢 ────────────────────────────────────────
    {
        "drug": "insulin",
        "aliases": ["胰岛素", "诺和灵", "优泌林", "lantus", "甘精胰岛素", "门冬胰岛素"],
        "source": "国家药品监督管理局公开说明书摘要",
        "sections": [
            {"title": "药物相互作用", "content": "β受体阻滞剂可掩盖低血糖症状。糖皮质激素、噻嗪类利尿剂可升高血糖对抗胰岛素作用。喹诺酮类抗生素可致严重的血糖紊乱。ACEI/ARB 可能增强胰岛素降糖作用。酒精可增强和延长胰岛素的低血糖效应。"},
            {"title": "警告与注意事项", "content": "低血糖是最常见和最严重的不良反应。剂量调整、饮食变化、运动、合并用药等均可影响血糖控制。不同品牌/类型的胰岛素不可随意互换。"}
        ],
        "interactions": [
            {"with": "metoprolol", "risk_level": "Medium", "mechanism": "β受体阻滞剂掩盖低血糖的心悸、震颤等警示症状。", "recommendation": "加强血糖自我监测。"},
            {"with": "prednisone", "risk_level": "Medium", "mechanism": "糖皮质激素升高血糖，对抗胰岛素降糖作用。", "recommendation": "合用时需增加胰岛素剂量，停用糖皮质激素后需及时减量避免低血糖。"},
            {"with": "levofloxacin", "risk_level": "High", "mechanism": "喹诺酮类可致严重低血糖或高血糖。", "recommendation": "糖尿病患者使用喹诺酮类时加强血糖监测。"}
        ]
    },
    {
        "drug": "prednisone",
        "aliases": ["泼尼松", "强的松", "deltasone"],
        "source": "国家药品监督管理局公开说明书摘要",
        "sections": [
            {"title": "药物相互作用", "content": "糖皮质激素可对抗降糖药的作用（升高血糖）。与 NSAIDs 合用增加消化道溃疡和出血风险。与华法林合用对凝血的影响不可预测。CYP3A4 诱导剂（利福平、苯妥英、卡马西平）可加速糖皮质激素代谢降低疗效。与喹诺酮类合用增加肌腱断裂风险。与利尿剂合用可加重低钾血症。"},
            {"title": "警告与注意事项", "content": "长期使用可致骨质疏松、库欣综合征、感染风险增加、高血糖、精神症状、消化道溃疡。不应突然停药，需逐渐减量。"}
        ],
        "interactions": [
            {"with": "insulin", "risk_level": "Medium", "mechanism": "糖皮质激素升高血糖，需增加胰岛素剂量。", "recommendation": "密切监测血糖，调整胰岛素剂量。"},
            {"with": "ibuprofen", "risk_level": "High", "mechanism": "糖皮质激素与 NSAIDs 均损伤胃肠道黏膜，合用显著增加消化道溃疡和出血风险。", "recommendation": "合用时应加用胃黏膜保护剂或 PPI。"},
            {"with": "levofloxacin", "risk_level": "High", "mechanism": "糖皮质激素与喹诺酮类合用显著增加肌腱炎和肌腱断裂风险。", "recommendation": "老年患者尤其应避免合用。"}
        ]
    },
    {
        "drug": "levothyroxine",
        "aliases": ["左甲状腺素", "优甲乐", "雷替斯", "synthroid"],
        "source": "国家药品监督管理局公开说明书摘要",
        "sections": [
            {"title": "药物相互作用", "content": "含钙、铁、铝、镁的制剂可与左甲状腺素结合降低吸收，应间隔 4 小时服用。消胆胺、考来替泊可降低其吸收。PPI、H2RA 可影响其在胃内的溶解。华法林合用时可增强抗凝作用。服用期间开始或停用雌激素可能需调整剂量。"},
            {"title": "警告与注意事项", "content": "应空腹服用（早餐前 30-60 分钟）。冠心病患者起始剂量应低。甲状腺功能亢进可诱发心律失常。应定期监测 TSH 调整剂量。"}
        ],
        "interactions": [
            {"with": "calcium_carbonate", "risk_level": "Medium", "mechanism": "钙剂与左甲状腺素在胃内结合，降低其吸收。", "recommendation": "两药至少间隔 4 小时服用。"},
            {"with": "warfarin", "risk_level": "Medium", "mechanism": "甲状腺激素可增加凝血因子代谢，增强华法林抗凝作用。", "recommendation": "开始或调整甲状腺激素剂量时应监测 INR。"},
            {"with": "omeprazole", "risk_level": "Low", "mechanism": "PPI 可能影响左甲状腺素在胃内溶解，略降低吸收。", "recommendation": "长期合用时监测 TSH，必要时增加左甲状腺素剂量。"}
        ]
    },
    # ── 镇痛药 ──────────────────────────────────────────
    {
        "drug": "tramadol",
        "aliases": ["曲马多", "奇曼丁", "ultram"],
        "source": "国家药品监督管理局公开说明书摘要",
        "sections": [
            {"title": "药物相互作用", "content": "曲马多有弱阿片活性和 5-HT 再摄取抑制作用。与 SSRIs、SNRIs、三环类抗抑郁药、MAOIs 合用可致 5-HT 综合征。经 CYP2D6 代谢为活性代谢物 M1，CYP2D6 抑制剂（帕罗西汀、氟西汀）可降低其镇痛效果。与苯二氮卓类或其他中枢抑制剂合用可致呼吸抑制。可降低癫痫发作阈值，与其他降低发作阈值的药物合用风险更高。"},
            {"title": "禁忌", "content": "与 MAOIs 合用或停用 MAOIs 未满 14 天者禁忌。急性酒精、安眠药、镇痛药或精神药物中毒者禁用。癫痫控制不佳者禁用。"},
            {"title": "警告与注意事项", "content": "有成瘾潜力。长期使用后突然停药可致撤药症状。可致癫痫发作。不应超过推荐最大日剂量 400mg。"}
        ],
        "interactions": [
            {"with": "paroxetine", "risk_level": "High", "mechanism": "5-HT 综合征风险加上帕罗西汀抑制 CYP2D6 降低曲马多活性代谢物。", "recommendation": "避免合用。"},
            {"with": "carbamazepine", "risk_level": "Medium", "mechanism": "卡马西平诱导 CYP3A4 可加速曲马多代谢，降低镇痛效果。", "recommendation": "可能需增加曲马多剂量或换用其他镇痛药。"}
        ]
    },
    # ── 抗凝 / 抗栓 ──────────────────────────────────────
    {
        "drug": "rivaroxaban",
        "aliases": ["利伐沙班", "拜瑞妥", "xarelto"],
        "source": "国家药品监督管理局公开说明书摘要",
        "sections": [
            {"title": "药物相互作用", "content": "利伐沙班经 CYP3A4 和 P-gp 代谢/转运。强 CYP3A4 和 P-gp 双重抑制剂（酮康唑、伊曲康唑、HIV 蛋白酶抑制剂）可显著升高利伐沙班暴露，增加出血风险。强 CYP3A4 诱导剂（利福平、卡马西平、苯妥英）可降低利伐沙班浓度影响疗效。与抗血小板药、其他抗凝药或 NSAIDs 合用增加出血风险。"},
            {"title": "禁忌", "content": "活动性临床相关出血禁用。具有重大出血风险的肝病患者禁用。妊娠和哺乳期禁用。"},
            {"title": "警告与注意事项", "content": "不可在房颤患者中于无替代抗凝的情况下突然停药（血栓风险反弹）。需根据肾功能调整剂量。脊椎/硬膜外麻醉时有硬膜外血肿风险。"}
        ],
        "interactions": [
            {"with": "ketoconazole", "risk_level": "High", "mechanism": "酮康唑双重抑制 CYP3A4 和 P-gp，可使利伐沙班 AUC 升高约 2.6 倍。", "recommendation": "避免合用。"},
            {"with": "carbamazepine", "risk_level": "High", "mechanism": "卡马西平强效诱导 CYP3A4，可显著降低利伐沙班浓度，导致抗凝不足。", "recommendation": "避免合用，或换用不受酶诱导影响的抗凝药。"},
            {"with": "aspirin", "risk_level": "High", "mechanism": "抗凝药与抗血小板药合用显著增加出血风险。", "recommendation": "仅在有明确适应症时合用，使用最短疗程和最低有效剂量。"}
        ]
    },
    # ── 其他高频 ──────────────────────────────────────────
    {
        "drug": "spironolactone",
        "aliases": ["螺内酯", "安体舒通", "aldactone"],
        "source": "国家药品监督管理局公开说明书摘要",
        "sections": [
            {"title": "药物相互作用", "content": "与 ACEI/ARB 合用可致高钾血症。与钾补充剂合用有严重高钾血症风险。与 NSAIDs 合用可减弱利尿和降压效果并增加高钾血症风险。与地高辛合用可升高地高辛血药浓度。与锂剂合用可升高锂浓度。"},
            {"title": "禁忌", "content": "高钾血症患者禁用。严重肾功能不全（eGFR < 30 mL/min）禁用。Addison 病禁用。与依普利酮合用禁忌。"},
            {"title": "警告与注意事项", "content": "应定期监测血钾和肾功能。可致男性乳房发育、女性月经不规则。老年患者高钾血症风险更高。"}
        ],
        "interactions": [
            {"with": "enalapril", "risk_level": "High", "mechanism": "ACEI + 保钾利尿剂双重保钾可致危及生命的高钾血症。", "recommendation": "合用时密切监测血钾，避免同时补钾。"},
            {"with": "losartan", "risk_level": "High", "mechanism": "ARB + 保钾利尿剂同样有严重高钾血症风险。", "recommendation": "合用时密切监测血钾。"},
            {"with": "digoxin", "risk_level": "Medium", "mechanism": "螺内酯可竞争性抑制地高辛的肾小管分泌，升高地高辛浓度。", "recommendation": "合用时监测地高辛浓度。"}
        ]
    },
    {
        "drug": "digoxin",
        "aliases": ["地高辛", "狄戈辛", "lanoxin"],
        "source": "国家药品监督管理局公开说明书摘要",
        "sections": [
            {"title": "药物相互作用", "content": "地高辛治疗窗极窄。胺碘酮、维拉帕米、奎尼丁、螺内酯等可升高地高辛浓度。低钾血症（利尿剂引起）可增加地高辛中毒风险。克拉霉素、红霉素可抑制 P-gp 转运升高地高辛浓度。抗酸药和考来烯胺可降低地高辛吸收。"},
            {"title": "禁忌", "content": "室性心动过速、室颤禁用。梗阻性肥厚型心肌病禁用。"},
            {"title": "警告与注意事项", "content": "治疗窗极窄，中毒症状包括恶心、呕吐、视觉异常（黄视）、心律失常。低钾、低镁、高钙可增加中毒敏感性。需监测血药浓度，目标 0.5-0.9 ng/mL。肾功能不全需减量。"}
        ],
        "interactions": [
            {"with": "amiodarone", "risk_level": "High", "mechanism": "胺碘酮抑制 P-gp 转运，可使地高辛浓度升高约 70-100%。", "recommendation": "合用时地高辛剂量应减半，密切监测血药浓度。"},
            {"with": "clarithromycin", "risk_level": "High", "mechanism": "克拉霉素抑制 P-gp 和可能减少肠道细菌对地高辛的灭活，可显著升高地高辛浓度。", "recommendation": "合用时监测地高辛浓度，选用阿奇霉素作为替代（不影响 P-gp）。"},
            {"with": "spironolactone", "risk_level": "Medium", "mechanism": "螺内酯竞争地高辛的肾小管分泌。", "recommendation": "监测地高辛浓度。"},
            {"with": "hydrochlorothiazide", "risk_level": "High", "mechanism": "噻嗪类利尿剂致低钾血症，增加地高辛中毒敏感性。", "recommendation": "合用时维持血钾在正常范围，必要时补钾。"}
        ]
    },
    {
        "drug": "phenytoin",
        "aliases": ["苯妥英", "苯妥英钠", "大仑丁", "dilantin"],
        "source": "国家药品监督管理局公开说明书摘要",
        "sections": [
            {"title": "药物相互作用", "content": "苯妥英是 CYP3A4 和 CYP2C 诱导剂，可加速华法林、口服避孕药、环孢素、地塞米松等代谢。苯妥英自身经 CYP2C9 和 CYP2C19 代谢，其抑制剂（氟康唑、奥美拉唑、异烟肼）可升高苯妥英浓度致中毒。苯妥英呈非线性药动学，剂量微调即可能导致浓度大幅波动。"},
            {"title": "禁忌", "content": "对乙内酰脲类过敏者禁用。与地拉韦啶合用禁忌。窦性心动过缓、房室传导阻滞者禁用静脉苯妥英。"},
            {"title": "警告与注意事项", "content": "治疗窗窄，必须监测血药浓度。可致严重皮肤反应（SJS/TEN）。长期使用可致骨密度降低和叶酸缺乏。Asian 人群 HLA-B*1502 阳性者 SJS 风险增高。"}
        ],
        "interactions": [
            {"with": "fluconazole", "risk_level": "High", "mechanism": "氟康唑抑制 CYP2C9，可使苯妥英浓度升高致中毒（眩晕、眼震、共济失调）。", "recommendation": "合用时密切监测苯妥英浓度并减量。"},
            {"with": "warfarin", "risk_level": "High", "mechanism": "苯妥英诱导华法林代谢，降低抗凝效果；但初期可能短暂增强抗凝。", "recommendation": "合用时频繁监测 INR 和苯妥英浓度。"},
            {"with": "oral_contraceptives", "risk_level": "High", "mechanism": "苯妥英诱导酶加速雌孕激素代谢，导致避孕失败。", "recommendation": "应使用非激素避孕方法。"}
        ]
    },
]

# ─── 中药 / 中成药与西药相互作用数据（第三步） ───────────────────────

TCM_DRUGS: List[Dict[str, Any]] = [
    {
        "drug": "danshen",
        "aliases": ["丹参", "丹参注射液", "复方丹参片", "复方丹参滴丸"],
        "source": "基于临床文献与药品说明书整理的中西药相互作用",
        "sections": [
            {"title": "药物相互作用", "content": "丹参及其制剂含丹参酮等成分，具有活血化瘀、抑制血小板聚集、抗凝等作用。与华法林合用可显著增强抗凝作用，增加出血风险。与阿司匹林、氯吡格雷等抗血小板药合用出血风险叠加。与地高辛合用可能影响地高辛血药浓度。丹参酮可影响 CYP 酶活性。"},
            {"title": "警告与注意事项", "content": "出血倾向、近期手术、消化道溃疡患者慎用。与抗凝/抗血小板药合用前应咨询医生。月经量多的女性慎用。"}
        ],
        "interactions": [
            {"with": "warfarin", "risk_level": "High", "mechanism": "丹参抑制血小板聚集并可能抑制华法林代谢，多例临床报告显示 INR 异常升高及出血事件。", "recommendation": "避免与华法林合用，或密切监测 INR；出现瘀斑、牙龈出血等应立即就医。"},
            {"with": "aspirin", "risk_level": "High", "mechanism": "丹参的活血作用叠加阿司匹林的抗血小板作用，出血风险显著增加。", "recommendation": "避免同时使用，有心血管适应症者应在医生指导下用药。"},
            {"with": "digoxin", "risk_level": "Medium", "mechanism": "丹参可能影响地高辛的蛋白结合和肾排泄，改变其血药浓度。", "recommendation": "合用时监测地高辛浓度。"}
        ]
    },
    {
        "drug": "ginkgo_biloba",
        "aliases": ["银杏叶", "银杏叶提取物", "金纳多", "银杏叶片", "银杏达莫"],
        "source": "基于临床文献与药品说明书整理的中西药相互作用",
        "sections": [
            {"title": "药物相互作用", "content": "银杏叶提取物含银杏内酯、黄酮等成分，具有抑制血小板活化因子（PAF）的作用。与抗凝药（华法林）、抗血小板药（阿司匹林、氯吡格雷）合用可增加出血风险。可能影响 CYP3A4、CYP2C9 酶活性。与抗癫痫药（苯妥英、卡马西平、丙戊酸）合用可能降低其血药浓度，增加发作风险。与 SSRIs 合用有增加出血和 5-HT 综合征的报告。"},
            {"title": "警告与注意事项", "content": "手术前 2 周应停用。有出血倾向者慎用。癫痫患者使用可能降低发作阈值。与降糖药合用可能影响血糖。"}
        ],
        "interactions": [
            {"with": "warfarin", "risk_level": "High", "mechanism": "银杏叶抑制 PAF 并可能影响凝血因子，有多例出血事件报告（颅内出血、眼前房出血等）。", "recommendation": "避免与华法林合用；正在服用华法林者不应自行加用银杏制剂。"},
            {"with": "aspirin", "risk_level": "High", "mechanism": "银杏叶与阿司匹林均抑制血小板功能，出血风险叠加。", "recommendation": "避免合用。"},
            {"with": "phenytoin", "risk_level": "Medium", "mechanism": "银杏叶可能诱导苯妥英代谢，降低其血药浓度。", "recommendation": "合用时监测苯妥英浓度。"},
            {"with": "ibuprofen", "risk_level": "Medium", "mechanism": "银杏叶的抗血小板作用叠加 NSAIDs 的血小板抑制和胃肠道损伤。", "recommendation": "合用时注意出血征象。"}
        ]
    },
    {
        "drug": "huangqi",
        "aliases": ["黄芪", "黄芪注射液", "黄芪颗粒", "astragalus"],
        "source": "基于临床文献与药品说明书整理的中西药相互作用",
        "sections": [
            {"title": "药物相互作用", "content": "黄芪具有免疫调节作用，可增强免疫功能。与免疫抑制剂（环孢素、他克莫司、糖皮质激素）合用时可能对抗其免疫抑制作用，影响疗效。黄芪具有利尿作用，与利尿剂合用可能增强利尿效果。可能影响降糖药的效果（黄芪有一定降糖作用）。"},
            {"title": "警告与注意事项", "content": "自身免疫性疾病活动期慎用（可能加重免疫反应）。器官移植患者在服用免疫抑制剂期间不宜使用。感冒初期表证未解时中医传统认为不宜使用。"}
        ],
        "interactions": [
            {"with": "cyclosporine", "risk_level": "High", "mechanism": "黄芪增强免疫功能，可能拮抗环孢素的免疫抑制作用，增加器官排斥风险。", "recommendation": "器官移植患者禁止合用。"},
            {"with": "insulin", "risk_level": "Low", "mechanism": "黄芪有一定降血糖作用，可能增强胰岛素降糖效果。", "recommendation": "合用时注意血糖监测，必要时调整胰岛素剂量。"}
        ]
    },
    {
        "drug": "gancao",
        "aliases": ["甘草", "甘草片", "复方甘草片", "甘草酸", "glycyrrhiza", "licorice"],
        "source": "基于临床文献与药品说明书整理的中西药相互作用",
        "sections": [
            {"title": "药物相互作用", "content": "甘草酸在体内水解为甘草次酸，抑制 11β-羟基类固醇脱氢酶，产生假性醛固酮增多症样作用（水钠潴留、排钾）。与利尿剂（尤其噻嗪类、袢利尿剂）合用加重低钾血症。低钾状态下地高辛中毒风险增加。与糖皮质激素合用可加重水钠潴留和低钾。与降压药合用可对抗降压效果。与螺内酯合用可拮抗其保钾作用。甘草可影响 CYP3A4 活性。"},
            {"title": "警告与注意事项", "content": "大剂量或长期使用可致低钾血症、高血压、水肿。高血压、心力衰竭、肾病患者慎用。不宜与大量含甘草的食品同时使用。低钾血症可致心律失常。"}
        ],
        "interactions": [
            {"with": "digoxin", "risk_level": "High", "mechanism": "甘草致低钾血症，低钾状态显著增加地高辛中毒敏感性，可致致死性心律失常。", "recommendation": "避免合用；必须合用时密切监测血钾和地高辛浓度。"},
            {"with": "hydrochlorothiazide", "risk_level": "High", "mechanism": "甘草和噻嗪类利尿剂均可致低钾血症，合用风险叠加。", "recommendation": "避免合用或密切监测血钾并补钾。"},
            {"with": "spironolactone", "risk_level": "Medium", "mechanism": "甘草的盐皮质激素样作用可拮抗螺内酯的保钾和降压效果。", "recommendation": "服用螺内酯者应避免大量摄入甘草制品。"},
            {"with": "enalapril", "risk_level": "Medium", "mechanism": "甘草导致水钠潴留和血压升高，对抗 ACEI 降压作用。", "recommendation": "高血压患者应避免长期或大量使用甘草制品。"},
            {"with": "prednisone", "risk_level": "Medium", "mechanism": "甘草抑制糖皮质激素的灭活酶，可增强泼尼松效应并加重低钾。", "recommendation": "合用时注意库欣样症状和低钾。"}
        ]
    },
    {
        "drug": "gegen",
        "aliases": ["葛根", "葛根素", "葛根素注射液", "puerarin"],
        "source": "基于临床文献与药品说明书整理的中西药相互作用",
        "sections": [
            {"title": "药物相互作用", "content": "葛根素具有扩张冠脉和脑血管、降低血管阻力的作用。与降压药合用可增强降压效果，有低血压风险。与美托洛尔等β受体阻滞剂合用可致心动过缓和低血压加重。与硝酸甘油等硝酸酯类合用可增强血管扩张作用。葛根素有抑制血小板聚集的作用，与抗凝/抗血小板药合用增加出血风险。"},
            {"title": "警告与注意事项", "content": "低血压患者慎用。葛根素注射液有过敏反应报告，包括溶血反应，首次使用应注意观察。"}
        ],
        "interactions": [
            {"with": "metoprolol", "risk_level": "Medium", "mechanism": "葛根素的降压和减慢心率作用可叠加β受体阻滞剂效应。", "recommendation": "合用时监测心率和血压。"},
            {"with": "nitroglycerin", "risk_level": "Medium", "mechanism": "葛根素与硝酸甘油均扩张血管，合用可致过度低血压。", "recommendation": "合用时注意低血压症状。"},
            {"with": "warfarin", "risk_level": "Medium", "mechanism": "葛根素有抗血小板作用，可能增加华法林治疗时的出血风险。", "recommendation": "合用时监测 INR 和出血表现。"}
        ]
    },
    {
        "drug": "sanqi",
        "aliases": ["三七", "三七粉", "田七", "血塞通", "panax notoginseng"],
        "source": "基于临床文献与药品说明书整理的中西药相互作用",
        "sections": [
            {"title": "药物相互作用", "content": "三七含三七总皂苷，具有活血化瘀、抑制血小板聚集、抗血栓作用。与华法林、阿司匹林、氯吡格雷等抗凝/抗血小板药合用可显著增加出血风险。三七总皂苷可能影响 CYP 酶活性，影响合用药物代谢。与降压药合用可增强降压效果。"},
            {"title": "警告与注意事项", "content": "月经量多或有出血倾向者慎用。手术前 2 周应停用。孕妇禁用（可能致流产）。与抗凝药合用前应告知医生。"}
        ],
        "interactions": [
            {"with": "warfarin", "risk_level": "High", "mechanism": "三七抗血小板和抗凝作用叠加华法林抗凝效应，出血风险显著增加。", "recommendation": "避免合用；正在服用华法林者不应自行使用三七制品。"},
            {"with": "aspirin", "risk_level": "High", "mechanism": "三七与阿司匹林均抑制血小板功能，出血风险叠加。", "recommendation": "避免合用，有心血管适应症者应咨询医生。"},
            {"with": "clopidogrel", "risk_level": "High", "mechanism": "双重抗血小板作用叠加三七的活血效果，出血风险极高。", "recommendation": "避免合用。"}
        ]
    },
    {
        "drug": "mahuang",
        "aliases": ["麻黄", "麻黄碱", "ephedra", "含麻黄碱制剂"],
        "source": "基于临床文献与药品说明书整理的中西药相互作用",
        "sections": [
            {"title": "药物相互作用", "content": "麻黄碱为拟交感胺类，可兴奋 α 和 β 肾上腺素受体。与单胺氧化酶抑制剂（MAOIs）合用可致高血压危象。与降压药合用可对抗降压效果。与强心苷合用增加心律失常风险。与甲状腺激素合用可增加心血管副作用。与茶碱合用增加中枢兴奋和胃肠道不良反应。与其他拟交感胺类药物（伪麻黄碱、去氧肾上腺素）合用升压和心血管风险叠加。"},
            {"title": "禁忌", "content": "高血压、冠心病、心动过速患者禁用或慎用。甲状腺功能亢进禁用。前列腺肥大排尿困难者慎用。严重失眠患者慎用。"},
            {"title": "警告与注意事项", "content": "许多中成药含麻黄成分（如感冒清热颗粒、防风通圣丸等），患者可能未意识到在使用。含麻黄碱的感冒药与上述处方药合用时应特别注意。"}
        ],
        "interactions": [
            {"with": "enalapril", "risk_level": "High", "mechanism": "麻黄碱的升压作用对抗 ACEI 降压效果，可致血压控制不佳甚至高血压急症。", "recommendation": "高血压患者避免使用含麻黄碱制品。"},
            {"with": "metoprolol", "risk_level": "Medium", "mechanism": "麻黄碱的β受体激动作用可对抗美托洛尔的β受体阻滞效果。", "recommendation": "合用可致血压和心率控制不佳。"},
            {"with": "digoxin", "risk_level": "High", "mechanism": "麻黄碱可致心律失常，与地高辛的致心律失常风险叠加。", "recommendation": "避免合用。"}
        ]
    },
    {
        "drug": "wuweizi",
        "aliases": ["五味子", "五味子颗粒", "护肝片", "schisandra"],
        "source": "基于临床文献与药品说明书整理的中西药相互作用",
        "sections": [
            {"title": "药物相互作用", "content": "五味子含五味子甲素、乙素等木脂素成分，是 CYP3A4 的强抑制剂。可显著升高经 CYP3A4 代谢药物的血药浓度，包括他克莫司、环孢素、辛伐他汀、阿托伐他汀、咪达唑仑等。在中国肝移植患者中常被用于减少他克莫司用量（作为「药物增效剂」），但存在浓度波动和中毒风险。"},
            {"title": "警告与注意事项", "content": "与经 CYP3A4 代谢的窄治疗窗药物合用时风险极高。即使含五味子的保肝中成药（如护肝片）也可能引起显著药物相互作用。肝移植患者未经医生指导不应自行加用。"}
        ],
        "interactions": [
            {"with": "cyclosporine", "risk_level": "High", "mechanism": "五味子甲素强效抑制 CYP3A4，可使环孢素血药浓度升高 2-3 倍，增加肾毒性和肝毒性风险。", "recommendation": "合用需由专科医生严密监测环孢素血药浓度并大幅减量。"},
            {"with": "simvastatin", "risk_level": "High", "mechanism": "五味子抑制 CYP3A4 可使辛伐他汀暴露量显著升高，增加横纹肌溶解风险。", "recommendation": "避免合用；使用他汀者不应自行加用含五味子的保肝药。"},
            {"with": "atorvastatin", "risk_level": "High", "mechanism": "五味子抑制 CYP3A4 可升高阿托伐他汀浓度。", "recommendation": "避免合用，或换用不经 CYP3A4 代谢的瑞舒伐他汀。"}
        ]
    },
]


def merge_records(existing: List[Dict], new_records: List[Dict]) -> List[Dict]:
    """合并新旧药物记录，以 drug 字段为 key，新数据覆盖旧数据但保留旧数据中新数据没有的交互。"""
    by_drug: Dict[str, Dict] = {}
    for rec in existing:
        by_drug[rec["drug"]] = rec
    for rec in new_records:
        key = rec["drug"]
        if key in by_drug:
            old = by_drug[key]
            # 合并 sections —— 新的覆盖同名 section，保留旧独有的
            old_sections = {s["title"]: s for s in old.get("sections", [])}
            for sec in rec.get("sections", []):
                old_sections[sec["title"]] = sec
            rec["sections"] = list(old_sections.values())
            # 合并 interactions
            old_inters = {i["with"]: i for i in old.get("interactions", [])}
            for inter in rec.get("interactions", []):
                old_inters[inter["with"]] = inter
            rec["interactions"] = list(old_inters.values())
            # 合并 aliases（去重）
            all_aliases = list(dict.fromkeys(old.get("aliases", []) + rec.get("aliases", [])))
            rec["aliases"] = all_aliases
        by_drug[key] = rec
    return list(by_drug.values())


def main():
    # 加载已有数据
    existing: List[Dict] = []
    if EXISTING_PATH.exists():
        existing = json.loads(EXISTING_PATH.read_text(encoding="utf-8"))
        print(f"已加载现有知识库: {len(existing)} 条药物记录")

    # 合并内置西药数据
    merged = merge_records(existing, BUILTIN_DRUGS)
    print(f"合并西药后: {len(merged)} 条")

    # 合并中药数据
    merged = merge_records(merged, TCM_DRUGS)
    print(f"合并中药后: {len(merged)} 条")

    # 统计
    total_interactions = sum(len(rec.get("interactions", [])) for rec in merged)
    total_sections = sum(len(rec.get("sections", [])) for rec in merged)
    print(f"总计: {len(merged)} 种药物, {total_interactions} 条交互关系, {total_sections} 个说明书章节")

    # 写出
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(
        json.dumps(merged, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"已写入: {OUT_PATH}")


if __name__ == "__main__":
    main()
