import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Activity,
  ArrowRight,
  BarChart3,
  Bot,
  CheckCircle2,
  ChevronRight,
  Circle,
  Clock3,
  Database,
  FileText,
  History,
  Image,
  ListChecks,
  Plus,
  Send,
  ShieldCheck,
  Sparkles,
  Target,
  User,
  Wrench,
} from "lucide-react";
import "./styles.css";

type EventItem = {
  type: string;
  payload: Record<string, any>;
  created_at?: string;
};

type Artifact = {
  kind: "image" | "csv" | "json" | "text" | "file";
  path: string;
  label: string;
};

type ToolResultPayload = {
  step_id?: string | null;
  tool: string;
  ok: boolean;
  summary: string;
  data?: Record<string, any>;
  artifacts?: Artifact[];
};

type TodoPayload = {
  id: string;
  title: string;
  status: string;
};

type Turn = {
  id: string;
  question: string;
  events: EventItem[];
  status: "running" | "done" | "error";
  error?: string;
};

type ConversationSession = {
  id: string;
  backendSessionId: string;
  createdAt: string;
  updatedAt: string;
  draftInput: string;
  error?: string;
  running: boolean;
  selectedTurnId: string;
  title: string;
  turns: Turn[];
};

type PersistedWorkspace = {
  activeSessionId?: string;
  sessions?: ConversationSession[];
};

type LegacyPersistedState = {
  input?: string;
  selectedTurnId?: string;
  sessionId?: string;
  turns?: Turn[];
};

type AnswerBlock =
  | { type: "heading"; level: number; text: string }
  | { type: "paragraph"; text: string }
  | { type: "unordered-list"; items: string[] }
  | { type: "ordered-list"; items: string[] };

const STORAGE_KEY = "chengdu-pollution-agent-ui-state-v3";
const LEGACY_STORAGE_KEY = "chengdu-pollution-agent-ui-state-v2";

const samplePrompts = [
  "分析成都未来14天 PM2.5 趋势并画图",
  "找出 O3 高值时段和空间热点",
  "结合网上资料解释本轮污染可能成因",
];

