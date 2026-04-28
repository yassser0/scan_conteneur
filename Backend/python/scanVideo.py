from ultralytics import YOLO

# 1. Charger le modèle
model = YOLO('yolov8n.pt')

# 2. Chemin de ta vidéo
video_path = 'videoplayback.mp4' 

print("Début de la détection filtrée (cars uniquement)...")



results = model.predict(
    source=video_path, 
    classes=[2],          
    project=r'C:\Users\user\Documents\MARSA MAROC\Projet\python', 
    name='cars',         
    exist_ok=True, 
    save=True,            
    conf=0.25,             
    imgsz=640,
    vid_stride=5,
    show=True 
                            
)

print(f"Détection terminée. Regarde dans : C:\\Users\\user\\Documents\\MARSA MAROC\\Projet\\python\\human")