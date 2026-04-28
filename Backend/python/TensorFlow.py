from ultralytics import YOLO

model = YOLO("best100.pt")
model.export(format="tflite")