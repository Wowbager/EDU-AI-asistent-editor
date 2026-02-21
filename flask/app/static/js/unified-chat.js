/**
 * UnifiedChat - Reusable chat component for EDU AI
 *
 * Provides:
 * - Consistent message rendering (user/assistant) using .message-item pattern
 * - Text input with character counter and validation
 * - WebSocket connection for live send/receive
 * - Loading message history from pre-loaded data
 * - Flag/unflag message button callbacks
 * - System and processing indicator messages
 *
 * Usage:
 *   const chat = new UnifiedChat({
 *       container: '#my-chat',
 *       wsUrl: 'wss://api.edu-ai.eu/ws/roleplay/',
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
 *   // Or connect via WebSocket for live chat
 *   await chat.connect(sessionId);
 *   chat.sendMessage('Hello!');
 */
class UnifiedChat {
    /**
     * @param {Object} options
     * @param {string} options.container - CSS selector for the chat container element
     * @param {number} [options.maxMessageLength=500] - Maximum characters per message
     * @param {string} [options.wsUrl] - WebSocket base URL (session ID is appended)
     * @param {boolean} [options.readOnly=false] - If true, hides input area
     * @param {Function} [options.onFlag] - Called when flag button clicked: (sessionId, content, messageIndex)
     * @param {Function} [options.onUnflag] - Called when unflag button clicked: (sessionId, content, flagInfo)
     * @param {Function} [options.onMessageSent] - Called after a message is sent: (message)
     * @param {Function} [options.onMessageReceived] - Called when assistant message arrives: (content)
     * @param {Function} [options.onConnected] - Called when WebSocket connects
     * @param {Function} [options.onDisconnected] - Called when WebSocket disconnects: (event)
     * @param {Function} [options.onError] - Called on WebSocket error
     * @param {Function} [options.onLimitReached] - Called when message limit is reached
     */
    constructor(options = {}) {
        // Configuration
        this.containerSelector = options.container || '#unified-chat';
        this.maxMessageLength = options.maxMessageLength || 500;
        this.wsBaseUrl = options.wsUrl || 'wss://api.edu-ai.eu/ws/roleplay/';
        this.readOnly = options.readOnly || false;

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
        this.websocket = null;
        this.assistantMessageCount = 0;
        this._inputBound = false;

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

        // Expose backward-compatible globals so existing page scripts and
        // websocket-chat.js can interoperate during migration.
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
        // Store instance globally for backward compat
        window._unifiedChat = this;

        window.chatLog = this.chatMessages;
        window.addMessage = (role, content) => this.addMessage(role, content);
        window.addSystemMessage = (content, isProcessing) => this.addSystemMessage(content, isProcessing);
        window.clearProcessingMessages = () => this.clearProcessingMessages();
        window.sendBtn = this.sendBtn;
        window.msgInput = this.msgInput;

        // Backward-compatible WebSocket globals
        window.connectWebSocket = (sessionId) => this.connect(sessionId);
        window.sendWebSocketMessage = (message) => this._wsSend(message);
        window.disconnectWebSocket = () => this.disconnect();
        window.isWebSocketConnected = () => this.isConnected();
    }

    // ===================================================================
    // Public API — UI
    // ===================================================================

    /**
     * Set the chat header inner HTML.
     * @param {string} html
     */
    setHeader(html) {
        if (this.chatHeader) {
            this.chatHeader.innerHTML = html;
        }
    }

    /**
     * Show the chat area (hide placeholder, show body + footer).
     */
    show() {
        this.container.classList.add('open');
        if (this.chatPlaceholder) this.chatPlaceholder.style.display = 'none';
        if (this.chatBody) this.chatBody.style.display = 'flex';
        if (this.chatFooter && !this.readOnly) this.chatFooter.style.display = 'block';
    }

    /**
     * Hide the chat area (show placeholder, hide body + footer).
     */
    hide() {
        this.container.classList.remove('open');
        if (this.chatPlaceholder) this.chatPlaceholder.style.display = 'flex';
        if (this.chatBody) this.chatBody.style.display = 'none';
        if (this.chatFooter) this.chatFooter.style.display = 'none';
        if (this.chatHeader) this.chatHeader.innerHTML = '';
    }

