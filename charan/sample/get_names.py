from ultralytics import YOLO
m1 = YOLO('foodsafety.pt')
m2 = YOLO('kitchenobj.pt')
with open('model_names.txt', 'w') as f:
    f.write(f'PPE: {m1.names}\n')
    f.write(f'Kitchen: {m2.names}\n')
