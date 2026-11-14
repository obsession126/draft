"use client";

import Link from "next/link";
import { FormEvent, useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { CrewProfile, Dashboard, missionApi, ProfileReport } from "@/lib/api";
import styles from "./chat.module.css";

const AUTH_EVENT = "mission-auth-change";
const PROFILE_STORAGE_KEY = "mission-profile-id";
const SUGGESTIONS = [
  {
    icon: "◷",
    title: "Mission snapshot",
    prompt: "Summarize the latest mission data. What is known and what remains uncertain?",
  },
  {
    icon: "⌁",
    title: "Explain a finding",
    prompt: "Which report findings deserve attention, and what evidence supports them?",
  },
  {
    icon: "✧",
    title: "Spaceflight context",
    prompt: "How can sleep and isolation affect astronauts on a long mission, according to NASA?",
  },
  {
    icon: "⌗",
    title: "Check data quality",
    prompt: "Which measurements are missing or low quality, and how does that limit the report?",
  },
];

type Evidence = {
  id: string;
  label: string;
  detail: string;
  url?: string;
};

type SuggestedAction = {
  id: string;
  text: string;
};

type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  text: string;
  evidence?: Evidence[];
  actions?: SuggestedAction[];
};

type ChatThread = {
  id: string;
  title: string;
  updatedAt: number;
  messages: ChatMessage[];
};

type ChatResponse = {
  reply: {
    answer: string;
    evidence: Evidence[];
    actions: SuggestedAction[];
  };
};

function subscribeToToken(onChange: () => void) {
  window.addEventListener(AUTH_EVENT, onChange);
  return () => window.removeEventListener(AUTH_EVENT, onChange);
}

function getTokenSnapshot() {
  return window.sessionStorage.getItem("mission-api-token") ?? "";
}

function getServerTokenSnapshot() {
  return "";
}

