function login(){
    const key = document.getElementById('apiKey').value;
    if(!key){
        document.getElementById('loginError').innerText = "API Key required!";
        return;
    }
    localStorage.setItem('ADMIN_API_KEY', key);
    window.location.href = '/';
}

function getApiKey(){
    return localStorage.getItem('ADMIN_API_KEY') || '';
}

function logout(){
    localStorage.removeItem('ADMIN_API_KEY');
    window.location.href = '/login';
}

function requireLogin(){
    if(!getApiKey()){
        window.location.href = '/login';
    }
}
