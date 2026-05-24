import { getCookie } from './fetching-utils';
const message_input = document.getElementById("send-message");
const send_button = document.getElementById("send-button");
const message_display = document.getElementById("message-display");

// 1. Variabila globală pentru conexiunea WebSocket
let chatSocket = null;

localStorage.setItem("currentConversationMessages","[]");
localStorage.setItem("chatCurrentPage","0");
localStorage.setItem("chatPageSize","300");
localStorage.setItem("conversationCurrentPage","0");
localStorage.setItem("conversationPageSize","500");

// Funcție folosită acum direct de WebSocket (pentru mesajele primite de la alții)
function appendMessageToDisplay(message) {
   const message_display = document.querySelector(".message-display");
    const newMessageDiv = document.createElement("div");

    newMessageDiv.classList.add("message");
    newMessageDiv.classList.add("received"); // Mesaj venit prin socket
    newMessageDiv.textContent = message.content;

    message_display.appendChild(newMessageDiv);
    message_display.scrollTop = message_display.scrollHeight;
}

// ==========================================
// 2. FUNCTIA SEPARATĂ PENTRU OBSERVER
// ==========================================
function setupChatObserver(conversationId) {
    // Închidem tunelul vechi dacă dăm click pe alt prieten
    if (chatSocket !== null) {
        chatSocket.close();
    }

    const protocol = window.location.protocol === 'https:' ? 'wss://' : 'ws://';
    chatSocket = new WebSocket(
        protocol + window.location.host + '/ws/chat/' + conversationId + '/'
    );

    // Când primim un mesaj nou pe socket
    chatSocket.onmessage = function(e) {
        const data = JSON.parse(e.data);
        const msg = data['message'];

        // Evităm să duplicăm mesajele trimise de noi (care deja au append din fetch-ul de Send)
        if (msg.sender_id !== window.djangoContext.chat_info.current_user_id) {
            appendMessageToDisplay(msg);
        }
    };

    // Aici pe viitor vei putea adăuga:
    // chatSocket.onopen = function(e) { ... logica ta de grupuri ... }
    // chatSocket.onclose = function(e) { ... logica ta de deconectare ... }
}
// ==========================================


async function sendMessage() {
    const message = message_input.value;
    const conversation_id = window.djangoContext.chat_info.conversation_id;
    const user_1o1 = window.djangoContext.chat_info.current_user_converstaion;

    // Blocăm trimiterea unui mesaj gol pe frontend
    if (!message.trim()) return;

    const response = await fetch('/chat/api/send', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCookie('csrftoken')
        },
        body: JSON.stringify({
            content: message,
            conversation_id: conversation_id,
            user_1o1: user_1o1
        })
    });

    const result = await response.json();

    if (result.success) {
        const bubble = document.createElement("div");
        bubble.classList.add("message", "sent");
        bubble.innerText = message;

        const messageDisplay = document.querySelector(".message-display");
        messageDisplay.appendChild(bubble);

        message_input.value = "";
        messageDisplay.scrollTop = messageDisplay.scrollHeight;
    }
}

async function loadAllUserConversations(){
    const rawConversationPage = localStorage.getItem("conversationCurrentPage");
    const rawConversationPageSize = localStorage.getItem("conversationPageSize");
    const convPage = JSON.parse(rawConversationPage) || 0;
    const convPageSize = JSON.parse(rawConversationPageSize) || 500;

    try {
        const desiredUrl = `/chat/conversations/?pageNumber=${convPage}&pageSize=${convPageSize}`;
        const response = await fetch(desiredUrl);
        if(!response.ok){
            throw new Error(`Eroare server ${response.status}`)
        }
        const received = await response.json();
        const conversations = received.content || received;

        const allConversationsDiv = document.querySelector(".all-conversations");
        const searchDiv = document.querySelector(".message-send-area");

        allConversationsDiv.innerHTML = "";
        if (searchDiv) allConversationsDiv.appendChild(searchDiv);

        conversations.forEach(conv => {
            const convDiv = document.createElement("div");
            convDiv.classList.add("conversation-item");

            convDiv.innerHTML = `
                <div class="conv-avatar">👤</div>
                <div class="conv-details">
                    <strong>${conv.name || 'Chat'}</strong>
                    <p>${conv.last_message_content || 'Niciun mesaj încă...'}</p>
                </div>
            `;

            convDiv.onclick = () => {
                loadNewConversation(conv.id);
            };

            allConversationsDiv.appendChild(convDiv);
        });
    } catch (error) {
        alert(`Eroare la incarcarea conversatiilor: ${error}`);
    }
}

async function loadNewConversation(conversationId){
    if(conversationId === null || conversationId === -1){
        return null;
    }

    window.djangoContext.chat_info.conversation_id = conversationId;

    const rawPageNumber = localStorage.getItem("chatCurrentPage");
    const rawchatPageSize = localStorage.getItem("chatPageSize");
    let chatPageNumber = JSON.parse(rawPageNumber) || 0;
    let chatPageSize = JSON.parse(rawchatPageSize) || 300;

    const messageDisplay = document.querySelector(".message-display");
    messageDisplay.innerHTML = ""; // Curățăm ecranul pentru mesajele noi

    // Aici pornim Observer-ul curat
    setupChatObserver(conversationId);

    try {
        const desiredUrl = `/chat/api/${conversationId}?pageNumber=${chatPageNumber}&pageSize=${chatPageSize}`;
        const response = await fetch(desiredUrl);

        if (!response.ok) {
            throw new Error(`Eroare server ${response.status}`);
        }

        const received = await response.json();
        const messages = received.content || [];
        const myUserId = window.djangoContext.chat_info.current_user_id;

        messages.forEach(msg => {
            const bubble = document.createElement("div");
            bubble.classList.add("message");

            if (msg.sender_id === myUserId) {
                bubble.classList.add("sent");
            } else {
                bubble.classList.add("received");
            }

            bubble.textContent = msg.content;
            messageDisplay.appendChild(bubble);
        });

        messageDisplay.scrollTop = messageDisplay.scrollHeight;

    } catch (error) {
        console.error("Eroare la încărcarea mesajelor:", error);
    }
}

document.addEventListener("DOMContentLoaded", async function() {
    try {
        await loadAllUserConversations();

        if (window.djangoContext.chat_info.conversation_id !== -1 && window.djangoContext.chat_info.conversation_id !== null) {
            await loadNewConversation(window.djangoContext.chat_info.conversation_id);
        }
    } catch (error) {
        console.error("Eroare la inițializare:", error);
    }
});