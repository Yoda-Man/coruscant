from PIL import Image
import os

def convert_to_ico():
    img_path = r"d:\Development\DBClient\docs\icon.png"
    ico_path = r"d:\Development\DBClient\docs\icon.ico"
    
    if not os.path.exists(img_path):
        print(f"Error: {img_path} not found")
        return
        
    img = Image.open(img_path)
    # Windows icons usually contain multiple sizes
    icon_sizes = [(16,16), (24,24), (32,32), (48,48), (64,64), (128,128), (256,256)]
    img.save(ico_path, sizes=icon_sizes)
    print(f"Successfully created {ico_path}")

if __name__ == "__main__":
    convert_to_ico()
