// Socket.IO Chat Transport for EDU-AI
// Keeps existing global API used by roleplay template:
// connectWebSocket, sendWebSocketMessage, disconnectWebSocket, isWebSocketConnected

(function () {
    "use strict";

    const FASTAPI_SOCKETIO_URL = window.FASTAPI_SOCKETIO_URL ||
        ((window.location.hostname === "localhost" ||
            window.location.hostname === "127.0.0.1")
            ? "http://localhost:6767"
            : "https://api.edu-ai.eu");

    window.FASTAPI_SOCKETIO_URL = FASTAPI_SOCKETIO_URL;

    let socket = null;
    let streamingContainer = null;
    let streamingBubble = null;

    function clearStreamingBubble() {
        if (streamingContainer && streamingContainer.parentNode) {
            streamingContainer.parentNode.removeChild(streamingContainer);
        }
        streamingContainer = null;
        streamingBubble = null;
    }

    function ensureStreamingBubble() {
        if (streamingContainer && streamingBubble) {
            return;
        }

        if (!window.chatLog) {
            return;
        }

        streamingContainer = document.createElement("div");
        streamingContainer.className = "d-flex mb-3";

        streamingBubble = document.createElement("div");
        streamingBubble.className = "bg-light p-2 rounded";
        streamingBubble.style.maxWidth = "80%";
        streamingBubble.style.whiteSpace = "pre-wrap";
        streamingBubble.style.wordBreak = "break-word";

        streamingContainer.appendChild(streamingBubble);
        window.chatLog.appendChild(streamingContainer);
    }

    window.connectWebSocket = function (sessionId) {
        return new Promise((resolve, reject) => {
            if (typeof io === "undefined") {
                reject(new Error("Socket.IO client library not loaded"));
                return;
            }

            if (socket) {
                socket.disconnect();
                socket = null;
            }

            socket = io(FASTAPI_SOCKETIO_URL, {
                path: "/socket.io",
                transports: ["websocket", "polling"],
                withCredentials: true,
                reconnection: false,
                query: {
                    session_id: sessionId,
                },
            });

            socket.on("connect", () => {
                resolve();
            });

            socket.on("connected", handleSocketMessage);
            socket.on("processing", handleSocketMessage);
            socket.on("stream_chunk", handleSocketMessage);
            socket.on("message", handleSocketMessage);
            socket.on("limit_reached", handleSocketMessage);
            socket.on("error", handleSocketMessage);

            socket.on("connect_error", (error) => {
                console.error("Socket.IO connection error:", error);
                reject(new Error("Chyba připojení k serveru"));
            });

            socket.on("disconnect", (reason) => {
                if (window.clearProcessingMessages) {
                    window.clearProcessingMessages();
                }
                clearStreamingBubble();

                if (reason !== "io client disconnect") {
                    if (typeof window.onSocketDisconnected === "function") {
                        window.onSocketDisconnected();
                    } else if (window.addSystemMessage) {
                        window.addSystemMessage("⚠️ Připojení bylo přerušeno.");
                    }
                }

                if (window.sendBtn) {
                    window.sendBtn.disabled = true;
                }
                if (window.msgInput) {
                    window.msgInput.disabled = true;
                }
            });
        });
    };

    function handleSocketMessage(data) {
        const messageType = data.type;

        switch (messageType) {
            case "connected":
                break;

            case "processing":
                if (window.clearProcessingMessages) {
                    window.clearProcessingMessages();
                }
                clearStreamingBubble();
                if (window.addSystemMessage) {
                    window.addSystemMessage(
                        data.message || "Generuji odpověď...",
                        true,
                    );
                }
                break;

            case "stream_chunk":
                if (window.clearProcessingMessages) {
                    window.clearProcessingMessages();
                }
                ensureStreamingBubble();
                if (streamingBubble) {
                    streamingBubble.textContent += data.content || "";
                    if (window.chatLog) {
                        window.chatLog.scrollTop = window.chatLog.scrollHeight;
                    }
                }
                break;

            case "message":
                if (window.clearProcessingMessages) {
                    window.clearProcessingMessages();
                }
                clearStreamingBubble();

                if (window.addMessage) {
                    window.addMessage("assistant", data.content);
                }

                if (window.sendBtn) {
                    window.sendBtn.disabled = false;
                }
                if (window.msgInput) {
                    window.msgInput.disabled = false;
                    window.msgInput.focus();
                }
                if (window.chatLog) {
                    window.chatLog.scrollTop = window.chatLog.scrollHeight;
                }
                break;

            case "limit_reached":
                if (window.clearProcessingMessages) {
                    window.clearProcessingMessages();
                }
                clearStreamingBubble();

                if (window.addSystemMessage) {
                    window.addSystemMessage("⚠️ " + data.message);
                }

                if (window.sendBtn) {
                    window.sendBtn.disabled = true;
                }
                if (window.msgInput) {
                    window.msgInput.disabled = true;
                }
                break;

            case "error":
                if (window.clearProcessingMessages) {
                    window.clearProcessingMessages();
                }
                clearStreamingBubble();

                if (window.addSystemMessage) {
                    window.addSystemMessage(`⚠️ ${data.message}`);
                }

                if (window.sendBtn) {
                    window.sendBtn.disabled = false;
                }
                if (window.msgInput) {
                    window.msgInput.disabled = false;
                    window.msgInput.focus();
                }
                break;

            default:
                console.warn("Unknown socket message type:", messageType, data);
        }
    }

    window.sendWebSocketMessage = function (message) {
        if (!socket || !socket.connected) {
            if (window.addSystemMessage) {
                window.addSystemMessage(
                    "⚠️ Připojení k serveru bylo ztraceno. Prosím, začněte novou konverzaci.",
                );
            }
            return false;
        }

        try {
            socket.emit("send_message", message);
            return true;
        } catch (error) {
            console.error("Error sending Socket.IO message:", error);
            if (window.addSystemMessage) {
                window.addSystemMessage(
                    `⚠️ Chyba při odesílání zprávy: ${error.message}`,
                );
            }
            return false;
        }
    };

    window.disconnectWebSocket = function () {
        if (socket) {
            socket.disconnect();
            socket = null;
        }
        clearStreamingBubble();
    };

    window.isWebSocketConnected = function () {
        return !!(socket && socket.connected);
    };
})();
