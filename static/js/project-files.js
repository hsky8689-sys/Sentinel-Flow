const repoCache = {}
async function loadDirectory(path = ""){
    if(repoCache[path]){
        console.log(`Afisam cache pentru: ${path}`)
        renderExplorer(repoCache[path],path)
        return;
    }
    try{
        //`https://api.github.com/repos/${window.djangoContext.owner_username}/${window.djangoContext.repo_name}/contents/${path}`;
        // /projects/api/github/<str:owner>/<str:repo>/<path:path>
        const desiredUrl = `/projects/api/github/${window.djangoContext.project.owner_username}/${window.djangoContext.project.repo_name}/${path}`;
        const response = await fetch(desiredUrl);
        const data = await response.json();
        repoCache[path] = data;
        renderExplorer(data,path);
    }catch(error){
        console.error("Eroare la fetch:",error);
    }
}
function renderExplorer(items,currentPath){
        const container = document.getElementById("project-structure");
        container.innerHTML = "";
        if(currentPath !== ""){
            const backBtn = document.createElement('div');
            backBtn.innerText = '< BACK';
            backBtn.onclick = () => {
                const parts = currentPath.split('/');
                parts.pop();
                loadDirectory(parts.join('/'));
            };
            container.appendChild(backBtn);
        }
        items.forEach(item => {
            const div = document.createElement('div');
            div.className = 'explorer-item';
            div.innerText = (item.type === 'dir' ? "📁 " : "📄 ") + item.name;
            div.onclick = () => {
            if (item.type === 'dir') {
                    loadDirectory(item.path);
                } else {
                    displayFileContent(item.path);
                }
            }
            container.appendChild(div);
        });
}
async function displayFileContent(path){
    if(repoCache[path]){
        console.log(`Afisam cache pentru: ${path}`)
        renderCode(repoCache[path],path)
        return;
    }
    const desiredUrl = `/projects/api/github/${window.djangoContext.project.owner_username}/${window.djangoContext.project.repo_name}/${path}`;
    try{
        const response = await fetch(desiredUrl);
        const data = await response.json();
        const base64content = data.content.replace(/\s/g, '');
        const decodedContent = decodeURIComponent(escape(atob(base64content)));
        repoCache[path] = decodedContent;
        renderCode(decodedContent, path);
    }catch(error){
        console.error("Eroare la fișier:", error);
        alert("Nu am putut încărca fișierul.");
    }
}
function renderCode(content, path) {
    const container = document.getElementById("code-textarea");
    container.innerHTML = content;
}
document.addEventListener('DOMContentLoaded', () => {
    loadDirectory();
});