function App() {
  const [sessions, setSessions] = useState<ConversationSession[]>([]);
  const [activeSessionId, setActiveSessionId] = useState("");
  const [bannerError, setBannerError] = useState("");
  const [creatingSession, setCreatingSession] = useState(false);

  const activeSession = sessions.find((session) => session.id === activeSessionId) ?? sessions[0] ?? null;
  const runningCount = sessions.filter((session) => session.running).length;
  const visibleError = activeSession?.error || bannerError;

  useEffect(() => {
    let disposed = false;

    const restore = async () => {
      try {
        const rawWorkspace = window.localStorage.getItem(STORAGE_KEY);
        if (rawWorkspace) {
          const cached = JSON.parse(rawWorkspace) as PersistedWorkspace;
          if (Array.isArray(cached.sessions) && cached.sessions.length) {
            if (!disposed) {
              setSessions(cached.sessions);
              setActiveSessionId(cached.activeSessionId || cached.sessions[0].id);
            }
            return;
          }
        }

        const rawLegacy = window.localStorage.getItem(LEGACY_STORAGE_KEY);
        if (rawLegacy) {
          const legacy = JSON.parse(rawLegacy) as LegacyPersistedState;
          const migrated = migrateLegacyState(legacy);
          if (migrated && !disposed) {
            setSessions([migrated]);
            setActiveSessionId(migrated.id);
            return;
          }
        }
      } catch (storageError) {
        console.warn("Failed to restore cached workspace.", storageError);
      }

      if (!disposed) {
        setSessions([]);
        setActiveSessionId("");
      }
    };

    restore();

    return () => {
      disposed = true;
    };
  }, []);

  useEffect(() => {
    try {
      const snapshot: PersistedWorkspace = {
        activeSessionId,
        sessions,
      };
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(snapshot));
    } catch (storageError) {
      console.warn("Failed to cache workspace.", storageError);
    }
  }, [activeSessionId, sessions]);

  useEffect(() => {
    if (!sessions.length) return;
    if (!activeSessionId || !sessions.some((session) => session.id === activeSessionId)) {
      setActiveSessionId(sessions[0].id);
    }
  }, [activeSessionId, sessions]);

  async function handleCreateSession() {
    if (creatingSession) return;

    setBannerError("");
    setCreatingSession(true);
    try {
      const session = await buildNewSession();
      setSessions((prev) => sortSessionsByUpdatedAt([session, ...prev]));
      setActiveSessionId(session.id);
    } catch (err) {
      setBannerError(err instanceof Error ? err.message : String(err));
    } finally {
      setCreatingSession(false);
    }
  }

  function updateSession(sessionId: string, updater: (session: ConversationSession) => ConversationSession) {
    setSessions((prev) => sortSessionsByUpdatedAt(prev.map((session) => (session.id === sessionId ? updater(session) : session))));
  }

  function handleDraftChange(value: string) {
    if (!activeSession) return;
    updateSession(activeSession.id, (session) => ({ ...session, draftInput: value }));
  }

  async function send() {
    if (!activeSession || activeSession.running) return;

    const question = activeSession.draftInput.trim();
    if (!question) return;

    const turnId = crypto.randomUUID();
    const now = new Date().toISOString();
    setBannerError("");
    updateSession(activeSession.id, (session) => ({
      ...session,
      draftInput: "",
      error: "",
      running: true,
      selectedTurnId: turnId,
      title: session.turns.length ? session.title : buildSessionTitle(question),
      turns: [...session.turns, { id: turnId, question, events: [], status: "running" }],
      updatedAt: now,
    }));

    try {
      let backendSessionId = activeSession.backendSessionId;
      let response = await postMessage(backendSessionId, question);
      if (response.status === 404) {
        backendSessionId = await createSession();
        updateSession(activeSession.id, (session) => ({ ...session, backendSessionId }));
        response = await postMessage(backendSessionId, question);
      }
      if (!response.ok) {
        const body = await response.text();
        throw new Error(body || `发送失败：HTTP ${response.status}`);
      }
      openEventStream(backendSessionId, activeSession.id, turnId);
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      updateSession(activeSession.id, (session) => ({
        ...session,
        error: message,
        running: false,
        updatedAt: new Date().toISOString(),
        turns: session.turns.map((turn) => (turn.id === turnId ? { ...turn, status: "error", error: message } : turn)),
      }));
    }
  }

  function openEventStream(backendSessionId: string, clientSessionId: string, turnId: string) {
    const stream = new EventSource(`/api/sessions/${backendSessionId}/events`);

    const handle = (message: MessageEvent) => {
      if (!message.data || message.data === "{}") return;

      const data = JSON.parse(message.data);
      const event = { type: data.type, payload: data.payload, created_at: data.created_at };
      const isFinalError = data.type === "final" && Boolean(data.payload?.error);

      updateSession(clientSessionId, (session) => ({
        ...session,
        error: isFinalError ? data.payload?.answer : session.error,
        running: data.type === "final" ? false : session.running,
        selectedTurnId: turnId,
        updatedAt: event.created_at || new Date().toISOString(),
        turns: session.turns.map((turn) => {
          if (turn.id !== turnId) return turn;
          const status = data.type === "final" ? (isFinalError ? "error" : "done") : turn.status;
          return { ...turn, status, error: isFinalError ? data.payload?.answer : turn.error, events: [...turn.events, event] };
        }),
      }));

      if (data.type === "final") {
        stream.close();
      }
    };

    stream.onmessage = handle;
    for (const type of ["plan", "todo", "tool_call", "tool_result", "artifact", "interrupt", "final"]) {
      stream.addEventListener(type, handle);
    }
    stream.onerror = () => {
      const message = "事件流连接中断，请刷新页面或重新发送。";
      updateSession(clientSessionId, (session) => ({
        ...session,
        error: message,
        running: false,
        updatedAt: new Date().toISOString(),
        turns: session.turns.map((turn) => (turn.id === turnId ? { ...turn, status: "error", error: message } : turn)),
      }));
      stream.close();
    };
  }

  function handleSelectSession(sessionId: string) {
    setActiveSessionId(sessionId);
    const targetSession = sessions.find((session) => session.id === sessionId);
    const targetTurnId = targetSession?.selectedTurnId || targetSession?.turns[targetSession.turns.length - 1]?.id;
    if (!targetTurnId) return;
    window.requestAnimationFrame(() => {
      document.getElementById(`turn-${targetTurnId}`)?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  }

  function handleSelectTurn(sessionId: string, turnId: string) {
    setActiveSessionId(sessionId);
    updateSession(sessionId, (session) => ({ ...session, selectedTurnId: turnId }));
    window.requestAnimationFrame(() => {
      document.getElementById(`turn-${turnId}`)?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  }

  return (
    <main className="appShell">
      <header className="topbar">
        <div className="brand">
          <div className="brandMark">
            <BarChart3 size={25} />
          </div>
          <div>
            <div className="brandKicker">CHENGDU AIR INTELLIGENCE</div>
            <h1>成都生态环境智能研判助手</h1>
            <p>空气质量研判 · 预警响应决策 · 精准管控建议</p>
          </div>
        </div>
        <div className="systemStatus">
          <span>决策支持系统</span>
          <div className="statusPill" data-running={runningCount > 0}>
            {runningCount > 0 ? <Activity size={16} /> : <CheckCircle2 size={16} />}
            {runningCount > 0 ? `${runningCount} 个会话分析中` : "系统就绪"}
          </div>
        </div>
      </header>

      <div className="workspaceShell">
        <HistorySidebar
          activeSessionId={activeSession?.id || ""}
          creatingSession={creatingSession}
          sessions={sessions}
          onCreateSession={handleCreateSession}
          onSelectSession={handleSelectSession}
          onSelectTurn={handleSelectTurn}
        />

        <section className="mainPane">
          <header className="conversationToolbar">
            <div>
              <span className="toolbarEyebrow">智能研判工作台</span>
              <h2>{activeSession ? activeSession.title : "等待创建分析会话"}</h2>
            </div>
            <div className="toolbarMeta">
              <Database size={15} />
              <span>CMAQ · 监测数据 · 专家规则</span>
            </div>
          </header>

          <section className="conversationStage">
            <ChatStream session={activeSession} onCreateSession={handleCreateSession} creatingSession={creatingSession} />
          </section>

          <footer className="chatDock">
            <div className="promptChips">
              {samplePrompts.map((prompt) => (
                <button
                  key={prompt}
                  onClick={() => handleDraftChange(prompt)}
                  disabled={!activeSession || activeSession.running}
                >
                  {prompt}
                </button>
              ))}
            </div>
            {visibleError && <div className="error">{visibleError}</div>}
            <div className="composer">
              <textarea
                value={activeSession?.draftInput || ""}
                onChange={(event) => handleDraftChange(event.target.value)}
                placeholder="继续提问，例如：把峰值时段的空间分布图也画出来"
                disabled={!activeSession}
                onKeyDown={(event) => {
                  if ((event.ctrlKey || event.metaKey) && event.key === "Enter") send();
                }}
              />
              <button className="send" onClick={send} disabled={!activeSession || activeSession.running}>
                {activeSession?.running ? <Activity size={18} /> : <Send size={18} />}
                {activeSession?.running ? "运行中" : "发送"}
              </button>
            </div>
          </footer>
        </section>
      </div>
    </main>
  );
}

function HistorySidebar({
  activeSessionId,
  creatingSession,
  sessions,
  onCreateSession,
  onSelectSession,
  onSelectTurn,
}: {
  activeSessionId: string;
  creatingSession: boolean;
  sessions: ConversationSession[];
  onCreateSession: () => void;
  onSelectSession: (sessionId: string) => void;
  onSelectTurn: (sessionId: string, turnId: string) => void;
}) {
  const orderedSessions = sortSessionsByUpdatedAt(sessions);
  const activeSession = orderedSessions.find((session) => session.id === activeSessionId) ?? orderedSessions[0] ?? null;

  return (
    <aside className="historyRail">
      <div className="historyCard">
        <div className="historyHeader">
          <div>
            <div className="historyEyebrow">
              <History size={14} />
              历史问答
            </div>
            <h2>多会话列表</h2>
            <p>左侧统一管理多个分析会话，并保留当前会话的轮次入口，方便随时切换。</p>
          </div>
          <div className="historyCount" data-running={orderedSessions.some((session) => session.running)}>
            {orderedSessions.length} 个会话
          </div>
        </div>

        <button className="sessionCreateButton" type="button" onClick={onCreateSession} disabled={creatingSession}>
          <Plus size={16} />
          {creatingSession ? "正在创建..." : "新建会话"}
        </button>

        {!orderedSessions.length && (
          <div className="historyEmpty">
            <Sparkles size={18} />
            <span>创建第一个会话后，这里会展示完整的多会话列表。</span>
          </div>
        )}

        {orderedSessions.length > 0 && (
          <>
            <div className="historySection">
              <div className="historySectionTitle">会话列表</div>
              <div className="historyList">
                {orderedSessions.map((session) => {
                  const active = session.id === activeSessionId;
                  return (
                    <button
                      key={session.id}
                      type="button"
                      className="historyItem"
                      data-active={active}
                      onClick={() => onSelectSession(session.id)}
                    >
                      <div className="historyItemTop">
                        <span className="historyStep">{session.title}</span>
                        <SessionStatusTag session={session} />
                      </div>
                      <h3>{getSessionHeadline(session)}</h3>
                      <p>{getSessionPreview(session)}</p>
                      <div className="historyItemFoot">
                        <span>{session.turns.length} 轮对话</span>
                        <span>{formatSessionTimestamp(session)}</span>
                      </div>
                    </button>
                  );
                })}
              </div>
            </div>

            <div className="historySection currentTurnsSection">
              <div className="historySectionTitle">当前会话轮次</div>
              {activeSession && activeSession.turns.length > 0 ? (
                <div className="turnNavigator">
                  {[...activeSession.turns].reverse().map((turn, index) => (
                    <button
                      key={turn.id}
                      type="button"
                      className="turnNavItem"
                      data-active={turn.id === activeSession.selectedTurnId}
                      onClick={() => onSelectTurn(activeSession.id, turn.id)}
                    >
                      <div className="turnNavStep">
                        <span>第 {activeSession.turns.length - index} 轮</span>
                        <StatusTag status={turn.status} />
                      </div>
                      <div className="turnNavText">{turn.question}</div>
                    </button>
                  ))}
                </div>
              ) : (
                <div className="turnNavEmpty">当前会话还没有问答记录，发起第一个问题后会在这里出现。</div>
              )}
            </div>
          </>
        )}
      </div>
    </aside>
  );
}

function ChatStream({
  session,
  onCreateSession,
  creatingSession,
}: {
  session: ConversationSession | null;
  onCreateSession: () => void;
  creatingSession: boolean;
}) {
  if (!session || !session.turns.length) {
    return (
      <section className="chatStream emptyChat">
        <div className="emptyHeroMark">
          <Sparkles size={28} />
        </div>
        <div className="emptyEyebrow">AIR QUALITY DECISION SUPPORT</div>
        <h2>{session ? "开始本次空气质量研判" : "面向决策的空气质量智能研判"}</h2>
        <p>融合模式预报、实时监测、气象条件与专家规则，形成可追溯的污染研判、预警判断和管控建议。</p>
        <div className="capabilityGrid">
          <div><BarChart3 size={18} /><span>污染过程研判</span></div>
          <div><ShieldCheck size={18} /><span>预警响应判断</span></div>
          <div><Target size={18} /><span>精准管控建议</span></div>
        </div>
        {!session && (
          <button className="emptyPrimaryAction" type="button" onClick={onCreateSession} disabled={creatingSession}>
            <Plus size={17} />
            {creatingSession ? "正在创建..." : "创建分析会话"}
            <ArrowRight size={17} />
          </button>
        )}
      </section>
    );
  }

  return (
    <section className="chatStream">
      {session.turns.map((turn) => (
        <ChatTurn key={turn.id} turn={turn} selected={turn.id === session.selectedTurnId} />
      ))}
      {session.running && <div className="typing">正在持续更新当前会话的最新分析...</div>}
    </section>
  );
}

function ChatTurn({ turn, selected }: { turn: Turn; selected: boolean }) {
  const final = latestEvent(turn.events, "final")?.payload?.answer;
  const artifacts = collectArtifacts(turn.events);
  const allImageArtifacts = artifacts.filter((artifact) => artifact.kind === "image");
  const imageArtifacts = selectCoreImageArtifacts(allImageArtifacts, turn.question);
  const fileArtifacts = artifacts.filter((artifact) => artifact.kind !== "image");

  return (
    <article id={`turn-${turn.id}`} className="turn" data-selected={selected}>
      <div className="bubble userBubble">
        <User size={18} />
        <p>{turn.question}</p>
      </div>

      <div className="bubble assistantBubble">
        <Bot size={19} />
        <div className="assistantContent">
          <ThinkingBlock events={turn.events} question={turn.question} status={turn.status} />

          {!final && turn.status !== "error" && <p className="muted">正在分析中，下面会继续更新步骤摘要与最终回答。</p>}
          {turn.status === "error" && turn.error && <p className="errorText">{turn.error}</p>}
          {final && <FormattedAnswer text={final} />}

          {imageArtifacts.length > 0 && (
            <section className="coreFiguresSection">
              <header className="artifactSectionHeader">
                <div>
                  <span className="artifactIcon"><Image size={16} /></span>
                  <div>
                    <strong>核心研判图</strong>
                    <span>优先呈现最能支撑结论的趋势与空间证据</span>
                  </div>
                </div>
                <span className="selectionCount">精选 {imageArtifacts.length} / {allImageArtifacts.length}</span>
              </header>
              <div className="inlineImages" data-count={imageArtifacts.length}>
                {imageArtifacts.map((artifact, index) => (
                  <figure key={artifact.path} data-featured={index === 0}>
                    <img src={artifactUrl(artifact.path)} alt={artifact.label} />
                    <figcaption>
                      <span>图 {index + 1}</span>
                      {artifact.label}
                    </figcaption>
                  </figure>
                ))}
              </div>
            </section>
          )}

          {fileArtifacts.length > 0 && (
            <div className="supportFiles">
              {fileArtifacts.slice(0, 5).map((artifact) => (
                <a key={artifact.path} href={artifactUrl(artifact.path)} target="_blank" rel="noreferrer">
                  <FileText size={14} />
                  {artifact.label}
                </a>
              ))}
            </div>
          )}
        </div>
      </div>
    </article>
  );
}

function ThinkingBlock({
  events,
  question,
  status,
}: {
  events: EventItem[];
  question: string;
  status: Turn["status"];
}) {
  const plan = latestEvent(events, "plan")?.payload;
  const todos = (latestEvent(events, "todo")?.payload?.todos ?? []) as TodoPayload[];
  const toolCalls = events.filter((event) => event.type === "tool_call");
  const toolResults = events.filter((event) => event.type === "tool_result");

  return (
    <details className="thinkingCard" open={status === "running"}>
      <summary className="thinkingHeader">
        <div className="thinkingHeaderTitle">
          <ListChecks size={18} />
          <div>
            <h3>分析过程与证据链</h3>
            <p>查看任务步骤、数据工具和结果摘要</p>
          </div>
        </div>
        <span className="thinkingStatus" data-status={status}>
          {status === "running" ? "分析中" : status === "error" ? "异常" : `${todos.length} 个步骤`}
        </span>
      </summary>

      <div className="thinkingBody">
        <div className="objective">
          <span>当前问题</span>
          <strong>{question}</strong>
        </div>

        {!todos.length && <p className="emptyText">正在生成 Todo List...</p>}

        <ol className="thinkingList">
          {todos.map((todo, index) => {
            const planStep = (plan?.steps ?? []).find((step: any) => step.id === todo.id);
            const call = toolCalls.find((event) => event.payload.step_id === todo.id);
            const resultEvent = [...toolResults].reverse().find((event) => event.payload.step_id === todo.id);
            const result = resultEvent?.payload as ToolResultPayload | undefined;
            const tool = result?.data?.display_tool ?? call?.payload?.tool ?? planStep?.tool_hint ?? "reasoning";
            const summary = buildStepSummary({
              planStep,
              question,
              result,
              status: todo.status,
              title: todo.title,
            });
            const artifactHint = summarizeArtifacts(result?.artifacts ?? []);

            return (
              <li key={todo.id} data-status={todo.status}>
                <div className="stepHead">
                  <StatusIcon status={todo.status} />
                  <div>
                    <span>Step {index + 1}</span>
                    <h3>{todo.title}</h3>
                  </div>
                </div>

                <div className="stepMetaRow">
                  <div className="toolLine">
                    <Wrench size={15} />
                    <span>{describeTool(tool)}</span>
                  </div>
                  {artifactHint && <div className="artifactChip">{artifactHint}</div>}
                </div>

                {summary && <p className="toolSummary">{summary}</p>}
              </li>
            );
          })}
        </ol>

        {status === "done" && <div className="timelineHint">本轮分析已完成，结果已整理为可直接阅读的研判结论。</div>}
      </div>
    </details>
  );
}

function FormattedAnswer({ text }: { text: string }) {
  const blocks = parseAnswerBlocks(text);
  const firstParagraphIndex = blocks.findIndex((block) => block.type === "paragraph");

  return (
    <section className="answerPanel">
      <div className="answerHeader">
        <div>
          <div className="answerEyebrow">
            <Sparkles size={14} />
            最终回答
          </div>
          <h3>分析结论</h3>
        </div>
      </div>

      <div className="answerBody">
        {blocks.map((block, index) => {
          if (block.type === "heading") {
            const HeadingTag = block.level <= 1 ? "h3" : "h4";
            return (
              <HeadingTag key={`heading-${index}`} className="answerHeading">
                {renderInlineText(block.text)}
              </HeadingTag>
            );
          }

          if (block.type === "unordered-list") {
            return (
              <ul key={`ul-${index}`} className="answerList">
                {block.items.map((item, itemIndex) => (
                  <li key={`ul-item-${itemIndex}`}>{renderInlineText(item)}</li>
                ))}
              </ul>
            );
          }

          if (block.type === "ordered-list") {
            return (
              <ol key={`ol-${index}`} className="answerList ordered">
                {block.items.map((item, itemIndex) => (
                  <li key={`ol-item-${itemIndex}`}>{renderInlineText(item)}</li>
                ))}
              </ol>
            );
          }

          const isLead = index === firstParagraphIndex;
          const isKeyPoint = /^\s*\*\*.+\*\*/.test(block.text);
          return (
            <p
              key={`p-${index}`}
              className={[
                "answerParagraph",
                isLead ? "leadAnswer" : "",
                isKeyPoint ? "keyAnswer" : "",
              ]
                .filter(Boolean)
                .join(" ")}
            >
              {renderInlineText(block.text)}
            </p>
          );
        })}
      </div>
    </section>
  );
}

function SessionStatusTag({ session }: { session: ConversationSession }) {
  const status = getSessionStatus(session);
  const labelMap: Record<string, string> = {
    done: "已完成",
    empty: "未开始",
    error: "异常",
    running: "进行中",
  };

  return (
    <span className="historyStatusTag" data-status={status}>
      {labelMap[status]}
    </span>
  );
}

function StatusTag({ status }: { status: Turn["status"] }) {
  const labelMap: Record<Turn["status"], string> = {
    done: "已完成",
    error: "异常",
    running: "进行中",
  };

  return (
    <span className="historyStatusTag" data-status={status}>
      {labelMap[status]}
    </span>
  );
}

function StatusIcon({ status }: { status: string }) {
  if (status === "completed") return <CheckCircle2 size={18} />;
  if (status === "in_progress") return <Clock3 size={18} />;
  if (status === "blocked") return <Activity size={18} />;
  return <Circle size={18} />;
}

async function buildNewSession() {
  const backendSessionId = await createSession();
  return createClientSession(backendSessionId);
}

function createClientSession(backendSessionId: string): ConversationSession {
  const now = new Date().toISOString();
  return {
    id: crypto.randomUUID(),
    backendSessionId,
    createdAt: now,
    updatedAt: now,
    draftInput: samplePrompts[0],
    running: false,
    selectedTurnId: "",
    title: "新会话",
    turns: [],
  };
}

function migrateLegacyState(legacy: LegacyPersistedState) {
  if (!legacy.sessionId) return null;
  const turns = Array.isArray(legacy.turns) ? legacy.turns : [];
  const latestTimestamp =
    turns[turns.length - 1]?.events[turns[turns.length - 1]?.events.length - 1]?.created_at ||
    new Date().toISOString();
  return {
    id: crypto.randomUUID(),
    backendSessionId: legacy.sessionId,
    createdAt: latestTimestamp,
    updatedAt: latestTimestamp,
    draftInput: typeof legacy.input === "string" ? legacy.input : samplePrompts[0],
    running: turns.some((turn) => turn.status === "running"),
    selectedTurnId: legacy.selectedTurnId || turns[turns.length - 1]?.id || "",
    title: turns.length ? buildSessionTitle(turns[0].question) : "新会话",
    turns,
  } satisfies ConversationSession;
}

async function createSession(): Promise<string> {
  const response = await fetch("/api/sessions", { method: "POST" });
  if (!response.ok) throw new Error(`创建会话失败：HTTP ${response.status}`);
  const data = await response.json();
  return data.session_id;
}

function postMessage(sessionId: string, content: string) {
  return fetch(`/api/sessions/${sessionId}/messages`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content }),
  });
}

