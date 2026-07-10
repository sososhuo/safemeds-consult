import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  AlertTriangle,
  Archive,
  ClipboardList,
  CheckCircle2,
  ChevronDown,
  Clock3,
  FileText,
  History,
  Loader2,
  MessageCircle,
  Pill,
  RefreshCw,
  Sparkles,
  Send,
  ShieldCheck,
  Trash2,
  Stethoscope
} from "lucide-react";
import { api } from "./api/client";
import "./styles.css";

const levelMeta = {
  High: { label: "高风险", action: "不建议自行合用", cls: "risk-high" },
  Medium: { label: "需谨慎", action: "建议先咨询医生或药师", cls: "risk-medium" },
  Low: { label: "低风险", action: "仍需按说明书或医嘱使用", cls: "risk-low" },
  Unknown: { label: "信息不足", action: "建议补充用药和身体情况", cls: "risk-unknown" }
};

const workflowLabels = {
  extract_entities: "识别药物和场景",
  query_kg: "核查用药关系",
  retrieve_evidence: "查找参考依据",
  assess_risk: "判断风险等级",
  prepare_answer: "生成咨询回复"
};

function formatTime(value) {
  if (!value) return "–";
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit"
  }).format(new Date(value));
}

function App() {
  const [message, setMessage] = useState("65岁男性，长期服用华法林，最近感冒发热想吃布洛芬，可以吗？");
  const [currentResponse, setCurrentResponse] = useState(null);
  const [sessions, setSessions] = useState([]);
  const [sessionId, setSessionId] = useState(null);
  const [health, setHealth] = useState(null);
  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [sessionLoading, setSessionLoading] = useState(false);
  const [deletingId, setDeletingId] = useState(null);
  const [error, setError] = useState("");

  const risk = useMemo(() => levelMeta[currentResponse?.risk_level] || levelMeta.Unknown, [currentResponse]);
  const extracted = currentResponse?.extracted_context || { normalized_drugs: [], population: [], conditions: [] };
  const ambiguousEntities = currentResponse?.extracted_context?.ambiguous_entities || [];
  const evidence = currentResponse?.evidence || [];
  const relations = currentResponse?.kg_relations || [];
  const workflowTrace = currentResponse?.workflow_trace || [];

  useEffect(() => {
    refresh();
  }, []);

  async function refresh() {
    setRefreshing(true);
    setError("");
    try {
      const [healthData, sessionData] = await Promise.all([api.health(), api.sessions()]);
      setHealth(healthData);
      setSessions(sessionData);
    } catch (err) {
      console.error("refresh_failed", err);
      setError(`连接服务失败：${err.message}`);
    } finally {
      setRefreshing(false);
    }
  }

  async function sendMessage() {
    setLoading(true);
    setError("");
    try {
      const item = await api.chat({ message, session_id: sessionId });
      setCurrentResponse(item);
      setSessionId(item.session_id);
      setSessions(await api.sessions());
    } catch (err) {
      console.error("chat_failed", err);
      setError(`咨询失败：${err.message}`);
    } finally {
      setLoading(false);
    }
  }

  async function openSession(id) {
    setSessionLoading(true);
    setError("");
    try {
      const detail = await api.sessionDetail(id);
      setSessionId(detail.id);
      const latest = detail.messages[detail.messages.length - 1] || null;
      setCurrentResponse(latest);
      if (latest?.message) setMessage(latest.message);
    } catch (err) {
      console.error("session_detail_failed", err);
      setError(`读取历史咨询失败：${err.message}`);
    } finally {
      setSessionLoading(false);
    }
  }

  async function deleteSession(id, event) {
    event.stopPropagation();
    const confirmed = window.confirm("确认删除这条咨询记录吗？删除后无法恢复。");
    if (!confirmed) return;
    setDeletingId(id);
    setError("");
    try {
      await api.deleteSession(id);
      setSessions((items) => items.filter((item) => item.id !== id));
      if (sessionId === id) {
        setSessionId(null);
        setCurrentResponse(null);
        setMessage("");
      }
    } catch (err) {
      console.error("delete_session_failed", err);
      setError(`删除失败：${err.message}`);
    } finally {
      setDeletingId(null);
    }
  }

  function startNewSession() {
    setSessionId(null);
    setCurrentResponse(null);
    setMessage("");
  }

  return (
    <main className="app-shell">
      <header className="topbar">
        <div className="brand-block">
          <div className="brand-mark">
            <ShieldCheck size={20} />
          </div>
          <div>
            <h1>SafeMeds 用药咨询</h1>
            <p>药物相互作用、特殊人群与风险依据核查</p>
          </div>
        </div>
        <div className="service-status">
          <span className={health?.status === "ok" ? "status-dot online" : "status-dot"} />
          <span>{health?.status === "ok" ? "服务可用" : "正在连接"}</span>
          <button className="icon-button" onClick={refresh} disabled={refreshing} title="刷新">
            <RefreshCw className={refreshing ? "spin" : ""} size={14} />
          </button>
        </div>
      </header>

      <section className="workspace">
        <aside className="question-pane">
          <div className="pane-head">
            <MessageCircle size={18} />
            <div>
              <h2>描述你的用药问题</h2>
              <p>可写明正在服用的药、年龄、疾病、症状或检查安排。</p>
            </div>
          </div>

          <div className="prompt-strip" aria-label="咨询要点">
            <span><Pill size={14} />药品名称</span>
            <span><Stethoscope size={14} />基础疾病</span>
            <span><ClipboardList size={14} />用药目的</span>
          </div>

          <textarea
            value={message}
            onChange={(event) => setMessage(event.target.value)}
            placeholder="例如：我长期吃华法林，感冒发热能吃布洛芬吗？"
          />

          <div className="input-meta">
            <span>{message.length} 字</span>
            <span>{sessionId ? `正在查看历史 #${sessionId}` : "新的咨询"}</span>
          </div>

          <div className="actions">
            <button className="primary" onClick={sendMessage} disabled={loading || message.trim().length < 2}>
              {loading ? <Loader2 className="spin" size={16} /> : <Send size={16} />}
              获取建议
            </button>
            <button className="secondary" onClick={startNewSession} disabled={loading}>
              新咨询
            </button>
          </div>

          {error && <div className="error">{error}</div>}

          <div className="notice-card">
            <ShieldCheck size={18} />
            <div>
              <strong>安全提示</strong>
              <p>本系统用于用药风险信息查询和患者教育，不替代医生或药师建议。</p>
            </div>
          </div>
        </aside>

        <section className="result-pane">
          {currentResponse ? (
            <div className="result-scroll">
              <div className="result-kicker">
                <Sparkles size={15} />
                <span>智能核查结果</span>
              </div>

              <article className={`risk-card ${risk.cls}`}>
                <div className="risk-main">
                  <span className="risk-label">
                    <AlertTriangle size={16} />
                    {risk.label}
                  </span>
                  <h2>{risk.action}</h2>
                  <p>{currentResponse.conclusion}</p>
                </div>
                <div className="risk-confidence">
                  <strong>{Math.round((currentResponse.confidence || 0) * 100)}%</strong>
                  <span>判断置信度</span>
                </div>
              </article>

              <div className="summary-grid">
                <div>
                  <span>识别药物</span>
                  <strong>{extracted.normalized_drugs.length || ambiguousEntities.length}</strong>
                </div>
                <div>
                  <span>参考依据</span>
                  <strong>{evidence.length}</strong>
                </div>
                <div>
                  <span>关系核查</span>
                  <strong>{relations.length}</strong>
                </div>
              </div>

              <article className="answer-card">
                <div className="section-title">
                  <CheckCircle2 size={17} />
                  <h2>建议</h2>
                </div>
                <p className="recommendation-text">{currentResponse.recommendation}</p>
                <div className="answer-text">{currentResponse.answer}</div>
              </article>

              <article className="info-card">
                <div className="section-title">
                  <Pill size={17} />
                  <h2>已识别信息</h2>
                </div>
                <div className="chips">
                  {extracted.normalized_drugs.map((item) => <span key={item}>{item}</span>)}
                  {extracted.population.map((item) => <span key={item}>{item}</span>)}
                  {extracted.conditions.map((item) => <span key={item}>{item}</span>)}
                  {!extracted.normalized_drugs.length && !extracted.population.length && !extracted.conditions.length && !ambiguousEntities.length && <em>暂无明确药物或场景信息</em>}
                </div>
                {ambiguousEntities.length > 0 && (
                  <div className="ambiguous-list">
                    {ambiguousEntities.map((item, index) => (
                      <div className="ambiguous-item" key={`${item.mention}-${index}`}>
                        <strong>{item.mention}</strong>
                        <span>{item.normalized || "未明确药品"}</span>
                        {item.possible_ingredients?.length > 0 && (
                          <small>常见可能成分：{item.possible_ingredients.join("、")}</small>
                        )}
                        <p>{item.user_message || "请补充具体药品名称。"}</p>
                      </div>
                    ))}
                  </div>
                )}
              </article>

              <details className="detail-card">
                <summary>
                  <span>
                    <FileText size={17} />
                    参考依据与核查详情
                  </span>
                  <ChevronDown size={17} />
                </summary>

                <div className="detail-section">
                  <h3>参考依据</h3>
                  <div className="evidence-list">
                    {evidence.map((item, index) => (
                      <details className="evidence-item" key={`${item.drug}-${item.section}-${index}`}>
                        <summary>
                          <strong>{item.drug} · {item.section}</strong>
                          <span>{item.source}</span>
                        </summary>
                        <p>{item.snippet}</p>
                      </details>
                    ))}
                    {!evidence.length && <p className="muted">暂未找到可展示的参考依据。</p>}
                  </div>
                </div>

                <div className="detail-section">
                  <h3>用药关系核查</h3>
                  <div className="relation-list">
                    {relations.slice(0, 8).map((item, index) => (
                      <div className="relation-item" key={`${item.subject}-${item.relation}-${item.object}-${index}`}>
                        <strong>{item.subject}</strong>
                        <span>{item.relation}</span>
                        <strong>{item.object}</strong>
                      </div>
                    ))}
                    {!relations.length && <p className="muted">未发现明确的结构化用药关系。</p>}
                  </div>
                </div>

                <div className="detail-section">
                  <h3>处理过程</h3>
                  <ol className="process-list">
                    {workflowTrace.map((item, index) => (
                      <li key={`${item.node}-${index}`}>{workflowLabels[item.node] || item.node}</li>
                    ))}
                  </ol>
                </div>
              </details>
            </div>
          ) : (
            <div className="empty-state">
              <div className="empty-icon">
                <Pill size={24} />
              </div>
              <h2>填写问题后查看风险提示</h2>
              <p>结果会优先展示风险等级、建议动作和通俗解释；依据和核查详情可按需展开。</p>
            </div>
          )}
        </section>

        <aside className="history-pane">
          <div className="history-head">
            <div>
              <History size={17} />
              <h2>历史咨询</h2>
            </div>
            {sessionLoading && <Loader2 className="spin" size={15} />}
          </div>

          <div className="history-list">
            {sessions.map((item) => {
              const meta = levelMeta[item.risk_level] || levelMeta.Unknown;
              return (
                <article className={sessionId === item.id ? "history-item active" : "history-item"} key={item.id}>
                  <button className="history-open" onClick={() => openSession(item.id)}>
                    <span className={`mini-risk ${meta.cls}`}>{meta.label}</span>
                    <strong>{item.conclusion}</strong>
                    <small><Clock3 size={12} /> {formatTime(item.updated_at)}</small>
                  </button>
                  <button
                    className="delete-button"
                    onClick={(event) => deleteSession(item.id, event)}
                    disabled={deletingId === item.id}
                    title="删除咨询记录"
                  >
                    {deletingId === item.id ? <Loader2 className="spin" size={14} /> : <Trash2 size={14} />}
                  </button>
                </article>
              );
            })}

            {!sessions.length && (
              <div className="history-empty">
                <Archive size={22} />
                <span>暂无历史咨询</span>
              </div>
            )}
          </div>
        </aside>
      </section>
    </main>
  );
}

createRoot(document.getElementById("root")).render(<App />);
