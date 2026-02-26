'use client';

import { useEffect, useRef, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import { testing, type TestProject, type ChatMessage } from '@/lib/api';

export default function ChatPage() {
  const searchParams = useSearchParams();
  const projectFilter = searchParams.get('project') || '';

  const [projects, setProjects] = useState<TestProject[]>([]);
  const [selectedProjectId, setSelectedProjectId] = useState(projectFilter);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const [loading, setLoading] = useState(true);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    async function load() {
      try {
        const p = await testing.listProjects({ limit: 100 });
        setProjects(p.projects);
        if (!selectedProjectId && p.projects.length > 0) {
          setSelectedProjectId(p.projects[0].id);
        }
      } catch (err) {
        console.error(err);
      } finally {
        setLoading(false);
      }
    }
    load();
  }, []);

  useEffect(() => {
    if (selectedProjectId) loadHistory();
  }, [selectedProjectId]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  async function loadHistory() {
    try {
      const h = await testing.chatHistory(selectedProjectId, 100);
      setMessages(h);
    } catch {
      setMessages([]);
    }
  }

  async function handleSend(e: React.FormEvent) {
    e.preventDefault();
    if (!input.trim() || !selectedProjectId) return;

    const userMessage = input.trim();
    setInput('');
    setSending(true);

    // Optimistically add user message
    const tempUserMsg: ChatMessage = {
      id: 'temp-' + Date.now(),
      project_id: selectedProjectId,
      role: 'user',
      content: userMessage,
      metadata: {},
      created_at: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, tempUserMsg]);

    try {
      const result = await testing.chat(selectedProjectId, userMessage);
      // Replace temp message with real ones from server
      setMessages((prev) => {
        const withoutTemp = prev.filter((m) => m.id !== tempUserMsg.id);
        return [
          ...withoutTemp,
          { ...tempUserMsg, id: 'user-' + Date.now() },
          result.reply,
        ];
      });
    } catch (err) {
      console.error('Chat error:', err);
      setMessages((prev) => [
        ...prev,
        {
          id: 'error-' + Date.now(),
          project_id: selectedProjectId,
          role: 'assistant',
          content: 'Sorry, I encountered an error. Please try again.',
          metadata: {},
          created_at: new Date().toISOString(),
        },
      ]);
    } finally {
      setSending(false);
    }
  }

  const quickActions = [
    'Analyze test coverage',
    'What endpoints are uncovered?',
    'Run functional tests',
    'Generate test data for User entity',
    'Run security scan',
    'Discover custom steps',
  ];

  if (loading) {
    return <p className="text-gray-500">Loading chat...</p>;
  }

  const selectedProject = projects.find((p) => p.id === selectedProjectId);

  return (
    <div className="flex flex-col h-[calc(100vh-8rem)]">
      {/* Header */}
      <div className="flex items-center justify-between pb-4 border-b border-gray-200">
        <div className="flex items-center gap-3">
          <h1 className="text-2xl font-bold text-gray-900">Testing Chat</h1>
          {selectedProject && (
            <span className="text-sm text-gray-500">
              - {selectedProject.name}
            </span>
          )}
        </div>
        <select
          value={selectedProjectId}
          onChange={(e) => setSelectedProjectId(e.target.value)}
          className="px-3 py-2 border border-gray-300 rounded-md text-sm"
        >
          <option value="">Select project...</option>
          {projects.map((p) => (
            <option key={p.id} value={p.id}>{p.name}</option>
          ))}
        </select>
      </div>

      {!selectedProjectId ? (
        <div className="flex-1 flex items-center justify-center text-gray-500">
          Select a project to start chatting
        </div>
      ) : (
        <>
          {/* Messages */}
          <div className="flex-1 overflow-y-auto py-4 space-y-4">
            {messages.length === 0 && (
              <div className="text-center py-12">
                <h3 className="text-lg font-medium text-gray-700 mb-2">
                  Testing Assistant
                </h3>
                <p className="text-sm text-gray-500 mb-6">
                  Ask me anything about testing your project. I can help with coverage analysis,
                  test generation, data injection, and more.
                </p>
                <div className="flex flex-wrap justify-center gap-2">
                  {quickActions.map((action) => (
                    <button
                      key={action}
                      onClick={() => {
                        setInput(action);
                      }}
                      className="px-3 py-1.5 text-xs bg-gray-100 text-gray-700 rounded-full hover:bg-gray-200 transition-colors"
                    >
                      {action}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {messages.map((msg) => (
              <div
                key={msg.id}
                className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
              >
                <div
                  className={`max-w-[70%] rounded-lg px-4 py-3 ${
                    msg.role === 'user'
                      ? 'bg-indigo-600 text-white'
                      : 'bg-white border border-gray-200 text-gray-800'
                  }`}
                >
                  <div className="flex items-center gap-2 mb-1">
                    <span className={`text-xs font-medium ${
                      msg.role === 'user' ? 'text-indigo-200' : 'text-gray-400'
                    }`}>
                      {msg.role === 'user' ? 'You' : 'Assistant'}
                    </span>
                    <span className={`text-xs ${
                      msg.role === 'user' ? 'text-indigo-300' : 'text-gray-300'
                    }`}>
                      {msg.created_at ? new Date(msg.created_at).toLocaleTimeString() : ''}
                    </span>
                  </div>
                  <div className={`text-sm whitespace-pre-wrap ${
                    msg.role === 'assistant' ? 'prose prose-sm max-w-none' : ''
                  }`}>
                    {renderMarkdown(msg.content)}
                  </div>
                </div>
              </div>
            ))}

            {sending && (
              <div className="flex justify-start">
                <div className="bg-white border border-gray-200 rounded-lg px-4 py-3">
                  <div className="flex items-center gap-2">
                    <div className="flex gap-1">
                      <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
                      <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
                      <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
                    </div>
                    <span className="text-xs text-gray-400">Thinking...</span>
                  </div>
                </div>
              </div>
            )}

            <div ref={messagesEndRef} />
          </div>

          {/* Quick actions (visible when there are messages) */}
          {messages.length > 0 && (
            <div className="flex gap-2 py-2 overflow-x-auto">
              {quickActions.slice(0, 4).map((action) => (
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

          {/* Input */}
          <form onSubmit={handleSend} className="flex gap-2 pt-2 border-t border-gray-200">
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Ask about testing, coverage, data injection..."
              disabled={sending}
              className="flex-1 px-4 py-3 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 disabled:bg-gray-50"
              autoFocus
            />
            <button
              type="submit"
              disabled={!input.trim() || sending}
              className="px-6 py-3 bg-indigo-600 text-white rounded-lg text-sm font-medium hover:bg-indigo-700 disabled:opacity-50"
            >
              Send
            </button>
          </form>
        </>
      )}
    </div>
  );
}

function renderMarkdown(text: string): React.ReactNode {
  // Simple markdown rendering for bold and bullet points
  const lines = text.split('\n');
  return lines.map((line, idx) => {
    // Bold
    let processed = line.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    // Bullet points
    if (processed.startsWith('- ')) {
      return (
        <div key={idx} className="flex gap-2 ml-2">
          <span>&#8226;</span>
          <span dangerouslySetInnerHTML={{ __html: processed.slice(2) }} />
        </div>
      );
    }
    return (
      <div key={idx}>
        <span dangerouslySetInnerHTML={{ __html: processed }} />
      </div>
    );
  });
}