function latestEvent(events: EventItem[], type: string) {
  return [...events].reverse().find((event) => event.type === type);
}

function collectArtifacts(events: EventItem[]) {
  const found: Artifact[] = [];
  for (const event of events) {
    if (event.type === "artifact") found.push(...(event.payload.artifacts ?? []));
    if (event.type === "final") found.push(...(event.payload.artifacts ?? []));
  }
  const seen = new Set<string>();
  return found.filter((artifact) => {
    if (seen.has(artifact.path)) return false;
    seen.add(artifact.path);
    return true;
  });
}

function selectCoreImageArtifacts(images: Artifact[], question: string, limit = 3) {
  const normalizedQuestion = question.toLowerCase();
  const wantsSpatial = /空间|高值|热点|分布|区域|spatial|map|hotspot/.test(normalizedQuestion);
  const wantsMeteorology = /气象|风场|风速|边界层|湿度|降水|meteorolog|wind/.test(normalizedQuestion);
  const wantsTrend = /未来|趋势|过程|时序|逐日|逐小时|日期|timeseries|time-series/.test(normalizedQuestion);
  const bestByStem = new Map<string, { artifact: Artifact; score: number; order: number }>();

  images.forEach((artifact, order) => {
    const pathName = artifact.path.replace(/\\/g, "/").split("/").pop() ?? artifact.path;
    const stem = pathName.replace(/\.(png|svg|jpg|jpeg|webp)$/i, "").toLowerCase();
    const searchable = `${stem} ${artifact.label}`.toLowerCase();
    let score = 0;

    if (searchable.includes("city_mean_timeseries")) score += 120;
    if (searchable.includes("corrected_spatial_peak")) score += 110;
    if (searchable.includes("correction_difference_spatial")) score += 100;
    if (/timeseries|time-series|时序|趋势/.test(searchable)) score += 50;
    if (/spatial_peak|hotspot|空间分布|高值分布/.test(searchable)) score += 45;
    if (/meteorolog|wind|气象|风场/.test(searchable)) score += 42;
    if (wantsTrend && /timeseries|time-series|时序|趋势/.test(searchable)) score += 28;
    if (wantsSpatial && /spatial|hotspot|空间|高值/.test(searchable)) score += 26;
    if (wantsMeteorology && /meteorolog|wind|气象|风场/.test(searchable)) score += 28;
    if (stem.startsWith("station_")) score -= 55;
    if (stem.startsWith("raw_")) score -= 25;
    if (stem.includes("spatial_factor")) score -= 18;
    if (/\.png$/i.test(pathName)) score += 8;

    const existing = bestByStem.get(stem);
    if (!existing || score > existing.score) bestByStem.set(stem, { artifact, score, order });
  });

  return [...bestByStem.values()]
    .sort((left, right) => right.score - left.score || left.order - right.order)
    .slice(0, limit)
    .map((item) => item.artifact);
}

