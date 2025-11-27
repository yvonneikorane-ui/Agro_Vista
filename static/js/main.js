let lastAnswer = "";
let isReading = false;
let currentUtterance = null;

async function ask(){
    const q = document.getElementById('q').value;
    if (!q) { document.getElementById('answer').innerText = "Please type a question first."; return; }
    document.getElementById('answer').innerText = "Thinking...";
    document.getElementById('chart').innerHTML = "";

    const key = getApiKey();
    if(!key){
        alert("Please login first.");
        window.location.href = '/login';
        return;
    }

    try{
        const res = await fetch('/ask', {
            method:"POST",
            headers:{
                'Content-Type':'application/json',
                'x-api-key': key
            },
            body: JSON.stringify({question:q})
        });
        const data = await res.json();
        lastAnswer = data.answer || data.response || JSON.stringify(data);
        document.getElementById('answer').innerText = lastAnswer;
        if(data.chart){
            document.getElementById('chart').innerHTML = '<img src="data:image/png;base64,' + data.chart + '">';
        }
    } catch(e){
        document.getElementById('answer').innerText = "Request failed: " + e.message;
    }
}

function startListening(){
    const recognition = new (window.SpeechRecognition || window.webkitSpeechRecognition)();
    recognition.lang = 'en-US';
    recognition.start();
    recognition.onresult = function(event){
        document.getElementById('q').value = event.results[0][0].transcript;
    };
}

function readResponse(){
    if (!lastAnswer){ alert("No response available."); return; }
    if(isReading){ speechSynthesis.cancel(); isReading=false; return; }
    currentUtterance = new SpeechSynthesisUtterance(lastAnswer);
    isReading=true;
    currentUtterance.onend = () => { isReading=false; };
    speechSynthesis.speak(currentUtterance);
}

function openDashboard(){
    window.location.href='/admin';
}

// Upload CSV (for admin dashboard)
async function uploadCsv(){
    const csv_url = document.getElementById('csvUrl').value;
    const table_name = document.getElementById('tableName').value;
    if(!csv_url || !table_name){
        alert("Both CSV URL and Table Name required");
        return;
    }
    const key = getApiKey();
    const res = await fetch('/upload_csv', {
        method:'POST',
        headers:{'Content-Type':'application/json','x-api-key': key},
        body: JSON.stringify({csv_url, table_name})
    });
    const data = await res.json();
    document.getElementById('uploadResult').innerText = JSON.stringify(data,null,2);
}
