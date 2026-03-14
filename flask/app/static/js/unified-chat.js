/**
 * UnifiedChat - Reusable chat component for EDU AI
 *
 * Uses Socket.IO to communicate with the FastAPI roleplay chat server.
 *
 * Server protocol (fastapi/main.py):
 *   connect   → pass session_id via query param
 *   emit "send_message" <string>   → send a user message
 *   listen "connected"             → server confirmed session
 *   listen "processing"            → server is generating a response
 *   listen "stream_chunk"          → incremental token streaming
 *   listen "message"               → complete assistant response
 *   listen "limit_reached"         → message limit exceeded
 *   listen "error"                 → server-side error
 *
 * Usage:
 *   const chat = new UnifiedChat({
 *       container: '#my-chat',
 *       socketUrl: 'https://api.edu-ai.eu',
 *       maxMessageLength: 500,
 *       onFlag: (sessionId, content, messageIndex) => { ... },
 *       onUnflag: (sessionId, content, flagInfo) => { ... },
 *   });
 *
 *   // Show chat and load history
 *   chat.show();
 *   chat.setHeader('<div>...</div>');
 *   chat.loadHistory(messages, { flaggedContentSet, flaggedMessages, isPublic });
 *
 *   // Or connect via Socket.IO for live chat
 *   await chat.connect(sessionId);
 *   chat.sendMessage('Hello!');
 */
class UnifiedChat {
    /**
     * @param {Object} options
     * @param {string} options.container - CSS selector for the chat container element
     * @param {number} [options.maxMessageLength=500] - Maximum characters per message
     * @param {string} [options.socketUrl] - Socket.IO server URL
     * @param {boolean} [options.readOnly=false] - If true, hides input area
     * @param {Function} [options.onFlag] - Called when flag button clicked: (sessionId, content, messageIndex)
     * @param {Function} [options.onUnflag] - Called when unflag button clicked: (sessionId, content, flagInfo)
     * @param {Function} [options.onMessageSent] - Called after a message is sent: (message)
     * @param {Function} [options.onMessageReceived] - Called when assistant message arrives: (content)
     * @param {Function} [options.onConnected] - Called when Socket.IO connects
     * @param {Function} [options.onDisconnected] - Called when Socket.IO disconnects: (reason)
     * @param {Function} [options.onError] - Called on error
     * @param {Function} [options.onLimitReached] - Called when message limit is reached
     */
    constructor(options = {}) {
        // Configuration
        this.containerSelector = options.container || '#unified-chat';
        this.maxMessageLength = options.maxMessageLength || 500;
        this.readOnly = options.readOnly || false;

        // Socket.IO URL — resolve once
        const defaultUrl = (window.location.hostname === 'localhost' ||
                            window.location.hostname === '127.0.0.1')
            ? 'http://localhost:6767'
            : 'https://api.edu-ai.eu';
        this.socketUrl = options.socketUrl || window.FASTAPI_SOCKETIO_URL || defaultUrl;
        window.FASTAPI_SOCKETIO_URL = this.socketUrl;

        // Callbacks
        this.onFlag = options.onFlag || null;
        this.onUnflag = options.onUnflag || null;
        this.onMessageSent = options.onMessageSent || null;
        this.onMessageReceived = options.onMessageReceived || null;
        this.onConnected = options.onConnected || null;
        this.onDisconnected = options.onDisconnected || null;
        this.onError = options.onError || null;
        this.onLimitReached = options.onLimitReached || null;

        // State
        this.sessionId = null;
        this.socket = null;                 // Socket.IO client instance
        this.assistantMessageCount = 0;
        this._inputBound = false;

        // Streaming state
        this._streamingContainer = null;
        this._streamingBubble = null;

        // DOM references
        this.container = null;
        this.chatHeader = null;
        this.chatBody = null;
        this.chatMessages = null;
        this.chatPlaceholder = null;
        this.chatFooter = null;
        this.msgInput = null;
        this.sendBtn = null;
        this.clearBtn = null;
        this.charCounter = null;
        this.processingIndicator = null;

        this._init();
    }

    // ===================================================================
    // Initialization
    // ===================================================================

