// WebSocket Chat Implementation for EDU-AI
// This script replaces the HTTP-based chat with WebSocket connections to FastAPI

(function() {
    'use strict';
    
    // Configuration
    const FASTAPI_WS_URL = 'wss://api.edu-ai.eu/ws/roleplay/';  // Production
    // const FASTAPI_WS_URL = 'ws://localhost:6767/ws/roleplay/';  // Development
    
    // WebSocket instance
    let websocket = null;
    
    /**
     * Connect to WebSocket server
     * @param {string} sessionId - The session ID to connect with
     * @returns {Promise} Resolves when connected, rejects on error
     */
    window.connectWebSocket = function(sessionId) {
        return new Promise((resolve, reject) => {
            const wsUrl = FASTAPI_WS_URL + sessionId;
            console.log('Connecting to WebSocket:', wsUrl);
            
            websocket = new WebSocket(wsUrl);
            
            websocket.onopen = () => {
                console.log('WebSocket connected successfully');
                resolve();
            };
            
            websocket.onmessage = (event) => {
                console.log('WebSocket message received:', event.data);
                
                try {
                    const data = JSON.parse(event.data);
                    handleWebSocketMessage(data);
                } catch (error) {
                    console.error('Error parsing WebSocket message:', error);
                    if (window.addSystemMessage) {
                        window.addSystemMessage('⚠️ Chyba při zpracování odpovědi serveru');
                    }
                }
            };
            
            websocket.onerror = (error) => {
                console.error('WebSocket error:', error);
                reject(new Error('Chyba připojení k serveru'));
            };
            
            websocket.onclose = (event) => {
                console.log('WebSocket closed:', event.code, event.reason);
                
                // Remove any processing indicators
                if (window.clearProcessingMessages) {
                    window.clearProcessingMessages();
                } else if (window.chatLog) {
                    const systemMessages = window.chatLog.querySelectorAll('.alert.processing-message');
                    systemMessages.forEach(msg => msg.remove());
                }
                
                if (event.code !== 1000) {  // 1000 = normal closure
                    if (window.addSystemMessage) {
                        window.addSystemMessage(`⚠️ Připojení ukončeno: ${event.reason || 'Neznámý důvod'}`);
                    }
                }
                
                // Disable inputs
                if (window.sendBtn) window.sendBtn.disabled = true;
                if (window.msgInput) window.msgInput.disabled = true;
            };
        });
    };
    
    /**
     * Handle different types of WebSocket messages
     * @param {Object} data - Parsed JSON message from server
     */
    function handleWebSocketMessage(data) {
        const messageType = data.type;
        
        switch (messageType) {
            case 'connected':
                console.log('WebSocket connection confirmed:', data.message);
                break;
                
            case 'processing':
                // Clear any existing processing messages first
                if (window.clearProcessingMessages) {
                    window.clearProcessingMessages();
                }
                // Show processing indicator
                if (window.addSystemMessage) {
                    window.addSystemMessage(data.message || "Generuji odpověď...", true);
                }
                break;
                
            case 'message':
                // Remove processing messages
                if (window.clearProcessingMessages) {
                    window.clearProcessingMessages();
                } else if (window.chatLog) {
                    // Fallback for backwards compatibility
                    const systemMessages = window.chatLog.querySelectorAll('.alert.processing-message');
                    systemMessages.forEach(msg => msg.remove());
                }
                
                // Add assistant's reply
                if (window.addMessage) {
                    window.addMessage('assistant', data.content);
                }
                
                if (window.assistantMessageCount !== undefined) {
                    window.assistantMessageCount++;
                }
                
                // Re-enable inputs
                if (window.sendBtn) {
                    window.sendBtn.disabled = false;
                }
                if (window.msgInput) {
                    window.msgInput.disabled = false;
                    window.msgInput.focus();
                }
                
                // Scroll to bottom
                if (window.chatLog) {
                    window.chatLog.scrollTop = window.chatLog.scrollHeight;
                }
                break;
                
            case 'limit_reached':
                // Remove processing messages
                if (window.clearProcessingMessages) {
                    window.clearProcessingMessages();
                } else if (window.chatLog) {
                    const processingMsgs = window.chatLog.querySelectorAll('.alert.processing-message');
                    processingMsgs.forEach(msg => msg.remove());
                }
                
                // Show limit reached message
                if (window.addSystemMessage) {
                    window.addSystemMessage("⚠️ " + data.message);
                }
                
                // Keep inputs disabled
                if (window.sendBtn) window.sendBtn.disabled = true;
                if (window.msgInput) window.msgInput.disabled = true;
                break;
                
            case 'error':
                // Remove processing messages
                if (window.clearProcessingMessages) {
                    window.clearProcessingMessages();
                } else if (window.chatLog) {
                    const errorProcMsgs = window.chatLog.querySelectorAll('.alert.processing-message');
                    errorProcMsgs.forEach(msg => msg.remove());
                }
                
                // Show error
                if (window.addSystemMessage) {
                    window.addSystemMessage(`⚠️ ${data.message}`);
                }
                
                // Re-enable inputs
                if (window.sendBtn) {
                    window.sendBtn.disabled = false;
                }
                if (window.msgInput) {
                    window.msgInput.disabled = false;
                    window.msgInput.focus();
                }
                break;
                
            default:
                console.warn('Unknown message type:', messageType, data);
        }
    }
    
    /**
     * Send message via WebSocket
     * @param {string} message - The message to send
     * @returns {boolean} Success status
     */
    window.sendWebSocketMessage = function(message) {
        if (!websocket || websocket.readyState !== WebSocket.OPEN) {
            console.error('WebSocket not connected');
            if (window.addSystemMessage) {
                window.addSystemMessage("⚠️ Připojení k serveru bylo ztraceno. Prosím, začněte novou konverzaci.");
            }
            return false;
        }
        
        try {
            websocket.send(message);
            console.log('Message sent via WebSocket:', message);
            return true;
        } catch (error) {
            console.error('Error sending WebSocket message:', error);
            if (window.addSystemMessage) {
                window.addSystemMessage(`⚠️ Chyba při odesílání zprávy: ${error.message}`);
            }
            return false;
        }
    };
    
    /**
     * Close WebSocket connection
     */
    window.disconnectWebSocket = function() {
        if (websocket && websocket.readyState === WebSocket.OPEN) {
            websocket.close(1000, 'User initiated disconnect');
            websocket = null;
            console.log('WebSocket disconnected');
        }
    };
    
    /**
     * Check if WebSocket is connected
     * @returns {boolean}
     */
    window.isWebSocketConnected = function() {
        return websocket && websocket.readyState === WebSocket.OPEN;
    };
    
})();
