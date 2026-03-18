'use client';

import { useEffect, useRef, useState, useCallback } from 'react';
import { repos, sessions, workflows as workflowsApi, migrations, type Repo, type Session, type Workflow, type WorkflowSubtask, type MigrationRecipe } from '@/lib/api';
import RecipePicker from '@/components/RecipePicker';
import MermaidBlock from '@/components/MermaidBlock';
import { useSessionStream, type WSMessage } from '@/lib/websocket';
import StructuredResult, { tryParseStructured } from '@/components/StructuredResult';
import ModelSelector from '@/components/ModelSelector';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  mode: 'ask' | 'plan' | 'agent';
  sessionId?: string;
  status?: string;
  partial?: boolean;
  canExploreDeeper?: boolean;
  timestamp: string;
}

interface ActivityEntry {
  timestamp: string;
  type: 'tool_call' | 'status' | 'error' | 'complete';
  turn?: number;
  tool?: string;
  detail?: string;
  result?: string;
}

type Mode = 'ask' | 'plan' | 'agent';

const MODE_META: Record<Mode, { label: string; color: string; bg: string; desc: string }> = {
  ask:   { label: 'Ask',   color: 'text-blue-700',   bg: 'bg-blue-100',   desc: 'Answer questions about the codebase (read-only)' },
  plan:  { label: 'Plan',  color: 'text-amber-700',  bg: 'bg-amber-100',  desc: 'Propose changes without writing files' },
  agent: { label: 'Agent', color: 'text-green-700',  bg: 'bg-green-100',  desc: 'Autonomous coding — decomposes goals, reads, writes, tests' },
};

