"use client";

import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import catalogSeed from "../server/wiki_catalog.json";

type InputType = "speech" | "action" | "thought" | "question" | "ooc";
type View = "home" | "setup" | "room";

type Topic = {
  title: string;
  source_url: string;
  groups?: string[];
  description?: string;
};

type CatalogSection = {
  id: "bdsm101" | "theory" | "disciplines";
  label: string;
  description: string;
  source_url: string;
  unique_count: number;
  group_labels?: string[];
  topics: Topic[];
};

type Catalog = {
  synced_at: string;
  source: string;
  sections: CatalogSection[];
};

type Message = {
  id: number | string;
  role: "user" | "main_ai" | "audience";
  input_type: InputType | "reply";
  speaker: string;
  content: string;
  action?: string;
};

type Session = {
  id: string;
  topic: string;
  mode: "study" | "experience";
  ai_name: string;
  audience_enabled: boolean;
  audience_style: string;
  audience_activity: string;
  topic_description: string;
  topic_excerpt: string;
  source_url: string;
  messages: Message[];
  suggestions?: string[];
  updated_at?: string;
};

const API_BASE = process.env.NEXT_PUBLIC_CAMP_API_BASE || "";
const initialCatalog = catalogSeed as Catalog;

const inputTypes: Array<{ id: InputType; label: string; hint: string }> = [
  { id: "speech", label: "说话", hint: "写下你想说的话……" },
  { id: "action", label: "行动", hint: "描述你此刻选择做什么……" },
  { id: "thought", label: "想法", hint: "写下角色此刻的内心想法……" },
  { id: "question", label: "提问", hint: "询问当前词条、风险或情境……" },
  { id: "ooc", label: "OOC", hint: "跳出角色，直接和 AI 讨论……" },
];

function getVisitorId() {
  const key = "bdsm-summer-camp-visitor";
  let value = window.localStorage.getItem(key);
  if (!value) {
    value = window.crypto.randomUUID();
    window.localStorage.setItem(key, value);
  }
  return value;
}

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
    });
  } catch {
    throw new Error("无法连接夏令营服务。请确认后端已经启动，或把仓库交给你的 AI 检查配置。");
  }
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload?.message || "服务暂时没有响应");
  return payload as T;
}

function topicCopy(topic: Topic, section: CatalogSection) {
  if (section.id === "bdsm101") return "BDSM Wiki 新手推荐阅读";
  if (section.id === "theory") return "BDSM Wiki 理论条目";
  return topic.groups?.length ? topic.groups.slice(0, 3).join(" · ") : "BDSM Wiki 学科条目";
}

