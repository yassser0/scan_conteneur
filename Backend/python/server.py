from flask import Flask, request, jsonify
from ultralytics import YOLO
import cv2
import numpy as np
import easyocr
import re
import os
import requests
import io

app = Flask(__name__)

script_dir = os.path.dirname(os.path.abspath(__file__))
model_path = os.path.join(script_dir, "best100.pt")

if not os.path.exists(model_path):
    model_path = "yolov8n.pt"

model = YOLO(model_path)
reader = easyocr.Reader(['en'])

def fix_iso(text):
    """Corrige les erreurs ISO (ex: 2261 -> 22G1)"""
    if len(text) != 4: return text
    chars = list(text)
    # Positions 0 et 1 : Chiffres
    for i in (0, 1):
        if chars[i] == 'O': chars[i] = '0'
        if chars[i] in ('I', 'l'): chars[i] = '1'
    # Position 2 : Lettre (Groupe ISO)
    if chars[2] == '6': chars[2] = 'G'
    if chars[2] == '8': chars[2] = 'B'
    if chars[2] == '5': chars[2] = 'S'
    if chars[2] == '0': chars[2] = 'O'
    return "".join(chars)

def fix_numeric(text):
    """Corrige les lettres lues à la place de chiffres (ex: 274312J -> 2743129)"""
    confusions = {
        'J': '9', 'I': '1', 'L': '1', 'O': '0', 'S': '5', 'B': '8', 'G': '6'
    }
    res = ""
    for char in text:
        res += confusions.get(char, char)
    return res

@app.route('/scan', methods=['POST'])
def scan():
    img = None
    if 'image' in request.files:
        file = request.files['image']
        img = cv2.imdecode(np.frombuffer(file.read(), np.uint8), cv2.IMREAD_COLOR)
    elif request.is_json:
        data = request.get_json()
        image_url = data.get('url') or data.get('image_url')
        if image_url:
            try:
                resp = requests.get(image_url, timeout=10)
                img = cv2.imdecode(np.frombuffer(resp.content, np.uint8), cv2.IMREAD_COLOR)
            except Exception as e:
                return jsonify({"status": "error", "message": str(e)}), 400
    
    if img is None:
        return jsonify({"status": "error", "message": "Aucune image fournie"}), 400

    results = model(img, conf=0.1)
    
    container_code = "Inconnu"
    iso_code = "Inconnu"
    found = False

    for r in results:
        for box in r.boxes:
            found = True
            x1, y1, x2, y2 = map(int, box.xyxy[0])
            crop = img[y1:y2, x1:x2]
            ocr_results = reader.readtext(crop)
            
            blocks = []
            for res in ocr_results:
                t = re.sub(r'[^A-Z0-9]', '', res[1].upper().strip())
                if len(t) >= 1: blocks.append(t)

            prefix = number = None
            for t in blocks:
                # 1. ISO Code (4 chars)
                if len(t) == 4 and (t[0].isdigit() or t[0] in ('L', 'I')):
                    iso_code = fix_iso(t)
                
                # 2. Matricule Complet (11 chars)
                elif len(t) == 11 and t[:4].isalpha():
                    container_code = t[:4] + fix_numeric(t[4:])
                
                # 3. Morceaux
                elif len(t) == 4 and t.isalpha():
                    prefix = t
                elif 6 <= len(t) <= 8:
                    # On nettoie le numéro (enlève les lettres parasites)
                    number = fix_numeric(t)

            if container_code == "Inconnu" and prefix and number:
                container_code = prefix + number

    if not found:
        return jsonify({"status": "error", "message": "Aucun conteneur détecté"}), 404

    return jsonify({
        "status": "success",
        "container_code": container_code,
        "iso_code": iso_code
    })

if __name__ == '__main__':
    print("--- [ SERVICE : SCAN_CONTENEUR ] ---")
    app.run(host="0.0.0.0", port=5000)