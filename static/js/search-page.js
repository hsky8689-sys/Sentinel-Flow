import { getCookie } from './fetching-utils';
async function searchQuery(){
             const query = document.getElementById("searchbar").value.trim();
             if(!query){
                alert('search for something!!');
                return;
             }
             query.innerHTML='';
             try{
                const response = await fetch('/users/search/api/',{
                    method:'POST',
                    headers:{
                        'X-CSRFToken':getCookie('csrftoken'),
                        'Content-Type':'application/json'
                    },
                    body: JSON.stringify({query:query})
                });
                const data = await response.json();
                if(data.status === 'success'){
                    displayResults(data.results);
                }
            }catch (error){
                alert('Error: '+error)
             }
        }
async function displayResults(results){
            const feed = document.getElementById('search-results');
            if(!feed){
                alert('Could not get feed element');
                return;
            }
            feed.innerHTML = '';
            let html = '';
            console.log(results.people,results.projects)
            if (results.people && results.people.length > 0){
                html += `<h2>People</h2>`;
                results.people.forEach(person=>{
                    html += `
                            <div class="searched-person">
                                <strong><a href="/users/profile/${person.username}/" target="_blank">${person.username}</a></strong> - ${person.email}
                            </div>
    <hr>
`;
                });
            }
            if(results.projects && results.projects.length>0){
                html += `<h2>Projects</h2>`;
                results.projects.forEach(project=>{
                    html += `
                            <div class="searched-person">
                                <strong><a href="/projects/project-page/${project.name}/" target="_blank">${project.name}</a></strong>
                            </div>
    <hr>
`;
                });
            }
            feed.innerHTML=html;
        }
        document.getElementById('searchbar').addEventListener('keypress',function (e){
            if (e.key === 'Enter') searchQuery();
        });