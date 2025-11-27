// Login page
function login() {
    const key = document.getElementById('apiKey').value;
    if (!key) {
        document.getElementById('loginError').innerText = "API Key required!";
        return;
    }
    // Store API key in localStorage
    localStorage.setItem('ADMIN_API_KEY', key);
    // Redirect to production UI page
    window.location.href = 'https://agrovista-production-3274.up.railway.app/';
}

// Get stored API key
function getApiKey() {
    return localStorage.getItem('ADMIN_API_KEY') || '';
}

// Logout function
function logout() {
    localStorage.removeItem('ADMIN_API_KEY');
    // Redirect back to production UI page
    window.location.href = 'https://agrovista-production-3274.up.railway.app/';
}

// Ensure login for protected pages
function requireLogin() {
    if (!getApiKey()) {
        window.location.href = '/login';
    }
}