    /**
     * Remove all messages from the chat body.
     */
    clear() {
        if (this.chatMessages) {
            this.chatMessages.innerHTML = '';
        }
        this.assistantMessageCount = 0;
    }

    /**
     * Scroll chat body to bottom.
     */
    scrollToBottom() {
        if (this.chatBody) {
            setTimeout(() => {
                this.chatBody.scrollTop = this.chatBody.scrollHeight;
            }, 50);
        }
    }

    /**
     * Enable or disable the input controls.
     * @param {boolean} enabled
     */
    setInputEnabled(enabled) {
        if (this.sendBtn) this.sendBtn.disabled = !enabled;
        if (this.msgInput) this.msgInput.disabled = !enabled;
    }

    /**
     * Switch from read-only to live input mode (e.g. to continue a past conversation).
     */
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
     * @param {string}  [options.timestamp]       - ISO timestamp string
     * @param {boolean} [options.isFlagged=false]  - Whether the message is flagged
     * @param {Object}  [options.flagInfo=null]    - { id, content, summary, ... }
     * @param {string}  [options.sessionId]        - Override current session ID
     * @param {boolean} [options.isPublic=false]   - Public flag view (hides flag buttons, shows reasons)
     * @param {boolean} [options.showFlagButton=true] - Show flag/unflag button on assistant messages
     * @returns {HTMLElement|null} The created message element
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

        const p = document.createElement('p');
        p.style.whiteSpace = 'pre-wrap';
        p.style.wordBreak = 'break-word';
        p.style.marginBottom = '0';
        p.textContent = content; // textContent auto-escapes HTML
        contentDiv.appendChild(p);

        // Public flag reason badge
        if (isPublic && flagInfo && flagInfo.summary) {
            const badge = document.createElement('div');
            badge.className = 'alert alert-warning mt-2 mb-0';
            badge.style.padding = '0.5rem 0.75rem';
            badge.innerHTML = `<small><strong><i class="fas fa-flag me-2"></i>Důvod označení:</strong> ${this._escapeHtml(flagInfo.summary)}</small>`;
            contentDiv.appendChild(badge);
        }