function artifactUrl(path: string) {
  return `/api/artifacts?path=${encodeURIComponent(path)}`;
}

function getSessionStatus(session: ConversationSession) {
  if (session.running) return "running";
  if (session.error || session.turns.some((turn) => turn.status === "error")) return "error";
  if (!session.turns.length) return "empty";
  return "done";
}

function buildSessionTitle(question: string) {
  return trimText(stripMarkdown(question), 16) || "新会话";
}

function getSessionHeadline(session: ConversationSession) {
  if (!session.turns.length) return "尚未开始提问";
  return session.turns[0].question;
}

function getSessionPreview(session: ConversationSession) {
  const latestTurn = session.turns[session.turns.length - 1];
  if (!latestTurn) return "点击进入该会话并开始新的分析。";
  return getTurnPreview(latestTurn);
}

function formatSessionTimestamp(session: ConversationSession) {
  return formatDateTime(session.updatedAt, session.running ? "正在更新" : "刚刚");
}

function formatTurnTimestamp(turn: Turn) {
  const createdAt = latestEvent(turn.events, "final")?.created_at || turn.events[turn.events.length - 1]?.created_at;
  return formatDateTime(createdAt, turn.status === "running" ? "正在更新" : "刚刚");
}

function formatDateTime(value?: string, fallback = "最近更新") {
  if (!value) return fallback;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return fallback;

  return new Intl.DateTimeFormat("zh-CN", {
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    month: "numeric",
  }).format(date);
}

