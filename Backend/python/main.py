from ultralytics import YOLO
import cv2
import easyocr
import requests
import re
import time

model = YOLO('../models/yolo26n.pt')

reader = easyocr.Reader(['en'])

BASE_URL = "http://localhost:82"
node_url = f"{BASE_URL}/extract-code"

session = requests.Session()

# Login
try:
    login_resp = session.post(f"{BASE_URL}/login", json={"email": "admin@marsa.ma", "password": "admin123"})
    if login_resp.status_code != 200 or not login_resp.json().get("success"):
        print(" Impossible de se connecter au serveur")
        exit()
except Exception as e:
    print(f" Connexion au serveur impossible: {e}")
    exit()

camera_ip = input(" Entrez l'adresse IP de la caméra (ex: 192.168.1.10): ").strip()
if not camera_ip:
    print("Adresse IP requise")
    exit()

try:
    resp = session.get(f"{BASE_URL}/cameras")
    cameras_list = resp.json() if resp.status_code == 200 else []
    match = next((c for c in cameras_list if c.get("ip_address") == camera_ip), None)
    if match:
        camera_db_id = str(match["_id"])
        print(f" Caméra trouvée: {match.get('name', camera_ip)} ({camera_ip})")
    else:
        print(f"  Aucune caméra avec l'IP {camera_ip} trouvée dans la base. Vérifiez la configuration.")
        exit()
        
except Exception as e:
    print(f" Connexion au serveur impossible: {e}")
    exit()

cap = cv2.VideoCapture(0)
if not cap.isOpened():
    print(" Cannot open camera")
    exit()

print(" Camera started... Press Q to quit")

detected_containers = {}

def fix_iso(text):
    """Fix common OCR misreads for ISO size type codes (e.g. 22G1, 42G0, 45G1, L5G1)"""
    if len(text) != 4:
        return text
    # Must start with digit or 'L' (for L5xx codes), second char must be digit
    if not (text[0].isdigit() or text[0] == 'L') or not (text[1].isdigit() or text[1] in 'OI'):
        return text
    chars = list(text)
    # Positions 0-1: size digits — fix letter/digit confusion
    for i in (0, 1):
        if chars[i] == 'O': chars[i] = '0'
        if chars[i] == 'I': chars[i] = '1'
        if chars[i] == 'l': chars[i] = '1'
    # Position 2: type group letter (G, R, T, B, H, P, S, U) — fix digit→letter
    if chars[2] == '6': chars[2] = 'G'
    if chars[2] == '8': chars[2] = 'B'
    if chars[2] == '5': chars[2] = 'S'
    if chars[2] == '1': chars[2] = 'I'
    # Position 3: height/subtype — usually digit, fix letter→digit
    if chars[3] == 'O': chars[3] = '0'
    if chars[3] == 'I': chars[3] = '1'
    if chars[3] == 'l': chars[3] = '1'
    return "".join(chars)

while True:
    ret, frame = cap.read()
    if not ret:
        print("Failed to grab frame")
        break

    # Run YOLO detection
    results = model(frame, conf=0.4)

    for r in results:
        for box in r.boxes:
            x1, y1, x2, y2 = map(int, box.xyxy[0])
            conf = float(box.conf[0])

            # Crop detected container area
            crop = frame[y1:y2, x1:x2]

            # OCR
            ocr_results = reader.readtext(crop)
            detected_texts = []
            for res in ocr_results:
                text = res[1].upper().strip()
                text = re.sub(r'[^A-Z0-9]', '', text)
                if len(text) > 2:
                    detected_texts.append(text)

            # Fix common ISO OCR mistakes
            corrected_texts = [fix_iso(t) for t in detected_texts]

            # Parse container code
            prefix = number = check_digit = container_code = iso_size_type = None
            container_pattern = r'[A-Z]{3}U\d{6}\d'
            # Covers 20/40/45ft codes (22G1, 42G0, 45G1) and L5xx codes (L5G1)
            iso_size_pattern = r'(?:[L\d]\d)[A-Z][A-Z0-9]'

            for text in corrected_texts:
                if re.fullmatch(r'[A-Z]{3}U', text):
                    prefix = text
                elif re.fullmatch(r'\d{6}', text):
                    number = text
                elif re.fullmatch(r'\d', text):
                    check_digit = text
                elif re.fullmatch(container_pattern, text):
                    container_code = text
                elif re.fullmatch(iso_size_pattern, text):
                    iso_size_type = text

            # Fallback: search for ISO code embedded in longer OCR strings
            if not iso_size_type:
                for text in corrected_texts:
                    m = re.search(iso_size_pattern, text)
                    if m:
                        iso_size_type = fix_iso(m.group())
                        break

            if not container_code and prefix and number:
                container_code = prefix + number + (check_digit if check_digit else "")

            # Only send new detections
            if container_code and container_code not in detected_containers:
                detected_containers[container_code] = time.time()
                data = {
                    "container_code": container_code,
                    "iso_size_type": iso_size_type if iso_size_type else "Non Scanné",
                    "confidence": round(conf * 100, 2),
                    "camera_id": camera_db_id
                }
                try:
                    # Encode the full frame as JPEG and send as multipart
                    _, img_encoded = cv2.imencode('.jpg', frame)
                    img_bytes = img_encoded.tobytes()
                    files = {'screenshot': ('screenshot.jpg', img_bytes, 'image/jpeg')}
                    r = session.post(node_url, data=data, files=files)
                    if r.status_code == 200:
                        print(f"✅ Sent {container_code} to server")
                    else:
                        print(f" Server rejected {container_code}: {r.status_code} - {r.text}")
                except Exception as e:
                    print(" Connection failed:", e)

            # Draw box and label on frame
            if container_code:
                label = f"{container_code} | ISO: {iso_size_type if iso_size_type else '?'}"
            else:
                label = f"Container {conf:.2f}"
            cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
            cv2.putText(frame, label, (x1, y1 - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

    # Show frame
    cv2.imshow("MarsaScan Camera", frame)

    # Press Q to quit
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()