        // Flag / Unflag buttons (assistant only, non-public)
        if (isAssistant && !isPublic && showFlagButton) {
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
     *
     * @param {string} content - Text to display
     * @param {boolean} [isProcessing=false] - If true, marked as removable processing msg
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

    /**
     * Remove all processing indicator messages.
     */
    clearProcessingMessages() {
        if (!this.chatMessages) return;
        this.chatMessages.querySelectorAll('.processing-message').forEach(el => el.remove());
    }

    /**
     * Render an entire conversation history.
     *
     * @param {Array} messages - Array of { role, content, timestamp }
     * @param {Object} [flaggedInfo]
     * @param {string[]} [flaggedInfo.flaggedContentSet] - Array of flagged content strings
     * @param {Object[]} [flaggedInfo.flaggedMessages]   - Array of { id, content, summary, ... }
     * @param {boolean}  [flaggedInfo.isPublic=false]
     */
    loadHistory(messages, flaggedInfo = {}) {
        this.clear();

        const {
            flaggedContentSet = [],
            flaggedMessages = [],
            isPublic = false,
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
                showFlagButton: !isPublic,
            });
        });

        this.scrollToBottom();
    }

    // ===================================================================
    // Public API — Sending
    // ===================================================================

    /**
     * Send a message. If `text` is omitted the current input value is used.
     *
     * @param {string} [text] - Optional explicit message text
     * @returns {boolean} Whether the message was sent successfully
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

        // Disable inputs while sending
        this.setInputEnabled(false);

        // Render user bubble
        this.addMessage('user', message);

        // Clear input (only if we read from the textarea)
        if (!text && this.msgInput) {
            this.msgInput.value = '';
            this.msgInput.style.height = '50px';
            this._updateCharCounter();
        }

        // Transmit via WebSocket
        const sent = this._wsSend(message);
        if (!sent) {
            this.setInputEnabled(true);
            return false;
        }

        if (this.onMessageSent) this.onMessageSent(message);
        return true;
    }

    // ===================================================================
    // WebSocket
    // ===================================================================

    /**
     * Open a WebSocket connection to the chat server.
     *
     * @param {string} sessionId
     * @returns {Promise<void>} Resolves when the connection is established
     */
    connect(sessionId) {
        return new Promise((resolve, reject) => {
            this.sessionId = sessionId;
            const wsUrl = this.wsBaseUrl + sessionId;
            console.log('UnifiedChat: Connecting to', wsUrl);

            this.websocket = new WebSocket(wsUrl);

            this.websocket.onopen = () => {
                console.log('UnifiedChat: WebSocket connected');
                if (this.onConnected) this.onConnected();
                resolve();
            };

            this.websocket.onmessage = (event) => {
                try {
                    const data = JSON.parse(event.data);
                    this._handleWSMessage(data);
                } catch (err) {
                    console.error('UnifiedChat: parse error', err);
                    this.addSystemMessage('⚠️ Chyba při zpracování odpovědi serveru');
                }
            };

            this.websocket.onerror = (error) => {
                console.error('UnifiedChat: WebSocket error', error);
                if (this.onError) this.onError(error);
                reject(new Error('Chyba připojení k serveru'));
            };

            this.websocket.onclose = (event) => {
                console.log('UnifiedChat: closed', event.code, event.reason);
                this.clearProcessingMessages();

                if (event.code !== 1000) {
                    this.addSystemMessage(`⚠️ Připojení ukončeno: ${event.reason || 'Neznámý důvod'}`);
                }

                this.setInputEnabled(false);
                if (this.onDisconnected) this.onDisconnected(event);
            };
        });
    }

    /**
     * Close the WebSocket connection gracefully.
     */
    disconnect() {
        if (this.websocket && this.websocket.readyState === WebSocket.OPEN) {
            this.websocket.close(1000, 'User initiated disconnect');
        }
        this.websocket = null;
    }

    /**
     * Check whether the WebSocket is currently open.
     * @returns {boolean}
     */
    isConnected() {
        return this.websocket && this.websocket.readyState === WebSocket.OPEN;
    }

    /** @private */
    _handleWSMessage(data) {
        switch (data.type) {
            case 'connected':
                console.log('UnifiedChat: server confirmed connection');
                break;

            case 'processing':
                this.clearProcessingMessages();
                this.addSystemMessage(data.message || 'Generuji odpověď...', true);
                break;

            case 'message':
                this.clearProcessingMessages();
                this.addMessage('assistant', data.content);
                this.setInputEnabled(true);
                if (this.msgInput) this.msgInput.focus();
                if (this.onMessageReceived) this.onMessageReceived(data.content);
                break;

            case 'limit_reached':
                this.clearProcessingMessages();
                this.addSystemMessage('⚠️ ' + data.message);
                this.setInputEnabled(false);
                if (this.onLimitReached) this.onLimitReached(data);
                break;

            case 'error':
                this.clearProcessingMessages();
                this.addSystemMessage(`⚠️ ${data.message}`);
                this.setInputEnabled(true);
                if (this.msgInput) this.msgInput.focus();
                if (this.onError) this.onError(data);
                break;

            default:
                console.warn('UnifiedChat: unknown message type', data.type, data);
        }
    }

    /** @private - low level WebSocket send */
    _wsSend(message) {
        if (!this.isConnected()) {
            console.error('UnifiedChat: not connected');
            this.addSystemMessage('⚠️ Připojení k serveru bylo ztraceno.');
            return false;
        }
        try {
            this.websocket.send(message);
            return true;
        } catch (err) {
            console.error('UnifiedChat: send error', err);
            this.addSystemMessage(`⚠️ Chyba při odesílání zprávy: ${err.message}`);
            return false;
        }
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