function getTurnPreview(turn: Turn) {
  if (turn.status === "error" && turn.error) return trimText(stripMarkdown(turn.error), 54);

  const finalAnswer = latestEvent(turn.events, "final")?.payload?.answer;
  if (typeof finalAnswer === "string" && finalAnswer.trim()) {
    return trimText(stripMarkdown(finalAnswer), 72);
  }

  const inProgressTodo = ((latestEvent(turn.events, "todo")?.payload?.todos ?? []) as TodoPayload[]).find(
    (todo) => todo.status === "in_progress"
  );
  if (inProgressTodo) return `进行中：${inProgressTodo.title}`;
  return turn.status === "running" ? "正在整理本轮分析..." : "等待结果返回";
}

function buildStepSummary({
  planStep,
  question,
  result,
  status,
  title,
}: {
  planStep?: any;
  question: string;
  result?: ToolResultPayload;
  status: string;
  title: string;
}) {
  const toolHint = planStep?.tool_hint ?? result?.tool ?? "reasoning";

  if (toolHint === "final" && status === "completed") {
    return "已汇总前序步骤的证据与图表，并生成最终回答。";
  }

  if (!result) {
    if (status === "in_progress") return "正在执行该步骤，新的摘要会在工具返回后显示。";
    if (status === "blocked") return "该步骤已阻塞，等待进一步处理。";
    if (status === "completed") return "本步骤已完成。";
    return "等待前序步骤完成后继续执行。";
  }

  const nestedResults = Array.isArray(result.data?.tool_results)
    ? (result.data?.tool_results as ToolResultPayload[])
    : [];
  const candidateSummaries = nestedResults
    .map((item) => humanizeObservedTool(item, title || question))
    .filter(Boolean);

  if (candidateSummaries.length) {
    return trimText(candidateSummaries.join("；"), 180);
  }

  const digest = cleanSentence(result.data?.thinking_digest);
  if (digest) return trimText(digest, 180);

  return trimText(cleanSentence(result.summary) || "本步骤已完成。", 180);
}

