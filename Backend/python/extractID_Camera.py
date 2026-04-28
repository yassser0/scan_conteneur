from ultralytics import YOLO
import cv2
import easyocr
import requests
import re

# Load AI model
model = YOLO('../models/best100.pt')

# OCR reader
reader = easyocr.Reader(['en'])

# Backend API
node_url = "http://localhost:82/extract-code"
url = "http://192.168.1.8:8080/video"
# Open webcam
cap = cv2.VideoCapture(url)

if not cap.isOpened():
    print("Cannot open camera")
    exit()

print("Camera started... Press Q to quit")

while True:

    ret, frame = cap.read()

    if not ret:
        print("Failed to grab frame")
        break

    # Run YOLO detection on frame
    results = model(frame, conf=0.5)

    detected_texts = []
    confidences = []

    for r in results:

        for box in r.boxes:

            x1, y1, x2, y2 = map(int, box.xyxy[0])
            confidences.append(float(box.conf[0]))

            # Crop detected region
            crop = frame[y1:y2, x1:x2]

            # OCR
            ocr = reader.readtext(crop)

            for res in ocr:

                text = res[1].upper().strip()
                text = re.sub(r'[^A-Z0-9]', '', text)

                if len(text) > 2:
                    detected_texts.append(text)

    print("OCR detected parts:", detected_texts)

    # -------- ISO FIX --------

    def fix_iso(text):

        if len(text) == 4 and text[:2].isdigit():

            chars = list(text)

            if chars[2] == '6':
                chars[2] = 'G'

            if chars[2] == '0':
                chars[2] = 'O'

            if chars[3] == '8':
                chars[3] = 'B'

            return "".join(chars)

        return text


    corrected_texts = [fix_iso(t) for t in detected_texts]

    prefix = None
    number = None
    check_digit = None
    container_code = None
    iso_size_type = None

    container_pattern = r'[A-Z]{3}U\d{6}\d'
    iso_size_pattern = r'\d{2}[A-Z0-9]{2}'

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


    if not container_code and prefix and number:

        if check_digit:
            container_code = prefix + number + check_digit
        else:
            container_code = prefix + number


    overall_conf = round(sum(confidences) / len(confidences), 4) if confidences else 0
    overall_conf_percent = round(overall_conf * 100, 2)

    print("Container Code:", container_code)
    print("ISO Size Type:", iso_size_type)
    print("Confidence:", overall_conf_percent, "%")

    # -------- SEND TO SERVER --------

    if container_code:

        payload = {
            "container_code": container_code,
            "iso_size_type": iso_size_type,
            "confidence": overall_conf_percent
        }

        try:

            r = requests.post(node_url, json=payload)

            if r.status_code == 200:
                print("Sent to server")

        except Exception as e:
            print("Connection failed:", e)

    # Show camera
    cv2.imshow("MarsaScan Camera", frame)

    # Press Q to exit
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break


cap.release()
cv2.destroyAllWindows()