export function ExperienceApp() {
  const [view, setView] = useState<View>("home");
  const [visitorId] = useState(() => typeof window === "undefined" ? "" : getVisitorId());
  const [catalog, setCatalog] = useState<Catalog>(initialCatalog);
  const [activeSectionId, setActiveSectionId] = useState<CatalogSection["id"]>("bdsm101");
  const [disciplineGroup, setDisciplineGroup] = useState("全部学科");
  const [recent, setRecent] = useState<Session[]>([]);
  const [selectedTopic, setSelectedTopic] = useState<Topic | null>(null);
  const [session, setSession] = useState<Session | null>(null);
  const [search, setSearch] = useState("");
  const [mode, setMode] = useState<"study" | "experience">("study");
  const [aiName, setAiName] = useState("");
  const [audienceEnabled, setAudienceEnabled] = useState(false);
  const [audienceStyle, setAudienceStyle] = useState("好奇");
  const [audienceActivity, setAudienceActivity] = useState("偶尔评论");
  const [sideTab, setSideTab] = useState<"knowledge" | "audience">("knowledge");
  const [inputType, setInputType] = useState<InputType>("speech");
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [mobilePanel, setMobilePanel] = useState(false);
  const listRef = useRef<HTMLDivElement>(null);

  const loadRecent = useCallback(async (id: string) => {
    try {
      const data = await api<{ sessions: Session[] }>(`/api/sessions?visitor_id=${encodeURIComponent(id)}`);
      setRecent(data.sessions || []);
    } catch {
      setRecent([]);
    }
  }, []);

  useEffect(() => {
    if (!visitorId) return;
    let active = true;
    api<{ sessions: Session[] }>(`/api/sessions?visitor_id=${encodeURIComponent(visitorId)}`)
      .then((data) => { if (active) setRecent(data.sessions || []); })
      .catch(() => { if (active) setRecent([]); });
    api<Catalog>("/api/catalog")
      .then((data) => { if (active) setCatalog(data); })
      .catch(() => undefined);
    return () => { active = false; };
  }, [visitorId]);

  useEffect(() => {
    if (view !== "room") return;
    const list = listRef.current;
    if (list) list.scrollTo({ top: list.scrollHeight, behavior: "smooth" });
  }, [session?.messages, busy, view]);

  const activeInput = useMemo(
    () => inputTypes.find((item) => item.id === inputType) || inputTypes[0],
    [inputType],
  );

  const activeSection = useMemo(
    () => catalog.sections.find((section) => section.id === activeSectionId) || catalog.sections[0],
    [catalog, activeSectionId],
  );

  const visibleTopics = useMemo(() => {
    const needle = search.trim().toLocaleLowerCase();
    if (needle) {
      const seen = new Set<string>();
      return catalog.sections.flatMap((section) =>
        section.topics
          .filter((topic) => topic.title.toLocaleLowerCase().includes(needle))
          .filter((topic) => {
            if (seen.has(topic.title)) return false;
            seen.add(topic.title);
            return true;
          })
          .map((topic) => ({ topic, section })),
      );
    }
    return activeSection.topics
      .filter((topic) =>
        activeSection.id !== "disciplines" ||
        disciplineGroup === "全部学科" ||
        topic.groups?.includes(disciplineGroup),
      )
      .map((topic) => ({ topic, section: activeSection }));
  }, [activeSection, catalog, disciplineGroup, search]);

  function chooseTopic(topic: Topic, section: CatalogSection) {
    setSelectedTopic({ ...topic, description: topicCopy(topic, section) });
    setView("setup");
    setError("");
    window.scrollTo({ top: 0 });
  }

  async function createSession() {
    if (!selectedTopic || !visitorId || busy) return;
    setBusy(true);
    setError("");
    try {
      const data = await api<{ session: Session }>("/api/sessions", {
        method: "POST",
        body: JSON.stringify({
          visitor_id: visitorId,
          topic: selectedTopic.title,
          mode,
          ai_name: aiName.trim(),
          audience_enabled: audienceEnabled,
          audience_style: audienceStyle,
          audience_activity: audienceActivity,
        }),
      });
      setSession(data.session);
      setView("room");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "暂时无法开始体验");
    } finally {
      setBusy(false);
    }
  }

  async function openSession(id: string) {
    if (!visitorId || busy) return;
    setBusy(true);
    setError("");
    try {
      const data = await api<{ session: Session }>(
        `/api/sessions/${encodeURIComponent(id)}?visitor_id=${encodeURIComponent(visitorId)}`,
      );
      setSession(data.session);
      setView("room");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "暂时无法恢复体验");
    } finally {
      setBusy(false);
    }
  }

  async function sendMessage(event?: FormEvent, suggestedText?: string) {
    event?.preventDefault();
    if (!session || busy) return;
    const content = (suggestedText ?? draft).trim();
    if (!content) return;

    const previousSession = session;
    const optimistic: Message = {
      id: `pending-${Date.now()}`,
      role: "user",
      input_type: inputType,
      speaker: "你",
      content,
    };
    setSession({ ...session, messages: [...session.messages, optimistic], suggestions: [] });
    setDraft("");
    setBusy(true);
    setError("");
    try {
      const data = await api<{ session: Session }>(
        `/api/sessions/${encodeURIComponent(session.id)}/messages`,
        {
          method: "POST",
          body: JSON.stringify({ visitor_id: visitorId, input_type: inputType, content }),
        },
      );
      setSession(data.session);
    } catch (reason) {
      setSession(previousSession);
      setError(reason instanceof Error ? reason.message : "AI 暂时没有回应");
      setDraft(content);
    } finally {
      setBusy(false);
    }
  }

  function returnHome() {
    setSession(null);
    setSelectedTopic(null);
    setView("home");
    setError("");
    window.scrollTo({ top: 0 });
  }

  if (view === "setup" && selectedTopic) {
    return (
      <main className="shell setup-shell">
        <button type="button" className="back-link" onClick={() => setView("home")}>
          ← 返回选课目录
        </button>
        <section className="setup-card">
          <p className="eyebrow">入营设置</p>
          <h1>{selectedTopic.title}</h1>
          <p className="setup-lead">{selectedTopic.description}</p>

          <fieldset>
            <legend>这次想怎么探索？</legend>
            <div className="choice-grid two">
              <button type="button" className={mode === "study" ? "choice active" : "choice"} onClick={() => setMode("study")}>
                <strong>一起学习</strong><span>阅读、解释、讨论和提问</span>
              </button>
              <button type="button" className={mode === "experience" ? "choice active" : "choice"} onClick={() => setMode("experience")}>
                <strong>文字体验</strong><span>边行动、边选择、边理解</span>
              </button>
            </div>
          </fieldset>

          <fieldset>
            <label className="field-label" htmlFor="ai-name">AI 名称 <span>可选</span></label>
            <input
              id="ai-name"
              className="name-input"
              value={aiName}
              maxLength={40}
              placeholder="由你命名；留空时只显示“AI”"
              onChange={(event) => setAiName(event.target.value)}
            />
          </fieldset>

          <fieldset>
            <legend>需要文字 AI 观众吗？</legend>
            <label className="switch-row">
              <span><strong>{audienceEnabled ? "AI 观众席已开启" : "不启用观众"}</strong><small>观众只会用文字动作和评论参与</small></span>
              <input type="checkbox" checked={audienceEnabled} onChange={(event) => setAudienceEnabled(event.target.checked)} />
            </label>
            {audienceEnabled && (
              <div className="audience-options">
                <div>
                  <span className="field-label">观众语气</span>
                  <div className="pill-row">
                    {["温柔", "好奇", "调侃", "冷静"].map((style) => (
                      <button type="button" key={style} className={audienceStyle === style ? "pill active" : "pill"} onClick={() => setAudienceStyle(style)}>{style}</button>
                    ))}
                  </div>
                </div>
                <div>
                  <span className="field-label">活跃度</span>
                  <div className="pill-row">
                    {["偶尔评论", "经常评论"].map((activity) => (
                      <button type="button" key={activity} className={audienceActivity === activity ? "pill active" : "pill"} onClick={() => setAudienceActivity(activity)}>{activity}</button>
                    ))}
                  </div>
                </div>
              </div>
            )}
          </fieldset>

          {error && <p className="error-note" role="alert">{error}</p>}
          <button type="button" className="primary-action" disabled={busy || !visitorId} onClick={createSession}>
            {busy ? "正在准备营地……" : "进入 BDSM 夏令营"}
          </button>
        </section>
      </main>
    );
  }

  if (view === "room" && session) {
    const audienceMessages = session.messages.filter((item) => item.role === "audience");
    const aiLabel = session.ai_name?.trim() || "AI";
    return (
      <main className="room-shell">
        <header className="room-header">
          <div className="room-navigation">
            <button type="button" className="room-back" onClick={returnHome}>← 返回选课目录</button>
          </div>
          <div className="room-title"><strong>{session.topic}</strong><span>{session.mode === "study" ? "一起学习" : "文字体验"}</span></div>
          <div className="room-actions">
            <button type="button" onClick={() => { setSideTab("knowledge"); setMobilePanel(true); }}>知识卡</button>
            <button type="button" onClick={() => { setSideTab("audience"); setMobilePanel(true); }}>{session.audience_enabled ? "AI 观众" : "无观众"}</button>
          </div>
        </header>

        <div className="room-grid">
          <section className="stage" aria-label="夏令营互动记录">
            <div className="stage-intro">
              <span className="live-dot" />
              <p>正在探索 <strong>{session.topic}</strong> · 主 AI 显示为 <strong>{aiLabel}</strong> · 所有观众均为 AI</p>
            </div>

            <div className="message-list" ref={listRef} aria-live="polite">
              {session.messages.map((message) => {
                const speaker = message.role === "main_ai" ? aiLabel : message.speaker;
                return (
                  <article key={message.id} className={`message ${message.role} ${message.input_type}`}>
                    <div className="message-meta">
                      <strong>{speaker || (message.role === "user" ? "你" : "AI")}</strong>
                      <span>{message.role === "audience" ? "AI 观众" : message.role === "user" ? inputTypes.find((item) => item.id === message.input_type)?.label : "AI"}</span>
                    </div>
                    {message.action && <p className="action-line">*{message.action}*</p>}
                    <p>{message.content}</p>
                  </article>
                );
              })}
              {busy && (
                <article className="message main_ai thinking">
                  <div className="message-meta"><strong>{aiLabel}</strong><span>正在回应</span></div>
                  <div className="thinking-dots"><i /><i /><i /></div>
                </article>
              )}
            </div>

            <div className="composer-wrap">
              {session.suggestions && session.suggestions.length > 0 && !busy && (
                <div className="suggestions" aria-label="回应灵感">
                  {session.suggestions.map((suggestion) => (
                    <button type="button" key={suggestion} onClick={() => setDraft(suggestion)}>{suggestion}</button>
                  ))}
                </div>
              )}
              {error && <p className="error-note compact" role="alert">{error}</p>}
              <form className="composer" onSubmit={(event) => void sendMessage(event)}>
                <div className="input-tabs" role="tablist" aria-label="输入方式">
                  {inputTypes.map((item) => (
                    <button type="button" role="tab" aria-selected={inputType === item.id} className={inputType === item.id ? "active" : ""} key={item.id} onClick={() => setInputType(item.id)}>{item.label}</button>
                  ))}
                </div>
                <div className="input-row">
                  <textarea
                    value={draft}
                    maxLength={3000}
                    rows={2}
                    placeholder={activeInput.hint}
                    onChange={(event) => setDraft(event.target.value)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
                        event.preventDefault();
                        void sendMessage();
                      }
                    }}
                  />
                  <button type="submit" className="send-button" disabled={busy || !draft.trim()} aria-label="发送">发送</button>
                </div>
              </form>
            </div>
          </section>

          <aside className={mobilePanel ? "side-panel mobile-open" : "side-panel"}>
            <button type="button" className="panel-close" onClick={() => setMobilePanel(false)} aria-label="关闭侧栏">×</button>
            <div className="side-tabs">
              <button type="button" className={sideTab === "knowledge" ? "active" : ""} onClick={() => setSideTab("knowledge")}>知识</button>
              <button type="button" className={sideTab === "audience" ? "active" : ""} onClick={() => setSideTab("audience")}>观众</button>
            </div>
            {sideTab === "knowledge" ? (
              <div className="knowledge-card">
                <p className="eyebrow">当前 Wiki 条目</p>
                <h2>{session.topic}</h2>
                <p className="topic-description">{session.topic_description}</p>
                <div className="rule" />
                <p className="excerpt">{session.topic_excerpt || "词条正在整理中，你仍然可以直接向 AI 提问。"}</p>
                <a href={session.source_url} target="_blank" rel="noreferrer">查看 BDSM Wiki 原始词条 →</a>
              </div>
            ) : (
              <div className="audience-panel">
                <p className="eyebrow">文字 AI 观众席</p>
                <h2>{session.audience_enabled ? `${session.audience_style} · ${session.audience_activity}` : "本次未启用"}</h2>
                {!session.audience_enabled ? (
                  <p className="empty-copy">这次只有你和主 AI，没有旁观评论。</p>
                ) : audienceMessages.length ? (
                  <div className="audience-feed">
                    {audienceMessages.slice(-8).reverse().map((message) => (
                      <div key={message.id} className="audience-note">
                        <strong>{message.speaker}</strong>
                        {message.action && <em>*{message.action}*</em>}
                        <p>{message.content}</p>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="empty-copy">观众正在安静旁观，不一定每轮都会评论。</p>
                )}
                <p className="ai-disclosure">这里的所有观众、动作和评论均由 AI 模拟，不是真人。</p>
              </div>
            )}
          </aside>
        </div>
      </main>
    );
  }

  return (
    <main className="home-shell">
      <nav className="home-nav">
        <div className="brand">
          <img className="brand-mark" src="/repository-assets/project-logo.png" alt="" />
          <span className="brand-copy"><strong>BDSM 夏令营</strong><small>THE SUMMER CAMP</small></span>
        </div>
        <span className="adult-note">18+ · TEXT ONLY · AI 共学与体验</span>
      </nav>

      <section className="hero">
        <p className="eyebrow">BDSM WIKI × AI · PRIVATE STUDY & EXPERIENCE</p>
        <h1>先学会理解，<br />再决定怎样体验。</h1>
        <p className="hero-copy">从一页隐秘的知识开始，与你的 AI 一同走进权力、欲望与信任彼此交缠的夜色。</p>
        <label className="catalog-search">
          <span>272 个词条 · 378 个目录入口</span>
          <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="例如 Consent、Safeword、Bondage……" />
          {search && <button type="button" onClick={() => setSearch("")} aria-label="清空搜索">清空</button>}
        </label>
        {error && <p className="error-note" role="alert">{error}</p>}
      </section>

      <section className="home-content" aria-label="课程目录">
        {recent.length > 0 && (
          <div className="recent-block">
            <div className="section-heading"><p className="eyebrow">继续上次</p><span>自动保存</span></div>
            <div className="recent-row">
              {recent.slice(0, 3).map((item) => (
                <button type="button" key={item.id} className="recent-card" onClick={() => void openSession(item.id)}>
                  <span>{item.mode === "study" ? "学习" : "体验"}</span>
                  <strong>{item.topic}</strong>
                  <small>{item.ai_name ? `AI：${item.ai_name}` : "未命名 AI"} · {item.audience_enabled ? "有 AI 观众" : "无观众"}</small>
                </button>
              ))}
            </div>
          </div>
        )}

        <div className="catalog-heading">
          <div><p className="eyebrow">完整选课目录</p><h2>{search ? `“${search}”的搜索结果` : activeSection.label}</h2></div>
          <p>{search ? `找到 ${visibleTopics.length} 个条目` : `${activeSection.unique_count} 个条目 · ${activeSection.description}`}</p>
        </div>

        {!search && (
          <div className="section-tabs" role="tablist" aria-label="Wiki 栏目">
            {catalog.sections.map((section) => (
              <button
                type="button"
                role="tab"
                aria-selected={activeSectionId === section.id}
                className={activeSectionId === section.id ? "active" : ""}
                key={section.id}
                onClick={() => { setActiveSectionId(section.id); setDisciplineGroup("全部学科"); }}
              >
                <strong>{section.label}</strong><span>{section.unique_count}</span>
              </button>
            ))}
          </div>
        )}

        {!search && activeSection.id === "disciplines" && (
          <div className="discipline-filters" aria-label="学科筛选">
            {["全部学科", ...(activeSection.group_labels || [])].map((group) => (
              <button type="button" key={group} className={disciplineGroup === group ? "active" : ""} onClick={() => setDisciplineGroup(group)}>{group}</button>
            ))}
          </div>
        )}

        <div className="topic-list">
          {visibleTopics.map(({ topic, section }, index) => (
            <button type="button" className="topic-item" key={`${section.id}-${topic.title}-${index}`} onClick={() => chooseTopic(topic, section)}>
              <span className="topic-index">{String(index + 1).padStart(2, "0")}</span>
              <span className="topic-name">{topic.title}</span>
              <span className="topic-kind">{topicCopy(topic, section)}</span>
              <span className="topic-arrow">→</span>
            </button>
          ))}
        </div>

        {visibleTopics.length === 0 && <p className="empty-results">没有匹配条目，试试英文原词或更短的关键词。</p>}
      </section>

      <footer>
        <span>目录核对自 BDSM Wiki · 快照日期 {catalog.synced_at}</span>
        <a href="https://www.bdsmwiki.info/Main_Page" target="_blank" rel="noreferrer">访问 BDSM Wiki →</a>
      </footer>
    </main>
  );
}
