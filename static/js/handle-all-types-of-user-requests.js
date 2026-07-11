function getCookie(name){
            let cookieValue = null;
            if (document.cookie && document.cookie !== '') {
                const cookies = document.cookie.split(';');
                for (let i = 0; i < cookies.length; i++) {
                    const cookie = cookies[i].trim();
                    if (cookie.substring(0, name.length + 1) === (name + '=')) {
                        cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                        break;
                    }
                }
            }
            return cookieValue;
}
async function handleProjectJoinRequest(senderId, receiverId, action) {
    if (!action) return;

    try {
        const response = await fetch('/projects/api/requests/project/handle/', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCookie('csrftoken')
            },
            body: JSON.stringify({
                sender_id: senderId,
                receiver_id: receiverId,
                action: action
            })
        });
        const data = await response.json();

        if (data.status === 'success') {
            document.getElementById(`req-project-${senderId}-${receiverId}`).remove();
        } else {
            alert(data.message);
        }
    } catch (error) {
        console.error('Eroare:', error);
    }
}
async function handleFriendRequestFromConversations(senderId, receiverId, action) {
    if (!action) return;

    try {
        const desiredUrl = action === 'accept' ? `/users/${senderId}/accept-friend-request/` : `/users/${senderId}/accept-friend-request/`
        const response = await fetch(desiredUrl, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCookie('csrftoken')
            },
            body: JSON.stringify({
                'sender_id': senderId,
                'receiver_id': receiverId,
                'action': action
            })
        });
        const data = await response.json();

        if (data.status === 'success') {
            document.getElementById(`req-friend-${senderId}-${receiverId}`).remove();
        } else {
            alert(data.message);
        }
    } catch (error) {
        console.error('Eroare:', error);
    }
}

async function handleFileAccessRequest(senderId, receiverId, action, filePath = null) {
    if (!action) return;

    try {
        const response = await fetch(`/api/requests/file/handle/`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCookie('csrftoken')
            },
            body: JSON.stringify({
                'sender_id': senderId,
                'receiver_id': receiverId,
                'action': action,
                'file_path': filePath
            })
        });
        const data = await response.json();

        if (data.status === 'success') {
            document.getElementById(`req-file-${senderId}-${receiverId}`).remove();
        } else {
            alert(data.message);
        }
    } catch (error) {
        console.error('Eroare:', error);
    }
}