const TOOL_ICONS: Record<string, { icon: string; color: string }> = {
  read_file:           { icon: '\u{1F4D6}', color: 'text-blue-400' },
  grep:                { icon: '\u{1F50D}', color: 'text-purple-400' },
  find_files:          { icon: '\u{1F50D}', color: 'text-purple-400' },
  list_dir:            { icon: '\u{1F4C2}', color: 'text-blue-300' },
  edit_file:           { icon: '\u270F\uFE0F', color: 'text-yellow-400' },
  write_file:          { icon: '\u270F\uFE0F', color: 'text-yellow-400' },
  delete_file:         { icon: '\u{1F5D1}\uFE0F', color: 'text-red-400' },
  run_command:         { icon: '\u26A1', color: 'text-orange-400' },
  propose_change:      { icon: '\u{1F4DD}', color: 'text-green-400' },
  update_memory:       { icon: '\u{1F9E0}', color: 'text-pink-400' },
  gcc_commit:          { icon: '\u{1F4E6}', color: 'text-green-400' },
  gcc_branch:          { icon: '\u{1F33F}', color: 'text-green-300' },
  gcc_context:         { icon: '\u{1F4CB}', color: 'text-cyan-400' },
  splunk_discover:     { icon: '\u{1F50E}', color: 'text-teal-400' },
  splunk_search:       { icon: '\u{1F4CA}', color: 'text-teal-400' },
  splunk_stats:        { icon: '\u{1F4C8}', color: 'text-teal-400' },
  splunk_saved_search: { icon: '\u{1F4CB}', color: 'text-teal-400' },
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function storageKey(repoId: string) {
  return `chat-history-${repoId}`;
}

function loadMessages(repoId: string): ChatMessage[] {
  if (typeof window === 'undefined' || !repoId) return [];
  try {
    const raw = localStorage.getItem(storageKey(repoId));
    return raw ? JSON.parse(raw) : [];
  } catch { return []; }
}

function saveMessages(repoId: string, msgs: ChatMessage[]) {
  if (typeof window === 'undefined' || !repoId) return;
  try {
    // Keep last 100 messages per repo
    localStorage.setItem(storageKey(repoId), JSON.stringify(msgs.slice(-100)));
  } catch { /* quota exceeded -- ignore */ }
}

function statusColor(status: string) {
  switch (status) {
    case 'running':   return 'text-blue-400';
    case 'completed': return 'text-green-400';
    case 'failed':    return 'text-red-400';
    case 'cancelled': return 'text-yellow-400';
    case 'paused':    return 'text-amber-400';
    case 'planning':  return 'text-purple-400';
    default:          return 'text-gray-400';
  }
}

function statusIcon(status: string) {
  switch (status) {
    case 'running':   return '\u27F3';
    case 'completed': return '\u2713';
    case 'failed':    return '\u2717';
    case 'cancelled': return '\u2298';
    case 'paused':    return '\u23F8';
    case 'planning':  return '\u2699';
    default:          return '\u2026';
  }
}

function getToolMeta(toolName: string) {
  return TOOL_ICONS[toolName] || { icon: '\u25B8', color: 'text-gray-400' };
}

// ---------------------------------------------------------------------------
// Code Block Component
// ---------------------------------------------------------------------------

function highlightSyntax(code: string, language: string): React.ReactNode[] {
  const lines = code.split('\n');
  return lines.map((line, i) => {
    const parts: React.ReactNode[] = [];
    let remaining = line;
    let key = 0;

    // Simple regex-based highlighting
    const patterns: [RegExp, string][] = [
      // Comments
      [/^(\s*)(\/\/.*)$/, 'text-gray-500 italic'],
      [/^(\s*)(#.*)$/, 'text-gray-500 italic'],
      // Strings (double-quoted)
      [/"(?:[^"\\]|\\.)*"/, 'text-green-400'],
      // Strings (single-quoted)
      [/'(?:[^'\\]|\\.)*'/, 'text-green-400'],
      // Keywords
      [/\b(def|class|return|import|from|if|else|elif|for|while|try|except|finally|with|as|yield|async|await|function|const|let|var|export|default|interface|type|extends|implements|new|throw|catch|public|private|protected|static|void|int|string|boolean|null|None|True|False|true|false|self)\b/, 'text-purple-400 font-bold'],
    ];

    // Check for full-line comment
    const commentMatch = remaining.match(/^(\s*)(\/\/.*|#.*)$/);
    if (commentMatch) {
      parts.push(
        <span key={key++}>{commentMatch[1]}</span>,
        <span key={key++} className="text-gray-500 italic">{commentMatch[2]}</span>
      );
      return <div key={i} className="leading-5">{parts.length > 0 ? parts : remaining}</div>;
    }

    // For non-comment lines, apply keyword and string highlighting
    const regex = /("(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*'|\b(?:def|class|return|import|from|if|else|elif|for|while|try|except|finally|with|as|yield|async|await|function|const|let|var|export|default|interface|type|extends|implements|new|throw|catch|public|private|protected|static|void|int|string|boolean|null|None|True|False|true|false|self)\b)/g;
    let lastIndex = 0;
    let match;

    while ((match = regex.exec(remaining)) !== null) {
      // Add text before match
      if (match.index > lastIndex) {
        parts.push(<span key={key++}>{remaining.slice(lastIndex, match.index)}</span>);
      }
      // Determine type
      const token = match[0];
      if (token.startsWith('"') || token.startsWith("'")) {
        parts.push(<span key={key++} className="text-green-400">{token}</span>);
      } else {
        parts.push(<span key={key++} className="text-purple-400 font-bold">{token}</span>);
      }
      lastIndex = regex.lastIndex;
    }
    if (lastIndex < remaining.length) {
      parts.push(<span key={key++}>{remaining.slice(lastIndex)}</span>);
    }

    return <div key={i} className="leading-5">{parts.length > 0 ? parts : remaining}</div>;
  });
}

function CodeBlock({ code, language }: { code: string; language: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch { /* clipboard not available */ }
  };

  // Mermaid diagram rendering
  if (language === 'mermaid') {
    return <MermaidBlock code={code} />;
  }

  // Diff detection
  if (language === 'diff' || code.split('\n').some(l => /^[+-]/.test(l) && !/^[+-]{3}/.test(l))) {
    return (
      <div className="my-2 rounded-lg overflow-hidden border border-gray-200 bg-gray-50">
        <div className="flex items-center justify-between px-3 py-1.5 bg-gray-100 border-b border-gray-200">
          <span className="text-[10px] font-mono text-gray-500">{language || 'diff'}</span>
          <button onClick={handleCopy} className="text-[10px] text-gray-400 hover:text-gray-600">
            {copied ? 'Copied!' : 'Copy'}
          </button>
        </div>
        <pre className="p-3 text-xs font-mono overflow-x-auto">
          {code.split('\n').map((line, i) => {
            let cls = 'text-gray-700';
            if (line.startsWith('+') && !line.startsWith('+++')) cls = 'text-green-700 bg-green-50';
            else if (line.startsWith('-') && !line.startsWith('---')) cls = 'text-red-700 bg-red-50';
            else if (line.startsWith('@@')) cls = 'text-blue-600';
            return <div key={i} className={cls}>{line}</div>;
          })}
        </pre>
      </div>
    );
  }

  return (
    <div className="my-2 rounded-lg overflow-hidden border border-gray-200 bg-gray-900">
      <div className="flex items-center justify-between px-3 py-1.5 bg-gray-800 border-b border-gray-700">
        <span className="text-[10px] font-mono text-gray-400">{language || 'code'}</span>
        <button onClick={handleCopy} className="text-[10px] text-gray-400 hover:text-gray-200 transition-colors">
          {copied ? 'Copied!' : 'Copy'}
        </button>
      </div>
      <pre className="p-3 text-xs font-mono overflow-x-auto text-gray-200">
        <code>{highlightSyntax(code, language)}</code>
      </pre>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Markdown renderer with code block support
// ---------------------------------------------------------------------------

function renderPlainMarkdown(text: string): React.ReactNode[] {
  const lines = text.split('\n');
  return lines.map((line, idx) => {
    // Code (inline)
    let processed = line.replace(/`([^`]+)`/g, '<code class="bg-gray-100 text-indigo-600 px-1 py-0.5 rounded text-xs">$1</code>');
    // Bold
    processed = processed.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    // Italic
    processed = processed.replace(/\*(.+?)\*/g, '<em>$1</em>');
    // Heading
    if (processed.startsWith('### ')) {
      return <div key={idx} className="font-semibold text-sm mt-2 mb-1" dangerouslySetInnerHTML={{ __html: processed.slice(4) }} />;
    }
    if (processed.startsWith('## ')) {
      return <div key={idx} className="font-bold text-sm mt-3 mb-1" dangerouslySetInnerHTML={{ __html: processed.slice(3) }} />;
    }
    // Bullet points
    if (/^\s*[-*]\s/.test(processed)) {
      const content = processed.replace(/^\s*[-*]\s/, '');
      return (
        <div key={idx} className="flex gap-2 ml-3">
          <span className="text-gray-400">&#8226;</span>
          <span dangerouslySetInnerHTML={{ __html: content }} />
        </div>
      );
    }
    // Numbered list
    if (/^\s*\d+\.\s/.test(processed)) {
      const match = processed.match(/^\s*(\d+)\.\s(.*)/);
      if (match) {
        return (
          <div key={idx} className="flex gap-2 ml-3">
            <span className="text-gray-400">{match[1]}.</span>
            <span dangerouslySetInnerHTML={{ __html: match[2] }} />
          </div>
        );
      }
    }
    // Empty line
    if (!processed.trim()) {
      return <div key={idx} className="h-2" />;
    }
    return (
      <div key={idx}>
        <span dangerouslySetInnerHTML={{ __html: processed }} />
      </div>
    );
  });
}

function renderMarkdown(text: string): React.ReactNode {
  if (!text) return null;

  // Split on fenced code blocks: ```lang\ncode\n```
  const parts = text.split(/(```[\s\S]*?```)/g);
  const elements: React.ReactNode[] = [];

  parts.forEach((part, i) => {
    if (part.startsWith('```') && part.endsWith('```')) {
      // Extract language and code
      const inner = part.slice(3, -3);
      const firstNewline = inner.indexOf('\n');
      const language = firstNewline > 0 ? inner.slice(0, firstNewline).trim() : '';
      const code = firstNewline > 0 ? inner.slice(firstNewline + 1) : inner;
      elements.push(<CodeBlock key={`code-${i}`} code={code} language={language} />);
    } else if (part.trim()) {
      elements.push(<div key={`text-${i}`}>{renderPlainMarkdown(part)}</div>);
    }
  });

  return <>{elements}</>;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function ChatPage() {
  // --- state ---
  const [repoList, setRepoList] = useState<Repo[]>([]);
  const [selectedRepoId, setSelectedRepoId] = useState('');
  const [branch, setBranch] = useState('main');
  const [mode, setMode] = useState<Mode>('ask');
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const [currentSession, setCurrentSession] = useState<Session | null>(null);
  const [showActivity, setShowActivity] = useState(true);
  const [activityLog, setActivityLog] = useState<ActivityEntry[]>([]);
  const [loadingRepos, setLoadingRepos] = useState(true);
  const [branchList, setBranchList] = useState<string[]>([]);
  const [currentBranch, setCurrentBranch] = useState('');
  const [branchSearch, setBranchSearch] = useState('');
  const [branchDropdownOpen, setBranchDropdownOpen] = useState(false);
  const [loadingBranches, setLoadingBranches] = useState(false);
  const [wsSessionId, setWsSessionId] = useState<string | null>(null);
  const [activeWorkflow, setActiveWorkflow] = useState<Workflow | null>(null);
  const [availableRecipes, setAvailableRecipes] = useState<MigrationRecipe[]>([]);
  const [selectedRecipeIds, setSelectedRecipeIds] = useState<string[]>([]);
  const [selectedModelId, setSelectedModelId] = useState('');
  const [modelOverrides, setModelOverrides] = useState<Record<string, any>>({});

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const activityEndRef = useRef<HTMLDivElement>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const branchRef = useRef<HTMLDivElement>(null);
  const workflowPollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // WebSocket streaming
  const { messages: wsMessages, connected: wsConnected, reconnecting: wsReconnecting, disconnect: wsDisconnect, clearMessages: wsClearMessages } = useSessionStream(wsSessionId);

  // --- process WebSocket messages into activity entries ---
  useEffect(() => {
    if (wsMessages.length === 0) return;
    const latest = wsMessages[wsMessages.length - 1];

    if (latest.type === 'turn') {
      const d = latest.data;
      const entry: ActivityEntry = {
        timestamp: new Date().toISOString(),
        type: 'tool_call',
        turn: d.turn,
        tool: d.tool,
        detail: d.detail || '',
        result: d.result || '',
      };
      setActivityLog(prev => [...prev, entry]);
    } else if (latest.type === 'complete') {
      const entry: ActivityEntry = {
        timestamp: new Date().toISOString(),
        type: 'complete',
        detail: latest.data.summary || 'Done',
      };
      setActivityLog(prev => [...prev, entry]);

      // Stop polling first to prevent duplicate messages
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }

      // Add assistant message from WS complete event
      const resultContent = latest.data.summary || 'Done.';
      setMessages(prev => {
        // Guard: skip if an assistant message for this session already exists
        if (wsSessionId && prev.some(m => m.role === 'assistant' && m.sessionId === wsSessionId && m.status)) {
          return prev;
        }
        return [
          ...prev,
          {
            id: `assistant-ws-${Date.now()}`,
            role: 'assistant',
            content: resultContent,
            mode,
            sessionId: wsSessionId || undefined,
            status: latest.data.success ? 'completed' : 'failed',
            partial: !!latest.data.partial,
            canExploreDeeper: !!latest.data.can_explore_deeper,
            timestamp: new Date().toISOString(),
          },
        ];
      });
      setSending(false);
      setWsSessionId(null);
    } else if (latest.type === 'error') {
      const entry: ActivityEntry = {
        timestamp: new Date().toISOString(),
        type: 'error',
        detail: latest.data.message || 'Unknown error',
      };
      setActivityLog(prev => [...prev, entry]);
    }
  }, [wsMessages]);

  // --- close branch dropdown on outside click ---
  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (branchRef.current && !branchRef.current.contains(e.target as Node)) {
        setBranchDropdownOpen(false);
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  // --- load repos on mount ---
  useEffect(() => {
    (async () => {
      try {
        const r = await repos.list();
        const list = Array.isArray(r) ? r : [];
        setRepoList(list);

        // Clean up localStorage for repos that no longer exist
        const validIds = new Set(list.map((repo) => repo.id));
        for (let i = localStorage.length - 1; i >= 0; i--) {
          const key = localStorage.key(i);
          if (key?.startsWith('chat-history-')) {
            const repoId = key.replace('chat-history-', '');
            if (!validIds.has(repoId)) {
              localStorage.removeItem(key);
            }
          }
        }

        if (list.length > 0) {
          setSelectedRepoId(list[0].id);
        } else {
          // No repos — clear all stale state
          setSelectedRepoId('');
          setBranchList([]);
          setBranch('main');
          setMessages([]);
        }
      } catch (err) {
        console.error('Failed to load repos:', err);
      } finally {
        setLoadingRepos(false);
      }
    })();
  }, []);

  // --- load available recipes on mount ---
  useEffect(() => {
    migrations.listRecipes()
      .then((r) => setAvailableRecipes(Array.isArray(r) ? r : []))
      .catch(() => setAvailableRecipes([]));
  }, []);

  // --- load branches + chat history when repo changes ---
  useEffect(() => {
    if (selectedRepoId) {
      setMessages(loadMessages(selectedRepoId));
      // Reset branch state for new repo
      setBranchList([]);
      setCurrentBranch('');
      setBranch('main');
      setLoadingBranches(true);
      repos.branches(selectedRepoId)
        .then((r) => {
          const list = r.branches || [];
          const active = r.current_branch || '';
          setBranchList(list);
          setCurrentBranch(active);
          // Auto-select: prefer workspace's current branch, then 'main', then first
          if (active && list.includes(active)) {
            setBranch(active);
          } else if (list.includes('main')) {
            setBranch('main');
          } else if (list.length > 0) {
            setBranch(list[0]);
          }
        })
        .catch(() => {
          setBranchList([]);
          setCurrentBranch('');
          setBranch('main');
        })
        .finally(() => setLoadingBranches(false));
    } else {
      setMessages([]);
      setBranchList([]);
      setCurrentBranch('');
      setBranch('main');
    }
  }, [selectedRepoId]);

  // --- persist messages ---
  useEffect(() => {
    if (selectedRepoId && messages.length > 0) {
      saveMessages(selectedRepoId, messages);
    }
  }, [messages, selectedRepoId]);

  // --- auto-scroll ---
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  useEffect(() => {
    activityEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [activityLog]);

  // --- cleanup poll on unmount ---
  useEffect(() => {
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
      if (workflowPollRef.current) clearInterval(workflowPollRef.current);
    };
  }, []);

  // --- poll workflow status ---
  useEffect(() => {
    if (!activeWorkflow || !['running', 'planning', 'paused'].includes(activeWorkflow.status)) {
      if (workflowPollRef.current) clearInterval(workflowPollRef.current);
      return;
    }

    workflowPollRef.current = setInterval(async () => {
      try {
        const wf = await workflowsApi.get(activeWorkflow.id);
        const prevStatus = activeWorkflow.status;
        setActiveWorkflow(wf);

        // Convert subtask progress to activity entries
        const entries: ActivityEntry[] = [];
        for (const st of wf.subtasks) {
          if (st.status === 'completed') {
            entries.push({ timestamp: st.completed_at || '', type: 'complete', detail: `${st.title}: ${st.result_summary || 'Done'}` });
          } else if (st.status === 'running') {
            entries.push({ timestamp: st.started_at || '', type: 'status', detail: `${st.title}...` });
          } else if (st.status === 'failed') {
            entries.push({ timestamp: st.completed_at || '', type: 'error', detail: `${st.title}: ${st.error || 'Failed'}` });
          }
        }
        setActivityLog(entries);

        // When workflow transitions to a terminal/paused state, add assistant message
        if (['completed', 'failed', 'paused'].includes(wf.status) && wf.status !== prevStatus) {
          const content = wf.status === 'paused'
            ? `Workflow paused at checkpoint after: "${wf.subtasks[wf.current_step]?.title}"\n\n${wf.subtasks[wf.current_step]?.result_summary || ''}`
            : wf.status === 'completed'
            ? `Workflow completed!\n\n${wf.result_summary || `All ${wf.subtasks.length} subtasks finished.`}`
            : `Workflow failed.\n\n${wf.result_summary || wf.subtasks.find(s => s.status === 'failed')?.error || 'Unknown error'}`;

          setMessages(prev => [...prev, {
            id: `workflow-${Date.now()}`,
            role: 'assistant',
            content,
            mode: 'agent',
            status: wf.status,
            timestamp: new Date().toISOString(),
          }]);

          if (wf.status !== 'paused') {
            setSending(false);
          }
        }
      } catch (err) {
        console.error('Workflow poll error:', err);
      }
    }, 2000);

    return () => { if (workflowPollRef.current) clearInterval(workflowPollRef.current); };
  }, [activeWorkflow?.id, activeWorkflow?.status]);

  // --- poll session (fallback when WS not connected) ---
  const startPolling = useCallback((sessionId: string) => {
    if (pollRef.current) clearInterval(pollRef.current);

    pollRef.current = setInterval(async () => {
      // Skip polling if WebSocket is connected
      if (wsConnected) return;

      try {
        const s = await sessions.get(sessionId);
        setCurrentSession(s);

        // Populate activity from session.log when polling
        if (s.log && s.log.length > 0) {
          const entries: ActivityEntry[] = s.log.map((entry: any) => ({
            timestamp: entry.timestamp || new Date().toISOString(),
            type: entry.tool ? 'tool_call' : 'status',
            turn: entry.turn,
            tool: entry.tool,
            detail: entry.detail || '',
            result: entry.result || '',
          }));
          setActivityLog(entries);
        }

        if (s.status !== 'running') {
          // Done -- clear poll
          if (pollRef.current) clearInterval(pollRef.current);
          pollRef.current = null;
          setSending(false);
          setWsSessionId(null);

          const resultContent = s.result_summary || (s.status === 'failed' ? 'Session failed.' : 'Done.');

          // Add completion entry to activity
          setActivityLog(prev => [...prev, {
            timestamp: new Date().toISOString(),
            type: 'complete',
            detail: `${s.status === 'completed' ? 'Completed' : 'Failed'} (${s.turns_used} turns)`,
          }]);

          // Add assistant message (skip if WS already added one for this session)
          const isPartial = s.status === 'failed' && !!s.result_summary;
          setMessages((prev) => {
            if (prev.some(m => m.role === 'assistant' && m.sessionId === s.id && m.status)) {
              return prev;
            }
            return [
              ...prev,
              {
                id: `assistant-poll-${Date.now()}`,
                role: 'assistant',
                content: resultContent,
                mode: s.mode as Mode,
                sessionId: s.id,
                status: s.status,
                partial: isPartial,
                canExploreDeeper: isPartial,
                timestamp: new Date().toISOString(),
              },
            ];
          });
        }
      } catch (err) {
        console.error('Poll error:', err);
      }
    }, 5000);
  }, [wsConnected]);

  // --- send message ---
  async function handleSend(e?: React.FormEvent) {
    e?.preventDefault();
    const text = input.trim();
    if (!text || !selectedRepoId || sending) return;

    setInput('');
    setSending(true);
    setActivityLog([]);
    wsClearMessages();

    // Add user message
    const userMsgId = `user-${Date.now()}`;
    const userMsg: ChatMessage = {
      id: userMsgId,
      role: 'user',
      content: text,
      mode,
      timestamp: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, userMsg]);

    // --- AGENT MODE: always decompose via workflow API ---
    if (mode === 'agent') {
      try {
        const wf = await workflowsApi.create({
          repo_id: selectedRepoId,
          goal: text,
          mode: 'engineering',
          branch: branch || undefined,
          config_overrides: Object.keys(modelOverrides).length > 0 ? modelOverrides : undefined,
        });
        setActiveWorkflow(wf);

        // Show decomposition as assistant message
        const subtaskList = wf.subtasks.map((s: WorkflowSubtask, i: number) => `${i + 1}. ${s.title}`).join('\n');
        const content = wf.subtasks.length > 1
          ? `Decomposed into ${wf.subtasks.length} steps:\n\n${subtaskList}\n\nExecuting...`
          : `Running: ${wf.subtasks[0]?.title || text}\n\nExecuting...`;
        setMessages(prev => [...prev, {
          id: `assistant-${Date.now()}`,
          role: 'assistant',
          content,
          mode: 'agent',
          timestamp: new Date().toISOString(),
        }]);

        setActivityLog([{
          timestamp: new Date().toISOString(),
          type: 'status',
          detail: `${wf.subtasks.length} step(s) planned`,
        }]);
      } catch (err: any) {
        setSending(false);
        setMessages(prev => [...prev, {
          id: `error-${Date.now()}`,
          role: 'assistant',
          content: `Error: ${err.message}`,
          mode: 'agent',
          status: 'failed',
          timestamp: new Date().toISOString(),
        }]);
      }
      return;
    }

    // --- ASK / PLAN MODE: use sessions API ---
    const context = messages
      .filter(m => m.role === 'user' || m.role === 'assistant')
      .slice(-6)
      .map(m => ({ role: m.role, content: m.content.slice(0, 500) }));

    try {
      const s = await sessions.create({
        repo_id: selectedRepoId,
        mode,
        requirements: text,
        branch: branch || undefined,
        context: context.length > 0 ? context : undefined,
        recipe_ids: selectedRecipeIds.length > 0 ? selectedRecipeIds : undefined,
        config_overrides: Object.keys(modelOverrides).length > 0 ? modelOverrides : undefined,
      });
      setCurrentSession(s);
      setWsSessionId(s.id);

      setActivityLog([{
        timestamp: new Date().toISOString(),
        type: 'status',
        detail: 'Session created -- running...',
      }]);

      startPolling(s.id);
    } catch (err: any) {
      setSending(false);
      setMessages((prev) => [
        ...prev,
        {
          id: `error-${Date.now()}`,
          role: 'assistant',
          content: `Error: ${err.message || 'Failed to create session'}`,
          mode,
          status: 'failed',
          timestamp: new Date().toISOString(),
        },
      ]);
      setActivityLog([{
        timestamp: new Date().toISOString(),
        type: 'error',
        detail: err.message || 'Failed to create session',
      }]);
    }
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  }

  function clearHistory() {
    if (selectedRepoId) {
      localStorage.removeItem(storageKey(selectedRepoId));
      setMessages([]);
    }
  }

  // --- quick actions per mode ---
  const quickActions: Record<Mode, string[]> = {
    ask: [
      'How does the API routing work?',
      'What testing framework is used?',
      'Explain the authentication flow',
      'What are the main dependencies?',
    ],
    plan: [
      'Add input validation to the create endpoint',
      'Refactor database access to use repository pattern',
      'Add error handling middleware',
      'Improve test coverage for the auth module',
    ],
    agent: [
      'Add a health check endpoint',
      'Write unit tests for the user service',
      'Achieve 80% test coverage for REST endpoints',
      'Add input validation and error handling across all API routes',
    ],
  };

  const selectedRepo = repoList.find((r) => r.id === selectedRepoId);

  // --- render activity entry ---
  function renderActivityEntry(entry: ActivityEntry, i: number) {
    if (entry.type === 'complete') {
      return (
        <div key={i} className="flex items-start gap-2 text-green-400">
          <span className="flex-shrink-0">{'\u2713'}</span>
          <span>{entry.detail}</span>
        </div>
      );
    }
    if (entry.type === 'error') {
      return (
        <div key={i} className="flex items-start gap-2 text-red-400">
          <span className="flex-shrink-0">{'\u2717'}</span>
          <span>{entry.detail}</span>
        </div>
      );
    }
    if (entry.type === 'status') {
      return (
        <div key={i} className="flex items-start gap-2 text-blue-400">
          <span className="flex-shrink-0">{'\u27F3'}</span>
          <span>{entry.detail}</span>
        </div>
      );
    }
    // tool_call
    const meta = getToolMeta(entry.tool || '');
    const structured = entry.result ? tryParseStructured(entry.result) : null;
    return (
      <div key={i}>
        <div className={`flex items-start gap-2 ${meta.color}`}>
          <span className="flex-shrink-0">{meta.icon}</span>
          <div className="min-w-0">
            <span className="font-medium">{entry.tool}</span>
            {entry.detail && <span className="text-gray-500 ml-1">{entry.detail}</span>}
            {!structured && entry.result && (
              <span className="text-gray-600 ml-1">{'\u2192'} {entry.result}</span>
            )}
            {entry.turn && (
              <span className="text-gray-600 text-[10px] ml-2">T{entry.turn}</span>
            )}
          </div>
        </div>
        {structured && <StructuredResult data={structured} />}
      </div>
    );
  }

  // --- render ---
  return (
    <div className="flex flex-col h-[calc(100vh-5rem)]">
      {/* ---- Top Bar ---- */}
      <div className="flex items-center gap-3 px-1 pb-3 border-b border-gray-200 flex-wrap">
        <h1 className="text-xl font-bold text-gray-900 mr-1">Chat</h1>

        {/* Repo selector */}
        <select
          value={selectedRepoId}
          onChange={(e) => setSelectedRepoId(e.target.value)}
          className="px-3 py-1.5 border border-gray-300 rounded-md text-sm bg-white max-w-[260px] truncate"
          disabled={loadingRepos}
        >
          <option value="">Select repo...</option>
          {repoList.map((r) => (
            <option key={r.id} value={r.id}>
              {r.nickname || r.url || r.local_path || r.id}
            </option>
          ))}
        </select>

        {/* Branch selector */}
        <div className="relative" ref={branchRef}>
          <button
            type="button"
            onClick={() => { setBranchDropdownOpen(!branchDropdownOpen); setBranchSearch(''); }}
            className="flex items-center gap-1.5 px-3 py-1.5 border border-gray-300 rounded-md text-sm bg-white hover:bg-gray-50 min-w-[140px]"
            disabled={!selectedRepoId}
          >
            <svg className="w-3.5 h-3.5 text-gray-400 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
            </svg>
            <span className="truncate max-w-[120px]">{branch || 'main'}{branch === currentBranch && currentBranch ? ' \u2190' : ''}</span>
            {loadingBranches ? (
              <svg className="w-3 h-3 animate-spin text-gray-400 ml-auto flex-shrink-0" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
            ) : (
              <svg className="w-3 h-3 text-gray-400 ml-auto flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
              </svg>
            )}
          </button>

          {branchDropdownOpen && (
            <div className="absolute top-full left-0 mt-1 w-64 bg-white border border-gray-200 rounded-lg shadow-lg z-50 overflow-hidden">
              {/* Search input */}
              <div className="p-2 border-b border-gray-100">
                <input
                  type="text"
                  value={branchSearch}
                  onChange={(e) => setBranchSearch(e.target.value)}
                  placeholder="Search branches..."
                  className="w-full px-2.5 py-1.5 text-sm border border-gray-200 rounded-md focus:outline-none focus:ring-1 focus:ring-indigo-500"
                  autoFocus
                />
              </div>
              {/* Branch list */}
              <div className="max-h-48 overflow-y-auto">
                {branchList.length === 0 && !loadingBranches && (
                  <div className="px-3 py-2 text-xs text-gray-400">No branches found</div>
                )}
                {loadingBranches && (
                  <div className="px-3 py-2 text-xs text-gray-400">Loading...</div>
                )}
                {branchList
                  .filter((b) => !branchSearch || b.toLowerCase().includes(branchSearch.toLowerCase()))
                  .map((b) => (
                    <button
                      key={b}
                      type="button"
                      onClick={() => { setBranch(b); setBranchDropdownOpen(false); }}
                      className={`w-full text-left px-3 py-1.5 text-sm hover:bg-indigo-50 flex items-center gap-2 ${
                        b === branch ? 'bg-indigo-50 text-indigo-700 font-medium' : b === currentBranch ? 'bg-green-50 text-green-700' : 'text-gray-700'
                      }`}
                    >
                      {b === branch && (
                        <svg className="w-3 h-3 text-indigo-600 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
                        </svg>
                      )}
                      <span className={`truncate ${b === branch ? '' : 'ml-5'}`}>
                        {b}{b === currentBranch ? ' \u2190 workspace' : ''}
                      </span>
                    </button>
                  ))}
                {branchSearch && !branchList.some((b) => b.toLowerCase().includes(branchSearch.toLowerCase())) && (
                  <button
                    type="button"
                    onClick={() => { setBranch(branchSearch); setBranchDropdownOpen(false); }}
                    className="w-full text-left px-3 py-1.5 text-sm text-indigo-600 hover:bg-indigo-50"
                  >
                    Use &quot;{branchSearch}&quot;
                  </button>
                )}
              </div>
            </div>
          )}
        </div>

        {/* Mode selector */}
        <div className="flex rounded-lg border border-gray-300 overflow-hidden ml-auto">
          {(['ask', 'plan', 'agent'] as Mode[]).map((m) => (
            <button
              key={m}
              onClick={() => setMode(m)}
              className={`px-3 py-1.5 text-sm font-medium transition-colors ${
                mode === m
                  ? `${MODE_META[m].bg} ${MODE_META[m].color}`
                  : 'bg-white text-gray-500 hover:bg-gray-50'
              }`}
              title={MODE_META[m].desc}
            >
              {MODE_META[m].label}
            </button>
          ))}
        </div>

        {/* Model selector */}
        <ModelSelector
          selectedModelId={selectedModelId}
          onChange={(id, overrides) => { setSelectedModelId(id); setModelOverrides(overrides); }}
          storageKey="selected-model-chat"
        />

        {/* Activity toggle + WS indicator */}
        <div className="flex items-center gap-1">
          {wsConnected ? (
            <span className="w-2 h-2 rounded-full bg-green-400 animate-pulse" title="WebSocket connected" />
          ) : wsReconnecting ? (
            <span className="w-2 h-2 rounded-full bg-yellow-400 animate-pulse" title="Reconnecting..." />
          ) : null}
          <button
            onClick={() => setShowActivity(!showActivity)}
            className="px-2 py-1.5 text-xs border border-gray-300 rounded-md text-gray-500 hover:bg-gray-50"
            title={showActivity ? 'Hide activity panel' : 'Show activity panel'}
          >
            {showActivity ? '\u25E7' : '\u25E8'}
          </button>
        </div>
      </div>

      {/* ---- Main Content ---- */}
      {!selectedRepoId ? (
        <div className="flex-1 flex items-center justify-center text-gray-400">
          <div className="text-center">
            <p className="text-lg mb-2">Select a repository to start</p>
            <p className="text-sm">Choose a repo and branch above, then ask questions or run agents.</p>
          </div>
        </div>
      ) : (
        <div className="flex flex-1 overflow-hidden mt-3 gap-3">
          {/* ---- Left: Conversation ---- */}
          <div className="flex flex-col flex-1 min-w-0">
            {/* Messages */}
            <div className="flex-1 overflow-y-auto space-y-3 pr-1">
              {messages.length === 0 && (
                <div className="text-center py-16">
                  <div className={`inline-block px-3 py-1 rounded-full text-sm font-medium mb-3 ${MODE_META[mode].bg} ${MODE_META[mode].color}`}>
                    {MODE_META[mode].label} Mode
                  </div>
                  <h3 className="text-lg font-medium text-gray-700 mb-1">
                    {mode === 'ask' ? 'Ask anything about this codebase' :
                     mode === 'plan' ? 'Describe changes you want planned' :
                     'Describe what you want done — from simple tasks to complex goals'}
                  </h3>
                  <p className="text-sm text-gray-400 mb-6">{MODE_META[mode].desc}</p>
                  <div className="flex flex-wrap justify-center gap-2 max-w-lg mx-auto">
                    {quickActions[mode].map((action) => (
                      <button
                        key={action}
                        onClick={() => setInput(action)}
                        className="px-3 py-1.5 text-xs bg-gray-100 text-gray-600 rounded-full hover:bg-gray-200 transition-colors"
                      >
                        {action}
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {messages.map((msg) => (
                <div key={msg.id} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                  <div className={`max-w-[75%] rounded-lg px-4 py-3 overflow-hidden ${
                    msg.role === 'user'
                      ? 'bg-indigo-600 text-white'
                      : 'bg-white border border-gray-200 text-gray-800'
                  }`} style={{ wordBreak: 'break-word' }}>
                    {/* Header */}
                    <div className="flex items-center gap-2 mb-1">
                      <span className={`text-xs font-medium ${
                        msg.role === 'user' ? 'text-indigo-200' : 'text-gray-400'
                      }`}>
                        {msg.role === 'user' ? 'You' : 'Assistant'}
                      </span>
                      <span className={`text-[10px] px-1.5 py-0.5 rounded ${MODE_META[msg.mode]?.bg || 'bg-gray-100'} ${MODE_META[msg.mode]?.color || 'text-gray-500'}`}>
                        {MODE_META[msg.mode]?.label || msg.mode}
                      </span>
                      <span className={`text-xs ${msg.role === 'user' ? 'text-indigo-300' : 'text-gray-300'}`}>
                        {new Date(msg.timestamp).toLocaleTimeString()}
                      </span>
                      {msg.partial ? (
                        <span className="text-xs px-1.5 py-0.5 rounded bg-amber-100 text-amber-700">partial</span>
                      ) : msg.status === 'failed' ? (
                        <span className="text-xs text-red-400">failed</span>
                      ) : null}
                    </div>
                    {/* Content */}
                    <div className={`text-sm whitespace-pre-wrap break-words ${
                      msg.role === 'assistant' ? 'prose prose-sm max-w-none' : ''
                    }`}>
                      {msg.role === 'assistant' ? renderMarkdown(msg.content) : msg.content}
                    </div>
                    {/* Session link */}
                    {msg.sessionId && (
                      <div className="mt-2 text-[10px] text-gray-400">
                        Session: {msg.sessionId}
                      </div>
                    )}
                    {/* Explore Deeper — shown on partial results that can be explored further */}
                    {msg.role === 'assistant' && msg.canExploreDeeper && msg.sessionId && (
                      <div className="mt-2 bg-amber-50 border border-amber-200 rounded-md px-3 py-2 flex items-center justify-between gap-3">
                        <p className="text-xs text-amber-800">
                          Partial results — can dig deeper for a more complete answer.
                        </p>
                        <button
                          onClick={async () => {
                            try {
                              setSending(true);
                              setActivityLog([{
                                timestamp: new Date().toISOString(),
                                type: 'status',
                                detail: 'Resuming from checkpoint...',
                              }]);
                              const s = await sessions.resume(msg.sessionId!);
                              setCurrentSession(s);
                              // Force WS reconnect: clear first so React sees a state change
                              // even when resuming the same session ID
                              wsClearMessages();
                              setWsSessionId(null);
                              setTimeout(() => setWsSessionId(s.id), 50);
                              startPolling(s.id);
                            } catch (err: any) {
                              setSending(false);
                              setMessages(prev => [...prev, {
                                id: `error-${Date.now()}`,
                                role: 'assistant',
                                content: `Resume failed: ${err.message}`,
                                mode,
                                status: 'failed',
                                timestamp: new Date().toISOString(),
                              }]);
                            }
                          }}
                          disabled={sending}
                          className="shrink-0 px-3 py-1.5 bg-amber-600 text-white rounded-md text-xs font-medium hover:bg-amber-700 disabled:opacity-50"
                        >
                          {sending ? 'Exploring...' : 'Explore Deeper'}
                        </button>
                      </div>
                    )}
                  </div>
                </div>
              ))}

              {/* Thinking indicator */}
              {sending && (
                <div className="flex justify-start">
                  <div className="bg-white border border-gray-200 rounded-lg px-4 py-3">
                    <div className="flex items-center gap-2">
                      <div className="flex gap-1">
                        <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
                        <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
                        <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
                      </div>
                      <span className="text-xs text-gray-400">
                        {mode === 'ask' ? 'Analyzing codebase...' :
                         mode === 'plan' ? 'Generating plan...' :
                         'Agent working...'}
                      </span>
                      {currentSession && (
                        <span className="text-xs text-gray-300">
                          Turn {currentSession.turns_used || 0}
                        </span>
                      )}
                      {wsConnected && (
                        <span className="w-1.5 h-1.5 rounded-full bg-green-400" title="Live" />
                      )}
                    </div>
                  </div>
                </div>
              )}

              <div ref={messagesEndRef} />
            </div>

            {/* Quick actions when messages exist */}
            {messages.length > 0 && !sending && (
              <div className="flex gap-2 py-2 overflow-x-auto">
                {quickActions[mode].slice(0, 3).map((action) => (
                  <button
                    key={action}
                    onClick={() => setInput(action)}
                    className="px-3 py-1 text-xs bg-gray-100 text-gray-600 rounded-full hover:bg-gray-200 whitespace-nowrap"
                  >
                    {action}
                  </button>
                ))}
              </div>
            )}

            {/* Recipe selector */}
            <div className="pt-2">
              <RecipePicker
                recipes={availableRecipes}
                selectedIds={selectedRecipeIds}
                onChange={setSelectedRecipeIds}
                accent="indigo"
              />
            </div>

            {/* Input bar */}
            <form onSubmit={handleSend} className="flex gap-2 pt-2 border-t border-gray-200">
              <div className="flex-1 relative">
                <textarea
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder={
                    mode === 'ask' ? 'Ask a question about the codebase...' :
                    mode === 'plan' ? 'Describe changes to plan...' :
                    'Tell the agent what to do — simple tasks or complex goals...'
                  }
                  disabled={sending}
                  rows={1}
                  className="w-full px-4 py-3 pr-20 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 disabled:bg-gray-50 resize-none"
                  autoFocus
                />
                <div className="absolute right-2 top-1/2 -translate-y-1/2 flex items-center gap-1">
                  <span className={`text-[10px] px-1.5 py-0.5 rounded ${MODE_META[mode].bg} ${MODE_META[mode].color}`}>
                    {MODE_META[mode].label}
                  </span>
                </div>
              </div>
              <button
                type="submit"
                disabled={!input.trim() || sending}
                className="px-5 py-3 bg-indigo-600 text-white rounded-lg text-sm font-medium hover:bg-indigo-700 disabled:opacity-50 transition-colors"
              >
                Send
              </button>
            </form>

            {/* Checkpoint actions */}
            {activeWorkflow?.status === 'paused' && (
              <div className="flex items-center gap-3 px-4 py-2 bg-amber-50 border border-amber-200 rounded-lg mt-2">
                <span className="text-sm text-amber-700">
                  Paused at checkpoint — Step {activeWorkflow.current_step + 1}/{activeWorkflow.subtasks.length}
                </span>
                <div className="ml-auto flex gap-2">
                  <button
                    onClick={async () => {
                      try {
                        const wf = await workflowsApi.resume(activeWorkflow.id);
                        setActiveWorkflow(wf);
                        setMessages(prev => [...prev, {
                          id: `system-${Date.now()}`,
                          role: 'user',
                          content: 'Resume workflow',
                          mode: 'agent' as Mode,
                          timestamp: new Date().toISOString(),
                        }]);
                      } catch (err: any) {
                        console.error('Resume failed:', err);
                      }
                    }}
                    className="px-3 py-1 text-sm bg-teal-600 text-white rounded-md hover:bg-teal-700"
                  >
                    Resume
                  </button>
                  <button
                    onClick={async () => {
                      try {
                        await workflowsApi.cancel(activeWorkflow.id);
                        setActiveWorkflow(null);
                        setSending(false);
                      } catch (err: any) {
                        console.error('Cancel failed:', err);
                      }
                    }}
                    className="px-3 py-1 text-sm bg-gray-200 text-gray-700 rounded-md hover:bg-gray-300"
                  >
                    Cancel
                  </button>
                </div>
              </div>
            )}

            {/* Footer actions */}
            <div className="flex items-center justify-between pt-1">
              <span className="text-[10px] text-gray-400">
                {selectedRepo ? (selectedRepo.nickname || selectedRepo.url || selectedRepo.local_path) : ''} @ {branch || 'default'}
              </span>
              {messages.length > 0 && (
                <button
                  onClick={clearHistory}
                  className="text-[10px] text-gray-400 hover:text-red-500 transition-colors"
                >
                  Clear history
                </button>
              )}
            </div>
          </div>

          {/* ---- Right: Activity Panel ---- */}
          {showActivity && (
            <div className="w-80 flex-shrink-0 bg-gray-900 rounded-lg flex flex-col overflow-hidden">
              <div className="flex items-center justify-between px-3 py-2 border-b border-gray-700">
                <span className="text-xs font-medium text-gray-300">Activity</span>
                <div className="flex items-center gap-2">
                  {wsConnected && (
                    <span className="text-[10px] text-green-400">LIVE</span>
                  )}
                  {currentSession && (
                    <span className={`text-xs ${statusColor(currentSession.status)}`}>
                      {statusIcon(currentSession.status)} {currentSession.status}
                    </span>
                  )}
                  {activeWorkflow && (
                    <span className={`text-xs ${statusColor(activeWorkflow.status)}`}>
                      {statusIcon(activeWorkflow.status)} {activeWorkflow.status}
                    </span>
                  )}
                </div>
              </div>
              <div className="flex-1 overflow-y-auto p-3 font-mono text-xs space-y-1.5">
                {/* Workflow subtask stepper */}
                {activeWorkflow && (
                  <div className="mb-3 pb-3 border-b border-gray-700 space-y-1">
                    <div className="text-gray-400 text-[10px] uppercase tracking-wide mb-1">
                      Workflow — Step {activeWorkflow.current_step + 1}/{activeWorkflow.subtasks.length}
                    </div>
                    {activeWorkflow.subtasks.map((st) => (
                      <div key={st.index} className={`flex items-center gap-2 text-xs ${
                        st.status === 'completed' ? 'text-green-400' :
                        st.status === 'running' ? 'text-blue-400' :
                        st.status === 'failed' ? 'text-red-400' :
                        'text-gray-500'
                      }`}>
                        <span>{
                          st.status === 'completed' ? '\u2713' :
                          st.status === 'running' ? '\u25B8' :
                          st.status === 'failed' ? '\u2717' :
                          '\u25CB'
                        }</span>
                        <span className="truncate">{st.title}</span>
                        {st.model_used && (
                          <span className="text-[10px] text-gray-500 font-mono flex-shrink-0">{st.model_used}</span>
                        )}
                        {(st.attempts || 1) > 1 && (
                          <span className="text-[10px] text-orange-400 flex-shrink-0">x{st.attempts}</span>
                        )}
                      </div>
                    ))}
                    <div className="mt-2 h-1.5 bg-gray-700 rounded-full overflow-hidden">
                      <div
                        className="h-full bg-teal-500 transition-all"
                        style={{ width: `${activeWorkflow.progress_pct}%` }}
                      />
                    </div>
                  </div>
                )}
                {activityLog.length === 0 && !activeWorkflow ? (
                  <div className="text-gray-500 text-center py-8">
                    <p>No activity yet.</p>
                    <p className="mt-1">Send a message to see live progress.</p>
                  </div>
                ) : (
                  activityLog.map((entry, i) => renderActivityEntry(entry, i))
                )}
                {sending && (
                  <div className="text-blue-400 animate-pulse">
                    {'\u258D'}
                  </div>
                )}
                <div ref={activityEndRef} />
              </div>
              {/* Session info */}
              {currentSession && (
                <div className="border-t border-gray-700 px-3 py-2 text-[10px] text-gray-500 space-y-0.5">
                  <div>Session: {currentSession.id}</div>
                  <div>Mode: {currentSession.mode}</div>
                  <div>Turns: {currentSession.turns_used || 0}</div>
                </div>
              )}
              {activeWorkflow && !currentSession && (
                <div className="border-t border-gray-700 px-3 py-2 text-[10px] text-gray-500 space-y-0.5">
                  <div>Workflow: {activeWorkflow.id}</div>
                  <div>Mode: {activeWorkflow.mode}</div>
                  <div>Step: {activeWorkflow.current_step + 1}/{activeWorkflow.subtasks.length}</div>
                  {activeWorkflow.total_tokens_used > 0 && (
                    <div>
                      Tokens: {activeWorkflow.total_tokens_used.toLocaleString()}
                      {activeWorkflow.token_budget > 0 && ` / ${activeWorkflow.token_budget.toLocaleString()}`}
                    </div>
                  )}
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
