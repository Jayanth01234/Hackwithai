import os
import cv2
from PIL import Image
import numpy as np
from ultralytics import YOLO
import sys

# Change to the project directory
os.chdir(r'c:\Users\chara\Desktop\Hackwithai-1\charan\sample')

from vision_llm import analyze_cleanliness

def main():
    BASE_DIR = os.getcwd()
    print(f"Working directory: {BASE_DIR}")
    
    # Check if files exist
    models = ["foodsafety.pt", "kitchenobj.pt"]
    for m in models:
        path = os.path.join(BASE_DIR, m)
        print(f"Checking {m}: {os.path.exists(path)}")
        
    image_path = "restaurant.jpg"
    print(f"Checking {image_path}: {os.path.exists(image_path)}")
    
    print("Loading models...")
    ppe_model = YOLO(os.path.join(BASE_DIR, "foodsafety.pt"))
    kitchen_model = YOLO(os.path.join(BASE_DIR, "kitchenobj.pt"))
    
    print("Step 1: Analyzing cleanliness (BLIP)...")
    try:
        caption, hygiene_score = analyze_cleanliness(image_path)
        print(f"Caption: {caption}, Score: {hygiene_score}")
    except Exception as e:
        print(f"Error in analyze_cleanliness: {e}")
        import traceback
        traceback.print_exc()

    print("Step 2: Processing image for YOLO...")
    img_pil = Image.open(image_path).convert("RGB")
    img_cv2 = cv2.cvtColor(np.array(img_pil), cv2.COLOR_RGB2BGR)
    h_img, w_img, _ = img_cv2.shape
    print(f"Image shape: {h_img}x{w_img}")
    
    print("Step 3: Running PPE YOLO...")
    try:
        ppe_results = ppe_model(image_path, conf=0.05)
        print(f"PPE Results: {len(ppe_results[0].boxes)} boxes")
    except Exception as e:
        print(f"Error in PPE YOLO: {e}")
        import traceback
        traceback.print_exc()
        
    print("Step 4: Running Kitchen YOLO...")
    try:
        kitchen_results = kitchen_model(image_path, conf=0.25)
        print(f"Kitchen Results: {len(kitchen_results[0].boxes)} boxes")
    except Exception as e:
        print(f"Error in Kitchen YOLO: {e}")
        import traceback
        traceback.print_exc()
        
    print("Done!")

if __name__ == "__main__":
    main()
