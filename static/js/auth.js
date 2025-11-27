// static/js/auth.js
function saveApiKey() {
    const key = document.getElementById("apiKey").value.trim();
    if (!key) {
        alert("API Key is required");
        return;
    }
    localStorage.setItem("agro_api_key", key);
    alert("API Key saved successfully.");
    window.location.href = "/";
}

function getApiKey() {
    return localStorage.getItem("agro_api_key");
}

function logout() {
    localStorage.removeItem("agro_api_key");
    window.location.href = "/login";
}