function formatTime(value: string | null | undefined) {
  if (!value) return "Awaiting telemetry";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Measurement time unavailable";
  return new Intl.DateTimeFormat("en", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function getStatusLabel(status: string | null | undefined) {
  if (!status) return "Awaiting data";
  const labels: Record<string, string> = {
    normal: "No detector review",
    anomaly_review: "Detector review",
    data_quality_review: "Data quality review",
    insufficient_data: "Insufficient data",
  };
  return labels[status] ?? status.replaceAll("_", " ");
}

async function sendToChatbot(
  token: string,
  profileId: string,
  message: string,
  history: Array<{ role: "user" | "model"; text: string }>,
): Promise<ChatResponse> {
  let response: Response;
  try {
    response = await fetch("/api/chatbot/chat", {
      method: "POST",
      headers: {
        Authorization: `Token ${token}`,
        "Content-Type": "application/json",
        Accept: "application/json",
      },
      body: JSON.stringify({ profile_id: profileId, message, history }),
      cache: "no-store",
    });
  } catch {
    throw new Error("Cannot reach the mission chat. Check that the chatbot service is running.");
  }

  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    throw new Error(
      typeof payload?.error === "string" ? payload.error : `Chat request failed (${response.status}).`,
    );
  }
  if (
    !payload ||
    typeof payload.reply?.answer !== "string" ||
    !Array.isArray(payload.reply.evidence) ||
    !Array.isArray(payload.reply.actions)
  ) {
    throw new Error("The chatbot returned an incomplete response.");
  }
  return payload as ChatResponse;
}

export default function HealthCopilotPage() {
  const token = useSyncExternalStore(subscribeToToken, getTokenSnapshot, getServerTokenSnapshot);
  const [profiles, setProfiles] = useState<CrewProfile[]>([]);
  const [profileId, setProfileId] = useState("");
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [report, setReport] = useState<ProfileReport | null>(null);
  const [contextError, setContextError] = useState("");
  const [loadingProfiles, setLoadingProfiles] = useState(true);
  const [loadingContext, setLoadingContext] = useState(false);
  const [consentAccepted, setConsentAccepted] = useState(false);
  const [threads, setThreads] = useState<ChatThread[]>([]);
  const [activeThreadId, setActiveThreadId] = useState("");
  const [draft, setDraft] = useState("");
  const [pending, setPending] = useState(false);
  const [chatError, setChatError] = useState("");
  const messageEndRef = useRef<HTMLDivElement>(null);

  const activeThread = useMemo(
    () => threads.find((thread) => thread.id === activeThreadId) ?? null,
    [activeThreadId, threads],
  );
  const messages = activeThread?.messages ?? [];
  const selectedProfile = profiles.find((profile) => profile.profile_id === profileId);
  const latest = dashboard?.latest;
  const latestIsSynthetic = latest?.payload.is_synthetic === true;
  const hasProfileData = (report?.window.sample_count ?? 0) > 0;
  const realDataBlocked =
    hasProfileData &&
    (latest ? !latestIsSynthetic : report?.window.is_synthetic !== true);
  const contextReady = Boolean(dashboard && report);
  const canSend =
    Boolean(token && profileId && contextReady && consentAccepted) &&
    !loadingContext &&
    !realDataBlocked &&
    !pending &&
    Boolean(draft.trim());

  useEffect(() => {
    if (!token) {
      setLoadingProfiles(false);
      setProfiles([]);
      setProfileId("");
      setDashboard(null);
      setReport(null);
      setThreads([]);
      setActiveThreadId("");
      setConsentAccepted(false);
      return;
    }

    let active = true;
    setLoadingProfiles(true);
    missionApi.profiles(token)
      .then((availableProfiles) => {
        if (!active) return;
        const savedProfileId = window.sessionStorage.getItem(PROFILE_STORAGE_KEY);
        const selectedProfile =
          availableProfiles.find((profile) => profile.profile_id === savedProfileId) ??
          availableProfiles[0];
        setProfiles(availableProfiles);
        setProfileId(selectedProfile?.profile_id ?? "");
        if (selectedProfile) {
          window.sessionStorage.setItem(PROFILE_STORAGE_KEY, selectedProfile.profile_id);
        } else {
          window.sessionStorage.removeItem(PROFILE_STORAGE_KEY);
        }
        setContextError(
          availableProfiles.length
            ? ""
            : "No crew profiles are available for this account. Create one in mission control first.",
        );
      })
      .catch((error: unknown) => {
        if (active) {
          setContextError(error instanceof Error ? error.message : "Could not load crew profiles.");
        }
      })
      .finally(() => {
        if (active) setLoadingProfiles(false);
      });
    return () => {
      active = false;
    };
  }, [token]);

  useEffect(() => {
    if (!token || !profileId) return;
    let active = true;

    async function refreshContext() {
      setLoadingContext(true);
      try {
        const [nextDashboard, nextReport] = await Promise.all([
          missionApi.dashboard(token, profileId),
          missionApi.report(token, profileId),
        ]);
        if (!active) return;
        setDashboard(nextDashboard);
        setReport(nextReport);
        setContextError("");
      } catch (error) {
        if (active) {
          setContextError(error instanceof Error ? error.message : "Could not load mission context.");
        }
      } finally {
        if (active) setLoadingContext(false);
      }
    }

    void refreshContext();
    const timer = window.setInterval(() => void refreshContext(), 15_000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [profileId, token]);

  useEffect(() => {
    messageEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [activeThreadId, messages.length, pending]);

  function startNewChat() {
    setActiveThreadId("");
    setChatError("");
    setDraft("");
  }

  function changeProfile(nextProfileId: string) {
    setProfileId(nextProfileId);
    window.sessionStorage.setItem(PROFILE_STORAGE_KEY, nextProfileId);
    setThreads([]);
    setActiveThreadId("");
    setConsentAccepted(false);
    setDashboard(null);
    setReport(null);
    setChatError("");
  }

  async function submitMessage(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const question = draft.trim();
    if (!canSend || !question || !token || !profileId) return;

    const existingThread = activeThread;
    const threadId = existingThread?.id ?? crypto.randomUUID();
    const threadMessages = existingThread?.messages ?? [];
    const userMessage: ChatMessage = {
      id: crypto.randomUUID(),
      role: "user",
      text: question,
    };
    const updatedThread: ChatThread = existingThread
      ? {
          ...existingThread,
          updatedAt: Date.now(),
          messages: [...threadMessages, userMessage],
        }
      : {
          id: threadId,
          title: question.slice(0, 52),
          updatedAt: Date.now(),
          messages: [userMessage],
        };

    setThreads((current) =>
      existingThread
        ? current.map((thread) => (thread.id === threadId ? updatedThread : thread))
        : [updatedThread, ...current],
    );
    setActiveThreadId(threadId);
    setDraft("");
    setChatError("");
    setPending(true);

    try {
      const history = threadMessages.slice(-12).map((message) => ({
        role: message.role === "assistant" ? ("model" as const) : ("user" as const),
        text: message.text,
      }));
      const result = await sendToChatbot(token, profileId, question, history);
      const assistantMessage: ChatMessage = {
        id: crypto.randomUUID(),
        role: "assistant",
        text: result.reply.answer,
        evidence: result.reply.evidence,
        actions: result.reply.actions,
      };
      setThreads((current) =>
        current.map((thread) =>
          thread.id === threadId
            ? {
                ...thread,
                updatedAt: Date.now(),
                messages: [...thread.messages, assistantMessage],
              }
            : thread,
        ),
      );
    } catch (error) {
      setChatError(error instanceof Error ? error.message : "The assistant could not answer.");
    } finally {
      setPending(false);
    }
  }

  if (!token) {
    return (
      <main className={styles.signInRequired}>
        <div className={styles.signInCard}>
          <span className={styles.brandMark}>O</span>
          <p className={styles.eyebrow}>MISSION HEALTH COPILOT</p>
          <h1>Sign in to ask about mission data.</h1>
          <p>Your authenticated crew profile supplies the latest measurements and report evidence.</p>
          <Link className={styles.primaryButton} href="/">Go to mission control <span>→</span></Link>
        </div>
      </main>
    );
  }

  const analysisStatus = latest?.analysis_status ?? report?.summary.latest_analysis_status;
  const profileName = selectedProfile?.display_name || selectedProfile?.profile_id || "Crew profile";
  const profileInitial = profileName.slice(0, 1).toUpperCase();

  return (
    <main className={styles.chatApp}>
      <aside className={styles.sidebar}>
        <Link className={styles.brand} href="/" aria-label="Orbital Health mission control">
          <span className={styles.brandMark}>O</span>
          <span>ORBITAL <b>HEALTH</b></span>
        </Link>

        <button className={styles.newChatButton} type="button" onClick={startNewChat}>
          <span>＋</span> New chat
          <kbd>⌘ K</kbd>
        </button>

        <div className={styles.sidebarLabel}>RECENT CONVERSATIONS</div>
        <nav className={styles.threadList} aria-label="Recent conversations">
          {threads.map((thread) => (
            <button
              className={`${styles.threadButton} ${thread.id === activeThreadId ? styles.threadActive : ""}`}
              key={thread.id}
              onClick={() => {
                setActiveThreadId(thread.id);
                setChatError("");
              }}
              type="button"
              title={thread.title}
            >
              <span className={styles.threadIcon}>◌</span>
              <span>{thread.title}</span>
            </button>
          ))}
          {threads.length === 0 && <p className={styles.emptyThreads}>Your conversations stay in this tab.</p>}
        </nav>

        <div className={styles.sidebarBottom}>
          <div className={styles.contextCard}>
            <div className={styles.contextHeader}>
              <span className={styles.contextGlyph}>⌁</span>
              <span>MISSION CONTEXT</span>
            </div>
            <label htmlFor="crew-profile">CREW PROFILE</label>
            <select
              id="crew-profile"
              value={profileId}
              disabled={loadingProfiles || pending || profiles.length === 0}
              onChange={(event) => changeProfile(event.target.value)}
            >
              {profiles.map((profile) => (
                <option key={profile.profile_id} value={profile.profile_id}>
                  {profile.display_name || profile.profile_id}
                </option>
              ))}
            </select>
            <strong className={styles.missionName}>
              {selectedProfile?.mission_name || "Mission profile"}
            </strong>
            <span className={styles.missionPhase}>
              {selectedProfile?.mission_phase || "Phase unavailable"}
            </span>
            <div className={styles.contextDivider} />
            <div className={styles.contextStat}>
              <span>Report samples</span><b>{report?.window.sample_count ?? "—"}</b>
            </div>
            <div className={styles.contextStat}>
              <span>Profile references</span>
              <b>
                {report
                  ? `${report.window.baseline_ready_metric_count}/${report.metrics.length}`
                  : "—"}
              </b>
            </div>
            <div className={styles.contextStat}>
              <span>Quality issues</span><b>{report?.summary.current_quality_issue_count ?? "—"}</b>
            </div>
            <div className={styles.contextUpdated}>
              {formatTime(latest?.measured_at)}
            </div>
          </div>
          <Link className={styles.backToMission} href="/">
            <span>◫</span> Mission overview <span>↗</span>
          </Link>
          <div className={styles.accountRow}>
            <span className={styles.avatar}>{profileInitial}</span>
            <span className={styles.accountName}>{profileName}</span>
            <span className={styles.accountBadge}>CREW</span>
          </div>
        </div>
      </aside>

      <section className={styles.mainPanel}>
        <header className={styles.topbar}>
          <div className={styles.topbarTitle}>
            <span className={styles.assistantMark}>✳</span>
            <div>
              <strong>Health Copilot</strong>
              <span>Mission-aware · Evidence-linked</span>
            </div>
          </div>
          <div className={styles.topbarRight}>
            <span className={`${styles.statusBadge} ${styles[`status_${analysisStatus ?? "unknown"}`]}`}>
              <i /> {getStatusLabel(analysisStatus)}
            </span>
            <span className={styles.modelBadge}><i>✳</i> Gemini</span>
          </div>
        </header>

        <div className={styles.conversationScroll}>
          {contextError && <p className={styles.contextError} role="alert">{contextError}</p>}
          {loadingContext && !report && <div className={styles.loadingContext}>Loading authenticated mission context…</div>}
          {realDataBlocked && (
            <div className={styles.blockedNotice} role="alert">
              <strong>External AI is limited to synthetic demo data.</strong>
              <span>This profile contains non-synthetic measurements, so its health data will not be sent to Gemini. Select a synthetic demo profile to use the copilot.</span>
            </div>
          )}

          {!activeThread ? (
            <section className={styles.welcome}>
              <div className={styles.welcomeMark}><span>O</span><i /><i /></div>
              <p className={styles.eyebrow}>EVIDENCE-FIRST · MISSION-AWARE</p>
              <h1>Understand the signal.<br />Ask the copilot.</h1>
              <p className={styles.welcomeCopy}>
                Explore current readings, changes against this profile&apos;s observed history,
                report findings, and NASA&apos;s human-spaceflight research.
              </p>
              {report && (
                <div className={styles.snapshotStrip}>
                  <div><span>MISSION</span><b>{selectedProfile?.mission_name || "Crew profile"}</b></div>
                  <div><span>DATA WINDOW</span><b>{report.window.sample_count} samples</b></div>
                  <div><span>ANALYSIS</span><b>{getStatusLabel(analysisStatus)}</b></div>
                </div>
              )}
              <div className={styles.suggestions}>
                {SUGGESTIONS.map((suggestion, index) => (
                  <button
                    className={styles.suggestion}
                    key={suggestion.title}
                    onClick={() => setDraft(suggestion.prompt)}
                    type="button"
                  >
                    <span className={`${styles.suggestionIcon} ${styles[`suggestion_${index}`]}`}>
                      {suggestion.icon}
                    </span>
                    <span><b>{suggestion.title}</b><small>{suggestion.prompt}</small></span>
                    <i>↗</i>
                  </button>
                ))}
              </div>
              {!!report?.insights.length && (
                <div className={styles.latestFindings}>
                  <div className={styles.findingsHeading}>LATEST REPORT FINDINGS</div>
                  {report.insights.slice(0, 2).map((insight) => (
                    <button
                      className={styles.finding}
                      key={insight.code}
                      onClick={() => setDraft(`Explain this report finding: ${insight.title}. What evidence and limitations should I know?`)}
                      type="button"
                    >
                      <span className={`${styles.findingDot} ${styles[`severity_${insight.severity}`]}`} />
                      <span><b>{insight.title}</b><small>{insight.summary}</small></span>
                      <i>Ask →</i>
                    </button>
                  ))}
                </div>
              )}
            </section>
          ) : (
            <section className={styles.messages} aria-live="polite">
              <div className={styles.threadHeading}>
                <span>MISSION CONVERSATION</span>
                <span>{profileName} · {selectedProfile?.mission_name || "Mission"}</span>
              </div>
              {activeThread.messages.map((message) => (
                <article
                  className={`${styles.message} ${message.role === "user" ? styles.userMessage : styles.assistantMessage}`}
                  key={message.id}
                >
                  <span className={message.role === "assistant" ? styles.messageAssistantAvatar : styles.messageUserAvatar}>
                    {message.role === "assistant" ? "O" : profileInitial}
                  </span>
                  <div className={styles.messageBody}>
                    <div className={styles.messageAuthor}>
                      {message.role === "assistant" ? "Orbital Health Copilot" : profileName}
                    </div>
                    <p className={styles.messageText}>{message.text}</p>
                    {!!message.evidence?.length && (
                      <div className={styles.evidenceCard}>
                        <div className={styles.evidenceTitle}><span>⌁</span> EVIDENCE USED</div>
                        {message.evidence.map((source) => (
                          <div className={styles.evidenceRow} key={source.id}>
                            <span className={styles.evidenceIcon}>↗</span>
                            <span className={styles.evidenceCopy}>
                              <b>{source.label}</b><small>{source.detail}</small>
                            </span>
                            {source.url && (
                              <a href={source.url} target="_blank" rel="noopener noreferrer">Source</a>
                            )}
                          </div>
                        ))}
                      </div>
                    )}
                    {!!message.actions?.length && (
                      <div className={styles.actionCard}>
                        <div className={styles.actionTitle}>SUGGESTED CHECKS FROM THE REPORT</div>
                        {message.actions.map((action) => (
                          <p key={action.id}><span>→</span>{action.text}</p>
                        ))}
                      </div>
                    )}
                    {message.role === "assistant" && (
                      <div className={styles.messageFootnote}>Prototype interpretation only · not a diagnosis</div>
                    )}
                  </div>
                </article>
              ))}
              {pending && (
                <div className={styles.typing}>
                  <span className={styles.messageAssistantAvatar}>O</span>
                  <span className={styles.typingDots}><i /><i /><i /></span>
                  <span>Reviewing mission evidence</span>
                </div>
              )}
              <div ref={messageEndRef} />
            </section>
          )}
        </div>

        <footer className={styles.composerArea}>
          <div className={styles.composerWrap}>
            <label className={styles.consentRow}>
              <input
                type="checkbox"
                checked={consentAccepted}
                onChange={(event) => setConsentAccepted(event.target.checked)}
              />
              <span>
                I understand this sends the selected profile&apos;s synthetic health data and my
                question to Google AI Studio. Real telemetry is blocked.
              </span>
            </label>
            <form className={styles.composer} onSubmit={submitMessage}>
              <textarea
                aria-label="Ask the health copilot"
                maxLength={2_000}
                onChange={(event) => setDraft(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && !event.shiftKey) {
                    event.preventDefault();
                    event.currentTarget.form?.requestSubmit();
                  }
                }}
                placeholder="Ask about mission data, a report finding, or spaceflight health…"
                rows={2}
                value={draft}
              />
              <div className={styles.composerBottom}>
                <span>↵ to send <i>·</i> ⇧ ↵ for a new line</span>
                <button aria-label="Send message" className={styles.sendButton} disabled={!canSend} type="submit">
                  ↑
                </button>
              </div>
            </form>
            {chatError && <p className={styles.chatError} role="alert">{chatError}</p>}
            <p className={styles.disclaimer}>
              Prototype only — not a medical device or diagnosis. Follow onboard procedures
              and contact the mission medical officer for health concerns. Use synthetic data only.
            </p>
          </div>
        </footer>
      </section>
    </main>
  );
}