function humanizeObservedTool(result: ToolResultPayload, fallbackText: string) {
  const summary = cleanSentence(result.summary);
  const data = result.data ?? {};

  if (result.tool === "web_search") {
    const query = String(data.query || fallbackText).trim();
    const answer = cleanSentence(data.answer);
    const results = Array.isArray(data.results) ? data.results.length : 0;
    if (results > 0 && containsChinese(answer)) return `已查询“${query}”，找到 ${results} 条相关线索，发现${trimText(answer, 88)}`;
    if (results > 0) return `已查询“${query}”，找到 ${results} 条相关线索。`;
    return `已查询“${query}”，${summary || "结果已返回。"} `;
  }

  if (result.tool === "cmaq_forecast_qa") {
    const rawSummary = typeof data.summary === "object" && data.summary ? data.summary : {};
    const metric = String(rawSummary.metric || rawSummary.field || "指标").trim();
    const period = rawSummary.period ?? {};
    const periodText =
      period?.start && period?.end ? `，时间范围 ${period.start} 至 ${period.end}` : "";
    return `已提取 ${metric} 的 CMAQ 结果${periodText}。${summary || "结果已返回。"} `;
  }

  if (result.tool === "cmaq_plot_data") {
    const rawSummary = typeof data.summary === "object" && data.summary ? data.summary : {};
    const variable = String(rawSummary.variable || "CMAQ").trim();
    const plots = Array.isArray(rawSummary.outputs)
      ? rawSummary.outputs.map((item: any) => item?.plot).filter(Boolean)
      : [];
    const plotText = plots.length ? `，并生成了${plots.join("、")}图件` : "";
    return `已提取 ${variable} 绘图数据${plotText}，结果已返回。`;
  }

  if (result.tool === "pollution_warning") {
    const rawSummary = typeof data.summary === "object" && data.summary ? data.summary : {};
    const warning = typeof rawSummary.warning === "object" && rawSummary.warning ? rawSummary.warning : {};
    const level = String((warning as any).warning_level || "").trim();
    return level ? `已完成成都污染预警研判，结论为 ${level}。` : summary || "已完成污染预警研判。";
  }

  if (result.tool === "read_file") {
    return summary || "已读取相关文件内容。";
  }

  if (result.tool === "current_time") {
    return summary || "已获取当前时间。";
  }

  if (result.tool === "read_skill") {
    return summary || "已读取相关技能说明。";
  }

  if (result.tool === "memory" || result.tool === "read_memory") {
    return summary || "已处理记忆信息。";
  }

  if (result.tool === "shell") {
    return summary || "已执行必要命令。";
  }

  return summary || `已完成 ${result.tool} 步骤。`;
}

