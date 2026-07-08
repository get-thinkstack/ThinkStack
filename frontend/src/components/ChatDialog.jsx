import { useState, useRef, useEffect } from 'react';
import { createPortal } from 'react-dom';
import { X, Send, Sparkles, CornerDownLeft, PanelRightOpen, PanelRightClose } from 'lucide-react';
import Loader from './Loader';

/**
 * persistent collapsible side panel chat component.
 */
export default function ChatDialog({
  title = 'AI Assistant',
  messages = [],
  onSend,
  loading = false,
  placeholder = 'ask a question about your research...',
}) {
  const [input, setInput] = useState('');
  const [collapsed, setCollapsed] = useState(true); // default to collapsed vertical tab
  const messagesEndRef = useRef(null);
  const inputRef = useRef(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, loading]);

  useEffect(() => {
    if (!collapsed) {
      setTimeout(() => inputRef.current?.focus(), 300);
    }
  }, [collapsed]);

  const handleSend = () => {
    const text = input.trim();
    if (!text || loading) return;
    onSend(text);
    setInput('');
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return createPortal(
    <div className={`chat-side-panel ${collapsed ? 'collapsed' : 'expanded'}`}>
      {/* collapsed tab */}
      {collapsed && (
        <button
          className="chat-collapsed-tab"
          onClick={() => setCollapsed(false)}
          title="Expand AI Assistant"
        >
          <PanelRightOpen size={18} />
          <span className="chat-collapsed-label">{title}</span>
          {messages.length > 0 && (
            <span className="chat-collapsed-badge">{messages.length}</span>
          )}
        </button>
      )}

      {/* expanded panel */}
      {!collapsed && (
        <div className="chat-panel-content">
          {/* header */}
          <div className="chat-panel-header">
            <div className="chat-panel-title">
              <Sparkles size={16} className="chat-title-icon" />
              <span>{title}</span>
            </div>
            <div className="chat-panel-actions">
              <button
                className="chat-header-btn"
                onClick={() => setCollapsed(true)}
                title="Collapse"
              >
                <PanelRightClose size={16} />
              </button>
            </div>
          </div>

          {/* messages */}
          <div className="chat-panel-body">
            {messages.length === 0 && !loading && (
              <div className="chat-empty">
                <p>chat with the agent</p>
              </div>
            )}

            {messages.map((msg, i) => (
              <div
                key={i}
                className={`chat-message ${msg.role === 'user' ? 'chat-message-user' : 'chat-message-assistant'}`}
              >
                {msg.role === 'assistant' && (
                  <div className="chat-avatar">
                    <Sparkles size={12} />
                  </div>
                )}
                <div className="chat-bubble">
                  <div className="chat-bubble-content">{msg.content}</div>
                </div>
              </div>
            ))}

            {loading && (
              <div className="chat-message chat-message-assistant">
                <div className="chat-avatar">
                  <Sparkles size={12} />
                </div>
                <div className="chat-bubble chat-bubble-loading">
                  <div className="chat-thinking-loader">
                    <Loader />
                  </div>
                  <span>loading...</span>
                </div>
              </div>
            )}

            <div ref={messagesEndRef} />
          </div>

          {/* input / loading footer */}
          <div className="chat-panel-footer">
            {loading ? (
              <div className="chat-input-loading">
                <div className="chat-loading-animation">
                  <Loader />
                </div>
                <span className="chat-loading-text">loading...</span>
              </div>
            ) : (
              <>
                <div className="chat-input-wrap">
                  <textarea
                    ref={inputRef}
                    className="chat-input"
                    value={input}
                    onChange={(e) => setInput(e.target.value)}
                    onKeyDown={handleKeyDown}
                    placeholder={placeholder}
                    rows={1}
                  />
                  <button
                    className="chat-send-btn"
                    onClick={handleSend}
                    disabled={!input.trim()}
                  >
                    <Send size={14} />
                  </button>
                </div>
                <div className="chat-input-hint">
                  <CornerDownLeft size={11} />
                  <span>enter to send</span>
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </div>,
    document.body
  );
}
