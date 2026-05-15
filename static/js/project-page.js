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
function loadPage(context){
    const role = context.role;
    window.localStorage.setItem("newDomains","[]");
    window.localStorage.setItem("removedDomains","[]");
    const domains_div = document.getElementsByClassName("project-domains");
    if(role === 'visitor'){
        console.log('fetching requirements');
        getProjectRequirements();
    }
}
async function goToMainProjectPage(project_name){
    const desiredUrl = `/projects/project-page/${project_name}/`;
    const bailoutUrl = location.href;
    try{
        const response = await fetch(desiredUrl,{
            headers : {'X-Requested-With': 'XMLHttpRequest'}
        });
         if (response.ok) {
            location.href = desiredUrl;
        } else {
            alert('Nu ai permisiunea sau pagina nu există.');
        }
    }catch (error){
        alert('Couldnt load project page');
        location.href = bailoutUrl;
    }
}
async function goToProjectMembersPage(project_name){
    const desiredUrl = `/projects/project-page/${project_name}/project-members/`;
    const bailoutUrl = location.href;
    try {
        const response = await fetch(desiredUrl, {
            headers: { 'X-Requested-With': 'XMLHttpRequest' }
        });
        if (response.ok) {
            location.href = desiredUrl;
        } else {
            alert('Nu ai permisiunea sau pagina nu există.');
        }
    } catch (error) {
        alert('Eroare de conexiune!');
        location.href = bailoutUrl;
    }
}
async function goToProjectSettings(project_name){
    const desiredUrl = `/projects/project-page/${project_name}/settings/`;
    const bailoutUrl = location.href;
    try{
        const response = await fetch(desiredUrl, {
            headers: { 'X-Requested-With': 'XMLHttpRequest' }
        });
        if (response.ok) {
            location.href = desiredUrl;
        } else {
            alert('Nu ai permisiunea sau pagina nu există.');
        }
    }
    catch (err){
        location.href=bailoutUrl;
    }
}
async function copyLinkToClipboard(){
    try{
        await navigator.clipboard.writeText(window.location.href);
        alert(`Link copied to clipboard`);
    }catch(err){
        console.error(`Fail to copy:`,err);
    }
}
async function getProjectRequirements(){
 try{
        const desiredUrl = `/projects/`+window.djangoContext.project.name+`/api-get-project-requirements`;
        const response = await fetch(desiredUrl,{
            headers: { 'X-Requested-With': 'XMLHttpRequest' }
        });
        if(response.ok){
            var section = document.getElementsByClassName("project-task-overview").item(0);
            if(section==null){
                return;
            }
            const data = await response.json();
            const requirementsMap = data.requirements;
            var text = '';
            Object.entries(requirementsMap).forEach(([sectionName,reqList]) => {
                text += `<h3>${sectionName}</h3><br>`;
                if (Array.isArray(reqList)) {
                    reqList.forEach(req => {
                        text += `<p>${req.skill}</p><br>`;
                    });
                }
                else{
                    console.log(sectionName+' does not have a list associated with id');
                }
            });
            section.innerHTML = text;
        }
    }catch(err){
        console.error(`Fail to copy:`,err);
    }
}
document.addEventListener('DOMContentLoaded', () => {
    if (window.djangoContext && window.djangoContext.user) {
        loadPage(window.djangoContext.user);
    } else {
        console.error('Contextul djangoContext lipsește din pagină!');
    }
});
async function runCode(){
    const consoleOutput = document.getElementById("console-output");
    const editor = document.getElementById("code-textarea");
    const sourceCode = editor.value;
    const languageSelect = document.getElementById("languages");
    //const selectedLanguage = languageSelect.value;
    const selectedLanguage = 113;
    if (!sourceCode.trim()) {
        consoleOutput.innerText = "Te rog să scrii niște cod mai întâi.";
        return;
    }
    consoleOutput.innerText = "Se execută pe server... ⏳";
    try {
        const response = await fetch('/projects/api/run-code/', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCookie('csrftoken')
            },
            body: JSON.stringify({
                source_code: sourceCode,
                language_id: selectedLanguage
            })
        });

        const result = await response.json();

        if (result.stdout) {
            consoleOutput.style.color = "#00ff00";
            consoleOutput.innerText = result.stdout;
        } else if (result.stderr) {
            consoleOutput.style.color = "#ff4c4c";
            consoleOutput.innerText = "Eroare la rulare:\n" + result.stderr;
        } else if (result.compile_output) {
            consoleOutput.style.color = "#ff4c4c";
            consoleOutput.innerText = "Eroare de compilare:\n" + result.compile_output;
        } else {
            consoleOutput.innerText = "Programul a rulat cu succes, dar nu a afișat nimic pe ecran.";
        }

    } catch (error) {
        consoleOutput.style.color = "#ff4c4c";
        consoleOutput.innerText = "Eroare de conexiune cu serverul Django.";
        console.error(error);
    }
}