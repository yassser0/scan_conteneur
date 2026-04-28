from ultralytics import YOLO

# Charger le modèle
model = YOLO('yolov8n.pt')

print("Début de l'entraînement...")

model.train(
    data='../data/dataset3/data.yaml',
    epochs=20,
    imgsz=640,
    batch=5,
    name='container_model',
    project='.'  
)