function summarizeArtifacts(artifacts: Artifact[]) {
  if (!artifacts.length) return "";

  const counts = artifacts.reduce(
    (acc, artifact) => {
      if (artifact.kind === "image") acc.images += 1;
      else acc.files += 1;
      return acc;
    },
    { files: 0, images: 0 }
  );

  const labels = [];
  if (counts.images) labels.push(`${counts.images} 张图`);
  if (counts.files) labels.push(`${counts.files} 份文件`);
  return labels.length ? `已返回 ${labels.join(" / ")}` : "";
}

function describeTool(tool: string) {
  const labels: Record<string, string> = {
    cmaq_forecast_qa: "CMAQ 问答分析",
    cmaq_plot_data: "CMAQ 图表生成",
    cmaq_forecast_correction: "CMAQ 预报订正",
    pollution_warning: "污染预警研判",
    current_time: "时间查询",
    final: "最终回答整理",
    list_skills: "技能清单",
    memory: "记忆写入",
    read_file: "文件读取",
    read_memory: "记忆读取",
    read_skill: "技能说明",
    reasoning: "上下文推理",
    shell: "受控命令",
    web_search: "联网检索",
  };

  return labels[tool] ?? tool;
}

function parseAnswerBlocks(text: string): AnswerBlock[] {
  const normalizedLines = text.replace(/\r\n/g, "\n").split("\n");
  const blocks: AnswerBlock[] = [];
  let paragraphBuffer: string[] = [];
  let listBuffer: { ordered: boolean; items: string[] } | null = null;

  const flushParagraph = () => {
    if (!paragraphBuffer.length) return;
    const paragraph = paragraphBuffer.join(" ").replace(/\s+/g, " ").trim();
    if (paragraph) blocks.push({ type: "paragraph", text: paragraph });
    paragraphBuffer = [];
  };

  const flushList = () => {
    if (!listBuffer || !listBuffer.items.length) return;
    blocks.push({
      type: listBuffer.ordered ? "ordered-list" : "unordered-list",
      items: listBuffer.items,
    });
    listBuffer = null;
  };

  for (const rawLine of normalizedLines) {
    const line = rawLine.trim();

    if (!line) {
      flushParagraph();
      flushList();
      continue;
    }

    const headingMatch = line.match(/^(#{1,3})\s+(.+)$/);
    if (headingMatch) {
      flushParagraph();
      flushList();
      blocks.push({ type: "heading", level: headingMatch[1].length, text: headingMatch[2].trim() });
      continue;
    }

    const unorderedMatch = line.match(/^[-*]\s+(.+)$/);
    if (unorderedMatch) {
      flushParagraph();
      if (!listBuffer || listBuffer.ordered) listBuffer = { ordered: false, items: [] };
      listBuffer.items.push(unorderedMatch[1].trim());
      continue;
    }

    const orderedMatch = line.match(/^\d+\.\s+(.+)$/);
    if (orderedMatch) {
      flushParagraph();
      if (!listBuffer || !listBuffer.ordered) listBuffer = { ordered: true, items: [] };
      listBuffer.items.push(orderedMatch[1].trim());
      continue;
    }

    flushList();
    paragraphBuffer.push(line);
  }

  flushParagraph();
  flushList();

  return blocks.length ? blocks : [{ type: "paragraph", text: text.trim() }];
}

function renderInlineText(text: string) {
  const parts: React.ReactNode[] = [];
  const pattern = /(\*\*[^*]+\*\*|`[^`]+`|\[[^\]]+\]\([^)]+\))/g;
  let lastIndex = 0;
  let match: RegExpExecArray | null = null;

  while ((match = pattern.exec(text)) !== null) {
    if (match.index > lastIndex) {
      parts.push(text.slice(lastIndex, match.index));
    }

    const token = match[0];
    if (token.startsWith("**")) {
      parts.push(
        <strong key={`${match.index}-strong`} className="answerStrong">
          {token.slice(2, -2)}
        </strong>
      );
    } else if (token.startsWith("`")) {
      parts.push(
        <code key={`${match.index}-code`} className="answerCode">
          {token.slice(1, -1)}
        </code>
      );
    } else {
      const linkMatch = token.match(/^\[([^\]]+)\]\(([^)]+)\)$/);
      if (linkMatch) {
        parts.push(
          <a
            key={`${match.index}-link`}
            className="answerLink"
            href={linkMatch[2]}
            target="_blank"
            rel="noreferrer"
          >
            {linkMatch[1]}
          </a>
        );
      }
    }

    lastIndex = match.index + token.length;
  }

  if (lastIndex < text.length) {
    parts.push(text.slice(lastIndex));
  }

  return parts.length ? parts : text;
}

function stripMarkdown(text: string) {
  return text
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, "$1")
    .replace(/\*\*/g, "")
    .replace(/`/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

function trimText(text: string, maxLength: number) {
  const cleaned = text.replace(/\s+/g, " ").trim();
  if (cleaned.length <= maxLength) return cleaned;
  return `${cleaned.slice(0, maxLength).trimEnd()}...`;
}

function cleanSentence(value: unknown) {
  return typeof value === "string" ? value.replace(/\s+/g, " ").trim() : "";
}

function containsChinese(text: string) {
  return /[\u4e00-\u9fff]/.test(text);
}

function sortSessionsByUpdatedAt(sessions: ConversationSession[]) {
  return [...sessions].sort((left, right) => {
    const leftTime = new Date(left.updatedAt).getTime();
    const rightTime = new Date(right.updatedAt).getTime();
    return rightTime - leftTime;
  });
}

createRoot(document.getElementById("root")!).render(<App />);
