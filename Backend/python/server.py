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

def validate_bic(code):
    """Calcule et valide le chiffre d'autocontrôle ISO 6346"""
    if not code or len(code) != 11:
        return False
    
    # Valeurs des lettres (A=10, ..., Z=38, saute les multiples de 11)
    letter_map = {
        'A': 10, 'B': 12, 'C': 13, 'D': 14, 'E': 15, 'F': 16, 'G': 17, 'H': 18, 'I': 19,
        'J': 20, 'K': 21, 'L': 23, 'M': 24, 'N': 25, 'O': 26, 'P': 27, 'Q': 28, 'R': 29,
        'S': 30, 'T': 31, 'U': 32, 'V': 34, 'W': 35, 'X': 36, 'Y': 37, 'Z': 38
    }
    
    try:
        s = 0
        for i in range(10):
            char = code[i]
            val = letter_map.get(char) if i < 4 else int(char)
            if val is None: return False
            s += val * (2 ** i)
        
        check_digit = (s % 11) % 10
        return check_digit == int(code[10])
    except:
        return False

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

    # Prétraitement d'image global
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    # Augmenter le contraste (CLAHE) pour mieux voir le texte blanc sur gris
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8,8))
    enhanced = clahe.apply(gray)
    
    results = model(img, conf=0.1)
    
    container_code = "Inconnu"
    iso_code = "Inconnu"
    found = False

    # Patterns Regex
    CONTAINER_RE = re.compile(r'([A-Z]{4})[\s-]*(\d{6,7})')

    for r in results:
        for box in r.boxes:
            found = True
            x1, y1, x2, y2 = map(int, box.xyxy[0])
            
            # Crop avec une marge de 15% pour éviter de couper les bords
            h_img, w_img = img.shape[:2]
            bw, bh = x2 - x1, y2 - y1
            x1_c = max(0, x1 - int(bw*0.15))
            y1_c = max(0, y1 - int(bh*0.15))
            x2_c = min(w_img, x2 + int(bw*0.15))
            y2_c = min(h_img, y2 + int(bh*0.15))
            
            # --- PRÉ-TRAITEMENT MULTI-PASSES ---
            # Passage 1: Gris original
            gray_crop = cv2.cvtColor(img[y1_c:y2_c, x1_c:x2_c], cv2.COLOR_BGR2GRAY)
            
            # Passage 2: CLAHE (Amélioration Contraste)
            clahe_local = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8,8))
            clahe_crop = clahe_local.apply(gray_crop)
            
            # Passage 3: Sharpen (Netteté)
            kernel = np.array([[-1,-1,-1], [-1,9,-1], [-1,-1,-1]])
            sharpen_crop = cv2.filter2D(clahe_crop, -1, kernel)
            
            crops_to_ocr = [gray_crop, clahe_crop, sharpen_crop]
            all_raw_blocks = []

            for c in crops_to_ocr:
                # Upscale auto pour EasyOCR
                h_c, w_c = c.shape[:2]
                if w_c < 300:
                    scale = 300 / w_c
                    c = cv2.resize(c, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
                
                ocr_res = reader.readtext(c)
                for r in ocr_res:
                    all_raw_blocks.append(r[1].upper().strip())

            # Nettoyage et dédoublonnage des blocs
            blocks = []
            for raw in all_raw_blocks:
                clean = re.sub(r'[^A-Z0-9]', '', raw)
                if len(clean) >= 1 and clean not in blocks:
                    blocks.append(clean)
                    print(f"[OCR DEBUG] Block detected: '{raw}' -> '{clean}'")

            prefix = number = check_digit = None
            
            for t in blocks:
                # 1. Test Matricule Complet
                match_cont = CONTAINER_RE.search(t)
                if match_cont:
                    p, n = match_cont.groups()
                    candidate = p + fix_numeric(n)
                    # Si c'est un BIC valide, on le garde en priorité absolue
                    if validate_bic(candidate):
                        container_code = candidate
                        print(f"[OCR DEBUG] Found Valid BIC: {container_code}")
                    elif container_code == "Inconnu":
                        container_code = candidate
                
                # 2. Test ISO
                if iso_code == "Inconnu" and len(t) == 4:
                    if t[0] in ('2', '4', 'L', 'I', 'O'):
                        iso_code = fix_iso(t)

                # Fallback : Morceaux
                if len(t) == 4 and t.isalpha():
                    prefix = t
                elif 6 <= len(t) <= 7:
                    number = fix_numeric(t)
                elif len(t) == 1 and t.isdigit():
                    check_digit = t

            # 3. Reconstitution intelligente
            if container_code == "Inconnu" and prefix and number:
                container_code = prefix + number
                if check_digit: container_code += check_digit
            
            # Si on a le matricule mais pas le check_digit, on cherche un bloc de 1 chiffre
            if container_code != "Inconnu" and len(container_code) <= 10 and check_digit:
                if not container_code.endswith(check_digit):
                    container_code += check_digit

    # --- PASSE 2 : SCAN GLOBAL (Fallback) ---
    # Si on n'a toujours pas de matricule, on tente un scan sur l'image entière
    if container_code == "Inconnu":
        print("[OCR DEBUG] Tentative de Scan Global sur l'image entière...")
        # On utilise l'image améliorée (CLAHE)
        global_ocr = reader.readtext(enhanced)
        global_blocks = []
        for res in global_ocr:
            raw = res[1].upper().strip()
            clean = re.sub(r'[^A-Z0-9]', '', raw)
            if len(clean) >= 1:
                global_blocks.append(clean)
        
        # On applique la même logique de détection sur les blocs globaux
        temp_prefix = temp_number = temp_check = None
        for t in global_blocks:
            m_cont = CONTAINER_RE.search(t)
            if m_cont:
                p, n = m_cont.groups()
                cand = p + fix_numeric(n)
                if validate_bic(cand):
                    container_code = cand
                    break
                elif container_code == "Inconnu":
                    container_code = cand
            
            if len(t) == 4 and t.isalpha(): temp_prefix = t
            elif 6 <= len(t) <= 7: temp_number = fix_numeric(t)
            elif len(t) == 1 and t.isdigit(): temp_check = t
            
        if container_code == "Inconnu" and temp_prefix and temp_number:
            container_code = temp_prefix + temp_number
            if temp_check: container_code += temp_check

    if not found and container_code == "Inconnu":
        return jsonify({"status": "error", "message": "Aucun conteneur détecté"}), 404

    # Nettoyage final du matricule (max 11 chars)
    is_valid_bic = False
    if container_code != "Inconnu":
        container_code = container_code[:11]
        is_valid_bic = validate_bic(container_code)

    print(f"--- RÉSULTAT FINAL : {container_code} ({'Valide' if is_valid_bic else 'Invalide'}) | {iso_code} ---")

    return jsonify({
        "status": "success",
        "container_code": container_code,
        "iso_code": iso_code,
        "is_valid": is_valid_bic
    })

if __name__ == '__main__':
    print("--- [ SERVICE : SCAN_CONTENEUR ] ---")
    app.run(host="0.0.0.0", port=5000)