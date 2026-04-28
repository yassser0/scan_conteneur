from ultralytics import YOLO

model = YOLO('../models/yolov8n.pt')

print("Début de la détection filtrée")

# Option 1: Remove stream=True for simple webcam detection
results = model.predict(
    classes=[0],
    source=0,           
    project=r'C:\Users\user\Documents\MARSA MAROC\Projet\python',         
    exist_ok=True,             
    conf=0.20,   
    show=True,
    # stream=True  # Remove this line
)

# Classe	Objet	Classe	Objet
# 1	Personne (person)	
# 2	Vélo (bicycle)	
# 3	Voiture (car)	
# 4	Moto (motorcycle)	
# 5	Avion (airplane)	45	Bol (bowl)
# 6	Bus (bus)	46	Banane (banana)
# 7	Train (train)	47	Pomme (apple)
# 8	Camion (truck)	48	Sandwich (sandwich)
# 9	Bateau (boat)	49	Orange (orange)
# 10	Feu de circulation (traffic light)	50	Brocoli (broccoli)
# 11	Bouche d'incendie (fire hydrant)	51	Carotte (carrot)
# 12	Panneau stop (stop sign)	52	Hot dog (hot dog)
# 13	Parcmètre (parking meter)	53	Pizza (pizza)
# 14	Banc (bench)	54	Donut (donut)
# 15	Oiseau (bird)	55	Gâteau (cake)
# 16	Chat (cat)	56	Chaise (chair)
# 17	Chien (dog)	57	Canapé (couch)
# 18	Cheval (horse)	58	Plante en pot (potted plant)
# 19	Mouton (sheep)	59	Lit (bed)
# 20	Vache (cow)	60	Table à manger (dining table)
# 21	Éléphant (elephant)	61	Toilettes (toilet)
# 22	Ours (bear)	62	Télévision (tv)
# 23	Zèbre (zebra)	63	Ordinateur portable (laptop)
# 24	Girafe (giraffe)	64	Souris (mouse)
# 25	Sac à dos (backpack)	65	Télécommande (remote)
# 26	Parapluie (umbrella)	66	Clavier (keyboard)
# 27	Sac à main (handbag)	67	Téléphone portable (cell phone)
# 28	Cravate (tie)	68	Micro-ondes (microwave)
# 29	Valise (suitcase)	69	Four (oven)
# 30	Frisbee (frisbee)	70	Grille-pain (toaster)
# 31	Skis (skis)	71	Évier (sink)
# 32	Snowboard (snowboard)	72	Réfrigérateur (refrigerator)
# 33	Ballon de sport (sports ball)	73	Livre (book)
# 34	Cerf-volant (kite)	74	Horloge (clock)
# 35	Batte de baseball (baseball bat)	75	Vase (vase)
# 36	Gant de baseball (baseball glove)	76	Ciseaux (scissors)
# 37	Skateboard (skateboard)	77	Ours en peluche (teddy bear)
# 38	Planche de surf (surfboard)	78	Sèche-cheveux (hair drier)
# 39	Raquette de tennis (tennis racket)	79	Brosse à dents (toothbrush)
# 40	Bouteille (bottle)
#41	Tasse (cup)
#42	Fourchette (fork)
#43	Couteau (knife)
