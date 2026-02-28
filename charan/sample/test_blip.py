from transformers import BlipProcessor, BlipForConditionalGeneration
from PIL import Image
import torch
import os

os.chdir(r'c:\Users\chara\Desktop\Hackwithai-1\charan\sample')

device = "cpu"
print("Loading processor...")
processor = BlipProcessor.from_pretrained("Salesforce/blip-image-captioning-base")
print("Loading model...")
model = BlipForConditionalGeneration.from_pretrained("Salesforce/blip-image-captioning-base").to(device)

print("Opening image...")
image = Image.open("restaurant.jpg").convert("RGB")
print("Processing inputs...")
inputs = processor(image, return_tensors="pt").to(device)
print("Generating...")
output = model.generate(**inputs, max_new_tokens=50)
print("Decoding...")
caption = processor.decode(output[0], skip_special_tokens=True)
print(f"DONE: {caption}")
