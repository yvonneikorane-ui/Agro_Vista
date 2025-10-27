import pandas as pd
from flask import Flask, request, jsonify
import google.generativeai as genai

# Gemini API key
genai.configure(api_key='AIzaSyBRFdxiMvOSGraVMX-Dh8GcZrOGdz6DcGc')

# Google Sheets config
sheet_id = "1e_ZMrZ_16K60iFRfDtUVHs4AjmvXiLM0v4haoOrfsbM"
sheet_name = "youth_women_empowerment_forecast"
csv_url = f'https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?tqx=out:csv&sheet={sheet_name}'

def load_forecast():
    return pd.read_csv(csv_url)

app = Flask(__name__)

@app.route('/ask', methods=['POST'])
def ask():
    q = request.json.get('question')
    f_df = load_forecast()
    prompt = f"""
You are an agricultural analyst.
Forecast data: {f_df.to_dict(orient='records')}
Question: {q}
"""
    model = genai.GenerativeModel('gemini-1.5-flash')
    resp = model.generate_content(prompt)
    return jsonify({'answer': resp.text})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
