from ultralytics import YOLO
import cv2
import easyocr
import requests
import re

model = YOLO('../models/yolo26n.pt')
reader = easyocr.Reader(['en'])

file_path = '../test/test3.jpg'
node_url = "http://localhost:82/extract-code"

results = model.predict(
    source=file_path,
    project=r'C:\Users\user\Documents\MARSA MAROC\Projet\Backend',
    name='containercode',
    exist_ok=True,
    conf=0.50,
    save=True
)

img = cv2.imread(file_path)

detected_texts = []
confidences = []

for r in results:
    for box in r.boxes:

        x1, y1, x2, y2 = map(int, box.xyxy[0])
        confidences.append(float(box.conf[0]))

        crop = img[y1:y2, x1:x2]

        ocr = reader.readtext(crop)

        for res in ocr:

            text = res[1].upper().strip()
            text = re.sub(r'[^A-Z0-9]', '', text)

            if len(text) > 2:
                detected_texts.append(text)

print("OCR detected parts:", detected_texts)


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

print("Corrected parts:", corrected_texts)


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


print("------------- RESULT -------------")
print("Container Code :", container_code)
print("ISO Size Type  :", iso_size_type)
print("Confidence     :", overall_conf_percent,'%')
print("----------------------------------")


if container_code:

    payload = {
        "container_code": container_code,
        "iso_size_type": iso_size_type,
        "confidence": overall_conf_percent,
        "source_file": file_path
    }

    try:

        r = requests.post(node_url, json=payload)

        if r.status_code == 200:
            print("Successfully sent to server")

        else:
            print("Server error:", r.status_code)

    except Exception as e:
        print("Connection failed:", e)

else:
    print("No valid container code detected")