    _init() {
        this.container = document.querySelector(this.containerSelector);
        if (!this.container) {
            console.error('UnifiedChat: Container not found:', this.containerSelector);
            return;
        }

        this.chatHeader = this.container.querySelector('.uc-header');
        this.chatBody = this.container.querySelector('.uc-body');
        this.chatMessages = this.container.querySelector('.uc-messages');
        this.chatPlaceholder = this.container.querySelector('.uc-placeholder');
        this.chatFooter = this.container.querySelector('.uc-footer');
        this.msgInput = this.container.querySelector('.uc-msg-input');
        this.sendBtn = this.container.querySelector('.uc-send-btn');
        this.clearBtn = this.container.querySelector('.uc-clear-btn');
        this.charCounter = this.container.querySelector('.uc-char-counter');
        this.processingIndicator = this.container.querySelector('.uc-processing-indicator');

        if (!this.readOnly) {
            this._bindInputEvents();
        } else if (this.chatFooter) {
            this.chatFooter.style.display = 'none';
        }

        // Expose backward-compatible globals
        this._exposeGlobals();
    }

    _bindInputEvents() {
        if (this._inputBound) return;
        this._inputBound = true;

        if (this.sendBtn) {
            this.sendBtn.addEventListener('click', () => this.sendMessage());
        }

        if (this.clearBtn) {
            this.clearBtn.addEventListener('click', () => this._clearInput());
        }

        if (this.msgInput) {
            this.msgInput.addEventListener('keypress', (e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    this.sendMessage();
                }
            });
            this.msgInput.addEventListener('input', () => this._updateCharCounter());
        }
    }

    _updateCharCounter() {
        if (!this.msgInput || !this.charCounter) return;
        const len = this.msgInput.value.length;
        const max = this.maxMessageLength;
        this.charCounter.textContent = `${len}/${max} znaků`;

        if (len >= max) {
            this.charCounter.className = 'uc-char-counter text-danger font-weight-bold mt-1 text-end';
            this.msgInput.style.borderColor = '#dc3545';
        } else if (len > max * 0.8) {
            this.charCounter.className = 'uc-char-counter text-danger mt-1 text-end';
            this.msgInput.style.borderColor = '';
        } else if (len > max * 0.6) {
            this.charCounter.className = 'uc-char-counter text-warning mt-1 text-end';
            this.msgInput.style.borderColor = '';
        } else {
            this.charCounter.className = 'uc-char-counter text-muted small mt-1 text-end';
            this.msgInput.style.borderColor = '';
        }

        if (this.sendBtn) {
            this.sendBtn.disabled = len === 0 || len > max;
        }
    }

    _clearInput() {
        if (!this.msgInput) return;
        this.msgInput.value = '';
        this.msgInput.style.height = '50px';
        this._updateCharCounter();
        this.msgInput.focus();
    }

    _exposeGlobals() {
        window._unifiedChat = this;

        window.chatLog = this.chatMessages;
        window.addMessage = (role, content) => this.addMessage(role, content);
        window.addSystemMessage = (content, isProcessing) => this.addSystemMessage(content, isProcessing);
        window.clearProcessingMessages = () => this.clearProcessingMessages();
        window.sendBtn = this.sendBtn;
        window.msgInput = this.msgInput;

        // Backward-compatible connection globals
        window.connectWebSocket = (sessionId) => this.connect(sessionId);
        window.sendWebSocketMessage = (message) => this._socketSend(message);
        window.disconnectWebSocket = () => this.disconnect();
        window.isWebSocketConnected = () => this.isConnected();
    }

    // ===================================================================
    // Public API — UI
    // ===================================================================

    /** Set the chat header inner HTML. */
    setHeader(html) {
        if (this.chatHeader) {
            this.chatHeader.innerHTML = html;
        }
    }

    setFooter(html) {
        if (this.chatFooter) {
            this.chatFooter.innerHTML = html;
        }
    }

    /** Show the chat area (hide placeholder, show body + footer). */
    show() {
        this.container.classList.add('open');
        if (this.chatPlaceholder) this.chatPlaceholder.style.display = 'none';
        if (this.chatBody) this.chatBody.style.display = 'block';
        if (this.chatFooter && !this.readOnly) this.chatFooter.style.display = 'block';
    }

    /** Hide the chat area (show placeholder, hide body + footer). */
    hide() {
        this.container.classList.remove('open');
        if (this.chatPlaceholder) this.chatPlaceholder.style.display = 'flex';
        if (this.chatBody) this.chatBody.style.display = 'none';
        if (this.chatFooter) this.chatFooter.style.display = 'none';
        if (this.chatHeader) this.chatHeader.innerHTML = '';
    }

    /** Remove all messages from the chat body. */
    clear() {
        if (this.chatMessages) {
            this.chatMessages.innerHTML = '';
        }
        this.assistantMessageCount = 0;
        this._clearStreamingBubble();
    }

    /** Scroll chat body to bottom. */
    scrollToBottom() {
        if (this.chatBody) {
            setTimeout(() => {
                this.chatBody.scrollTop = this.chatBody.scrollHeight;
            }, 50);
        }
    }

    /** Enable or disable the input controls. */
    setInputEnabled(enabled) {
        if (this.sendBtn) this.sendBtn.disabled = !enabled;
        if (this.msgInput) this.msgInput.disabled = !enabled;
    }

    /** Switch from read-only to live input mode. */
    enableLiveMode() {
        this.readOnly = false;
        if (this.chatFooter) this.chatFooter.style.display = 'block';
        this._bindInputEvents();
    }

    // ===================================================================
    // Public API — Messages
    // ===================================================================

    /**
     * Add a single message to the chat.
     *
     * @param {string} role - 'user' | 'assistant' | 'system'
     * @param {string} content - Plain-text message content
     * @param {Object} [options]
     * @param {string}  [options.timestamp]
     * @param {boolean} [options.isFlagged=false]
     * @param {Object}  [options.flagInfo=null]
     * @param {string}  [options.sessionId]
     * @param {boolean} [options.isPublic=false]
     * @param {boolean} [options.showFlagButton=true]
     * @returns {HTMLElement|null}
     */
    addMessage(role, content, options = {}) {
        if (role === 'system') return null;
        if (!this.chatMessages) return null;

        const isUser = role === 'user';
        const isAssistant = role === 'assistant';
        const {
            timestamp = null,
            isFlagged = false,
            flagInfo = null,
            sessionId = this.sessionId,
            isPublic = false,
            showFlagButton = true,
        } = options;

        const messageIndex = isAssistant ? this.assistantMessageCount : null;

        // --- Build message-item element ---
        const messageItem = document.createElement('div');
        messageItem.className = `message-item${isUser ? ' outgoing-message' : ''}`;

        // Avatar row
        const avatarRow = document.createElement('div');
        avatarRow.className = 'message-avatar';

        const figure = document.createElement('figure');
        figure.className = 'avatar';
        const avatarSpan = document.createElement('span');
        avatarSpan.className = 'avatar-title rounded-circle';
        avatarSpan.style.backgroundColor = isUser ? '#0a80ff' : '#17a2b8';
        avatarSpan.innerHTML = isUser
            ? '<i class="fas fa-user"></i>'
            : '<i class="fas fa-robot"></i>';
        figure.appendChild(avatarSpan);
        avatarRow.appendChild(figure);

        const infoDiv = document.createElement('div');
        const nameEl = document.createElement('h5');
        nameEl.textContent = isUser ? 'Vy' : 'AI Asistent';
        infoDiv.appendChild(nameEl);

        if (timestamp) {
            const timeEl = document.createElement('div');
            timeEl.className = 'time';
            timeEl.textContent = this._formatTimestamp(timestamp);
            infoDiv.appendChild(timeEl);
        }
        avatarRow.appendChild(infoDiv);
        messageItem.appendChild(avatarRow);

        // Content bubble
        const contentDiv = document.createElement('div');
        contentDiv.className = 'message-content';

        /* const p = document.createElement('p');
        p.style.whiteSpace = 'pre-wrap';
        p.style.wordBreak = 'break-word';
        p.style.marginBottom = '0';
        p.textContent = content;
        contentDiv.appendChild(p); */

        const htmlContent = marked.parse(content);
        const sanitizedContent = DOMPurify.sanitize(htmlContent);

        contentDiv.innerHTML = sanitizedContent;

        // Public flag reason badge
        if (isPublic && flagInfo && flagInfo.summary) {
            const badge = document.createElement('div');
            badge.className = 'alert alert-warning mt-2 mb-0';
            badge.style.padding = '0.5rem 0.75rem';
            badge.innerHTML = `<small><strong><i class="fas fa-flag me-2"></i>Důvod označení:</strong> ${this._escapeHtml(flagInfo.summary)}</small>`;
            contentDiv.appendChild(badge);
        }

        // Flag / Unflag buttons (assistant only, non-public)
        if (isAssistant && showFlagButton) {
            const actionsDiv = document.createElement('div');
            actionsDiv.className = 'message-actions mt-2';

            if (isFlagged) {
                const btn = document.createElement('button');
                btn.className = 'btn btn-sm btn-warning uc-unflag-btn';
                btn.innerHTML = '<i class="fas fa-flag me-2"></i> Označeno';
                btn.title = 'Upravit označení';
                btn.addEventListener('click', () => {
                    if (this.onUnflag) this.onUnflag(sessionId, content, flagInfo);
                });
                actionsDiv.appendChild(btn);
            } else {
                const btn = document.createElement('button');
                btn.className = 'btn btn-sm btn-outline-secondary uc-flag-btn';
                btn.innerHTML = '<i class="far fa-flag me-2"></i> Označit';
                btn.title = 'Označit tuto zprávu';
                btn.addEventListener('click', () => {
                    if (this.onFlag) this.onFlag(sessionId, content, messageIndex);
                });
                actionsDiv.appendChild(btn);
            }

            contentDiv.appendChild(actionsDiv);
        }

        messageItem.appendChild(contentDiv);
        this.chatMessages.appendChild(messageItem);
        this.scrollToBottom();

        if (isAssistant) {
            this.assistantMessageCount++;
        }

        return messageItem;
    }

    /**
     * Add a system/warning message banner.
     * @param {string} content
     * @param {boolean} [isProcessing=false]
     * @returns {HTMLElement}
     */
    addSystemMessage(content, isProcessing = false) {
        if (!this.chatMessages) return null;

        const div = document.createElement('div');
        div.className = 'alert alert-warning uc-system-message';
        if (isProcessing) div.classList.add('processing-message');
        div.textContent = content;
        this.chatMessages.appendChild(div);
        this.scrollToBottom();
        return div;
    }

    /** Remove all processing indicator messages. */
    clearProcessingMessages() {
        if (!this.chatMessages) return;
        this.chatMessages.querySelectorAll('.processing-message').forEach(el => el.remove());
    }

    /**
     * Render an entire conversation history.
     *
     * @param {Array} messages - Array of { role, content, timestamp }
     * @param {Object} [flaggedInfo]
     */
    loadHistory(messages, flaggedInfo = {}) {
        this.clear();

        const {
            flaggedContentSet = [],
            flaggedMessages = [],
            isPublic = false,
            scrollToFlagged = false,
            isPostedByUser = true,
        } = flaggedInfo;

        if (!messages || messages.length === 0) {
            const emptyP = document.createElement('p');
            emptyP.className = 'text-center text-muted my-5';
            emptyP.textContent = 'Žádné zprávy v této konverzaci.';
            if (this.chatMessages) this.chatMessages.appendChild(emptyP);
            return;
        }

        messages.forEach((msg) => {
            if (msg.role === 'system') return;

            const isFlagged = flaggedContentSet.includes(msg.content);
            let flagInfo = null;
            if (isFlagged && flaggedMessages) {
                flagInfo = flaggedMessages.find(f => f.content === msg.content);
            }

            this.addMessage(msg.role, msg.content, {
                timestamp: msg.timestamp,
                isFlagged,
                flagInfo,
                isPublic,
                showFlagButton: isPostedByUser,
            });
        });

        if (scrollToFlagged) {
            const flaggedEl = this.chatMessages.querySelector('.uc-flagged');
            if (flaggedEl) {
                flaggedEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
            }
        } else {
            this.scrollToBottom();
        }
    }

    // ===================================================================
    // Public API — Sending
    // ===================================================================

    /**
     * Send a message. If `text` is omitted the current input value is used.
     * @param {string} [text]
     * @returns {boolean}
     */
    sendMessage(text) {
        const message = text || (this.msgInput ? this.msgInput.value.trim() : '');
        if (!message) return false;

        if (message.length > this.maxMessageLength) {
            this.addSystemMessage(`Zpráva přesahuje maximální délku ${this.maxMessageLength} znaků`);
            return false;
        }

        if (!this.isConnected()) {
            this.addSystemMessage('⚠️ Připojení k serveru bylo ztraceno. Prosím, začněte novou konverzaci.');
            return false;
        }

        this.setInputEnabled(false);
        this.addMessage('user', message);

        // Clear input (only if we read from the textarea)
        if (!text && this.msgInput) {
            this.msgInput.value = '';
            this.msgInput.style.height = '50px';
            this._updateCharCounter();
        }

        const sent = this._socketSend(message);
        if (!sent) {
            this.setInputEnabled(true);
            return false;
        }

        if (this.onMessageSent) this.onMessageSent(message);
        return true;
    }

    // ===================================================================
    // Socket.IO connection
    // ===================================================================

    /**
     * Open a Socket.IO connection to the chat server.
     *
     * @param {string} sessionId
     * @returns {Promise<void>} Resolves when the connection is established
     */
    connect(sessionId) {
        return new Promise((resolve, reject) => {
            if (typeof io === 'undefined') {
                reject(new Error('Socket.IO client library not loaded'));
                return;
            }

            // Disconnect any previous connection
            if (this.socket) {
                this.socket.disconnect();
                this.socket = null;
            }

            this.sessionId = sessionId;
            console.log('UnifiedChat: Connecting to', this.socketUrl, 'session:', sessionId);

            this.socket = io(this.socketUrl, {
                path: '/socket.io',
                transports: ['websocket', 'polling'],
                withCredentials: true,
                reconnection: false,
                query: {
                    session_id: sessionId,
                },
            });

            this.socket.on('connect', () => {
                console.log('UnifiedChat: Socket.IO connected');
                if (this.onConnected) this.onConnected();
                resolve();
            });

            // Server events — each has { type, ... } payload
            this.socket.on('connected', (data) => this._handleServerEvent(data));
            this.socket.on('processing', (data) => this._handleServerEvent(data));
            this.socket.on('stream_chunk', (data) => this._handleServerEvent(data));
            this.socket.on('message', (data) => this._handleServerEvent(data));
            this.socket.on('limit_reached', (data) => this._handleServerEvent(data));
            this.socket.on('error', (data) => this._handleServerEvent(data));

            this.socket.on('connect_error', (error) => {
                console.error('UnifiedChat: Socket.IO connection error:', error);
                if (this.onError) this.onError(error);
                reject(new Error('Chyba připojení k serveru'));
            });

            this.socket.on('disconnect', (reason) => {
                console.log('UnifiedChat: Socket.IO disconnected, reason:', reason);
                this.clearProcessingMessages();
                this._clearStreamingBubble();

                if (reason !== 'io client disconnect') {
                    if (this.onDisconnected) this.onDisconnected(reason);
                }

                this.setInputEnabled(false);
            });
        });
    }

    /** Close the Socket.IO connection gracefully. */
    disconnect() {
        if (this.socket) {
            this.socket.disconnect();
            this.socket = null;
        }
        this._clearStreamingBubble();
    }

    /** Check whether Socket.IO is currently connected. */
    isConnected() {
        return !!(this.socket && this.socket.connected);
    }

    // ===================================================================
    // Socket.IO event handling (private)
    // ===================================================================

    /** @private */
    _handleServerEvent(data) {
        const messageType = data && data.type;

        switch (messageType) {
            case 'connected':
                console.log('UnifiedChat: server confirmed session');
                break;

            case 'processing':
                this.clearProcessingMessages();
                this._clearStreamingBubble();
                this.addSystemMessage(data.message || 'Generuji odpověď...', true);
                break;

            case 'stream_chunk':
                this.clearProcessingMessages();
                this._ensureStreamingBubble();
                if (this._streamingBubble) {
                    this._streamingBubble.textContent += data.content || '';
                    this.scrollToBottom();
                }
                break;

            case 'message':
                this.clearProcessingMessages();
                this._clearStreamingBubble();
                this.addMessage('assistant', data.content);
                this.setInputEnabled(true);
                if (this.msgInput) this.msgInput.focus();
                if (this.onMessageReceived) this.onMessageReceived(data.content);
                break;

            case 'limit_reached':
                this.clearProcessingMessages();
                this._clearStreamingBubble();
                this.addSystemMessage('⚠️ ' + data.message);
                this.setInputEnabled(false);
                if (this.onLimitReached) this.onLimitReached(data);
                break;

            case 'error':
                this.clearProcessingMessages();
                this._clearStreamingBubble();
                this.addSystemMessage(`⚠️ ${data.message}`);
                this.setInputEnabled(true);
                if (this.msgInput) this.msgInput.focus();
                if (this.onError) this.onError(data);
                break;

            default:
                console.warn('UnifiedChat: unknown server event type:', messageType, data);
        }
    }

    /** @private - Send a message via Socket.IO */
    _socketSend(message) {
        if (!this.isConnected()) {
            console.error('UnifiedChat: not connected');
            this.addSystemMessage('⚠️ Připojení k serveru bylo ztraceno.');
            return false;
        }
        try {
            this.socket.emit('send_message', message);
            return true;
        } catch (err) {
            console.error('UnifiedChat: send error', err);
            this.addSystemMessage(`⚠️ Chyba při odesílání zprávy: ${err.message}`);
            return false;
        }
    }

    // Backward-compatible alias
    _wsSend(message) {
        return this._socketSend(message);
    }

    // ===================================================================
    // Streaming bubble helpers
    // ===================================================================

    /** @private */
    _ensureStreamingBubble() {
        if (this._streamingContainer && this._streamingBubble) return;
        if (!this.chatMessages) return;

        this._streamingContainer = document.createElement('div');
        this._streamingContainer.className = 'message-item';

        // Avatar
        const avatarRow = document.createElement('div');
        avatarRow.className = 'message-avatar';
        const figure = document.createElement('figure');
        figure.className = 'avatar';
        const avatarSpan = document.createElement('span');
        avatarSpan.className = 'avatar-title rounded-circle';
        avatarSpan.style.backgroundColor = '#17a2b8';
        avatarSpan.innerHTML = '<i class="fas fa-robot"></i>';
        figure.appendChild(avatarSpan);
        avatarRow.appendChild(figure);

        const infoDiv = document.createElement('div');
        const nameEl = document.createElement('h5');
        nameEl.textContent = 'AI Asistent';
        infoDiv.appendChild(nameEl);
        avatarRow.appendChild(infoDiv);
        this._streamingContainer.appendChild(avatarRow);

        // Content bubble
        const contentDiv = document.createElement('div');
        contentDiv.className = 'message-content';
        this._streamingBubble = document.createElement('p');
        this._streamingBubble.style.whiteSpace = 'pre-wrap';
        this._streamingBubble.style.wordBreak = 'break-word';
        this._streamingBubble.style.marginBottom = '0';
        contentDiv.appendChild(this._streamingBubble);
        this._streamingContainer.appendChild(contentDiv);

        this.chatMessages.appendChild(this._streamingContainer);
    }

    /** @private */
    _clearStreamingBubble() {
        if (this._streamingContainer && this._streamingContainer.parentNode) {
            this._streamingContainer.parentNode.removeChild(this._streamingContainer);
        }
        this._streamingContainer = null;
        this._streamingBubble = null;
    }

    // ===================================================================
    // Helpers
    // ===================================================================

    /** @private */
    _escapeHtml(text) {
        const map = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' };
        return String(text).replace(/[&<>"']/g, m => map[m]);
    }

    /** @private */
    _formatTimestamp(timestamp) {
        if (typeof timestamp === 'string') {
            const d = new Date(timestamp);
            return d.toLocaleTimeString('cs-CZ', { hour: '2-digit', minute: '2-digit' });
        }
        return '';
    }
}
